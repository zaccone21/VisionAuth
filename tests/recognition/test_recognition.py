"""Unit tests for the Recognition module."""

from unittest.mock import MagicMock, patch
import numpy as np

from visionauth.events.event_bus import EventBus, EventType
from visionauth.recognition.recognition import Recognition


def create_mock_detection(
    xmin: float, ymin: float, width: float, height: float, score: float
) -> MagicMock:
    """Helper to build a mocked MediaPipe face detection result."""
    detection = MagicMock()
    detection.score = [score]
    bbox = MagicMock()
    bbox.xmin = xmin
    bbox.ymin = ymin
    bbox.width = width
    bbox.height = height
    detection.location_data.relative_bounding_box = bbox
    return detection


@patch("visionauth.recognition.recognition.mp_face_detection.FaceDetection")
def test_recognition_no_face(mock_face_detection_class: MagicMock) -> None:
    """Tests when no faces are detected in the frame."""
    mock_instance = MagicMock()
    mock_results = MagicMock()
    mock_results.detections = None
    mock_instance.process.return_value = mock_results
    mock_face_detection_class.return_value = mock_instance

    event_bus = MagicMock(spec=EventBus)
    recognition = Recognition(event_bus, confidence_threshold=0.6)

    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    results = recognition.process_frame(dummy_frame)

    assert results == []
    event_bus.emit.assert_not_called()
    mock_instance.process.assert_called_once()


@patch("visionauth.recognition.recognition.mp_face_detection.FaceDetection")
def test_recognition_one_face(mock_face_detection_class: MagicMock) -> None:
    """Tests when exactly one face is detected above the confidence threshold."""
    mock_instance = MagicMock()
    mock_results = MagicMock()
    mock_results.detections = [create_mock_detection(0.1, 0.2, 0.3, 0.4, 0.85)]
    mock_instance.process.return_value = mock_results
    mock_face_detection_class.return_value = mock_instance

    event_bus = MagicMock(spec=EventBus)
    recognition = Recognition(event_bus, confidence_threshold=0.6)

    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    results = recognition.process_frame(dummy_frame)

    assert len(results) == 1
    assert results[0].bounding_box == (0.1, 0.2, 0.3, 0.4)
    assert results[0].confidence == 0.85

    # Check event bus emission
    event_bus.emit.assert_called_once_with(
        EventType.FACE_DETECTED,
        {
            "count": 1,
            "detections": [
                {
                    "bounding_box": (0.1, 0.2, 0.3, 0.4),
                    "confidence": 0.85,
                }
            ],
        },
    )


@patch("visionauth.recognition.recognition.mp_face_detection.FaceDetection")
def test_recognition_multiple_faces(mock_face_detection_class: MagicMock) -> None:
    """Tests when multiple faces are detected above the confidence threshold."""
    mock_instance = MagicMock()
    mock_results = MagicMock()
    mock_results.detections = [
        create_mock_detection(0.1, 0.2, 0.3, 0.4, 0.8),
        create_mock_detection(0.5, 0.6, 0.2, 0.2, 0.95),
    ]
    mock_instance.process.return_value = mock_results
    mock_face_detection_class.return_value = mock_instance

    event_bus = MagicMock(spec=EventBus)
    recognition = Recognition(event_bus, confidence_threshold=0.6)

    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    results = recognition.process_frame(dummy_frame)

    assert len(results) == 2
    assert results[0].confidence == 0.8
    assert results[1].confidence == 0.95

    # Check payload structure and event emit call
    event_bus.emit.assert_called_once()
    args, _ = event_bus.emit.call_args
    assert args[0] == EventType.FACE_DETECTED
    assert args[1]["count"] == 2
    assert len(args[1]["detections"]) == 2


@patch("visionauth.recognition.recognition.mp_face_detection.FaceDetection")
def test_recognition_confidence_filtering(mock_face_detection_class: MagicMock) -> None:
    """Tests that detections below confidence threshold are filtered out."""
    mock_instance = MagicMock()
    mock_results = MagicMock()
    mock_results.detections = [
        create_mock_detection(0.1, 0.2, 0.3, 0.4, 0.55),  # Below 0.6 threshold
        create_mock_detection(0.5, 0.6, 0.2, 0.2, 0.75),  # Above 0.6 threshold
    ]
    mock_instance.process.return_value = mock_results
    mock_face_detection_class.return_value = mock_instance

    event_bus = MagicMock(spec=EventBus)
    recognition = Recognition(event_bus, confidence_threshold=0.6)

    dummy_frame = np.ones((480, 640, 3), dtype=np.uint8)
    results = recognition.process_frame(dummy_frame)

    assert len(results) == 1
    assert results[0].confidence == 0.75
    event_bus.emit.assert_called_once_with(
        EventType.FACE_DETECTED,
        {
            "count": 1,
            "detections": [
                {
                    "bounding_box": (0.5, 0.6, 0.2, 0.2),
                    "confidence": 0.75,
                }
            ],
        },
    )


def test_recognition_empty_frame() -> None:
    """Tests that empty or None frame input returns empty list immediately."""
    event_bus = MagicMock(spec=EventBus)
    recognition = Recognition(event_bus, confidence_threshold=0.6)

    # Test None frame
    assert recognition.process_frame(None) == []  # type: ignore

    # Test empty array frame
    empty_frame = np.array([])
    assert recognition.process_frame(empty_frame) == []

    event_bus.emit.assert_not_called()


@patch("visionauth.recognition.recognition.mp_face_detection.FaceDetection")
def test_recognition_cleanup(mock_face_detection_class: MagicMock) -> None:
    """Tests the close method and context manager resource cleanup."""
    mock_instance = MagicMock()
    mock_face_detection_class.return_value = mock_instance

    event_bus = MagicMock(spec=EventBus)
    with Recognition(event_bus):
        pass

    mock_instance.close.assert_called_once()
