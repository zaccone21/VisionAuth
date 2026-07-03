"""Development-only integration demo for VisionAuth.

Connects Camera, Recognition, and EventBus modules to display real-time face
detection bounding boxes on a live webcam feed.
"""

import logging
import sys
import cv2
import numpy as np

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

    # 2. Instantiate Recognition, Camera, and Embeddings components
    recognition = Recognition(event_bus=event_bus, confidence_threshold=0.6)
    
    from visionauth.recognition.recognition_embeddings import EmbeddingExtractor, EmbeddingMatcher, crop_face
    try:
        extractor = EmbeddingExtractor()
    except Exception as e:
        print(f"CRITICAL ERROR: FaceNet model failed to load. {e}")
        sys.exit(1)
        
    matcher = EmbeddingMatcher(data_dir="examples/data")

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

            # Match and display faces
            for d in detections:
                xmin_px = int(d.bounding_box[0] * w)
                ymin_px = int(d.bounding_box[1] * h)
                width_px = int(d.bounding_box[2] * w)
                height_px = int(d.bounding_box[3] * h)

                # Crop face using unified crop_face helper
                face_crop = crop_face(frame, d.bounding_box, padding=0.15)
                
                matched_user = "Unknown"
                similarity = 0.0
                if face_crop.size > 0:
                    emb = extractor.extract_embedding(face_crop)
                    emb_norm = float(np.linalg.norm(emb))
                    print(f"Embedding norm: {emb_norm:.4f}")
                    
                    res_user, res_sim = matcher.match_face(emb, threshold=0.65)
                    print(f"Similarity: {res_sim:.2f}")
                    print(f"Threshold: 0.65")
                    
                    if res_user is not None:
                        matched_user = res_user
                        similarity = res_sim
                        print(f"Loaded profile: {matched_user}")
                        print("MATCH")
                    else:
                        print("NO MATCH")

                # Draw green box if matched, red if unknown
                color = (0, 255, 0) if matched_user != "Unknown" else (0, 0, 255)
                cv2.rectangle(
                    frame,
                    (xmin_px, ymin_px),
                    (xmin_px + width_px, ymin_px + height_px),
                    color,
                    2,
                )

                # Display matched name and similarity text
                text = f"{matched_user} ({similarity:.2f})" if matched_user != "Unknown" else "Unknown"
                cv2.putText(
                    frame,
                    text,
                    (xmin_px, max(0, ymin_px - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2,
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
