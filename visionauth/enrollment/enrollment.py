"""Core enrollment service for VisionAuth.

Orchestrates user registration by capturing valid camera frames,
verifying presence of exactly one face, and persisting metadata and samples.
"""

import logging
import time
from collections.abc import Callable
from typing import Any
import numpy as np

from visionauth.camera.camera import Camera, CameraError
from visionauth.config.config import EnrollmentConfig
from visionauth.faces import InvalidFaceName, validate_face_name
from visionauth.events.event_bus import EventBus
from visionauth.enrollment.embedder import DummyFaceEmbedder, FaceEmbedder, RealFaceEmbedder
from visionauth.enrollment.stability import FaceStabilityTracker
from visionauth.persistence.persistence import UserPersistence
from visionauth.recognition.recognition import DetectionResult, Recognition
from visionauth.recognition.head_pose import HeadPose, classify_pose, estimate_head_pose
from visionauth.recognition.recognition_embeddings import EMBEDDING_DIMENSION, is_profile_compatible

logger = logging.getLogger(__name__)


class EnrollmentError(Exception):
    """Base class for enrollment-related errors."""

    pass


class InvalidUserError(EnrollmentError, ValueError):
    """Raised when the username is invalid."""

    pass


class UserAlreadyExistsError(EnrollmentError):
    """Raised when attempting to enroll a user who is already registered."""

    pass


class UserNotFoundError(EnrollmentError):
    """Raised when adding samples to a user who is not enrolled."""

    pass


class EnrollmentTimeoutError(EnrollmentError):
    """Raised when the time limit between successful captures is exceeded."""

    pass


