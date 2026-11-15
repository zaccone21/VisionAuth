"""Tests for the session unlock loop."""

from unittest.mock import MagicMock

import numpy as np

from visionauth.auth.auth_service import AuthResult
from visionauth.camera.camera import Camera, CameraError
from visionauth.service.unlock_service import AWAY_SECONDS, HeldCamera, UnlockService

SUCCESS = AuthResult(success=True, reason="success", confidence=0.8, user="owner")
NO_FACE = AuthResult(success=False, reason="timeout", confidence=0.0, user=None)


class FakeCamera:
    def __init__(self, fail_start: bool = False) -> None:
        self.is_running = False
        self.fail_start = fail_start
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        if self.fail_start:
            raise CameraError("busy")
        self.starts += 1
        self.is_running = True

    def stop(self) -> None:
        self.stops += 1
        self.is_running = False


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_service(locked: list[bool], results: list[AuthResult], camera: FakeCamera | None = None, clock=None):
    state = {"locked": locked}
    service = UnlockService(
        is_locked=lambda: state["locked"][0],
        authenticate=MagicMock(side_effect=results),
        camera=camera or FakeCamera(),
        clock=clock or Clock(),
        sleep=lambda seconds: None,
    )
    return service, state


def test_unlocked_session_keeps_camera_closed_and_never_authenticates() -> None:
    service, _ = make_service([False], [])
    service.step()
    service.step()
    assert service.camera.starts == 0
    service.authenticate.assert_not_called()


def test_locked_session_opens_camera_and_verifies_owner_once() -> None:
    service, _ = make_service([True], [SUCCESS])
    service.step()

    assert service.camera.is_running
    assert service.take_verification() == "owner"
    assert service.take_verification() is None


def test_no_new_attempts_while_a_verification_is_pending() -> None:
    service, _ = make_service([True], [SUCCESS])
    service.step()
    service.step()
    service.step()
    assert service.authenticate.call_count == 1


def test_verification_expires() -> None:
    clock = Clock()
    service, _ = make_service([True], [SUCCESS], clock=clock)
    service.step()
    clock.now += service.verification_ttl + 1
    assert service.take_verification() is None


def test_failed_attempt_leaves_no_verification_and_retries() -> None:
    service, _ = make_service([True], [NO_FACE, SUCCESS])
    service.step()
    assert service.take_verification() is None
    service.step()
    assert service.take_verification() == "owner"


def test_unlocking_releases_camera_and_drops_pending_verification() -> None:
    service, state = make_service([True], [SUCCESS])
    service.step()
    state["locked"] = [False]
    service.step()

    assert not service.camera.is_running
    assert service.take_verification() is None


def test_camera_error_does_not_crash_the_loop() -> None:
    service, _ = make_service([True], [], camera=FakeCamera(fail_start=True))
    service.step()
    service.authenticate.assert_not_called()


def test_held_camera_yields_frames_without_releasing_the_device() -> None:
    camera = MagicMock(spec=Camera)
    camera.is_running = True
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    camera.capture_frame.side_effect = [frame, frame, None]

    held = HeldCamera(camera)
    frames = held.frames()
    next(frames)
    frames.close()

    camera.stop.assert_not_called()
    assert held.is_running


def test_held_camera_skips_repeated_frames() -> None:
    camera = MagicMock(spec=Camera)
    camera.is_running = True
    first = np.zeros((32, 32, 3), dtype=np.uint8)
    second = np.full((32, 32, 3), 9, dtype=np.uint8)
    camera.capture_frame.side_effect = [first, first.copy(), second, second.copy(), None]

    assert len(list(HeldCamera(camera).frames())) == 2


def test_phase_follows_the_session_and_the_face() -> None:
    clock = Clock()
    service, state = make_service([False], [NO_FACE, SUCCESS], clock=clock)
    service.step()
    assert service.phase == "idle"

    state["locked"] = [True]
    service.is_locked = lambda: True
    service._locked = True
    assert service.phase == "starting"

    service.authenticate.side_effect = lambda: (service.note_face(), NO_FACE)[1]
    service.step()
    assert service.phase == "unrecognized"

    clock.now += 5
    assert service.phase == "searching"
    service.note_face()
    assert service.phase == "face"

    service.authenticate.side_effect = [SUCCESS]
    service.step()
    assert service.phase == "verified"
    service.take_verification()
    assert service.phase == "face"


def test_phase_goes_away_after_a_while_without_a_face_and_back_on_one() -> None:
    clock = Clock()
    service, state = make_service([True], [NO_FACE] * 4, clock=clock)
    service.step()
    # Right after the lock it looks for a face at once
    assert service.phase == "searching"
    clock.now += AWAY_SECONDS - 1
    assert service.phase == "searching"
    clock.now += 2
    assert service.phase == "away"

    service.note_face()
    assert service.phase == "face"
    clock.now += AWAY_SECONDS + 1
    assert service.phase == "away"

    # A new lock starts searching again, without waiting
    state["locked"] = [False]
    service.step()
    state["locked"] = [True]
    service.step()
    assert service.phase == "searching"
