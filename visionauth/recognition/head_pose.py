"""Approximate head pose estimation from the face detector's 2D landmarks.

The MediaPipe face detector returns six keypoints per face. The nose tip sits
in front of the plane of the eyes and mouth, so its offset from the eye
midpoint grows as the head turns. That offset, measured in inter-eye and
eye-to-mouth distances, is a cheap and scale-independent pose signal.
"""

from dataclasses import dataclass

RIGHT_EYE = 0
LEFT_EYE = 1
NOSE_TIP = 2
MOUTH_CENTER = 3

# Nose tip position between the eyes (0.0) and the mouth (1.0) on a frontal face.
NEUTRAL_PITCH_RATIO = 0.55
MIN_LANDMARK_DISTANCE = 1e-3

DEFAULT_YAW_THRESHOLD = 0.2
DEFAULT_PITCH_THRESHOLD = 0.12


@dataclass(frozen=True)
class HeadPose:
    """Approximate head rotation derived from 2D landmarks.

    Attributes:
        yaw: Horizontal nose offset from the eye midpoint, in inter-eye distances.
            Positive when the person turns toward their own left.
        pitch: Vertical nose offset relative to a frontal face, in eye-to-mouth
            distances. Positive when the person looks up.
    """

    yaw: float
    pitch: float


def estimate_head_pose(keypoints: tuple[tuple[float, float], ...] | None) -> HeadPose | None:
    """Estimates yaw and pitch from detector keypoints.

    Args:
        keypoints: Relative (x, y) landmarks in MediaPipe order, on an unmirrored frame.

    Returns:
        The estimated HeadPose, or None if the landmarks are missing or degenerate.
    """
    if keypoints is None or len(keypoints) <= MOUTH_CENTER:
        return None

    right_eye_x, right_eye_y = keypoints[RIGHT_EYE]
    left_eye_x, left_eye_y = keypoints[LEFT_EYE]
    nose_x, nose_y = keypoints[NOSE_TIP]
    _, mouth_y = keypoints[MOUTH_CENTER]

    eye_mid_x = (right_eye_x + left_eye_x) / 2
    eye_mid_y = (right_eye_y + left_eye_y) / 2
    eye_distance = abs(left_eye_x - right_eye_x)
    eye_to_mouth = mouth_y - eye_mid_y
    if eye_distance < MIN_LANDMARK_DISTANCE or eye_to_mouth < MIN_LANDMARK_DISTANCE:
        return None

    # On an unmirrored frame the person's left is the image's right.
    yaw = (nose_x - eye_mid_x) / eye_distance
    pitch = NEUTRAL_PITCH_RATIO - (nose_y - eye_mid_y) / eye_to_mouth
    return HeadPose(yaw=yaw, pitch=pitch)


def classify_pose(
    pose: HeadPose,
    yaw_threshold: float = DEFAULT_YAW_THRESHOLD,
    pitch_threshold: float = DEFAULT_PITCH_THRESHOLD,
) -> str:
    """Buckets a head pose into CENTER, LEFT, RIGHT, UP or DOWN.

    LEFT and RIGHT are from the person's point of view. The dominant axis wins
    when the head is turned both horizontally and vertically.
    """
    yaw_strength = abs(pose.yaw) / yaw_threshold
    pitch_strength = abs(pose.pitch) / pitch_threshold
    if max(yaw_strength, pitch_strength) < 1.0:
        return "CENTER"
    if yaw_strength >= pitch_strength:
        return "LEFT" if pose.yaw > 0 else "RIGHT"
    return "UP" if pose.pitch > 0 else "DOWN"
