"""Unit tests for the Enrollment module."""

import json
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from visionauth.camera.camera import Camera, CameraError
from visionauth.config.config import EnrollmentConfig
from visionauth.events.event_bus import EventBus
from visionauth.enrollment.enrollment import (
    EnrollmentError,
    EnrollmentService,
    EnrollmentTimeoutError,
    InvalidUserError,
    UserAlreadyExistsError,
)
from visionauth.persistence.persistence import UserPersistence
from visionauth.recognition.recognition_embeddings import EMBEDDING_DIMENSION
from visionauth.recognition.recognition import DetectionResult, Recognition


def create_detection(confidence: float) -> DetectionResult:
    """Helper to create a DetectionResult."""
    return DetectionResult(bounding_box=(0.1, 0.2, 0.3, 0.4), confidence=confidence)


def test_enrollment_success(tmp_path: pytest.TempPathFactory) -> None:
    """Tests successful user enrollment under ideal conditions."""
    # 1. Setup paths
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=3,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
    )

    # 2. Mock Camera
    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    mock_camera.frames.return_value = [dummy_frame, dummy_frame, dummy_frame]

    # 3. Mock Recognition
    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.return_value = [create_detection(0.85)]

    # 4. Event Bus
    event_bus = MagicMock(spec=EventBus)

    # 5. Service
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
    )

    # 6. Execute
    metadata = service.enroll("test_user")

    # 7. Assertions
    assert metadata["name"] == "test_user"
    assert metadata["sample_count"] == 3
    assert metadata["model_version"] == "v0.0.0"
    assert metadata["format_version"] == "1.0"

    mock_camera.start.assert_called_once()
    mock_camera.stop.assert_called_once()
    assert mock_recognition.process_frame.call_count == 3

    # Check persistence directories & files
    user_dir = os.path.join(data_dir, "users", "test_user")
    assert os.path.isdir(user_dir)

    samples_dir = os.path.join(user_dir, "samples")
    assert os.path.isdir(samples_dir)
    assert len(os.listdir(samples_dir)) == 3
    assert os.path.exists(os.path.join(samples_dir, "sample_001.jpg"))
    assert os.path.exists(os.path.join(samples_dir, "sample_002.jpg"))
    assert os.path.exists(os.path.join(samples_dir, "sample_003.jpg"))

    metadata_path = os.path.join(user_dir, "metadata.json")
    assert os.path.exists(metadata_path)
    with open(metadata_path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["name"] == "test_user"
    assert loaded["sample_count"] == 3

    # EventBus assertions
    event_bus.emit.assert_any_call("ENROLLMENT_STARTED", {"username": "test_user"})
    event_bus.emit.assert_any_call("ENROLLMENT_COMPLETED", {"username": "test_user", "sample_count": 3})


@pytest.mark.parametrize(
    "invalid_name",
    [
        "",
        "   ",
        "user/name",
        "user\\name",
        "../traverse",
        "user*name",
        "user?name",
    ],
)
def test_enrollment_invalid_username(invalid_name: str) -> None:
    """Tests that invalid usernames are rejected before camera starts."""
    mock_camera = MagicMock(spec=Camera)
    mock_recognition = MagicMock(spec=Recognition)
    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(mock_camera, mock_recognition, event_bus)

    with pytest.raises(InvalidUserError):
        service.enroll(invalid_name)

    mock_camera.start.assert_not_called()


def test_enrollment_user_already_exists(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that attempting to register an already enrolled user raises an error."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(data_dir=data_dir)

    mock_camera = MagicMock(spec=Camera)
    mock_recognition = MagicMock(spec=Recognition)
    event_bus = MagicMock(spec=EventBus)

    # Create dummy user folder to simulate registration
    os.makedirs(os.path.join(data_dir, "users", "existing_user"))

    service = EnrollmentService(mock_camera, mock_recognition, event_bus, config=config)

    with pytest.raises(UserAlreadyExistsError, match="existing_user"):
        service.enroll("existing_user")

    mock_camera.start.assert_not_called()


@patch("time.time")
def test_enrollment_timeout(mock_time: MagicMock, tmp_path: pytest.TempPathFactory) -> None:
    """Tests that a timeout raises EnrollmentTimeoutError when no face is found in time."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=3,
        max_time_between_captures=5.0,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)

    # Use a stateful frame generator to progress mock time naturally per frame
    current_time = 100.0
    def frames_generator():
        nonlocal current_time
        current_time = 100.0
        yield dummy_frame
        current_time = 106.0
        yield dummy_frame

    mock_camera.frames.return_value = frames_generator()

    # No faces detected
    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.return_value = []

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(mock_camera, mock_recognition, event_bus, config=config)

    mock_time.side_effect = lambda: current_time

    with pytest.raises(EnrollmentTimeoutError, match="Timeout exceeded between captures"):
        service.enroll("timed_out_user")

    mock_camera.stop.assert_called_once()


def test_enrollment_multiple_faces_discarded(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that frames with multiple faces are discarded and do not count."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=2,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    # Stream returns 4 frames:
    # 1. 2 faces (discarded)
    # 2. 1 face (accepted)
    # 3. 3 faces (discarded)
    # 4. 1 face (accepted)
    mock_camera.frames.return_value = [dummy_frame, dummy_frame, dummy_frame, dummy_frame]

    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.side_effect = [
        [create_detection(0.8), create_detection(0.9)],  # 2 faces
        [create_detection(0.85)],                       # 1 face
        [create_detection(0.7), create_detection(0.8), create_detection(0.9)],  # 3 faces
        [create_detection(0.95)],                       # 1 face
    ]

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(mock_camera, mock_recognition, event_bus, config=config)

    metadata = service.enroll("multi_face_user")
    assert metadata["sample_count"] == 2
    assert mock_recognition.process_frame.call_count == 4


def test_enrollment_insufficient_confidence_discarded(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that frames with low face confidence are discarded."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=2,
        min_confidence=0.6,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    # Stream returns 3 frames:
    # 1. confidence 0.4 (discarded)
    # 2. confidence 0.7 (accepted)
    # 3. confidence 0.8 (accepted)
    mock_camera.frames.return_value = [dummy_frame, dummy_frame, dummy_frame]

    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.side_effect = [
        [create_detection(0.4)],  # Below threshold
        [create_detection(0.7)],  # Above threshold
        [create_detection(0.8)],  # Above threshold
    ]

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(mock_camera, mock_recognition, event_bus, config=config)

    metadata = service.enroll("low_conf_user")
    assert metadata["sample_count"] == 2
    assert mock_recognition.process_frame.call_count == 3


def test_enrollment_camera_start_error() -> None:
    """Tests that camera start failure aborts enrollment."""
    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    mock_camera.start.side_effect = CameraError("Could not initialize device")

    mock_recognition = MagicMock(spec=Recognition)
    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(mock_camera, mock_recognition, event_bus)

    with pytest.raises(CameraError, match="Could not initialize device"):
        service.enroll("camera_error_user")

    mock_camera.frames.assert_not_called()
    mock_camera.stop.assert_not_called()


def test_enrollment_camera_stream_premature_end() -> None:
    """Tests when camera stream ends before capturing all required samples."""
    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    # Yields only 1 frame, but we need 3 samples
    mock_camera.frames.return_value = [dummy_frame]

    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.return_value = [create_detection(0.8)]

    event_bus = MagicMock(spec=EventBus)
    config = EnrollmentConfig(
        num_samples=3,
        stability_window_size=1,
        stability_consecutive_threshold=1,
    )
    service = EnrollmentService(mock_camera, mock_recognition, event_bus, config=config)

    with pytest.raises(EnrollmentError, match="Camera stream closed prematurely"):
        service.enroll("premature_end_user")

    mock_camera.stop.assert_called_once()


def test_enrollment_persistence_error(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that filesystem errors during save propagate as EnrollmentError."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=1,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    mock_camera.frames.return_value = [dummy_frame]

    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.return_value = [create_detection(0.9)]

    mock_persistence = MagicMock(spec=UserPersistence)
    mock_persistence.user_exists.return_value = False
    mock_persistence.save_user.side_effect = IOError("Disk full or permission denied")

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        persistence=mock_persistence,
        config=config,
    )

    with pytest.raises(EnrollmentError, match="Failed to save enrollment data"):
        service.enroll("io_error_user")


def test_enrollment_stability_tracking(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that the temporal stability tracker filters out face count flickering."""
    data_dir = str(tmp_path)
    # Set threshold to 3 consecutive frames
    config = EnrollmentConfig(
        num_samples=2,
        data_dir=data_dir,
        stability_window_size=5,
        stability_consecutive_threshold=3,
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)

    # Frame stream:
    # 1: raw=1 (not sustained, stable=0, discarded)
    # 2: raw=1 (not sustained, stable=0, discarded)
    # 3: raw=1 (sustained 3x, stable=1, accepted sample 1)
    # 4: raw=0 (flicker drop, stable=1, but raw=0, skipped)
    # 5: raw=1 (stable=1, accepted sample 2)
    mock_camera.frames.return_value = [
        dummy_frame,
        dummy_frame,
        dummy_frame,
        dummy_frame,
        dummy_frame,
    ]

    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.side_effect = [
        [create_detection(0.8)],
        [create_detection(0.8)],
        [create_detection(0.8)],  # accepted sample 1
        [],
        [create_detection(0.8)],  # accepted sample 2
    ]

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
    )

    metadata = service.enroll("stable_user")
    assert metadata["sample_count"] == 2
    samples_dir = os.path.join(data_dir, "users", "stable_user", "samples")
    assert len(os.listdir(samples_dir)) == 2


@patch("time.time")
def test_enrollment_fps_throttling(mock_time: MagicMock, tmp_path: pytest.TempPathFactory) -> None:
    """Tests that the frame processing rate is throttled when target_fps is active."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=1,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
        target_fps=10.0,  # 0.1s minimum period
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)

    # Use stateful frame generator to progress mock time naturally per frame
    current_time = 100.0
    def frames_generator():
        nonlocal current_time
        current_time = 100.0
        yield dummy_frame
        current_time = 100.05
        yield dummy_frame
        current_time = 100.20
        yield dummy_frame

    mock_camera.frames.return_value = frames_generator()

    mock_recognition = MagicMock(spec=Recognition)
    # Only 2 frames will pass the throttle check
    mock_recognition.process_frame.side_effect = [
        [],  # 1st processed frame (t=100.0): 0 faces
        [create_detection(0.9)],  # 2nd processed frame (t=100.20): 1 face (accepted)
    ]

    mock_time.side_effect = lambda: current_time

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
    )

    metadata = service.enroll("throttle_user")
    assert metadata["sample_count"] == 1
    assert mock_recognition.process_frame.call_count == 2


@patch("time.time")
def test_enrollment_cooldown_and_movement(mock_time: MagicMock, tmp_path: pytest.TempPathFactory) -> None:
    """Tests that enrollment respects capture cooldowns and minimum face movement thresholds."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=2,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
        cooldown_between_captures=0.5,  # 0.5s cooldown
        min_face_movement=0.05,        # 5% relative movement
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)

    # Use stateful frame generator to progress mock time naturally per frame
    current_time = 100.0
    def frames_generator():
        nonlocal current_time
        current_time = 100.0
        yield dummy_frame
        current_time = 100.1
        yield dummy_frame
        current_time = 100.6
        yield dummy_frame
        current_time = 101.2
        yield dummy_frame

    mock_camera.frames.return_value = frames_generator()

    mock_recognition = MagicMock(spec=Recognition)

    # Frame 1: center = 0.1 + 0.3/2 = 0.25 (accepted sample 1)
    # Frame 2: center = 0.25 (skipped: cooldown not met, 0.1s < 0.5s)
    # Frame 3: center = 0.1 + 0.3/2 = 0.25 (skipped: cooldown met, but movement too small, same center)
    # Frame 4: center = 0.25 + 0.3/2 = 0.40 (accepted sample 2: cooldown met 1.2s, movement met 0.15 > 0.05)
    mock_recognition.process_frame.side_effect = [
        [DetectionResult(bounding_box=(0.1, 0.2, 0.3, 0.4), confidence=0.9)],
        [DetectionResult(bounding_box=(0.1, 0.2, 0.3, 0.4), confidence=0.9)],
        [DetectionResult(bounding_box=(0.1, 0.2, 0.3, 0.4), confidence=0.9)],
        [DetectionResult(bounding_box=(0.25, 0.2, 0.3, 0.4), confidence=0.9)],
    ]

    mock_time.side_effect = lambda: current_time

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
    )

    metadata = service.enroll("cooldown_user")
    assert metadata["sample_count"] == 2
    assert mock_recognition.process_frame.call_count == 4
    samples_dir = os.path.join(data_dir, "users", "cooldown_user", "samples")
    assert len(os.listdir(samples_dir)) == 2


