"""Interactive enrollment demo for VisionAuth.

Prompts the user for a username, opens the camera stream, processes faces
in real-time, displays visual enrollment feedback (e.g. green bounding box
for valid captures, red for multiple faces), and persists the profile.
"""

import logging
import sys
import cv2
import numpy as np

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
from visionauth.recognition.recognition import Recognition

# Configure basic logging for CLI demo
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("enrollment_demo")


def main() -> None:
    """Runs the interactive enrollment demo."""
    print("====================================================")
    print("           VisionAuth - Enrollment Demo             ")
    print("====================================================")

    # 1. Prompt for username
    try:
        username = input("Ingrese el nombre del usuario a registrar: ")
    except (KeyboardInterrupt, EOFError):
        print("\nOperación cancelada por el usuario.")
        return

    # 2. Setup components
    event_bus = EventBus()
    config = EnrollmentConfig(
        num_samples=8,  # Target 8 high-quality samples
        min_confidence=0.6,
        resolution=(640, 480),
        max_time_between_captures=8.0,  # 8 seconds to align face
        data_dir="data",
        target_fps=10.0,
        cooldown_between_captures=0.5,  # 500ms cooldown
        min_face_movement=0.015,
        min_face_size=0.12,             # Tolerant face size check (12%)
        max_face_size=0.8,
        max_face_offset=0.25,           # Wide movement tolerance (25%)
        min_blur_threshold=40.0,        # Very tolerant webcam ROI blur limit
        max_samples_per_pose=4,         # (CENTER max 4, LEFT/RIGHT max 2)
    )

    recognition = Recognition(
        event_bus=event_bus,
        confidence_threshold=config.min_confidence,
        min_face_size=config.min_face_size,
        max_face_offset_y=0.65,             # Exclude lower zone (neck/chin/chest)
        consecutive_frames_required=3,      # Face must persist for 3 frames
    )
    camera = Camera(
        device_index=0,
        width=config.resolution[0],
        height=config.resolution[1],
        fps=30.0,
    )

    service = EnrollmentService(
        camera=camera,
        recognition=recognition,
        event_bus=event_bus,
        config=config,
    )

    # 3. Track state for the UI overlay
    state = {
        "accepted_samples": 0,
        "status_message": "Alinee su rostro frente a la camara...",
        "status_color": (255, 255, 255),  # BGR White
        "aborted": False,
    }

    # 4. Event Bus Handlers for progress feedback
    def on_started(payload: dict) -> None:
        print(f"\n[Sistema] Iniciando registro de: {payload['username']}")
        state["status_message"] = "Iniciando captura de rostro..."
        state["status_color"] = (255, 255, 255)

    def on_accepted(payload: dict) -> None:
        idx = payload["sample_index"]
        total = payload["total_needed"]
        print(f"[Captura] Muestra {idx}/{total} aceptada.")
        state["accepted_samples"] = idx
        state["status_message"] = f"Muestra {idx}/{total} aceptada! Mantenga la posicion."
        state["status_color"] = (0, 255, 0)  # BGR Green

    def on_discarded(payload: dict) -> None:
        reason = payload["reason"]
        samples = payload["current_samples"]
        if reason == "zero_faces":
            msg = "Buscando rostro... Acerquese a la camara"
            state["status_color"] = (0, 255, 255)  # BGR Yellow
        elif reason == "multiple_faces":
            msg = "ATENCION: Multiples personas detectadas!"
            state["status_color"] = (0, 0, 255)  # BGR Red
        elif reason == "insufficient_confidence":
            msg = "Rostro inestable. Alinee y mantenga la posicion."
            state["status_color"] = (0, 255, 255)  # BGR Yellow
        elif reason == "blurry":
            msg = "Imagen borrosa. Mantengase quieto..."
            state["status_color"] = (0, 165, 255)  # BGR Orange
        elif reason == "off_center":
            msg = "Rostro descentrado. Centre su cara."
            state["status_color"] = (0, 165, 255)  # BGR Orange
        elif reason == "face_too_small":
            msg = "Rostro muy lejano. Acerquese a la camara."
            state["status_color"] = (0, 165, 255)  # BGR Orange
        elif reason == "face_too_large":
            msg = "Rostro muy cercano. Aleje su cara."
            state["status_color"] = (0, 165, 255)  # BGR Orange
        elif reason == "insufficient_movement":
            msg = "Muestras identicas. Gire levemente la cabeza..."
            state["status_color"] = (0, 255, 255)  # BGR Yellow
        elif reason == "duplicate_pose":
            msg = "Pose repetida consecutivamente. Gire la cabeza..."
            state["status_color"] = (0, 255, 255)  # BGR Yellow
        elif reason == "pose_limit_reached":
            msg = "Suficientes muestras en esta pose. Gire la cabeza..."
            state["status_color"] = (0, 255, 255)  # BGR Yellow
        else:
            msg = "Captura descartada."
            state["status_color"] = (0, 165, 255)  # BGR Orange

        print(f"[Captura] Descartada: {reason} (Muestras validas: {samples})")
        state["status_message"] = msg

    def on_completed(payload: dict) -> None:
        print(f"\n[Sistema] Registro finalizado con {payload['sample_count']} muestras.")

    def on_failed(payload: dict) -> None:
        print(f"\n[Sistema] Registro fallido: {payload['reason']}")

    event_bus.subscribe("ENROLLMENT_STARTED", on_started)
    event_bus.subscribe("ENROLLMENT_FRAME_ACCEPTED", on_accepted)
    event_bus.subscribe("ENROLLMENT_FRAME_DISCARDED", on_discarded)
    event_bus.subscribe("ENROLLMENT_COMPLETED", on_completed)
    event_bus.subscribe("ENROLLMENT_FAILED", on_failed)

    # 5. UI Frame Callback
    def on_frame(frame: np.ndarray, detections: list) -> None:
        h, w, _ = frame.shape

        # Draw detections
        for d in detections:
            xmin, ymin, width, height = d.bounding_box
            xmin_px = int(xmin * w)
            ymin_px = int(ymin * h)
            width_px = int(width * w)
            height_px = int(height * h)

            # Draw box around face matching the current status color
            cv2.rectangle(
                frame,
                (xmin_px, ymin_px),
                (xmin_px + width_px, ymin_px + height_px),
                state["status_color"],
                2,
            )

            # Draw confidence text
            cv2.putText(
                frame,
                f"Conf: {d.confidence:.2f}",
                (xmin_px, max(0, ymin_px - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                state["status_color"],
                1,
                cv2.LINE_AA,
            )

        # Draw top status bar backdrop
        cv2.rectangle(frame, (0, 0), (w, 40), (0, 0, 0), -1)

        # Draw status message text
        cv2.putText(
            frame,
            state["status_message"],
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            state["status_color"],
            2,
            cv2.LINE_AA,
        )

        # Draw progress bar at bottom of screen
        total_samples = config.num_samples
        progress_ratio = state["accepted_samples"] / total_samples
        progress_px = int(w * progress_ratio)

        # Black background bar
        cv2.rectangle(frame, (0, h - 15), (w, h), (30, 30, 30), -1)
        # Green filling bar
        if progress_px > 0:
            cv2.rectangle(frame, (0, h - 15), (progress_px, h), (0, 255, 0), -1)

        # Render display
        try:
            cv2.imshow("VisionAuth - Registro de Usuario (Presione 'q' para cancelar)", frame)
        except cv2.error as err:
            logger.error("Error al mostrar ventana OpenCV: %s", err)

        # Abort if user presses 'q'
        if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
            state["aborted"] = True
            raise KeyboardInterrupt("Cancelado por teclado en la pantalla.")

    # 6. Execute Enrollment
    try:
        metadata = service.enroll(username, on_frame=on_frame)
        print("\n====================================================")
        print("          ¡Registro Completado con Éxito!           ")
        print("====================================================")
        print(f"Usuario:            {metadata['name']}")
        print(f"Muestras:           {metadata['sample_count']}")
        print(f"Fecha de Creación:  {metadata['created_at']}")
        print(f"Ruta:               data/users/{username}/")
        print("====================================================")

    except InvalidUserError as e:
        print(f"\n[ERROR] Nombre de usuario inválido: {e}")
    except UserAlreadyExistsError as e:
        print(f"\n[ERROR] El usuario ya existe: {e}")
    except EnrollmentTimeoutError as e:
        print(f"\n[ERROR] Tiempo límite excedido: {e}")
    except CameraError as e:
        print(f"\n[ERROR] Error al acceder a la cámara: {e}")
    except KeyboardInterrupt:
        print("\n[INFO] Registro cancelado por el usuario.")
    except EnrollmentError as e:
        print(f"\n[ERROR] Ocurrió un error en el registro: {e}")
    finally:
        # Cleanup
        logger.info("Cerrando recursos...")
        camera.stop()
        recognition.close()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
        print("Demo finalizado.")


if __name__ == "__main__":
    main()
