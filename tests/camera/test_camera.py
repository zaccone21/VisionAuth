"""Unit tests for the Camera class in visionauth.camera.camera."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from visionauth.camera.camera import Camera, CameraError


def test_camera_initialization() -> None:
    """Tests that the Camera class initializes properties correctly."""
    camera = Camera(device_index=0, width=640, height=480, fps=30.0)
    assert camera.device_index == 0
    assert camera.width == 640
    assert camera.height == 480
    assert camera.fps == 30.0
    assert camera.is_running is False
    assert camera._cap is None


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_camera_start_success(mock_video_capture: MagicMock) -> None:
    """Tests starting the camera successfully and setting capture properties."""
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = True
    mock_cap_instance.get.side_effect = lambda prop: {
        3: 640.0,  # cv2.CAP_PROP_FRAME_WIDTH
        4: 480.0,  # cv2.CAP_PROP_FRAME_HEIGHT
        5: 30.0,  # cv2.CAP_PROP_FPS
    }.get(prop, 0.0)

    mock_video_capture.return_value = mock_cap_instance

    camera = Camera(device_index=1, width=640, height=480, fps=30)
    camera.start()

    assert camera.is_running is True
    assert camera._cap == mock_cap_instance
    mock_video_capture.assert_called_once_with(1)

    # Assert properties were set on the VideoCapture instance
    # CAP_PROP_FRAME_WIDTH = 3, CAP_PROP_FRAME_HEIGHT = 4, CAP_PROP_FPS = 5
    mock_cap_instance.set.assert_any_call(3, 640)
    mock_cap_instance.set.assert_any_call(4, 480)
    mock_cap_instance.set.assert_any_call(5, 30)


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_camera_start_failure(mock_video_capture: MagicMock) -> None:
    """Tests starting the camera fails when VideoCapture fails to open."""
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = False
    mock_video_capture.return_value = mock_cap_instance

    camera = Camera(device_index=0)
    with pytest.raises(CameraError, match="Failed to open camera device"):
        camera.start()

    assert camera.is_running is False
    assert camera._cap is None
    mock_cap_instance.release.assert_not_called()


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_camera_stop(mock_video_capture: MagicMock) -> None:
    """Tests that stop releases the capture device and resets state."""
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = True
    mock_video_capture.return_value = mock_cap_instance

    camera = Camera(device_index=0)
    camera.start()
    assert camera.is_running is True

    camera.stop()
    assert camera.is_running is False
    assert camera._cap is None
    mock_cap_instance.release.assert_called_once()


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_capture_frame_success(mock_video_capture: MagicMock) -> None:
    """Tests capturing a single frame successfully."""
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = True
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mock_cap_instance.read.return_value = (True, dummy_frame)
    mock_video_capture.return_value = mock_cap_instance

    camera = Camera(device_index=0)
    camera.start()

    frame = camera.capture_frame()
    assert frame is not None
    assert np.array_equal(frame, dummy_frame)
    mock_cap_instance.read.assert_called_once()


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_capture_frame_not_open(mock_video_capture: MagicMock) -> None:
    """Tests capturing a frame fails if the camera is not open."""
    camera = Camera(device_index=0)
    frame = camera.capture_frame()
    assert frame is None


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_capture_frame_read_failure(mock_video_capture: MagicMock) -> None:
    """Tests capturing a frame handles read failure correctly."""
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = True
    mock_cap_instance.read.return_value = (False, None)
    mock_video_capture.return_value = mock_cap_instance

    camera = Camera(device_index=0)
    camera.start()

    frame = camera.capture_frame()
    assert frame is None


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_camera_stream(mock_video_capture: MagicMock) -> None:
    """Tests streaming frames continuously."""
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = True
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mock_cap_instance.read.return_value = (True, dummy_frame)
    mock_video_capture.return_value = mock_cap_instance

    camera = Camera(device_index=0)

    frames_generator = camera.stream()

    # Read two frames from stream
    frame1 = next(frames_generator)
    frame2 = next(frames_generator)

    assert np.array_equal(frame1, dummy_frame)
    assert np.array_equal(frame2, dummy_frame)

    assert camera.is_running is True

    # Stop the stream/camera
    camera.stop()

    # The generator should exit on next cycle or if we try to call next
    with pytest.raises(StopIteration):
        next(frames_generator)

    assert camera.is_running is False
    mock_cap_instance.release.assert_called_once()


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_camera_context_manager(mock_video_capture: MagicMock) -> None:
    """Tests the context manager protocol for Camera."""
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = True
    mock_video_capture.return_value = mock_cap_instance

    with Camera(device_index=0) as camera:
        assert camera.is_running is True
        assert camera._cap == mock_cap_instance

    assert camera.is_running is False
    assert camera._cap is None
    mock_cap_instance.release.assert_called_once()


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_camera_read_success(mock_video_capture: MagicMock) -> None:
    """Tests that read() returns (True, frame) on success."""
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = True
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mock_cap_instance.read.return_value = (True, dummy_frame)
    mock_video_capture.return_value = mock_cap_instance

    camera = Camera(device_index=0)
    camera.start()

    success, frame = camera.read()
    assert success is True
    assert np.array_equal(frame, dummy_frame)


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_camera_read_failure(mock_video_capture: MagicMock) -> None:
    """Tests that read() returns (False, None) on failure."""
    camera = Camera(device_index=0)
    # camera is not started, so it should fail
    success, frame = camera.read()
    assert success is False
    assert frame is None


@patch("visionauth.camera.camera.cv2.VideoCapture")
def test_camera_frames_stream(mock_video_capture: MagicMock) -> None:
    """Tests streaming frames using the frames() generator."""
    mock_cap_instance = MagicMock()
    mock_cap_instance.isOpened.return_value = True
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mock_cap_instance.read.return_value = (True, dummy_frame)
    mock_video_capture.return_value = mock_cap_instance

    camera = Camera(device_index=0)
    camera.start()

    frames_generator = camera.frames()

    frame1 = next(frames_generator)
    assert np.array_equal(frame1, dummy_frame)

    camera.stop()
    with pytest.raises(StopIteration):
        next(frames_generator)