def test_enrollment_blur_filtering(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that blurry frames are filtered out and sharp frames are accepted."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=1,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
        min_blur_threshold=50.0,
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False

    # Frame 1, 2, 3: completely smooth ones (variance = 0.0 -> blurry)
    blurry_frame = np.ones((480, 640, 3), dtype=np.uint8)
    # Frame 4: random noise (variance > 1000.0 -> sharp)
    np.random.seed(42)
    sharp_frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)

    mock_camera.frames.return_value = [blurry_frame, blurry_frame, blurry_frame, sharp_frame]

    mock_recognition = MagicMock(spec=Recognition)
    # All frames detect a face with 0.9 confidence
    mock_recognition.process_frame.return_value = [
        DetectionResult(bounding_box=(0.35, 0.35, 0.3, 0.3), confidence=0.9)
    ]

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
    )

    metadata = service.enroll("blur_user")
    assert metadata["sample_count"] == 1
    
    # Assert event_bus was notified about the blurry discard
    event_bus.emit.assert_any_call(
        "ENROLLMENT_FRAME_DISCARDED",
        {
            "reason": "blurry",
            "current_samples": 0,
            "blur_variance": pytest.approx(0.0, abs=1e-2),
        }
    )


def test_enrollment_centeredness_check(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that off-center frames are rejected and centered frames are accepted."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=1,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
        max_face_offset=0.2,  # Center must be within [0.3, 0.7]
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    mock_camera.frames.return_value = [dummy_frame, dummy_frame]

    mock_recognition = MagicMock(spec=Recognition)
    # Frame 1: center = 0.05 + 0.3/2 = 0.20 (off-center)
    # Frame 2: center = 0.35 + 0.3/2 = 0.50 (centered)
    mock_recognition.process_frame.side_effect = [
        [DetectionResult(bounding_box=(0.05, 0.35, 0.3, 0.3), confidence=0.9)],
        [DetectionResult(bounding_box=(0.35, 0.35, 0.3, 0.3), confidence=0.9)],
    ]

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
    )

    metadata = service.enroll("centered_user")
    assert metadata["sample_count"] == 1

    # Assert off-center frame was discarded with correct payload
    event_bus.emit.assert_any_call(
        "ENROLLMENT_FRAME_DISCARDED",
        {
            "reason": "off_center",
            "current_samples": 0,
            "offset": (0.3, 0.0),
        }
    )


