"""Development-only integration demo for VisionAuth.

Connects Camera, Recognition, and EventBus modules to display real-time face
detection bounding boxes on a live webcam feed.
"""

import logging
import sys
import cv2

from visionauth.camera import Camera
from visionauth.events import EventBus, EventType
from visionauth.recognition import Recognition

# Configure basic logging to see system prints
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("camera_recognition_demo")


def main() -> None:
    """Runs the live face detection integration loop."""
    logger.info("Initializing VisionAuth Integration Demo...")

    # 1. Create EventBus and subscribe to FACE_DETECTED
    event_bus = EventBus()

    def on_face_detected(payload: dict) -> None:
        count = payload.get("count", 0)
        print(f"[Event Received] FACE_DETECTED: {count} face(s) detected.")

    event_bus.subscribe(EventType.FACE_DETECTED, on_face_detected)

    # 2. Instantiate Recognition and Camera
    recognition = Recognition(event_bus=event_bus, confidence_threshold=0.6)

    # Use default webcam (index 0)
    camera = Camera(device_index=0, width=640, height=480, fps=30.0)

    # 3. Start Camera and stream frames
    logger.info("Starting camera stream...")
    camera.start()

    logger.info("Stream started. Press 'q' or 'Q' on the video window to exit.")

    try:
        for frame in camera.frames():
            # Get dimensions
            h, w, _ = frame.shape

            # Send frame to Recognition processor
            detections = recognition.process_frame(frame)

            # Draw bounding boxes and confidence scores around detected faces
            for d in detections:
                xmin, ymin, width, height = d.bounding_box

                # Convert relative coordinates to pixels
                xmin_px = int(xmin * w)
                ymin_px = int(ymin * h)
                width_px = int(width * w)
                height_px = int(height * h)

                # Draw green box
                cv2.rectangle(
                    frame,
                    (xmin_px, ymin_px),
                    (xmin_px + width_px, ymin_px + height_px),
                    (0, 255, 0),
                    2,
                )

                # Display confidence text
                text = f"{d.confidence:.2f}"
                cv2.putText(
                    frame,
                    text,
                    (xmin_px, max(0, ymin_px - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                    cv2.LINE_AA,
                )

            # Show the video feed
            try:
                cv2.imshow("VisionAuth Live Face Detection (Press 'q' to Quit)", frame)
            except cv2.error as e:
                logger.error(
                    "OpenCV display error (possibly running in a headless environment): %s",
                    e,
                )
                logger.info("Detections: %s", detections)

            # Exit cleanly if 'q' is pressed
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                logger.info("Exit requested by user keypress.")
                break

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting...")
    finally:
        # 4. Graceful Cleanup
        logger.info("Releasing camera and closing windows...")
        camera.stop()
        recognition.close()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
        logger.info("Demo closed cleanly.")


if __name__ == "__main__":
    main()
