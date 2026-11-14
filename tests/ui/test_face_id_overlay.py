"""Unit tests for the Face ID style enrollment overlay."""

import math

import numpy as np

from visionauth.recognition.head_pose import HeadPose
from visionauth.ui.face_id_overlay import FaceIdOverlay


def covered_angles(overlay: FaceIdOverlay) -> list[float]:
    """Screen angles in degrees (0 = right, 90 = down) of the covered ticks."""
    return [math.degrees(2 * math.pi * i / overlay.tick_count) for i in np.flatnonzero(overlay.covered)]


def look(overlay: FaceIdOverlay, pose: HeadPose, frames: int = 10) -> None:
    for _ in range(frames):
        overlay.update(pose)


def test_frontal_face_covers_nothing() -> None:
    overlay = FaceIdOverlay()
    look(overlay, HeadPose(yaw=0.0, pitch=0.0))
    assert overlay.coverage == 0.0


def test_turning_left_covers_left_side_of_mirrored_view() -> None:
    overlay = FaceIdOverlay(yaw_threshold=0.2, pitch_threshold=0.12)
    look(overlay, HeadPose(yaw=0.4, pitch=0.0))
    angles = covered_angles(overlay)
    assert angles
    assert all(150 <= a <= 210 for a in angles)


def test_looking_up_covers_top_of_ring() -> None:
    overlay = FaceIdOverlay(yaw_threshold=0.2, pitch_threshold=0.12)
    look(overlay, HeadPose(yaw=0.0, pitch=0.3))
    # Screen y grows downwards, so "up" is around 270 degrees
    assert all(240 <= a <= 300 for a in covered_angles(overlay))


def test_reset_clears_coverage() -> None:
    overlay = FaceIdOverlay()
    look(overlay, HeadPose(yaw=0.5, pitch=0.0))
    overlay.reset()
    assert overlay.coverage == 0.0


def test_render_returns_canvas_of_requested_size() -> None:
    overlay = FaceIdOverlay(canvas_size=(400, 500))
    frame = np.full((480, 640, 3), 100, dtype=np.uint8)
    canvas = overlay.render(frame, "Título con tildes y ñ", "subtítulo")
    assert canvas.shape == (500, 400, 3)
    overlay.mark_complete()
    assert overlay.render(frame, "Listo").shape == (500, 400, 3)
