"""Authentication service implementation for VisionAuth.
"""

import time
import cv2
import numpy as np
import logging
from visionauth.camera.camera import Camera
from visionauth.events.event_bus import EventBus, EventType
from visionauth.recognition.recognition import Recognition
from visionauth.enrollment.embedder import RealFaceEmbedder
from visionauth.persistence.persistence import UserPersistence
from visionauth.liveness.liveness_detector import LivenessDetector
from visionauth.recognition.recognition_embeddings import (
    DEFAULT_MATCH_THRESHOLD,
    crop_face,
    is_profile_compatible,
)

logger = logging.getLogger(__name__)


class AuthResult:
    """Represents the outcome of an authentication request."""

    def __init__(self, success: bool, reason: str, confidence: float, user: str | None) -> None:
        self.success = success
        self.reason = reason
        self.confidence = confidence
        self.user = user


class AuthService:
    """Orchestrates the biometric authentication pipeline with liveness verification.
    """

    def __init__(
        self,
        camera: Camera,
        recognition: Recognition,
        persistence: UserPersistence | None = None,
        embedder: RealFaceEmbedder | None = None,
        liveness_detector: LivenessDetector | None = None,
        auth_threshold: float = DEFAULT_MATCH_THRESHOLD,
        max_auth_time: float = 5.0,
        event_bus: EventBus | None = None,
    ) -> None:
        self.camera = camera
        self.recognition = recognition
        self.persistence = persistence or UserPersistence()
        self.embedder = embedder or RealFaceEmbedder()
        self.liveness_detector = liveness_detector or LivenessDetector()
        self.auth_threshold = auth_threshold
        self.max_auth_time = max_auth_time
        self.event_bus = event_bus

    def authenticate(self, username: str, visualize: bool = False) -> AuthResult:
        """Processes live frame inputs to authenticate a user.

        On success publishes FACE_RECOGNIZED, AUTH_SUCCESS and UNLOCK_REQUESTED,
        in that order; on failure publishes AUTH_FAILED with the reason.

        Args:
            username: The registered username.
            visualize: If True, draws rectangles and displays window preview.

        Returns:
            AuthResult instance containing status, reason, confidence, and username.
        """
        return self.authenticate_any([username], visualize)

    def authenticate_any(self, usernames: list[str], visualize: bool = False) -> AuthResult:
        """Authenticates the live face against several enrolled faces.

        Faces without a usable profile (removed, renamed or made with another
        model) are skipped. On success the result's user is the closest face.
        Events are published as in authenticate(); a failure names every face.

        Args:
            usernames: The enrolled faces to compare against.
            visualize: If True, draws rectangles and displays window preview.
        """
        result = self._authenticate(usernames, visualize)
        self._publish(", ".join(usernames), result)
        return result

    def _publish(self, username: str, result: AuthResult) -> None:
        """Publishes the outcome of an authentication attempt on the EventBus."""
        if self.event_bus is None:
            return
        if result.success:
            # A separate payload per event, so a handler that edits one cannot change the next
            self.event_bus.emit(EventType.FACE_RECOGNIZED, {"user": result.user, "confidence": result.confidence})
            self.event_bus.emit(EventType.AUTH_SUCCESS, {"user": result.user, "confidence": result.confidence})
            self.event_bus.emit(EventType.UNLOCK_REQUESTED, {"user": result.user})
        else:
            self.event_bus.emit(EventType.AUTH_FAILED, {"user": username, "reason": result.reason})

    def _load_references(self, usernames: list[str]) -> tuple[np.ndarray, list[str]] | AuthResult:
        """Stacks the enrolled samples of every usable face, with the face each row belongs to.

        Returns:
            (references, owners), or a failed AuthResult if no face is usable.
        """
        rows: list[list[float]] = []
        owners: list[str] = []
        reason = "user_not_found"
        for username in usernames:
            profile = self.persistence.load_user_profile(username)
            if profile is None:
                logger.error("Face '%s' has no profile: skipped.", username)
                continue
            if not is_profile_compatible(profile):
                logger.error("Face '%s' was enrolled with an incompatible embedding model. Please enroll again.", username)
                reason = "incompatible_profile"
                continue
            # Match against every enrolled sample rather than their average, so a face
            # seen from the side is compared with the samples taken from that side
            samples = profile.get("embeddings") or []
            if not samples and profile.get("centroid") is not None:
                samples = [profile["centroid"]]
            if not samples:
                logger.error("Face '%s' has no embeddings in its profile.", username)
                reason = "invalid_profile_data"
                continue
            rows.extend(samples)
            owners.extend([username] * len(samples))
        if not rows:
            return AuthResult(success=False, reason=reason, confidence=0.0, user=None)
        logger.info("Loaded %d reference embedding(s) for %s", len(rows), ", ".join(dict.fromkeys(owners)))
        return np.array(rows, dtype=np.float32), owners

    def _authenticate(self, usernames: list[str], visualize: bool) -> AuthResult:
        """Runs the authentication pipeline without publishing events."""
        # 1. Load the enrolled samples of every face
        loaded = self._load_references(usernames)
        if isinstance(loaded, AuthResult):
            return loaded
        references, owners = loaded

        # 2. Start camera
        camera_started_by_us = False
        if not self.camera.is_running:
            try:
                self.camera.start()
                camera_started_by_us = True
            except Exception as e:
                logger.error("Failed to start camera: %s", e)
                return AuthResult(success=False, reason="camera_error", confidence=0.0, user=None)

        self.liveness_detector.clear()
        start_time = time.time()

        try:
            for frame in self.camera.frames():
                now = time.time()
                if now - start_time > self.max_auth_time:
                    logger.warning("Authentication timeout.")
                    return AuthResult(success=False, reason="timeout", confidence=0.0, user=None)

                # Detection
                detections = self.recognition.process_frame(frame)

                if len(detections) == 1:
                    det = detections[0]
                    xmin, ymin, width, height = det.bounding_box
                    h_img, w_img, _ = frame.shape
                    
                    x = max(0, int(xmin * w_img))
                    y = max(0, int(ymin * h_img))
                    w = min(w_img - x, int(width * w_img))
                    h = min(h_img - y, int(height * h_img))

                    face_crop = crop_face(frame, det.bounding_box, padding=0.15)

                    if face_crop.size > 0:
                        emb = self.embedder.generate_embedding(face_crop)

                        # Feed liveness buffer
                        self.liveness_detector.add_frame(emb, det.bounding_box)

                        # Evaluate liveness
                        liveness_res = self.liveness_detector.evaluate()

                        # Optional rendering
                        if visualize:
                            color = (0, 255, 0) if liveness_res.is_live else (0, 0, 255)
                            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                            cv2.putText(
                                frame,
                                f"Live: {liveness_res.is_live} ({liveness_res.score:.2f})",
                                (x, max(0, y - 10)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                color,
                                1,
                                cv2.LINE_AA,
                            )
                            cv2.imshow("VisionAuth Authenticate", frame)
                            cv2.waitKey(1)

                        # Evaluate biometric match only if live
                        if liveness_res.is_live:
                            similarities = references @ emb
                            best = int(np.argmax(similarities))
                            sim = float(similarities[best])
                            username = owners[best]
                            logger.info("Similarity score: %.4f (threshold: %.2f)", sim, self.auth_threshold)
                            if sim >= self.auth_threshold:
                                logger.info("MATCH decision: User '%s' authenticated successfully. Similarity: %.4f", username, sim)
                                return AuthResult(success=True, reason="success", confidence=sim, user=username)
                            else:
                                logger.info("NO MATCH decision: Biometric mismatch for '%s'. Similarity: %.4f", username, sim)
                        else:
                            # Immediate rejection on explicit spoof diagnosis
                            if "Spoof detected" in liveness_res.reason:
                                logger.warning("Spoofing attempt detected: %s", liveness_res.reason)
                                return AuthResult(success=False, reason="spoof_detected", confidence=0.0, user=None)
                else:
                    # Clear buffer if face tracking is lost
                    self.liveness_detector.clear()
                    if visualize:
                        cv2.imshow("VisionAuth Authenticate", frame)
                        cv2.waitKey(1)

            return AuthResult(success=False, reason="no_face_detected", confidence=0.0, user=None)

        finally:
            if camera_started_by_us:
                self.camera.stop()
            if visualize:
                try:
                    cv2.destroyWindow("VisionAuth Authenticate")
                except cv2.error:
                    pass
