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
from visionauth.recognition.recognition_embeddings import MODELS_DIR

logger = logging.getLogger(__name__)

DETECTOR_MODEL_FILE = "blaze_face_short_range.tflite"


@dataclass(frozen=True)
class DetectionResult:
    """Holds the result of a single face detection.

    Attributes:
        bounding_box: Bounding box relative coordinates (xmin, ymin, width, height).
        confidence: Confidence score of the detection.
        keypoints: Relative (x, y) facial landmarks in MediaPipe order (right eye,
            left eye, nose tip, mouth center, right ear, left ear), or None when
            the detector does not provide them.
    """

    bounding_box: tuple[float, float, float, float]
    confidence: float
    keypoints: tuple[tuple[float, float], ...] | None = None


class Recognition:
    """Performs face detection on camera frames using MediaPipe.

    Responsible for checking each frame, extracting bounding box details, and
    broadcasting detections to the EventBus.
    """

    def __init__(
        self,
        event_bus: EventBus,
        confidence_threshold: float = 0.4,
        min_face_size: float = 0.0,
        max_face_offset_y: float = 1.0,
        consecutive_frames_required: int = 1,
    ) -> None:
        """Initializes the Recognition processor.

        Args:
            event_bus: The EventBus instance to emit events onto.
            confidence_threshold: Minimum confidence to register a face. Defaults to 0.4.
            min_face_size: Minimum face size relative to the frame (width or height).
            max_face_offset_y: Bounding box top limit relative to the frame (reject neck/chest).
            consecutive_frames_required: N frames required for stability.
        """
        self.event_bus: EventBus = event_bus
        self.confidence_threshold: float = confidence_threshold
        self.min_face_size: float = min_face_size
        self.max_face_offset_y: float = max_face_offset_y
        self.consecutive_frames_required: int = consecutive_frames_required
        
        self._stability_counter = 0

        self._face_detection = mp_face_detection.FaceDetection(
            min_detection_confidence=self.confidence_threshold
        )

        # Initialize Haar Cascade as fallback/backup for Python 3.14+ or missing solutions package
        self._haar_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self.use_fallback = isinstance(self._face_detection, _StubFaceDetection)

        # Initialize MediaPipe Tasks API Face Detector
        self.use_tasks_api = False
        self._tasks_detector = None
        
        try:
            import os
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            # Resolve against the project, not the working directory the app was launched from
            model_path = str(MODELS_DIR / DETECTOR_MODEL_FILE)
            if not os.path.exists(model_path):
                logger.error("Face detection model not found: %s", model_path)
            else:
                base_options = python.BaseOptions(model_asset_path=model_path)
                options = vision.FaceDetectorOptions(base_options=base_options)
                self._tasks_detector = vision.FaceDetector.create_from_options(options)
                self.use_tasks_api = True
                logger.info("MediaPipe Tasks API initialized successfully using model: %s", model_path)
        except Exception as e:
            logger.warning("Could not initialize MediaPipe Tasks API: %s. Falling back to legacy/stub solutions.", e)

        if not self.use_tasks_api and self.use_fallback and self._haar_cascade.empty():
            logger.error(
                "No face detector is available (MediaPipe model missing and Haar cascade "
                "not shipped with this OpenCV build). No faces will ever be detected."
            )

    def process_frame(
        self, frame: np.ndarray, visualize: bool = False
    ) -> list[DetectionResult]:
        """Processes a single BGR frame to detect faces.

        Converts BGR to RGB, executes MediaPipe face detection, processes relative
        bounding box coordinates, and emits a FACE_DETECTED event if faces exist.
        Falls back to OpenCV Haar Cascade if MediaPipe solutions is unavailable.

        Args:
            frame: NumPy BGR frame.
            visualize: If True, draws bounding boxes and displays the frame using cv2.imshow.

        Returns:
            A list of DetectionResult objects.
        """
        if frame is None or frame.size == 0:
            logger.warning("Empty or None frame received for processing.")
            return []

        h, w, _ = frame.shape
        raw_detections: list[DetectionResult] = []

        # 1. Attempt MediaPipe Tasks API first
        if self.use_tasks_api and self._tasks_detector is not None:
            try:
                import mediapipe as mp
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                result = self._tasks_detector.detect(mp_image)
                if result and result.detections:
                    for detection in result.detections:
                        confidence = detection.categories[0].score if detection.categories else 0.0
                        if confidence < self.confidence_threshold:
                            continue
                        bbox = detection.bounding_box
                        xmin = float(bbox.origin_x) / w
                        ymin = float(bbox.origin_y) / h
                        box_width = float(bbox.width) / w
                        box_height = float(bbox.height) / h
                        keypoints = tuple((float(k.x), float(k.y)) for k in detection.keypoints or [])
                        raw_detections.append(
                            DetectionResult(
                                bounding_box=(xmin, ymin, box_width, box_height),
                                confidence=confidence,
                                keypoints=keypoints or None,
                            )
                        )
            except Exception as e:
                logger.error("MediaPipe Tasks API execution failed: %s", e)

        # 2. Attempt MediaPipe legacy solutions face detection if Tasks API returned nothing
        if not raw_detections and not self.use_fallback:
            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self._face_detection.process(rgb_frame)

                if results and results.detections:
                    for detection in results.detections:
                        confidence = detection.score[0] if detection.score else 0.0
                        if confidence < self.confidence_threshold:
                            continue

                        bbox = detection.location_data.relative_bounding_box
                        bounding_box = (bbox.xmin, bbox.ymin, bbox.width, bbox.height)
                        raw_detections.append(
                            DetectionResult(bounding_box=bounding_box, confidence=confidence)
                        )
            except Exception as e:
                logger.error("MediaPipe legacy processing failed: %s. Switching to OpenCV Haar Cascade.", e)
                self.use_fallback = True

        # 3. Fallback to OpenCV Haar Cascade
        if not raw_detections and (self.use_fallback or not self.use_tasks_api):
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self._haar_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
                )
                for (x, y, width, height) in faces:
                    xmin = float(x) / w
                    ymin = float(y) / h
                    box_width = float(width) / w
                    box_height = float(height) / h
                    # Haar Cascade doesn't return confidence, default to 0.8
                    raw_detections.append(
                        DetectionResult(
                            bounding_box=(xmin, ymin, box_width, box_height),
                            confidence=0.8,
                        )
                    )
            except Exception as e:
                logger.error("Haar Cascade processing failed: %s", e)

        # 4. Apply Geometric Quality Filters
        valid_detections: list[DetectionResult] = []
        for d in raw_detections:
            xmin, ymin, box_w, box_h = d.bounding_box
            cy = ymin + box_h / 2
            
            # A. Size check (min relative size)
            if self.min_face_size > 0.0:
                if box_w < self.min_face_size or box_h < self.min_face_size:
                    logger.debug("Face rejected: too small (w=%.2f, h=%.2f < %.2f)", box_w, box_h, self.min_face_size)
                    continue

            # B. Lower zone check (reject neck/chest/chin)
            if self.max_face_offset_y < 1.0:
                if ymin > self.max_face_offset_y or cy > (self.max_face_offset_y + 0.1):
                    logger.debug("Face rejected: in the lower frame zone (ymin=%.2f, cy=%.2f)", ymin, cy)
                    continue

            # C. Aspect ratio check (~0.6 to 1.3)
            if box_h > 0.0:
                ratio = box_w / box_h
                if ratio < 0.6 or ratio > 1.3:
                    logger.debug("Face rejected: aspect ratio out of range (ratio=%.2f)", ratio)
                    continue

            valid_detections.append(d)

        # 5. Apply Temporal Stability Filter
        if len(valid_detections) > 0:
            self._stability_counter += 1
            if self._stability_counter >= self.consecutive_frames_required:
                detections = valid_detections
            else:
                detections = []
        else:
            self._stability_counter = 0
            detections = []

        # Debug logging
        logger.debug("Number of detections in frame: %d", len(detections))
        for idx, d in enumerate(detections):
            logger.debug(
                "Detection %d - Confidence: %.4f, Bounding Box: %s",
                idx,
                d.confidence,
                d.bounding_box,
            )

        if visualize:
            for d in detections:
                xmin, ymin, width, height = d.bounding_box
                xmin_px = int(xmin * w)
                ymin_px = int(ymin * h)
                width_px = int(width * w)
                height_px = int(height * h)
                cv2.rectangle(
                    frame,
                    (xmin_px, ymin_px),
                    (xmin_px + width_px, ymin_px + height_px),
                    (0, 255, 0),
                    2,
                )
                cv2.putText(
                    frame,
                    f"Conf: {d.confidence:.2f}",
                    (xmin_px, max(0, ymin_px - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                    cv2.LINE_AA,
                )
            try:
                cv2.imshow("Recognition Visualization", frame)
                cv2.waitKey(1)
            except cv2.error as e:
                logger.error("OpenCV display error in visualization mode: %s", e)

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
            logger.debug("Detected %d face(s). Emitting FACE_DETECTED.", len(detections))
            self.event_bus.emit(EventType.FACE_DETECTED, payload)

        return detections

    def close(self) -> None:
        """Releases the underlying MediaPipe face detection resource."""
        if hasattr(self, "_face_detection") and self._face_detection is not None:
            logger.info("Releasing MediaPipe face detection resources.")
            self._face_detection.close()
        if hasattr(self, "_tasks_detector") and self._tasks_detector is not None:
            logger.info("Releasing MediaPipe Tasks API resources.")
            self._tasks_detector = None

    def __enter__(self) -> "Recognition":
        """Context manager entry."""
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: type | None
    ) -> None:
        """Context manager exit, cleaning up resources."""
        self.close()