def test_enrollment_face_size_check(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that faces that are too small or too large are filtered out."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=1,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
        min_face_size=0.2,
        max_face_size=0.6,
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    mock_camera.frames.return_value = [dummy_frame, dummy_frame, dummy_frame]

    mock_recognition = MagicMock(spec=Recognition)
    # Frame 1: size = 0.1 (too small)
    # Frame 2: size = 0.7 (too large)
    # Frame 3: size = 0.4 (perfect)
    mock_recognition.process_frame.side_effect = [
        [DetectionResult(bounding_box=(0.45, 0.45, 0.1, 0.1), confidence=0.9)],
        [DetectionResult(bounding_box=(0.15, 0.15, 0.7, 0.7), confidence=0.9)],
        [DetectionResult(bounding_box=(0.3, 0.3, 0.4, 0.4), confidence=0.9)],
    ]

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
    )

    metadata = service.enroll("size_user")
    assert metadata["sample_count"] == 1

    # Assert both size discard events were emitted
    event_bus.emit.assert_any_call(
        "ENROLLMENT_FRAME_DISCARDED",
        {
            "reason": "face_too_small",
            "current_samples": 0,
            "size": (0.1, 0.1),
        }
    )
    event_bus.emit.assert_any_call(
        "ENROLLMENT_FRAME_DISCARDED",
        {
            "reason": "face_too_large",
            "current_samples": 0,
            "size": (0.7, 0.7),
        }
    )


