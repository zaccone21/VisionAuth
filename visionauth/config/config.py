"""Configuration structures for the VisionAuth application.

This module contains configuration classes and defaults used by components
like Enrollment and Camera.
"""

from dataclasses import dataclass


@dataclass
class EnrollmentConfig:
    """Configuration options for the enrollment process.

    Attributes:
        num_samples: Number of valid face samples to capture.
        min_confidence: Minimum confidence threshold for face detection.
        resolution: Camera target resolution as a (width, height) tuple.
        max_time_between_captures: Max seconds allowed between successive valid captures.
        data_dir: Base directory path for storing user data.
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
