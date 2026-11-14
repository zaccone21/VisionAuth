"""Liveness detection based on temporal embeddings and bounding box micro-movements.
"""

import numpy as np
import logging
from visionauth.recognition.recognition_embeddings import cosine_similarity

logger = logging.getLogger(__name__)


class LivenessResult:
    """Holds evaluation results of a liveness check."""

    def __init__(self, is_live: bool, score: float, reason: str) -> None:
        self.is_live = is_live
        self.score = score
        self.reason = reason


class LivenessDetector:
    """Detects face liveness using micro-movements and temporal embedding variation.

    Requires a rolling buffer of size N (default 10) to compute checks.
    """

    def __init__(
        self,
        buffer_size: int = 10,
        min_cos_dist: float = 0.01,
        max_cos_dist: float = 0.25,
        min_bbox_variance: float = 1e-6,
        required_valid_ratio: float = 0.7,  # e.g., 7 out of 10 (or 7 out of 9 transitions)
    ) -> None:
        self.buffer_size = buffer_size
        self.min_cos_dist = min_cos_dist
        self.max_cos_dist = max_cos_dist
        self.min_bbox_variance = min_bbox_variance
        self.required_valid_ratio = required_valid_ratio

        self.embeddings: list[np.ndarray] = []
        self.centers: list[tuple[float, float]] = []
        self.areas: list[float] = []

    def clear(self) -> None:
        """Clears all buffered frame details."""
        self.embeddings.clear()
        self.centers.clear()
        self.areas.clear()

    def add_frame(self, embedding: np.ndarray, bbox: tuple[float, float, float, float]) -> None:
        """Adds a detection frame to the temporal rolling buffer.

        Args:
            embedding: L2-normalized face embedding numpy array.
            bbox: Bounding box relative coordinates (xmin, ymin, width, height).
        """
        xmin, ymin, w, h = bbox
        center_x = xmin + w / 2.0
        center_y = ymin + h / 2.0
        area = w * h

        self.embeddings.append(embedding)
        self.centers.append((center_x, center_y))
        self.areas.append(area)

        # Enforce rolling buffer window
        if len(self.embeddings) > self.buffer_size:
            self.embeddings.pop(0)
            self.centers.pop(0)
            self.areas.pop(0)

    def evaluate(self) -> LivenessResult:
        """Evaluates liveness based on the current buffer contents."""
        n = len(self.embeddings)
        if n < self.buffer_size:
            return LivenessResult(
                is_live=False,
                score=0.0,
                reason=f"Accumulating frames: {n}/{self.buffer_size}"
            )

        # 1. Micro-movement: check bounding box center variance
        centers_x = [c[0] for c in self.centers]
        centers_y = [c[1] for c in self.centers]
        var_x = float(np.var(centers_x))
        var_y = float(np.var(centers_y))
        total_var = var_x + var_y

        if total_var < self.min_bbox_variance:
            return LivenessResult(
                is_live=False,
                score=0.0,
                reason=f"Spoof detected: static bounding box (variance {total_var:.8f} < {self.min_bbox_variance:.8f})"
            )

        # 2. Embedding variance: compute consecutive frame transition distances
        valid_transitions = 0
        total_transitions = n - 1

        for i in range(1, n):
            cos_sim = cosine_similarity(self.embeddings[i], self.embeddings[i - 1])
            cos_dist = 1.0 - cos_sim
            
            # Natural micro-movements yield small embedding variation
            is_valid = self.min_cos_dist <= cos_dist <= self.max_cos_dist
            if is_valid:
                valid_transitions += 1

        valid_ratio = valid_transitions / total_transitions
        liveness_score = float(valid_ratio)

        if valid_ratio < self.required_valid_ratio:
            return LivenessResult(
                is_live=False,
                score=liveness_score,
                reason=f"Spoof detected: inconsistent embedding variation (ratio {valid_ratio:.2f} < {self.required_valid_ratio:.2f})"
            )

        return LivenessResult(
            is_live=True,
            score=liveness_score,
            reason="Liveness verified: natural micro-movements detected"
        )