def test_enrollment_pose_diversity(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that the service enforces pose diversity: limits per pose and consecutive identical poses."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=3,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
        max_samples_per_pose=1,  # Only 1 sample allowed per pose bucket
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    mock_camera.frames.return_value = [dummy_frame] * 6

    mock_recognition = MagicMock(spec=Recognition)
    
    # Frame 1: center = 0.35 + 0.3/2 = 0.50 -> Pose CENTER (accepted CENTER sample 1)
    # Frame 2: center = 0.35 + 0.3/2 = 0.50 -> Pose CENTER (rejected: duplicate consecutive pose CENTER)
    # Frame 3: center = 0.10 + 0.3/2 = 0.25 -> Pose LEFT (accepted LEFT sample 2)
    # Frame 4: center = 0.35 + 0.3/2 = 0.50 -> Pose CENTER (rejected: pose limit reached for CENTER)
    # Frame 5: center = 0.50 + 0.3/2 = 0.65 -> Pose RIGHT (accepted RIGHT sample 3)
    mock_recognition.process_frame.side_effect = [
        [DetectionResult(bounding_box=(0.35, 0.35, 0.3, 0.3), confidence=0.9)],
        [DetectionResult(bounding_box=(0.35, 0.35, 0.3, 0.3), confidence=0.9)],
        [DetectionResult(bounding_box=(0.10, 0.35, 0.3, 0.3), confidence=0.9)],
        [DetectionResult(bounding_box=(0.35, 0.35, 0.3, 0.3), confidence=0.9)],
        [DetectionResult(bounding_box=(0.50, 0.35, 0.3, 0.3), confidence=0.9)],
    ]

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
    )

    metadata = service.enroll("pose_user")
    assert metadata["sample_count"] == 3

    # Verify duplicate_pose event was emitted (occurred when samples had 1 item)
    event_bus.emit.assert_any_call(
        "ENROLLMENT_FRAME_DISCARDED",
        {
            "reason": "duplicate_pose",
            "pose": "CENTER",
            "current_samples": 1,
        }
    )

    # Verify pose_limit_reached event was emitted (occurred when samples had 2 items)
    event_bus.emit.assert_any_call(
        "ENROLLMENT_FRAME_DISCARDED",
        {
            "reason": "pose_limit_reached",
            "pose": "CENTER",
            "current_samples": 2,
        }
    )


