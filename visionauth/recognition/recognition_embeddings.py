"""Face embedding extractor and similarity comparison for VisionAuth.

Uses FaceNet ONNX model loaded with OpenCV DNN for CPU-efficient inference.
"""

import os
import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)


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
    """Extracts 512-dimensional L2-normalized face embeddings from face images using FaceNet ONNX."""

    def __init__(self, model_path: str | None = None) -> None:
        if model_path is None:
            from pathlib import Path
            project_root = Path(__file__).parent.parent.parent.resolve()
            self.model_path = str(project_root / "models" / "facenet.onnx")
        else:
            self.model_path = model_path
            
        self.net = None

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Embedding model not found: {self.model_path}")

        try:
            self.net = cv2.dnn.readNetFromONNX(self.model_path)
            logger.info("Embedding model loaded successfully from %s", self.model_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load Embedding model from {self.model_path}: {e}")

        # Perform test validation inference
        try:
            dummy_input = np.zeros((160, 160, 3), dtype=np.uint8)
            face_rgb = cv2.cvtColor(dummy_input, cv2.COLOR_BGR2RGB)
            face_resized = cv2.resize(face_rgb, (160, 160))
            blob = cv2.dnn.blobFromImage(
                face_resized,
                scalefactor=1.0 / 128.0,
                size=(160, 160),
                mean=(127.5, 127.5, 127.5),
                swapRB=False,
                crop=False
            )
            self.net.setInput(blob)
            out = self.net.forward()
            
            if not isinstance(out, np.ndarray):
                raise TypeError("Model output is not a numpy ndarray.")

            flat_out = out.flatten()
            if len(flat_out) != 512:
                raise ValueError(f"Model output dimension is {len(flat_out)}, expected 512.")
            
            norm = np.linalg.norm(flat_out)
            if not (norm > 0.0):
                raise ValueError(f"Model output has zero norm: {norm}")
                
            if np.isnan(flat_out).any():
                raise ValueError("Model output contains NaN.")
                
            if np.isinf(flat_out).any():
                raise ValueError("Model output contains Inf.")
                
            logger.info("Embedding model loaded. Output dimension: 512")
            print(f"Loaded FaceNet model:\n{os.path.abspath(self.model_path)}")
            print(f"Output dimension:\n512")
            print(f"Backend:\nOpenCV DNN")
        except Exception as e:
            raise RuntimeError(f"Embedding model validation failed: {e}")

    def extract_embedding(self, face_crop: np.ndarray) -> np.ndarray:
        """Extracts a 512-dimensional L2-normalized embedding from a BGR face crop.

        Args:
            face_crop: BGR image crop of the face.

        Returns:
            A 512-dimensional float numpy array.
        """
        if face_crop is None or face_crop.size == 0:
            return np.zeros(512, dtype=np.float32)

        try:
            # Convert BGR to RGB and resize to FaceNet expectation (160x160)
            face_rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
            face_resized = cv2.resize(face_rgb, (160, 160))

            # Normalize pixel values using blobFromImage
            blob = cv2.dnn.blobFromImage(
                face_resized,
                scalefactor=1.0 / 128.0,
                size=(160, 160),
                mean=(127.5, 127.5, 127.5),
                swapRB=False,
                crop=False
            )
            self.net.setInput(blob)
            embedding = self.net.forward()  # shape (1, 512)
            emb = embedding.flatten()

            # Apply L2 normalization
            norm = np.linalg.norm(emb)
            if norm > 0.0:
                emb = emb / norm
            return emb
        except Exception as e:
            logger.error("Error during embedding extraction: %s. Returning zero embedding.", e)
            return np.zeros(512, dtype=np.float32)


def cosine_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Computes cosine similarity between two L2-normalized embeddings.

    Since they are L2-normalized, cosine similarity is simply the dot product.
    """
    return float(np.dot(emb1, emb2))


class EmbeddingMatcher:
    """Matches face embeddings against enrolled user profiles using cosine similarity."""

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.users_dir = os.path.join(data_dir, "users")

    def load_profiles(self) -> dict[str, list[np.ndarray]]:
        """Loads all user profiles and their embeddings from profile.json files."""
        import json
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
                        
                        # Validate profile compatibility
                        model = data.get("embedding_model")
                        dimension = data.get("embedding_dimension")
                        version = data.get("embedding_version")
                        
                        if model != "FaceNet-512" or dimension != 512 or version != 2:
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

    def match_face(self, query_emb: np.ndarray, threshold: float = 0.65) -> tuple[str | None, float]:
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
