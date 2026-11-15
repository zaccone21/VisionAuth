"""Live recognition test: shows the camera with each face's best match.

Used by the command line (test) and by examples/camera_recognition_demo.py.
It compares against every enrolled face, like the unlock service, but without
the liveness check, to see how well each face is recognized.
"""

import logging
import unicodedata

import cv2

from visionauth.camera.camera import Camera
from visionauth.events.event_bus import EventBus
from visionauth.recognition.recognition import Recognition
from visionauth.recognition.recognition_embeddings import EmbeddingExtractor, EmbeddingMatcher, crop_face

logger = logging.getLogger(__name__)

WINDOW_NAME = "VisionAuth - Probar reconocimiento (Q para salir)"


def _ascii(text: str) -> str:
    """OpenCV's fonts only draw ASCII: "Joaquín" becomes "Joaquin"."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def run_recognition_test(data_dir: str, camera_index: int, threshold: float) -> None:
    """Shows the camera until Q is pressed, with the closest face and its similarity."""
    recognition = Recognition(event_bus=EventBus(), confidence_threshold=0.6)
    extractor = EmbeddingExtractor()
    matcher = EmbeddingMatcher(data_dir=data_dir)
    camera = Camera(device_index=camera_index, width=640, height=480, fps=30.0)
    camera.start()
    try:
        for frame in camera.frames():
            h, w, _ = frame.shape
            for detection in recognition.process_frame(frame):
                x, y, bw, bh = detection.bounding_box
                face = crop_face(frame, detection.bounding_box, padding=0.15)
                name, similarity = (None, 0.0)
                if face.size > 0:
                    name, similarity = matcher.match_face(extractor.extract_embedding(face), threshold=threshold)
                color = (0, 200, 0) if name else (0, 0, 220)
                label = f"{_ascii(name)} ({similarity:.2f})" if name else f"No reconocida ({similarity:.2f})"
                top_left = (int(x * w), int(y * h))
                cv2.rectangle(frame, top_left, (int((x + bw) * w), int((y + bh) * h)), color, 2)
                cv2.putText(
                    frame, label, (top_left[0], max(0, top_left[1] - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA,
                )
            cv2.imshow(WINDOW_NAME, frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                break
    except KeyboardInterrupt:
        pass
    finally:
        camera.stop()
        recognition.close()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