def test_enrollment_blur_smoothing(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that isolated blurry frames are ignored, and a blurry event is only triggered after 3 consecutive frames."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=1,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
        min_blur_threshold=50.0,
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False

    # Frames 1 and 2: blurry (smooth)
    blurry_frame = np.ones((480, 640, 3), dtype=np.uint8)
    # Frame 3: sharp (random noise)
    np.random.seed(42)
    sharp_frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)

    mock_camera.frames.return_value = [blurry_frame, blurry_frame, sharp_frame]

    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.return_value = [
        DetectionResult(bounding_box=(0.35, 0.35, 0.3, 0.3), confidence=0.9)
    ]

    event_bus = MagicMock(spec=EventBus)
    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
    )

    metadata = service.enroll("blur_smoothing_user")
    assert metadata["sample_count"] == 1

    # Check that ENROLLMENT_FRAME_DISCARDED with reason="blurry" was NOT emitted, since consecutive_blurry_count only reached 2
    for call in event_bus.emit.call_args_list:
        args, kwargs = call
        if args[0] == "ENROLLMENT_FRAME_DISCARDED" and args[1].get("reason") == "blurry":
            pytest.fail("Should not emit blurry discard event for just 2 consecutive blurry frames")


def test_enrollment_self_similarity_fail(tmp_path: pytest.TempPathFactory) -> None:
    """Tests that user enrollment is cancelled if self-similarity of the last frame is too low."""
    data_dir = str(tmp_path)
    config = EnrollmentConfig(
        num_samples=1,
        data_dir=data_dir,
        stability_window_size=1,
        stability_consecutive_threshold=1,
    )

    mock_camera = MagicMock(spec=Camera)
    mock_camera.is_running = False
    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    mock_camera.frames.return_value = [dummy_frame]

    mock_recognition = MagicMock(spec=Recognition)
    mock_recognition.process_frame.return_value = [create_detection(0.85)]

    # Mock embedder that returns incompatible embeddings (e.g. opposite vectors) on consecutive calls
    # first call (during enrollment loop) returns vector A, second call (during self test) returns opposite vector -A
    mock_embedder = MagicMock()
    vec_a = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
    vec_a[0] = 1.0
    vec_b = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
    vec_b[0] = -1.0 # Cosine similarity will be -1.0
    mock_embedder.generate_embedding.side_effect = [vec_a, vec_b]

    mock_persistence = MagicMock(spec=UserPersistence)
    mock_persistence.user_exists.return_value = False
    event_bus = MagicMock(spec=EventBus)

    service = EnrollmentService(
        camera=mock_camera,
        recognition=mock_recognition,
        event_bus=event_bus,
        config=config,
        embedder=mock_embedder,
        persistence=mock_persistence,
    )

    with pytest.raises(EnrollmentError) as excinfo:
        service.enroll("fail_user")
        
    assert "low self-similarity" in str(excinfo.value)
    mock_persistence.save_user.assert_not_called()
    event_bus.emit.assert_any_call("ENROLLMENT_FAILED", {"reason": "low_self_similarity"})



