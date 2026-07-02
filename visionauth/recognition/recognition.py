"""Recognition module (v0) for VisionAuth.

Handles face detection in frames using MediaPipe.
"""

import logging
from dataclasses import dataclass
import cv2
import numpy as np

try:
    import mediapipe.solutions.face_detection as mp_face_detection
except (ImportError, AttributeError, ModuleNotFoundError):
    # Stub fallback to allow importing and testing under Python 3.14+
    class _StubFaceDetection:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def process(self, *args, **kwargs):
            return None

        def close(self) -> None:
            pass

    class _StubSolutions:
        FaceDetection = _StubFaceDetection

    mp_face_detection = _StubSolutions()

from visionauth.events.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectionResult:
    """Holds the result of a single face detection.

    Attributes:
        bounding_box: Bounding box relative coordinates (xmin, ymin, width, height).
        confidence: Confidence score of the detection.
    """

    bounding_box: tuple[float, float, float, float]
    confidence: float


class Recognition:
    """Performs face detection on camera frames using MediaPipe.

    Responsible for checking each frame, extracting bounding box details, and
    broadcasting detections to the EventBus.
    """

    def __init__(self, event_bus: EventBus, confidence_threshold: float = 0.6) -> None:
        """Initializes the Recognition processor.

        Args:
            event_bus: The EventBus instance to emit events onto.
            confidence_threshold: Minimum confidence to register a face. Defaults to 0.6.
        """
        self.event_bus: EventBus = event_bus
        self.confidence_threshold: float = confidence_threshold

        self._face_detection = mp_face_detection.FaceDetection(
            min_detection_confidence=self.confidence_threshold
        )

    def process_frame(self, frame: np.ndarray) -> list[DetectionResult]:
        """Processes a single BGR frame to detect faces.

        Converts BGR to RGB, executes MediaPipe face detection, processes relative
        bounding box coordinates, and emits a FACE_DETECTED event if faces exist.

        Args:
            frame: NumPy BGR frame.

        Returns:
            A list of DetectionResult objects.
        """
        if frame is None or frame.size == 0:
            logger.warning("Empty or None frame received for processing.")
            return []

        # MediaPipe expects RGB images
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._face_detection.process(rgb_frame)

        detections: list[DetectionResult] = []
        if results.detections:
            for detection in results.detections:
                confidence = detection.score[0] if detection.score else 0.0
                if confidence < self.confidence_threshold:
                    continue

                bbox = detection.location_data.relative_bounding_box
                bounding_box = (bbox.xmin, bbox.ymin, bbox.width, bbox.height)
                detections.append(
                    DetectionResult(bounding_box=bounding_box, confidence=confidence)
                )

        if detections:
            payload = {
                "count": len(detections),
                "detections": [
                    {
                        "bounding_box": d.bounding_box,
                        "confidence": d.confidence,
                    }
                    for d in detections
                ],
            }
            logger.info("Detected %d face(s). Emitting FACE_DETECTED.", len(detections))
            self.event_bus.emit(EventType.FACE_DETECTED, payload)

        return detections

    def close(self) -> None:
        """Releases the underlying MediaPipe face detection resource."""
        if hasattr(self, "_face_detection") and self._face_detection is not None:
            logger.info("Releasing MediaPipe face detection resources.")
            self._face_detection.close()

    def __enter__(self) -> "Recognition":
        """Context manager entry."""
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: type | None
    ) -> None:
        """Context manager exit, cleaning up resources."""
        self.close()
