"""AuthService compares one live face against every enrolled face."""

from unittest.mock import MagicMock

import numpy as np

from visionauth.auth.auth_service import AuthService
from visionauth.camera.camera import Camera
from visionauth.enrollment.embedder import RealFaceEmbedder
from visionauth.persistence.persistence import UserPersistence
from visionauth.recognition.recognition import DetectionResult, Recognition
from visionauth.recognition.recognition_embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_VERSION,
)

FRAMES = 11


def axis(index: int) -> list[float]:
    vector = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
    vector[index] = 1.0
    return vector.tolist()


def profile(name: str, sample: list[float], model: str = EMBEDDING_MODEL) -> dict:
    return {
        "user": name,
        "embeddings": [sample],
        "embedding_model": model,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "embedding_version": EMBEDDING_VERSION,
    }


def make_service(profiles: dict[str, dict | None]) -> AuthService:
    """A live face close to axis 0 in front of the camera, and these enrolled faces."""
    camera = MagicMock(spec=Camera)
    camera.is_running = False
    camera.frames.return_value = [np.ones((480, 640, 3), dtype=np.uint8)] * FRAMES

    recognition = MagicMock(spec=Recognition)
    recognition.process_frame.side_effect = [
        [DetectionResult(bounding_box=(0.35 + 0.002 * (i % 3 - 1), 0.35, 0.3, 0.3), confidence=0.9)]
        for i in range(FRAMES)
    ]

    persistence = MagicMock(spec=UserPersistence)
    persistence.load_user_profile.side_effect = lambda name: profiles.get(name)

    rng = np.random.default_rng(123)
    embeddings = []
    for _ in range(FRAMES):
        emb = np.array(axis(0), dtype=np.float32) + rng.normal(0.0, 0.02, EMBEDDING_DIMENSION).astype(np.float32)
        embeddings.append(emb / np.linalg.norm(emb))
    embedder = MagicMock(spec=RealFaceEmbedder)
    embedder.generate_embedding.side_effect = embeddings

    return AuthService(
        camera=camera,
        recognition=recognition,
        persistence=persistence,
        embedder=embedder,
        auth_threshold=0.65,
        max_auth_time=2.0,
    )


def test_matches_the_closest_face() -> None:
    service = make_service({"Ana": profile("Ana", axis(1)), "Joaquín": profile("Joaquín", axis(0))})
    result = service.authenticate_any(["Ana", "Joaquín"])
    assert result.success
    assert result.user == "Joaquín"


def test_missing_or_incompatible_face_is_skipped() -> None:
    service = make_service(
        {"Vieja": profile("Vieja", axis(0), model="old-model"), "Joaquín": profile("Joaquín", axis(0))}
    )
    result = service.authenticate_any(["Borrada", "Vieja", "Joaquín"])
    assert result.success
    assert result.user == "Joaquín"


def test_no_usable_face_fails_without_camera() -> None:
    service = make_service({})
    result = service.authenticate_any(["Borrada"])
    assert result.reason == "user_not_found"
    service.camera.start.assert_not_called()


def test_empty_list_fails_without_camera() -> None:
    service = make_service({})
    result = service.authenticate_any([])
    assert result.reason == "user_not_found"
    service.camera.start.assert_not_called()
