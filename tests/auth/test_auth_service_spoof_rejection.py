"""Unit tests for spoof rejection flow."""

import numpy as np
from unittest.mock import MagicMock
from visionauth.camera.camera import Camera
from visionauth.recognition.recognition import Recognition, DetectionResult
from visionauth.persistence.persistence import UserPersistence
from visionauth.auth.auth_service import AuthService
from visionauth.enrollment.embedder import RealFaceEmbedder


def test_auth_service_spoof_rejection_static_photo() -> None:
    """Verifies rejection of a static photo spoofing attempt (completely static box/embedding)."""
    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    mock_camera.frames.return_value = [dummy_frame] * 11

    # Static bounding box: no variation in center
    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.return_value = [
        DetectionResult(bounding_box=(0.35, 0.35, 0.3, 0.3), confidence=0.9)
    ]

    mock_persistence = MagicMock(spec=UserPersistence)
    centroid_vec = np.zeros(512, dtype=np.float32)
    centroid_vec[0] = 1.0
    mock_persistence.load_user_profile.return_value = {
        "user": "test_user",
        "centroid": centroid_vec.tolist(),
        "embedding_model": "FaceNet-512",
        "embedding_dimension": 512,
        "embedding_version": 2
    }

    # Static embedding: identical across all frames
    mock_embedder = MagicMock(spec=RealFaceEmbedder)
    static_emb = np.zeros(512, dtype=np.float32)
    static_emb[0] = 1.0
    mock_embedder.generate_embedding.return_value = static_emb

    service = AuthService(
        camera=mock_camera,
        recognition=mock_recognition,
        persistence=mock_persistence,
        embedder=mock_embedder,
        auth_threshold=0.65,
        max_auth_time=2.0
    )

    res = service.authenticate("test_user")
    assert res.success is False
    assert res.reason == "spoof_detected"
    assert res.user is None
