"""Unit test to simulate face liveness detection with real micro-movements."""

import numpy as np
from visionauth.liveness.liveness_detector import LivenessDetector


def test_liveness_real_motion() -> None:
    """Simulates a live user with slight head movements and normal embedding noise."""
    detector = LivenessDetector(
        buffer_size=10,
        min_bbox_variance=1e-6,
        min_cos_dist=0.01,
        max_cos_dist=0.25,
    )

    # Fill buffer with simulated active frames
    np.random.seed(42)
    
    for i in range(10):
        # Micro-movements: slight center shifts
        shift_x = 0.002 * (i % 3 - 1)
        shift_y = 0.001 * (i % 2 * 2 - 1)
        bbox = (0.35 + shift_x, 0.35 + shift_y, 0.3, 0.3)
        
        # Slight variation in embedding (cosine distance around 0.02 - 0.05)
        emb = np.zeros(512, dtype=np.float32)
        emb[0] = 1.0
        # Add random noise to embeddings
        noise = np.random.normal(0.0, 0.02, 512).astype(np.float32)
        emb += noise
        emb /= np.linalg.norm(emb)
        
        detector.add_frame(emb, bbox)

    res = detector.evaluate()
    assert res.is_live is True
    assert "Liveness verified" in res.reason
