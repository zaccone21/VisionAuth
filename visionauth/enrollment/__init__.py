"""Enrollment module initialization.

Exposes the primary service, config, embedder interface, and custom exceptions.
"""

from visionauth.enrollment.embedder import DummyFaceEmbedder, FaceEmbedder, RealFaceEmbedder
from visionauth.enrollment.enrollment import (
    EnrollmentError,
    EnrollmentService,
    EnrollmentTimeoutError,
    InvalidUserError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from visionauth.enrollment.stability import FaceStabilityTracker

__all__ = [
    "EnrollmentService",
    "EnrollmentError",
    "InvalidUserError",
    "UserAlreadyExistsError",
    "UserNotFoundError",
    "EnrollmentTimeoutError",
    "FaceEmbedder",
    "DummyFaceEmbedder",
    "RealFaceEmbedder",
    "FaceStabilityTracker",
]
