"""Wires the unlock service to Windows: session state, camera, profiles and the pipe."""

import logging
import threading
from typing import Any

from integration.windows.pipe_server import SYSTEM_ONLY_SDDL, PipeServer
from integration.windows.session import console_session_id, session_locked, session_user
from visionauth.auth.auth_service import AuthResult, AuthService
from visionauth.camera.camera import Camera
from visionauth.events.event_bus import EventBus, EventType
from visionauth.faces import list_faces
from visionauth.persistence.persistence import UserPersistence
from visionauth.recognition.recognition import Recognition
from visionauth.service.unlock_service import HeldCamera, UnlockService
from visionauth.settings import configured_account, match_threshold

logger = logging.getLogger(__name__)


def console_waiting(account: str | None) -> bool:
    """Whether the console is waiting for the configured account to sign in.

    True on the sign-in screen after boot (nobody signed in) and while the
    account's own session is locked. Windows user names ignore case.
    """
    if account is None:
        return False
    console = console_session_id()
    user = session_user(console)
    if user is None:
        return True
    return user.lower() == account.lower() and bool(session_locked(console))


def status_reply(service: UnlockService) -> str:
    """Answer to the sign-in screen's STATUS request.

    The verification is taken here, once: "MATCH <face>" greets the face that
    was recognized by its name.
    """
    user = service.take_verification()
    if user:
        logger.info("Verification handed to the sign-in screen for '%s'.", user)
        return f"MATCH {user}"
    return f"STATE {service.phase}"


def build(config: dict[str, Any]) -> tuple[UnlockService, PipeServer]:
    """Builds the unlock service and its pipe from the service configuration."""
    account = configured_account(config)
    data_dir = config.get("data_dir", "data")
    event_bus = EventBus()
    recognition = Recognition(event_bus=event_bus, confidence_threshold=float(config.get("min_confidence", 0.5)))
    # No resolution or frame rate: asking DirectShow for them costs about 2.5 s on
    # every open, and this camera ignores them anyway
    camera = HeldCamera(Camera(device_index=int(config.get("camera", 0))))
    auth = AuthService(
        camera=camera,
        recognition=recognition,
        persistence=UserPersistence(data_dir),
        auth_threshold=match_threshold(config),
        max_auth_time=float(config.get("attempt_seconds", 4.0)),
        event_bus=event_bus,
    )
    logger.info("Unlocking '%s' with any enrolled face, threshold %.2f.", account, auth.auth_threshold)

    def face_names() -> list[str]:
        # Read on every attempt: faces added or removed apply without a restart
        return [face.name for face in list_faces(data_dir)]

    def is_locked() -> bool:
        # With no face enrolled the camera stays closed
        return console_waiting(account) and bool(face_names())

    def authenticate() -> AuthResult:
        return auth.authenticate_any(face_names())

    service = UnlockService(is_locked=is_locked, authenticate=authenticate, camera=camera)
    event_bus.subscribe(EventType.FACE_DETECTED, lambda payload: service.note_face())

    def handle_request(line: str) -> str:
        if line == "STATUS":
            return status_reply(service)
        return "ERROR unknown request"

    pipe = PipeServer(handle_request, sddl=config.get("pipe_sddl", SYSTEM_ONLY_SDDL))
    return service, pipe


def run(config: dict[str, Any], stop: threading.Event) -> None:
    """Runs the pipe and the unlock loop until stop is set."""
    service, pipe = build(config)
    pipe.start()
    try:
        service.run(stop)
    finally:
        pipe.stop()
