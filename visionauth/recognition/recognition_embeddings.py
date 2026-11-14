"""Face embedding extractor and similarity comparison for VisionAuth.

Uses the SFace recognition model from the OpenCV Model Zoo, with YuNet
landmark-based face alignment, both running on OpenCV for CPU-efficient inference.
Run ``python scripts/download_models.py`` to fetch the models into ``models/``.
"""

import json
import logging
import os
from pathlib import Path

import cv2
import numpy as np

from visionauth.paths import resolve_data_dir

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"
RECOGNIZER_MODEL_FILE = "face_recognition_sface_2021dec.onnx"
ALIGNMENT_MODEL_FILE = "face_detection_yunet_2023mar.onnx"

EMBEDDING_MODEL = "SFace-128"
EMBEDDING_DIMENSION = 128
EMBEDDING_VERSION = 3
SFACE_INPUT_SIZE = (112, 112)

# OpenCV recommends 0.363 for SFace on LFW; slightly stricter for unlocking.
DEFAULT_MATCH_THRESHOLD = 0.45


def is_profile_compatible(profile: dict) -> bool:
    """Checks whether a stored profile was created with the current embedding model.

    Args:
        profile: Parsed contents of a user's profile.json.

    Returns:
        True if the profile's model, dimension and version match the extractor.
    """
    return (
        profile.get("embedding_model") == EMBEDDING_MODEL
        and profile.get("embedding_dimension") == EMBEDDING_DIMENSION
        and profile.get("embedding_version") == EMBEDDING_VERSION
    )


def crop_face(frame: np.ndarray, bounding_box: tuple[float, float, float, float], padding: float = 0.15) -> np.ndarray:
    """Crops the face from the frame using relative bounding box coordinates and applying padding.

    This ensures consistent facial features (forehead, chin, ears) are captured
    and filters out neck and background noise.
    """
    if frame is None or frame.size == 0:
        return np.empty((0, 0, 3), dtype=np.uint8)

    h_img, w_img, _ = frame.shape
    xmin, ymin, width, height = bounding_box

    # Apply padding relative to the bbox size
    pad_w = width * padding
    pad_h = height * padding

    x1 = max(0, int((xmin - pad_w) * w_img))
    y1 = max(0, int((ymin - pad_h) * h_img))
    x2 = min(w_img, int((xmin + width + pad_w) * w_img))
    y2 = min(h_img, int((ymin + height + pad_h) * h_img))

    if (x2 - x1) > 0 and (y2 - y1) > 0:
        return frame[y1:y2, x1:x2]
    return np.empty((0, 0, 3), dtype=np.uint8)


