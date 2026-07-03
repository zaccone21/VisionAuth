"""Face embedding generation interface and stub implementation.

Prepares the architecture for integrating model-based embeddings (e.g., InsightFace)
without introducing real model dependencies in this sprint.
"""

from abc import ABC, abstractmethod
import numpy as np


class FaceEmbedder(ABC):
    """Abstract base class representing a face embedding extractor."""

    @abstractmethod
    def generate_embedding(self, face_image: np.ndarray) -> np.ndarray:
        """Extracts facial embeddings from a cropped face image.

        Args:
            face_image: BGR numpy array containing only the cropped face area.

        Returns:
            A NumPy array representing the face embedding vector.
        """
        pass


class DummyFaceEmbedder(FaceEmbedder):
    """Placeholder embedder returning dummy vectors for development/testing."""

    def generate_embedding(self, face_image: np.ndarray) -> np.ndarray:
        """Returns an empty 1D float32 numpy array as a mock embedding.

        Args:
            face_image: BGR numpy array of the cropped face.

        Returns:
            An empty float32 numpy array.
        """
        return np.array([], dtype=np.float32)


class RealFaceEmbedder(FaceEmbedder):
    """Real FaceEmbedder implementation using the lightweight FaceNet ONNX model."""

    def __init__(self, model_path: str | None = None) -> None:
        from visionauth.recognition.recognition_embeddings import EmbeddingExtractor
        self.extractor = EmbeddingExtractor(model_path)

    def generate_embedding(self, face_image: np.ndarray) -> np.ndarray:
        """Extracts face embeddings using the underlying ONNX extractor.

        Args:
            face_image: BGR numpy array containing only the cropped face area.

        Returns:
            A 128-dimensional L2-normalized face embedding.
        """
        return self.extractor.extract_embedding(face_image)
