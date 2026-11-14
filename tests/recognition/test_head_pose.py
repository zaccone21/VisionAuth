"""Unit tests for landmark-based head pose estimation."""

import pytest

from visionauth.recognition.head_pose import (
    NEUTRAL_PITCH_RATIO,
    HeadPose,
    classify_pose,
    estimate_head_pose,
)


def make_keypoints(yaw: float = 0.0, pitch: float = 0.0) -> tuple[tuple[float, float], ...]:
    """Builds MediaPipe-ordered keypoints for a face with the given pose.

    Eyes are 0.1 apart horizontally and 0.2 above the mouth, so the nose offset
    maps directly onto the expected yaw and pitch values.
    """
    eye_y, mouth_y = 0.4, 0.6
    nose = (0.5 + yaw * 0.1, eye_y + (NEUTRAL_PITCH_RATIO - pitch) * 0.2)
    return (
        (0.45, eye_y),  # right eye (image left on an unmirrored frame)
        (0.55, eye_y),  # left eye
        nose,
        (0.5, mouth_y),
        (0.38, 0.45),
        (0.62, 0.45),
    )


def test_frontal_face_has_zero_pose() -> None:
    pose = estimate_head_pose(make_keypoints())
    assert pose is not None
    assert pose.yaw == pytest.approx(0.0)
    assert pose.pitch == pytest.approx(0.0)


def test_pose_values_follow_nose_offset() -> None:
    pose = estimate_head_pose(make_keypoints(yaw=0.3, pitch=-0.15))
    assert pose is not None
    assert pose.yaw == pytest.approx(0.3)
    assert pose.pitch == pytest.approx(-0.15)


@pytest.mark.parametrize("keypoints", [None, (), ((0.5, 0.5),) * 3])
def test_missing_landmarks_return_none(keypoints: tuple | None) -> None:
    assert estimate_head_pose(keypoints) is None


def test_degenerate_landmarks_return_none() -> None:
    # Both eyes at the same point
    keypoints = ((0.5, 0.4), (0.5, 0.4), (0.5, 0.5), (0.5, 0.6))
    assert estimate_head_pose(keypoints) is None


@pytest.mark.parametrize(
    ("yaw", "pitch", "expected"),
    [
        (0.0, 0.0, "CENTER"),
        (0.1, 0.05, "CENTER"),
        (0.3, 0.0, "LEFT"),
        (-0.3, 0.0, "RIGHT"),
        (0.0, 0.2, "UP"),
        (0.0, -0.2, "DOWN"),
        (0.25, 0.2, "UP"),  # pitch is further past its threshold than yaw
    ],
)
def test_classify_pose(yaw: float, pitch: float, expected: str) -> None:
    assert classify_pose(HeadPose(yaw=yaw, pitch=pitch), yaw_threshold=0.2, pitch_threshold=0.12) == expected