class EnrollmentService:
    """Orchestrates the enrollment process for registering users in the system."""

    def __init__(
        self,
        camera: Camera,
        recognition: Recognition,
        event_bus: EventBus,
        persistence: UserPersistence | None = None,
        embedder: FaceEmbedder | None = None,
        config: EnrollmentConfig | None = None,
    ) -> None:
        """Initializes the EnrollmentService.

        Args:
            camera: The Camera instance to grab frames from.
            recognition: The Recognition face detector.
            event_bus: The EventBus instance for event notifications.
            persistence: UserPersistence helper. Defaults to a new instance.
            config: EnrollmentConfig configuration. Defaults to standard configuration.
            embedder: FaceEmbedder implementation. Defaults to RealFaceEmbedder.
        """
        self.camera: Camera = camera
        self.recognition: Recognition = recognition
        self.event_bus: EventBus = event_bus
        self.config: EnrollmentConfig = config or EnrollmentConfig()
        self.persistence: UserPersistence = persistence or UserPersistence(
            data_dir=self.config.data_dir
        )
        self.embedder: FaceEmbedder = embedder or RealFaceEmbedder()
        self.stability_tracker = FaceStabilityTracker(
            window_size=self.config.stability_window_size,
            consecutive_threshold=self.config.stability_consecutive_threshold,
        )

    def _validate_username(self, username: str) -> None:
        """Validates the username format.

        Raises:
            InvalidUserError: If the name cannot be used for a face (see validate_face_name).
        """
        try:
            validate_face_name(username)
        except InvalidFaceName as e:
            raise InvalidUserError(str(e)) from e

    def enroll(
        self,
        username: str,
        on_frame: Callable[[Any, list[DetectionResult]], None] | None = None,
        visualize: bool = False,
        append: bool = False,
    ) -> dict[str, Any]:
        """Registers a new user by capturing valid face samples from the camera.

        Args:
            username: The unique identifier for the user.
            on_frame: Optional callback invoked after each frame is processed,
                receiving (frame, detections).
            visualize: If True, displays a real-time visual preview of detections.
            append: If True, adds the new samples to an existing user instead of
                creating one, e.g. to enroll again from the final camera position.

        Returns:
            The created user metadata dictionary.

        Raises:
            InvalidUserError: If the username fails validation.
            UserAlreadyExistsError: If the user is already enrolled and append is False.
            UserNotFoundError: If append is True and the user is not enrolled.
            EnrollmentTimeoutError: If the timeout between captures is exceeded.
            CameraError: If the camera cannot start or fails to return frames.
            EnrollmentError: For any other enrollment execution failures.
        """
        # Validate user name and check duplicates
        self._validate_username(username)
        username = username.strip()

        if append:
            profile = self.persistence.load_user_profile(username)
            if profile is None:
                logger.error("Cannot add samples: user '%s' is not enrolled.", username)
                raise UserNotFoundError(f"User '{username}' is not enrolled.")
            if not is_profile_compatible(profile):
                raise EnrollmentError(
                    f"User '{username}' was enrolled with an incompatible embedding model. "
                    "Enroll again from scratch."
                )
        elif self.persistence.user_exists(username):
            logger.error("User '%s' is already registered.", username)
            raise UserAlreadyExistsError(f"User '{username}' is already registered.")

        logger.info("Starting enrollment process for user '%s'", username)
        self.event_bus.emit("ENROLLMENT_STARTED", {"username": username})

        self.stability_tracker = FaceStabilityTracker(
            window_size=self.config.stability_window_size,
            consecutive_threshold=self.config.stability_consecutive_threshold,
        )

        samples: list[Any] = []
        embeddings: list[list[float]] = []
        sample_poses: list[dict[str, Any]] = []
        last_head_pose: HeadPose | None = None
        last_capture_time = time.time()
        last_processed_time = 0.0
        last_bbox_center: tuple[float, float] | None = None
        last_bounding_box: tuple[float, float, float, float] | None = None
        
        # Biometric quality and diversity counters
        pose_counts = {"LEFT": 0, "RIGHT": 0, "CENTER": 0, "UP": 0, "DOWN": 0}
        last_accepted_pose: str | None = None
        consecutive_blurry_count = 0
        
        camera_started_by_us = False

        # Performance tracking metrics
        frames_captured = 0
        frames_processed = 0
        frames_skipped = 0
        start_run_time = time.time()
        sum_inference_time = 0.0

        detections: list[DetectionResult] = []
        stable_face_count = 0

        if not self.camera.is_running:
            try:
                self.camera.start()
                camera_started_by_us = True
            except CameraError as e:
                logger.error("Failed to start camera for enrollment: %s", e)
                self.event_bus.emit("ENROLLMENT_FAILED", {"reason": "camera_error"})
                raise

        try:
            # Stream frames from camera
            for frame in self.camera.frames():
                now = time.time()
                frames_captured += 1

                # 1. Throttle real inference: check if we should run face detection (5-10 FPS)
                run_inference = False
                if self.config.target_fps <= 0.0 or (now - last_processed_time >= (1.0 / self.config.target_fps)):
                    run_inference = True
                    last_processed_time = now

                if run_inference:
                    frames_processed += 1
                    t0 = time.time()
                    # Process face detection
                    detections = self.recognition.process_frame(frame)
                    t1 = time.time()
                    sum_inference_time += (t1 - t0)

                    # Stabilize face count
                    stable_face_count = self.stability_tracker.update(len(detections))

                    # Check timeout since last capture
                    time_elapsed = now - last_capture_time
                    if time_elapsed > self.config.max_time_between_captures:
                        logger.error(
                            "Timeout: %.2f seconds exceeded between captures.",
                            time_elapsed,
                        )
                        self.event_bus.emit("ENROLLMENT_FAILED", {"reason": "timeout"})
                        raise EnrollmentTimeoutError(
                            f"Timeout exceeded between captures: {time_elapsed:.2f}s > "
                            f"{self.config.max_time_between_captures}s"
                        )

                    # Determine if this frame is eligible for capture
                    eligible_for_capture = False
                    pose = "CENTER"

                    if stable_face_count == 0:
                        logger.info("Sample rejected: unstable (0 faces detected)")
                        last_capture_time = now  # Reset timeout to prevent timeout debt in empty state
                        self.event_bus.emit(
                            "ENROLLMENT_FRAME_DISCARDED",
                            {
                                "reason": "zero_faces",
                                "current_samples": len(samples),
                            },
                        )
                    elif stable_face_count > 1:
                        logger.info("Sample rejected: unstable (%d faces detected)", stable_face_count)
                        last_capture_time = now  # Reset timeout
                        self.event_bus.emit(
                            "ENROLLMENT_FRAME_DISCARDED",
                            {
                                "reason": "multiple_faces",
                                "current_samples": len(samples),
                            },
                        )
                    else:
                        # stable_face_count == 1
                        if len(detections) > 0:
                            detection = detections[0]
                            xmin, ymin, width, height = detection.bounding_box
                            cx = xmin + width / 2
                            cy = ymin + height / 2

                            # Quality Checks
                            
                            # A. Blur check (Laplacian variance on face ROI)
                            sharp = True
                            if self.config.min_blur_threshold > 0.0:
                                import cv2
                                h_img, w_img, _ = frame.shape
                                x = max(0, int(xmin * w_img))
                                y = max(0, int(ymin * h_img))
                                w = min(w_img - x, int(width * w_img))
                                h = min(h_img - y, int(height * h_img))
                                
                                if w > 0 and h > 0:
                                    face_roi = frame[y:y+h, x:x+w]
                                    if face_roi.size > 0:
                                        gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
                                        blur_var = cv2.Laplacian(gray, cv2.CV_64F).var()
                                        if blur_var < self.config.min_blur_threshold:
                                            sharp = False
                                            consecutive_blurry_count += 1
                                            if consecutive_blurry_count >= 3:
                                                logger.info("Sample rejected: blurry (variance: %.2f < %.2f)", blur_var, self.config.min_blur_threshold)
                                                last_capture_time = now
                                                self.event_bus.emit(
                                                    "ENROLLMENT_FRAME_DISCARDED",
                                                    {
                                                        "reason": "blurry",
                                                        "current_samples": len(samples),
                                                        "blur_variance": blur_var,
                                                    },
                                                )
                                        else:
                                            consecutive_blurry_count = 0
                                else:
                                    sharp = False
                            
                            # Classify pose from head rotation when landmarks exist,
                            # otherwise from the face position in the frame
                            head_pose = estimate_head_pose(detection.keypoints)
                            if head_pose is not None:
                                pose = classify_pose(
                                    head_pose,
                                    yaw_threshold=self.config.pose_yaw_threshold,
                                    pitch_threshold=self.config.pose_pitch_threshold,
                                )
                            elif cx < 0.43:
                                pose = "LEFT"
                            elif cx > 0.57:
                                pose = "RIGHT"
                            else:
                                pose = "CENTER"
                                    
                            if sharp:
                                # B. Centeredness check
                                centered = True
                                if self.config.max_face_offset < 1.0:
                                    offset_x = abs(cx - 0.5)
                                    offset_y = abs(cy - 0.5)
                                    if offset_x > self.config.max_face_offset or offset_y > self.config.max_face_offset:
                                        centered = False
                                        logger.info("Sample rejected: off-center (offset: x=%.2f, y=%.2f > %.2f)", offset_x, offset_y, self.config.max_face_offset)
                                        last_capture_time = now
                                        self.event_bus.emit(
                                            "ENROLLMENT_FRAME_DISCARDED",
                                            {
                                                "reason": "off_center",
                                                "current_samples": len(samples),
                                                "offset": (offset_x, offset_y),
                                            },
                                        )
                                        
                            if sharp and centered:
                                # C. Face size check
                                size_ok = True
                                if width < self.config.min_face_size or height < self.config.min_face_size:
                                    size_ok = False
                                    logger.info("Sample rejected: off-center (too small: w=%.2f, h=%.2f < %.2f)", width, height, self.config.min_face_size)
                                    last_capture_time = now
                                    self.event_bus.emit(
                                        "ENROLLMENT_FRAME_DISCARDED",
                                        {
                                            "reason": "face_too_small",
                                            "current_samples": len(samples),
                                            "size": (width, height),
                                        },
                                    )
                                elif width > self.config.max_face_size or height > self.config.max_face_size:
                                    size_ok = False
                                    logger.info("Sample rejected: off-center (too large: w=%.2f, h=%.2f > %.2f)", width, height, self.config.max_face_size)
                                    last_capture_time = now
                                    self.event_bus.emit(
                                        "ENROLLMENT_FRAME_DISCARDED",
                                        {
                                            "reason": "face_too_large",
                                            "current_samples": len(samples),
                                            "size": (width, height),
                                        },
                                    )
                                    
                            if sharp and centered and size_ok:
                                # D. Cooldown check between successful captures
                                cooldown_ok = True
                                if len(samples) > 0 and self.config.cooldown_between_captures > 0.0:
                                    if now - last_capture_time < self.config.cooldown_between_captures:
                                        cooldown_ok = False

                                if not cooldown_ok:
                                    logger.debug("Waiting for capture cooldown...")
                                else:
                                    # E. Pose Buckets check
                                    pose_ok = True
                                    if self.config.max_samples_per_pose > 0:
                                        limit = self.config.max_samples_per_pose
                                        if self.config.num_samples == 8:
                                            # Custom 4 / 2 / 2 distribution
                                            if pose == "CENTER":
                                                limit = 4
                                            else:
                                                limit = 2
                                                
                                        if pose == last_accepted_pose:
                                            pose_ok = False
                                            logger.info("Sample rejected: duplicate (consecutive identical pose %s)", pose)
                                            last_capture_time = now
                                            self.event_bus.emit(
                                                "ENROLLMENT_FRAME_DISCARDED",
                                                {
                                                    "reason": "duplicate_pose",
                                                    "pose": pose,
                                                    "current_samples": len(samples),
                                                },
                                            )
                                        elif pose_counts.get(pose, 0) >= limit:
                                            pose_ok = False
                                            logger.info("Sample rejected: duplicate (pose bucket limit reached for %s)", pose)
                                            last_capture_time = now
                                            self.event_bus.emit(
                                                "ENROLLMENT_FRAME_DISCARDED",
                                                {
                                                    "reason": "pose_limit_reached",
                                                    "pose": pose,
                                                    "current_samples": len(samples),
                                                },
                                            )

                                    if pose_ok:
                                        # F. Face movement (sample diversity) check
                                        movement_ok = True
                                        if head_pose is not None and last_head_pose is not None:
                                            pose_change = (
                                                (head_pose.yaw - last_head_pose.yaw) ** 2
                                                + (head_pose.pitch - last_head_pose.pitch) ** 2
                                            ) ** 0.5
                                            if pose_change < self.config.min_pose_change:
                                                movement_ok = False
                                                logger.info(
                                                    "Sample rejected: duplicate (insufficient head rotation: %.3f < %.3f).",
                                                    pose_change,
                                                    self.config.min_pose_change,
                                                )
                                                last_capture_time = now
                                                self.event_bus.emit(
                                                    "ENROLLMENT_FRAME_DISCARDED",
                                                    {
                                                        "reason": "insufficient_movement",
                                                        "current_samples": len(samples),
                                                    },
                                                )
                                        elif last_bbox_center is not None and self.config.min_face_movement > 0.0:
                                            prev_cx, prev_cy = last_bbox_center
                                            dist = ((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2) ** 0.5
                                            if dist < self.config.min_face_movement:
                                                movement_ok = False
                                                logger.info(
                                                    "Sample rejected: duplicate (insufficient movement: %.4f < %.4f).",
                                                    dist,
                                                    self.config.min_face_movement,
                                                )
                                                last_capture_time = now  # Reset timeout on skip
                                                self.event_bus.emit(
                                                    "ENROLLMENT_FRAME_DISCARDED",
                                                    {
                                                        "reason": "insufficient_movement",
                                                        "current_samples": len(samples),
                                                    },
                                                )

                                        if movement_ok:
                                            if detection.confidence < self.config.min_confidence:
                                                logger.info(
                                                    "Sample rejected: unstable (confidence %.2f < %.2f).",
                                                    detection.confidence,
                                                    self.config.min_confidence,
                                                )
                                                last_capture_time = now  # Reset timeout
                                                self.event_bus.emit(
                                                    "ENROLLMENT_FRAME_DISCARDED",
                                                    {
                                                        "reason": "insufficient_confidence",
                                                        "confidence": detection.confidence,
                                                        "current_samples": len(samples),
                                                    },
                                                )
                                            else:
                                                eligible_for_capture = True
                        else:
                            # stable_face_count == 1 but len(detections) == 0 (temporary drop)
                            logger.debug("Stable face count is 1, but current frame has 0 raw detections (flicker). Skipping.")
                            last_capture_time = now

                    # Accept capture if eligible
                    if eligible_for_capture:
                        detection = detections[0]
                        xmin, ymin, width, height = detection.bounding_box
                        
                        # Extract BGR face crop using unified crop_face helper
                        from visionauth.recognition.recognition_embeddings import crop_face
                        face_crop = crop_face(frame, detection.bounding_box, padding=0.15)
                        
                        if face_crop.size > 0:
                            emb = self.embedder.generate_embedding(face_crop)
                            if len(emb) == 0:
                                emb = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
                            embeddings.append(emb.tolist())
                        else:
                            embeddings.append(np.zeros(EMBEDDING_DIMENSION, dtype=np.float32).tolist())
                            
                        samples.append(frame.copy())
                        
                        # Update pose variables
                        pose_counts[pose] += 1
                        last_accepted_pose = pose
                        last_head_pose = head_pose
                        sample_poses.append(
                            {
                                "label": pose,
                                "yaw": head_pose.yaw if head_pose is not None else None,
                                "pitch": head_pose.pitch if head_pose is not None else None,
                            }
                        )

                        logger.info("Sample accepted: frontal/stable/sharp (Sample %d of %d, Pose: %s)", len(samples), self.config.num_samples, pose)
                        self.event_bus.emit(
                            "ENROLLMENT_FRAME_ACCEPTED",
                            {
                                "sample_index": len(samples),
                                "total_needed": self.config.num_samples,
                                "pose": pose,
                            },
                        )
                        # Reset timer on successful capture and save face center
                        last_capture_time = time.time()
                        last_bbox_center = (xmin + width / 2, ymin + height / 2)
                        last_bounding_box = detection.bounding_box
                else:
                    frames_skipped += 1

                # --- 2. ALWAYS RENDER (Every Frame at 30 FPS) ---
                # Call optional frame callback with new or cached detections
                if on_frame is not None:
                    on_frame(frame, detections)

                # Show visual debug window directly inside enrollment if visualize=True
                if visualize:
                    import cv2
                    h, w, _ = frame.shape

                    # Draw performance overlay metrics (visual FPS, inference FPS, inference processing ms, skips)
                    elapsed_total = time.time() - start_run_time
                    fps_visual = frames_captured / max(0.001, elapsed_total)
                    fps_inference = frames_processed / max(0.001, elapsed_total)
                    avg_inf_ms = (sum_inference_time / max(1, frames_processed)) * 1000.0
                    metrics_text = f"Visual FPS: {fps_visual:.1f} | Inf FPS: {fps_inference:.1f} | Avg Inf: {avg_inf_ms:.1f}ms | Skipped: {frames_skipped}"
                    cv2.putText(
                        frame,
                        metrics_text,
                        (15, h - 25),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        (255, 255, 255),
                        1,
                        cv2.LINE_AA,
                    )

                    # Draw rectangles using cached or new detections
                    for d in detections:
                        xmin, ymin, width, height = d.bounding_box
                        xmin_px = int(xmin * w)
                        ymin_px = int(ymin * h)
                        width_px = int(width * w)
                        height_px = int(height * h)
                        cv2.rectangle(
                            frame,
                            (xmin_px, ymin_px),
                            (xmin_px + width_px, ymin_px + height_px),
                            (0, 255, 0) if stable_face_count == 1 else (0, 0, 255),
                            2,
                        )

                    # Top status overlay
                    progress_text = f"Samples: {len(samples)}/{self.config.num_samples} | Stable Count: {stable_face_count}"
                    cv2.putText(
                        frame,
                        progress_text,
                        (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0) if stable_face_count == 1 else (0, 0, 255),
                        2,
                        cv2.LINE_AA,
                    )
                    try:
                        cv2.imshow("VisionAuth Debug", frame)
                        cv2.waitKey(1)
                    except cv2.error as e:
                        logger.error("OpenCV imshow error in enrollment: %s", e)

                if len(samples) >= self.config.num_samples:
                    break

            # If loop exited but samples are insufficient
            if len(samples) < self.config.num_samples:
                logger.error(
                    "Camera stream ended before capturing all required %d samples. Captured: %d.",
                    self.config.num_samples,
                    len(samples),
                )
                self.event_bus.emit(
                    "ENROLLMENT_FAILED", {"reason": "insufficient_samples"}
                )
                raise EnrollmentError(
                    f"Camera stream closed prematurely. Captured {len(samples)}/{self.config.num_samples}."
                )

            # Quality audit: drop samples that do not look like the same person.
            # The cutoff is absolute rather than relative to the spread, so side
            # poses, which are naturally further from the centroid, are kept.
            emb_arrays = [np.array(e, dtype=np.float32) for e in embeddings]
            centroid = np.mean(emb_arrays, axis=0)
            centroid_norm = np.linalg.norm(centroid)
            if centroid_norm > 0.0:
                centroid = centroid / centroid_norm

            sims = [float(np.dot(emb, centroid)) for emb in emb_arrays]
            logger.info("Sample similarity to centroid: %s", ", ".join(f"{sim:.2f}" for sim in sims))

            kept = [idx for idx, sim in enumerate(sims) if sim >= self.config.min_sample_similarity]
            for idx, sim in enumerate(sims):
                if idx not in kept:
                    logger.info(
                        "Discarding embedding %d (similarity %.2f below %.2f)",
                        idx + 1,
                        sim,
                        self.config.min_sample_similarity,
                    )
            if not kept:
                self.event_bus.emit("ENROLLMENT_FAILED", {"reason": "inconsistent_samples"})
                raise EnrollmentError("Enrollment failed: captured samples are not consistent with each other.")

            filtered_embeddings = [embeddings[idx] for idx in kept]
            filtered_poses = [sample_poses[idx] for idx in kept] if len(sample_poses) == len(embeddings) else None

            # Self-Similarity Validation (Requisito 6): re-embedding the last frame
            # must match one of the kept samples, which guards against an unstable embedder
            last_frame = samples[-1]
            if last_bounding_box is not None:
                from visionauth.recognition.recognition_embeddings import crop_face
                last_face_crop = crop_face(last_frame, last_bounding_box, padding=0.15)
                if last_face_crop.size > 0:
                    last_emb = self.embedder.generate_embedding(last_face_crop)
                else:
                    last_emb = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
            else:
                last_emb = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)

            self_sim = max(float(np.dot(last_emb, np.array(e, dtype=np.float32))) for e in filtered_embeddings)
            logger.info("Enrollment self similarity: %.2f", self_sim)

            if self_sim < 0.85:
                logger.error("Enrollment failed: self similarity %.2f below threshold 0.85.", self_sim)
                self.event_bus.emit("ENROLLMENT_FAILED", {"reason": "low_self_similarity"})
                raise EnrollmentError(f"Enrollment failed due to low self-similarity ({self_sim:.2f} < 0.85).")

            # Persist data
            try:
                metadata = self.persistence.save_user(
                    username,
                    samples,
                    embeddings=filtered_embeddings,
                    poses=filtered_poses,
                    append=append,
                )
            except IOError as e:
                logger.error("Persistence write error during enrollment: %s", e)
                self.event_bus.emit("ENROLLMENT_FAILED", {"reason": "persistence_error"})
                raise EnrollmentError("Failed to save enrollment data to disk.") from e

            logger.info("User '%s' registered successfully.", username)
            self.event_bus.emit(
                "ENROLLMENT_COMPLETED",
                {
                    "username": username,
                    "sample_count": len(samples),
                },
            )
            return metadata

        finally:
            if camera_started_by_us:
                self.camera.stop()
            if visualize:
                import cv2
                try:
                    cv2.destroyWindow("VisionAuth Debug")
                except cv2.error:
                    pass
