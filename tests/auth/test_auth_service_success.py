"""Unit test for successful authentication flow."""

import numpy as np
from unittest.mock import MagicMock
from visionauth.camera.camera import Camera
from visionauth.recognition.recognition import Recognition, DetectionResult
from visionauth.persistence.persistence import UserPersistence
from visionauth.auth.auth_service import AuthService
from visionauth.enrollment.embedder import RealFaceEmbedder


def test_auth_service_success() -> None:
    """Verifies that authentication succeeds for a valid, live matching user."""
    # 1. Setup mock camera returning 11 frames
    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    mock_camera.frames.return_value = [dummy_frame] * 11

    # 2. Setup mock recognition returning exactly 1 face per frame with micro-movement
    mock_recognition = MagicMock(spec=Recognition)
    detections = []
    for i in range(11):
        shift = 0.002 * (i % 3 - 1)
        detections.append([
            DetectionResult(bounding_box=(0.35 + shift, 0.35, 0.3, 0.3), confidence=0.9)
        ])
    mock_recognition.process_frame.side_effect = detections

    # 3. Setup mock persistence loading centroid
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

    # 4. Setup mock embedder returning embeddings with slight noise
    mock_embedder = MagicMock(spec=RealFaceEmbedder)
    np.random.seed(123)
    embeddings = []
    for i in range(11):
        emb = np.zeros(512, dtype=np.float32)
        emb[0] = 1.0
        noise = np.random.normal(0.0, 0.02, 512).astype(np.float32)
        emb += noise
        emb /= np.linalg.norm(emb)
        embeddings.append(emb)
    mock_embedder.generate_embedding.side_effect = embeddings

    # 5. Initialize AuthService and run authentication
    service = AuthService(
        camera=mock_camera,
        recognition=mock_recognition,
        persistence=mock_persistence,
        embedder=mock_embedder,
        auth_threshold=0.65,
        max_auth_time=2.0
    )

    res = service.authenticate("test_user")
    assert res.success is True
    assert res.reason == "success"
    assert res.user == "test_user"
    assert res.confidence > 0.8
