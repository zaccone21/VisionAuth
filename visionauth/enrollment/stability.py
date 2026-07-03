"""Temporal stability tracking for face detection in VisionAuth.

Maintains a history of face counts and filters out frame-by-frame flicker
to ensure smooth state transitions.
"""

import logging

logger = logging.getLogger(__name__)


class FaceStabilityTracker:
    """Filters high-frequency changes (flickering) in detected face counts.

    Utilizes a sliding window of past frames and a consecutive frame threshold
    to determine the current stable face count.
    """

    def __init__(self, window_size: int = 5, consecutive_threshold: int = 3) -> None:
        """Initializes the FaceStabilityTracker.

        Args:
            window_size: The max number of historical frames to store in the buffer.
            consecutive_threshold: The number of consecutive frames required
                to accept a state transition.
        """
        self.window_size: int = window_size
        self.consecutive_threshold: int = consecutive_threshold

        self.history: list[int] = []
        self.current_stable_count: int = 0

        self.candidate_value: int | None = None
        self.candidate_count: int = 0

    def update(self, face_count: int) -> int:
        """Updates the tracker with a new raw face count and returns the stable count.

        Args:
            face_count: The raw number of faces detected in the current frame.

        Returns:
            The stabilized face count.
        """
        # Append to sliding window
        self.history.append(face_count)
        if len(self.history) > self.window_size:
            self.history.pop(0)

        # Detect potential state transition
        if face_count != self.current_stable_count:
            if face_count == self.candidate_value:
                self.candidate_count += 1
            else:
                self.candidate_value = face_count
                self.candidate_count = 1

            if self.candidate_count >= self.consecutive_threshold:
                logger.info(
                    "Face count state transitioned: %d -> %d (sustained for %d frames)",
                    self.current_stable_count,
                    face_count,
                    self.candidate_count,
                )
                self.current_stable_count = face_count
                self.candidate_value = None
                self.candidate_count = 0
        else:
            # Current count matches stable count, reset candidate tracker
            self.candidate_value = None
            self.candidate_count = 0

        logger.info(
            "Stability - Raw: %d, Stable: %d, History: %s",
            face_count,
            self.current_stable_count,
            self.history,
        )

        return self.current_stable_count
