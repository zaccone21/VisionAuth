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
def test_recognition_process_returns_none(mock_face_detection_class: MagicMock) -> None:
    """Tests when MediaPipe process() returns None."""
    mock_instance = MagicMock()
    mock_instance.process.return_value = None
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


def test_recognition_fallback_to_haar_cascade() -> None:
    """Tests that the processor falls back to Haar Cascade when MediaPipe solutions is disabled or fails."""
    event_bus = MagicMock(spec=EventBus)

    # Mock cv2.CascadeClassifier to return a deterministic face box
    with patch("visionauth.recognition.recognition.cv2.CascadeClassifier") as mock_cascade_class:
        mock_instance = MagicMock()
        mock_instance.detectMultiScale.return_value = [(160, 120, 80, 80)]
        mock_cascade_class.return_value = mock_instance

        # Force fallback mode
        recognition = Recognition(event_bus)
        recognition.use_fallback = True

        dummy_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        results = recognition.process_frame(dummy_frame)

        assert len(results) == 1
        assert results[0].confidence == 0.8
        # Scaled values: xmin=160/640=0.25, ymin=120/480=0.25, w=80/640=0.125, h=80/480=0.1667
        assert results[0].bounding_box[0] == 0.25
        assert results[0].bounding_box[1] == 0.25
        assert results[0].bounding_box[2] == 0.125
        assert results[0].bounding_box[3] == 80.0 / 480.0


def test_recognition_aspect_ratio_filter() -> None:
    """Tests that detections with non-human aspect ratios (too wide/tall) are rejected."""
    event_bus = MagicMock(spec=EventBus)
    with patch("visionauth.recognition.recognition.cv2.CascadeClassifier") as mock_cascade_class:
        mock_instance = MagicMock()
        # BBox 1: 100x100 (ratio 1.0 -> valid)
        # BBox 2: 200x50 (ratio 4.0 -> invalid)
        mock_instance.detectMultiScale.return_value = [(100, 100, 100, 100), (100, 100, 200, 50)]
        mock_cascade_class.return_value = mock_instance

        recognition = Recognition(event_bus)
        recognition.use_fallback = True

        dummy_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        results = recognition.process_frame(dummy_frame)

        assert len(results) == 1
        # BBox 1 should be returned
        assert results[0].bounding_box[2] == 100.0 / 640.0


def test_recognition_aspect_ratio_uses_pixels_on_widescreen_frame() -> None:
    """A square face on a 16:9 frame is accepted.

    Its relative width/height ratio is 0.56, so a ratio computed on relative
    coordinates rejected every face from a 1280x720 camera.
    """
    event_bus = MagicMock(spec=EventBus)
    with patch("visionauth.recognition.recognition.cv2.CascadeClassifier") as mock_cascade_class:
        mock_instance = MagicMock()
        mock_instance.detectMultiScale.return_value = [(590, 300, 265, 265)]
        mock_cascade_class.return_value = mock_instance

        recognition = Recognition(event_bus)
        recognition.use_fallback = True

        dummy_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128
        results = recognition.process_frame(dummy_frame)

        assert len(results) == 1


def test_recognition_lower_zone_filter() -> None:
    """Tests that detections in the lower portion of the frame (neck/chest) are filtered."""
    event_bus = MagicMock(spec=EventBus)
    with patch("visionauth.recognition.recognition.cv2.CascadeClassifier") as mock_cascade_class:
        mock_instance = MagicMock()
        # BBox 1: ymin = 50 -> cy = 100 -> valid (upper zone)
        # BBox 2: ymin = 350 -> cy = 400 -> invalid (lower zone)
        mock_instance.detectMultiScale.return_value = [(100, 50, 100, 100), (100, 350, 100, 100)]
        mock_cascade_class.return_value = mock_instance

        recognition = Recognition(event_bus, max_face_offset_y=0.6)
        recognition.use_fallback = True

        dummy_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        results = recognition.process_frame(dummy_frame)

        assert len(results) == 1
        assert results[0].bounding_box[1] == 50.0 / 480.0


def test_recognition_temporal_stability() -> None:
    """Tests that face detections are only returned after N consecutive stable frames."""
    event_bus = MagicMock(spec=EventBus)
    with patch("visionauth.recognition.recognition.cv2.CascadeClassifier") as mock_cascade_class:
        mock_instance = MagicMock()
        mock_instance.detectMultiScale.return_value = [(100, 100, 100, 100)]
        mock_cascade_class.return_value = mock_instance

        # Require N=3 consecutive stable frames
        recognition = Recognition(event_bus, consecutive_frames_required=3)
        recognition.use_fallback = True

        dummy_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        
        # Frame 1: stability counter = 1 -> returns []
        results_1 = recognition.process_frame(dummy_frame)
        assert results_1 == []

        # Frame 2: stability counter = 2 -> returns []
        results_2 = recognition.process_frame(dummy_frame)
        assert results_2 == []

        # Frame 3: stability counter = 3 -> returns face!
        results_3 = recognition.process_frame(dummy_frame)
        assert len(results_3) == 1
        assert results_3[0].bounding_box[0] == 100.0 / 640.0
