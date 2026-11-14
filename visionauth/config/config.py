"""Configuration structures for the VisionAuth application.

This module contains configuration classes and defaults used by components
like Enrollment and Camera.
"""

from dataclasses import dataclass

from visionauth.recognition.head_pose import DEFAULT_PITCH_THRESHOLD, DEFAULT_YAW_THRESHOLD


@dataclass
class EnrollmentConfig:
    """Configuration options for the enrollment process.

    Attributes:
        num_samples: Number of valid face samples to capture.
        min_confidence: Minimum confidence threshold for face detection.
        resolution: Camera target resolution as a (width, height) tuple.
        max_time_between_captures: Max seconds allowed between successive valid captures.
        data_dir: Base directory path for storing user data.
        min_face_movement: Min bbox center shift between captures, used when the
            detector provides no landmarks.
        min_pose_change: Min head rotation (yaw/pitch distance) between captures,
            used instead of min_face_movement when landmarks are available.
        pose_yaw_threshold: Yaw beyond which a sample counts as LEFT or RIGHT.
        pose_pitch_threshold: Pitch beyond which a sample counts as UP or DOWN.
        min_sample_similarity: Samples less similar than this to the centroid
            are discarded as not belonging to the same person.
    """

    num_samples: int = 8
    min_confidence: float = 0.2
    resolution: tuple[int, int] = (640, 480)
    max_time_between_captures: float = 5.0
    data_dir: str = "data"
    stability_window_size: int = 7
    stability_consecutive_threshold: int = 4
    target_fps: float = 0.0
    cooldown_between_captures: float = 0.0
    min_face_movement: float = 0.0
    min_face_size: float = 0.0
    max_face_size: float = 1.0
    max_face_offset: float = 1.0
    min_blur_threshold: float = 0.0
    max_samples_per_pose: int = 0
    min_pose_change: float = 0.0
    pose_yaw_threshold: float = DEFAULT_YAW_THRESHOLD
    pose_pitch_threshold: float = DEFAULT_PITCH_THRESHOLD
    min_sample_similarity: float = 0.4
