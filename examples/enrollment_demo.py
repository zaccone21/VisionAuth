"""Interactive enrollment demo for VisionAuth.

Prompts for a username, then shows a Face ID style enrollment screen: the camera
appears mirrored inside a circle and a ring of ticks fills as the user turns
their head. If the user already exists, the new samples can be added to the
existing profile, e.g. to enroll again from the final camera position.
"""

import logging
import sys
import time

import cv2
import numpy as np

from visionauth.camera.camera import Camera, CameraError
from visionauth.config.config import EnrollmentConfig
from visionauth.enrollment.enrollment import (
    EnrollmentError,
    EnrollmentService,
    EnrollmentTimeoutError,
    InvalidUserError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from visionauth.events.event_bus import EventBus
from visionauth.recognition.head_pose import estimate_head_pose
from visionauth.recognition.recognition import Recognition
from visionauth.ui import FaceIdOverlay

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("enrollment_demo")

WINDOW_NAME = "VisionAuth - Configurar Face ID (Q para cancelar)"

MOVE_HEAD = "Mueve la cabeza lentamente para completar el círculo."
DISCARD_MESSAGES = {
    "zero_faces": "Coloca tu cara dentro del círculo.",
    "multiple_faces": "Hay más de una cara frente a la cámara.",
    "insufficient_confidence": "Mantén la cara frente a la cámara.",
    "blurry": "Quédate quieto un momento.",
    "off_center": "Centra tu cara en el círculo.",
    "face_too_small": "Acércate un poco a la cámara.",
    "face_too_large": "Aléjate un poco de la cámara.",
    "insufficient_movement": MOVE_HEAD,
    "duplicate_pose": MOVE_HEAD,
    "pose_limit_reached": MOVE_HEAD,
}


def ask_username(service: EnrollmentService) -> tuple[str, bool] | None:
    """Prompts for the username and whether to add samples to an existing user.

    Returns:
        (username, append), or None if the user cancels.
    """
    try:
        username = input("Nombre del usuario a registrar: ").strip()
        append = False
        if username and service.persistence.user_exists(username):
            answer = input(f"'{username}' ya existe. ¿Agregar muestras a su perfil? (s/n): ")
            if answer.strip().lower() not in ("s", "si", "sí", "y", "yes"):
                return None
            append = True
        return username, append
    except (KeyboardInterrupt, EOFError):
        return None


def main() -> None:
    """Runs the interactive enrollment demo."""
    event_bus = EventBus()
    config = EnrollmentConfig(
        num_samples=8,
        min_confidence=0.6,
        resolution=(640, 480),
        max_time_between_captures=8.0,
        data_dir="data",
        target_fps=10.0,
        cooldown_between_captures=0.5,
        min_face_movement=0.015,
        min_pose_change=0.1,
        min_face_size=0.12,
        max_face_size=0.8,
        max_face_offset=0.25,
        min_blur_threshold=40.0,
        max_samples_per_pose=4,  # CENTER max 4, every other pose max 2
    )

    recognition = Recognition(
        event_bus=event_bus,
        confidence_threshold=config.min_confidence,
        min_face_size=config.min_face_size,
        max_face_offset_y=0.65,
        consecutive_frames_required=3,
    )
    camera = Camera(device_index=0, width=config.resolution[0], height=config.resolution[1], fps=30.0)
    service = EnrollmentService(camera=camera, recognition=recognition, event_bus=event_bus, config=config)

    answer = ask_username(service)
    if answer is None:
        print("Operación cancelada.")
        return
    username, append = answer

    overlay = FaceIdOverlay(
        yaw_threshold=config.pose_yaw_threshold,
        pitch_threshold=config.pose_pitch_threshold,
    )
    state = {"title": "Coloca tu cara dentro del círculo.", "accepted": 0, "last_frame": None}

    def on_accepted(payload: dict) -> None:
        state["accepted"] = payload["sample_index"]
        state["title"] = MOVE_HEAD

    def on_discarded(payload: dict) -> None:
        state["title"] = DISCARD_MESSAGES.get(payload["reason"], MOVE_HEAD)

    event_bus.subscribe("ENROLLMENT_FRAME_ACCEPTED", on_accepted)
    event_bus.subscribe("ENROLLMENT_FRAME_DISCARDED", on_discarded)

    def show(canvas: np.ndarray) -> None:
        cv2.imshow(WINDOW_NAME, canvas)
        if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
            raise KeyboardInterrupt("Cancelado desde la ventana.")

    def on_frame(frame: np.ndarray, detections: list) -> None:
        state["last_frame"] = frame.copy()
        head_pose = estimate_head_pose(detections[0].keypoints) if len(detections) == 1 else None
        overlay.update(head_pose)
        subtitle = f"Muestras: {state['accepted']} de {config.num_samples}"
        show(overlay.render(frame, state["title"], subtitle))

    def show_final(title: str, subtitle: str, error: bool = False, seconds: float = 2.5) -> None:
        """Keeps the last camera frame on screen with a final message."""
        if state["last_frame"] is None:
            return
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                show(overlay.render(state["last_frame"], title, subtitle, error=error))
            except KeyboardInterrupt:
                return

    try:
        metadata = service.enroll(username, on_frame=on_frame, append=append)
        overlay.mark_complete()
        show_final("Face ID configurado", f"{metadata['sample_count']} muestras guardadas para {username}.")
        print(f"\nRegistro completado: {metadata['sample_count']} muestras en data/users/{username}/")
    except KeyboardInterrupt:
        print("\nRegistro cancelado.")
    except (InvalidUserError, UserAlreadyExistsError, UserNotFoundError) as e:
        print(f"\n[ERROR] {e}")
    except EnrollmentTimeoutError:
        show_final("Se agotó el tiempo", "Vuelve a intentarlo con buena luz.", error=True)
        print("\n[ERROR] Se agotó el tiempo entre capturas.")
    except CameraError as e:
        print(f"\n[ERROR] No se pudo acceder a la cámara: {e}")
    except EnrollmentError as e:
        show_final("No se pudo configurar", str(e), error=True)
        print(f"\n[ERROR] {e}")
    finally:
        camera.stop()
        recognition.close()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass


if __name__ == "__main__":
    main()
