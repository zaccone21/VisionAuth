"""Wires the unlock service to Windows: session state, camera, profiles and the pipe."""

import logging
import threading
from typing import Any

from integration.windows.pipe_server import SYSTEM_ONLY_SDDL, PipeServer
from integration.windows.session import console_session_id, session_locked, session_user
from visionauth.auth.auth_service import AuthResult, AuthService
from visionauth.camera.camera import Camera
from visionauth.events.event_bus import EventBus
from visionauth.persistence.persistence import UserPersistence
from visionauth.recognition.recognition import Recognition
from visionauth.service.unlock_service import HeldCamera, UnlockService

logger = logging.getLogger(__name__)


def resolve_target(profiles: dict[str, str]) -> tuple[str | None, bool]:
    """Which VisionAuth profile to verify, and whether the console is waiting for a sign-in.

    Args:
        profiles: Windows user name (any case) to VisionAuth profile name.

    Returns:
        (profile, waiting). With somebody signed in, the profile is theirs and
        waiting means their session is locked. With nobody signed in (sign-in
        screen after boot) the only configured profile is used.
    """
    by_user = {user.lower(): profile for user, profile in profiles.items()}
    console = console_session_id()
    user = session_user(console)
    if user is None:
        only = next(iter(by_user.values())) if len(by_user) == 1 else None
        return only, True
    return by_user.get(user.lower()), bool(session_locked(console))


def build(config: dict[str, Any]) -> tuple[UnlockService, PipeServer]:
    """Builds the unlock service and its pipe from the service configuration."""
    profiles: dict[str, str] = config["profiles"]
    event_bus = EventBus()
    recognition = Recognition(event_bus=event_bus, confidence_threshold=float(config.get("min_confidence", 0.5)))
    camera = HeldCamera(Camera(device_index=int(config.get("camera", 0)), width=640, height=480, fps=30.0))
    auth = AuthService(
        camera=camera,
        recognition=recognition,
        persistence=UserPersistence(config.get("data_dir", "data")),
        max_auth_time=float(config.get("attempt_seconds", 4.0)),
        event_bus=event_bus,
    )

    def is_locked() -> bool:
        profile, waiting = resolve_target(profiles)
        return waiting and profile is not None

    def authenticate() -> AuthResult:
        profile, _ = resolve_target(profiles)
        if profile is None:
            return AuthResult(success=False, reason="user_not_found", confidence=0.0, user=None)
        return auth.authenticate(profile)

    service = UnlockService(is_locked=is_locked, authenticate=authenticate, camera=camera)

    def handle_request(line: str) -> str:
        if line == "STATUS":
            user = service.take_verification()
            if user:
                logger.info("Verification handed to the sign-in screen for '%s'.", user)
                return f"MATCH {user}"
            return "NONE"
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
