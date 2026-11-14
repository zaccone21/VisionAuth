"""Unlocks the session when the enrolled user sits in front of the camera.

The service watches the session state. While it is locked, it keeps the
camera open and runs authentication attempts; a successful one leaves a
short-lived verification that the sign-in screen component takes, once, to
unlock the session. While the session is unlocked the camera stays closed.

It also reports a phase (camera starting, searching, face in view, face not
recognized, verified) that the sign-in screen shows to the user.

Nothing here touches the Windows API: the session state, the camera and the
authentication are injected, so the logic is testable on its own.
"""

import logging
import threading
import time
from collections.abc import Callable, Generator

import numpy as np

from visionauth.auth.auth_service import AuthResult
from visionauth.camera.camera import Camera, CameraError

logger = logging.getLogger(__name__)

# Failures that a retry a moment later cannot fix: wait longer before trying again
CONFIGURATION_FAILURES = ("user_not_found", "incompatible_profile", "invalid_profile_data", "camera_error")

# Phases reported to the sign-in screen
PHASE_IDLE = "idle"
PHASE_STARTING = "starting"
PHASE_SEARCHING = "searching"
PHASE_FACE = "face"
PHASE_UNRECOGNIZED = "unrecognized"
PHASE_VERIFIED = "verified"

FACE_RECENT_SECONDS = 1.0
UNRECOGNIZED_SECONDS = 3.0


class HeldCamera:
    """Frame source for AuthService that leaves the camera open between attempts.

    Camera.frames() releases the device when the generator is discarded, which
    happens at the end of every authentication attempt. Reopening it costs
    over a second, so the service holds it open and feeds AuthService through
    this wrapper.

    Some drivers hand out the same frame twice when read faster than they
    capture. Repeated frames carry no new information and make the face look
    frozen to the liveness check, so they are skipped.
    """

    def __init__(self, camera: Camera) -> None:
        self.camera = camera

    @property
    def is_running(self) -> bool:
        return self.camera.is_running

    def start(self) -> None:
        self.camera.start()

    def stop(self) -> None:
        self.camera.stop()

    def frames(self) -> Generator[np.ndarray, None, None]:
        previous: np.ndarray | None = None
        while self.camera.is_running:
            frame = self.camera.capture_frame()
            if frame is None:
                return
            sample = frame[::16, ::16]
            if previous is not None and np.array_equal(sample, previous):
                continue
            previous = sample.copy()
            yield frame


class UnlockService:
    """Turns "the owner is in front of the locked screen" into a one-time verification."""

    def __init__(
        self,
        is_locked: Callable[[], bool],
        authenticate: Callable[[], AuthResult],
        camera: HeldCamera,
        verification_ttl: float = 15.0,
        idle_poll: float = 0.2,
        failure_pause: float = 0.3,
        configuration_pause: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initializes the service.

        Args:
            is_locked: Whether the session to unlock is locked (or nobody is signed in).
            authenticate: Runs one bounded authentication attempt for the owner.
            camera: Camera held open while the session is locked.
            verification_ttl: Seconds a successful verification stays available.
            idle_poll: Seconds between session checks while unlocked.
            failure_pause: Pause after a rejected attempt (e.g. a spoof).
            configuration_pause: Pause after a failure retrying cannot fix.
            clock: Monotonic clock, injectable for tests.
            sleep: Sleep function, injectable for tests.
        """
        self.is_locked = is_locked
        self.authenticate = authenticate
        self.camera = camera
        self.verification_ttl = verification_ttl
        self.idle_poll = idle_poll
        self.failure_pause = failure_pause
        self.configuration_pause = configuration_pause
        self.clock = clock
        self.sleep = sleep

        self._lock = threading.Lock()
        self._verified_until: float | None = None
        self._verified_user: str | None = None
        self._locked = False
        self._last_face: float | None = None
        self._unrecognized_until: float | None = None

    def note_face(self) -> None:
        """Records that a face is in view (called for each detected face)."""
        self._last_face = self.clock()

    @property
    def phase(self) -> str:
        """What the service is doing, for the sign-in screen."""
        now = self.clock()
        if not self._locked:
            return PHASE_IDLE
        if self.has_verification():
            return PHASE_VERIFIED
        if not self.camera.is_running:
            return PHASE_STARTING
        if self._unrecognized_until is not None and now <= self._unrecognized_until:
            return PHASE_UNRECOGNIZED
        if self._last_face is not None and now - self._last_face <= FACE_RECENT_SECONDS:
            return PHASE_FACE
        return PHASE_SEARCHING

    def take_verification(self) -> str | None:
        """Consumes the current verification, if any.

        Returns:
            The verified user, or None. A verification can be taken only once,
            so a replayed request cannot unlock the session a second time.
        """
        with self._lock:
            if self._verified_until is None or self.clock() > self._verified_until:
                return None
            user = self._verified_user
            self._verified_until = None
            self._verified_user = None
            return user

    def has_verification(self) -> bool:
        with self._lock:
            return self._verified_until is not None and self.clock() <= self._verified_until

    def _clear_verification(self) -> None:
        with self._lock:
            self._verified_until = None
            self._verified_user = None

    def step(self) -> None:
        """Runs one iteration: idle while unlocked, authenticate while locked."""
        self._locked = self.is_locked()
        if not self._locked:
            if self.camera.is_running:
                logger.info("Session unlocked: releasing the camera.")
                self.camera.stop()
            self._clear_verification()
            self._last_face = None
            self._unrecognized_until = None
            self.sleep(self.idle_poll)
            return

        if self.has_verification():
            # Waiting for the sign-in screen to take it
            self.sleep(0.05)
            return

        if not self.camera.is_running:
            try:
                logger.info("Session locked: opening the camera.")
                started = self.clock()
                self.camera.start()
                logger.info("Camera open in %.2f s.", self.clock() - started)
            except CameraError as e:
                logger.error("Could not open the camera: %s", e)
                self.sleep(self.configuration_pause)
                return

        attempt_started = self.clock()
        result = self.authenticate()
        if result.success:
            logger.info("Owner verified (similarity %.3f).", result.confidence)
            with self._lock:
                self._verified_until = self.clock() + self.verification_ttl
                self._verified_user = result.user
            self._unrecognized_until = None
            return

        face_seen = self._last_face is not None and self._last_face >= attempt_started
        if result.reason in CONFIGURATION_FAILURES:
            logger.error("Authentication cannot run: %s", result.reason)
            self.sleep(self.configuration_pause)
        elif result.reason == "spoof_detected":
            logger.warning("Rejected a face that did not look live.")
            self.sleep(self.failure_pause)
        else:
            if face_seen:
                self._unrecognized_until = self.clock() + UNRECOGNIZED_SECONDS
            logger.debug("No verification this attempt: %s", result.reason)

    def run(self, stop: threading.Event) -> None:
        """Runs until stop is set, then releases the camera."""
        logger.info("Unlock service running.")
        try:
            while not stop.is_set():
                try:
                    self.step()
                except Exception:
                    logger.exception("Unexpected error in the unlock loop.")
                    self.sleep(self.failure_pause)
        finally:
            if self.camera.is_running:
                self.camera.stop()
            logger.info("Unlock service stopped.")
