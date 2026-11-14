"""AuthService publishes its outcome on the EventBus."""

from unittest.mock import MagicMock

import numpy as np

from visionauth.auth.auth_service import AuthService
from visionauth.camera.camera import Camera
from visionauth.enrollment.embedder import RealFaceEmbedder
from visionauth.events.event_bus import EventBus, EventType
from visionauth.persistence.persistence import UserPersistence
from visionauth.recognition.recognition import DetectionResult, Recognition
from visionauth.recognition.recognition_embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_VERSION,
)

FRAMES = 11


def _reference() -> np.ndarray:
    vector = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
    vector[0] = 1.0
    return vector


def _service(profile: dict | None, live: bool, event_bus: EventBus) -> AuthService:
    """Builds an AuthService whose camera shows one face for FRAMES frames.

    Args:
        profile: What persistence returns for the user.
        live: True for a moving face matching the reference, False for a static photo.
        event_bus: Bus the service publishes on.
    """
    camera = MagicMock(spec=Camera)
    camera.is_running = False
    camera.frames.return_value = [np.ones((480, 640, 3), dtype=np.uint8)] * FRAMES

    recognition = MagicMock(spec=Recognition)
    shift = (lambda i: 0.002 * (i % 3 - 1)) if live else (lambda i: 0.0)
    recognition.process_frame.side_effect = [
        [DetectionResult(bounding_box=(0.35 + shift(i), 0.35, 0.3, 0.3), confidence=0.9)]
        for i in range(FRAMES)
    ]

    persistence = MagicMock(spec=UserPersistence)
    persistence.load_user_profile.return_value = profile

    embedder = MagicMock(spec=RealFaceEmbedder)
    if live:
        rng = np.random.default_rng(123)
        embeddings = []
        for _ in range(FRAMES):
            emb = _reference() + rng.normal(0.0, 0.02, EMBEDDING_DIMENSION).astype(np.float32)
            embeddings.append(emb / np.linalg.norm(emb))
        embedder.generate_embedding.side_effect = embeddings
    else:
        embedder.generate_embedding.return_value = _reference()

    return AuthService(
        camera=camera,
        recognition=recognition,
        persistence=persistence,
        embedder=embedder,
        event_bus=event_bus,
        auth_threshold=0.65,
        max_auth_time=2.0,
    )


def _profile() -> dict:
    return {
        "user": "test_user",
        "embeddings": [_reference().tolist()],
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "embedding_version": EMBEDDING_VERSION,
    }


def _record(event_bus: EventBus) -> list[tuple[str, dict]]:
    received: list[tuple[str, dict]] = []
    for event in (
        EventType.FACE_RECOGNIZED,
        EventType.AUTH_SUCCESS,
        EventType.AUTH_FAILED,
        EventType.UNLOCK_REQUESTED,
    ):
        event_bus.subscribe(event, lambda payload, name=event.value: received.append((name, payload)))
    return received


def test_success_publishes_recognized_success_and_unlock_in_order() -> None:
    event_bus = EventBus()
    received = _record(event_bus)

    result = _service(_profile(), live=True, event_bus=event_bus).authenticate("test_user")

    assert result.success is True
    assert [name for name, _ in received] == ["FACE_RECOGNIZED", "AUTH_SUCCESS", "UNLOCK_REQUESTED"]
    for _, payload in received:
        assert payload["user"] == "test_user"
    assert received[0][1]["confidence"] == result.confidence
    assert received[1][1]["confidence"] == result.confidence


def test_spoof_publishes_only_auth_failed_with_reason() -> None:
    event_bus = EventBus()
    received = _record(event_bus)

    result = _service(_profile(), live=False, event_bus=event_bus).authenticate("test_user")

    assert result.reason == "spoof_detected"
    assert received == [("AUTH_FAILED", {"user": "test_user", "reason": "spoof_detected"})]


def test_unknown_user_publishes_auth_failed() -> None:
    event_bus = EventBus()
    received = _record(event_bus)

    _service(None, live=True, event_bus=event_bus).authenticate("ghost")

    assert received == [("AUTH_FAILED", {"user": "ghost", "reason": "user_not_found"})]


def test_works_without_event_bus() -> None:
    service = _service(_profile(), live=True, event_bus=EventBus())
    service.event_bus = None

    assert service.authenticate("test_user").success is True