class EmbeddingExtractor:
    """Extracts 128-dimensional L2-normalized face embeddings using SFace.

    When the YuNet model is available, each crop is aligned with its five facial
    landmarks before inference, which is the input SFace was trained on. Without
    it, crops are only resized and accuracy drops.
    """

    def __init__(self, model_path: str | None = None, alignment_model_path: str | None = None) -> None:
        """Loads and validates the recognition model and the optional alignment model.

        Args:
            model_path: Path to the SFace ONNX model. Defaults to models/ in the project.
            alignment_model_path: Path to the YuNet ONNX model. Defaults to models/.

        Raises:
            FileNotFoundError: If the recognition model does not exist.
            RuntimeError: If the recognition model cannot be loaded or fails validation.
        """
        self.model_path = model_path or str(MODELS_DIR / RECOGNIZER_MODEL_FILE)
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Embedding model not found: {self.model_path}. "
                "Run 'python scripts/download_models.py' to download it."
            )

        try:
            self.recognizer = cv2.FaceRecognizerSF.create(self.model_path, "")
        except Exception as e:
            raise RuntimeError(f"Failed to load Embedding model from {self.model_path}: {e}") from e

        self.aligner = self._load_aligner(alignment_model_path or str(MODELS_DIR / ALIGNMENT_MODEL_FILE))

        try:
            self._validate_model()
        except Exception as e:
            raise RuntimeError(f"Embedding model validation failed: {e}") from e

        logger.info(
            "Embedding model loaded from %s (output dimension %d, alignment %s)",
            os.path.abspath(self.model_path),
            EMBEDDING_DIMENSION,
            "enabled" if self.aligner is not None else "disabled",
        )

    @staticmethod
    def _load_aligner(path: str) -> cv2.FaceDetectorYN | None:
        """Loads the YuNet detector used to find alignment landmarks, if present."""
        if not os.path.exists(path):
            logger.warning("Alignment model not found at %s; embeddings will be less accurate.", path)
            return None
        try:
            return cv2.FaceDetectorYN.create(path, "", (320, 320))
        except Exception as e:
            logger.warning("Could not load alignment model %s: %s", path, e)
            return None

    def _validate_model(self) -> None:
        """Runs a test inference and checks the output shape and values."""
        out = self.recognizer.feature(np.zeros((*SFACE_INPUT_SIZE, 3), dtype=np.uint8))
        if not isinstance(out, np.ndarray):
            raise TypeError("Model output is not a numpy ndarray.")

        flat_out = out.flatten()
        if len(flat_out) != EMBEDDING_DIMENSION:
            raise ValueError(f"Model output dimension is {len(flat_out)}, expected {EMBEDDING_DIMENSION}.")
        if np.isnan(flat_out).any():
            raise ValueError("Model output contains NaN.")
        if np.isinf(flat_out).any():
            raise ValueError("Model output contains Inf.")
        norm = np.linalg.norm(flat_out)
        if not (norm > 0.0):
            raise ValueError(f"Model output has zero norm: {norm}")

    def _align(self, face_crop: np.ndarray) -> np.ndarray:
        """Aligns a face crop to the SFace input using YuNet landmarks.

        Falls back to a plain resize when no aligner is loaded or no face is found.
        """
        if self.aligner is not None:
            h, w = face_crop.shape[:2]
            self.aligner.setInputSize((w, h))
            _, faces = self.aligner.detect(face_crop)
            if faces is not None and len(faces) > 0:
                best_face = max(faces, key=lambda f: f[-1])
                return self.recognizer.alignCrop(face_crop, best_face)
            logger.debug("Alignment landmarks not found; using plain resize.")
        return cv2.resize(face_crop, SFACE_INPUT_SIZE)

    def extract_embedding(self, face_crop: np.ndarray) -> np.ndarray:
        """Extracts a 128-dimensional L2-normalized embedding from a BGR face crop.

        Args:
            face_crop: BGR image crop of the face.

        Returns:
            A 128-dimensional float numpy array, or zeros if extraction fails.
        """
        if face_crop is None or face_crop.size == 0:
            return np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)

        try:
            aligned = self._align(face_crop)
            emb = self.recognizer.feature(aligned).flatten().astype(np.float32)

            norm = np.linalg.norm(emb)
            if norm > 0.0:
                emb = emb / norm
            return emb
        except Exception as e:
            logger.error("Error during embedding extraction: %s. Returning zero embedding.", e)
            return np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)


def cosine_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Computes cosine similarity between two L2-normalized embeddings.

    Since they are L2-normalized, cosine similarity is simply the dot product.
    """
    return float(np.dot(emb1, emb2))


class EmbeddingMatcher:
    """Matches face embeddings against enrolled user profiles using cosine similarity."""

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = resolve_data_dir(data_dir)
        self.users_dir = os.path.join(self.data_dir, "users")

    def load_profiles(self) -> dict[str, list[np.ndarray]]:
        """Loads all user profiles and their embeddings from profile.json files."""
        profiles = {}
        if not os.path.exists(self.users_dir):
            return profiles

        for username in os.listdir(self.users_dir):
            user_path = os.path.join(self.users_dir, username)
            profile_path = os.path.join(user_path, "profile.json")
            if os.path.isfile(profile_path):
                try:
                    with open(profile_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                        if not is_profile_compatible(data):
                            logger.error(
                                "User profile created with an incompatible embedding model for '%s'. Please enroll again.",
                                username
                            )
                            continue

                        embs = [np.array(e, dtype=np.float32) for e in data.get("embeddings", [])]
                        if embs:
                            profiles[username] = embs
                except Exception as e:
                    logger.error("Failed to load profile for %s: %s", username, e)
        return profiles

    def match_face(self, query_emb: np.ndarray, threshold: float = DEFAULT_MATCH_THRESHOLD) -> tuple[str | None, float]:
        """Matches a query embedding against all enrolled profiles using cosine similarity.

        Returns:
            Tuple of (username, max_similarity) if matched above threshold, else (None, max_similarity).
        """
        profiles = self.load_profiles()
        best_match = None
        best_similarity = -1.0

        for username, embs in profiles.items():
            # Compare against all samples of this user
            for emb in embs:
                sim = cosine_similarity(query_emb, emb)
                if sim > best_similarity:
                    best_similarity = sim
                    best_match = username

        if best_similarity >= threshold:
            return best_match, best_similarity
        return None, best_similarity
