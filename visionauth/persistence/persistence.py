"""Persistence layer for VisionAuth.

Handles writing and reading user metadata and captured face sample images to disk.
"""

import datetime
import json
import logging
import os
import cv2
import numpy as np

from visionauth.paths import resolve_data_dir
from visionauth.recognition.recognition_embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_VERSION,
)

logger = logging.getLogger(__name__)


class UserPersistence:
    """Manages filesystem operations for user profiles and face samples.

    Creates and manages directories under `<data_dir>/users/<username>/`.
    Saves JPG samples and writes metadata JSON files.
    """

    def __init__(self, data_dir: str = "data") -> None:
        """Initializes the UserPersistence manager.

        Args:
            data_dir: Base directory for all data storage. A relative path is
                resolved against the project root. Defaults to "data".
        """
        self.data_dir = resolve_data_dir(data_dir)
        self.users_dir = os.path.join(self.data_dir, "users")

    def user_exists(self, username: str) -> bool:
        """Checks if a user is already enrolled.

        Args:
            username: The username to check.

        Returns:
            True if the user's directory exists, False otherwise.
        """
        user_path = os.path.join(self.users_dir, username)
        return os.path.isdir(user_path)

    def save_user(
        self,
        username: str,
        samples: list[np.ndarray],
        embeddings: list[list[float]] | None = None,
        poses: list[dict] | None = None,
        append: bool = False,
    ) -> dict[str, str | int]:
        """Saves enrollment samples and writes user metadata.json to disk.

        Args:
            username: The unique name of the user.
            samples: List of BGR image frames captured during enrollment.
            embeddings: List of extracted face embedding vectors.
            poses: Optional head pose of each embedding ({"label", "yaw", "pitch"}).
            append: If True, adds samples and embeddings to the user's existing
                profile instead of replacing it.

        Returns:
            A dictionary containing the generated user metadata.

        Raises:
            IOError: If directory creation or file writing fails.
        """
        user_path = os.path.join(self.users_dir, username)
        samples_dir = os.path.join(user_path, "samples")

        logger.info("Saving persistence data for user '%s' in: %s", username, user_path)

        try:
            os.makedirs(samples_dir, exist_ok=True)
        except OSError as e:
            logger.error("Failed to create directory %s: %s", samples_dir, e)
            raise IOError(f"Could not create user directory: {samples_dir}") from e

        existing_profile = (self.load_user_profile(username) or {}) if append else {}
        existing_metadata = (self._load_json(os.path.join(user_path, "metadata.json")) or {}) if append else {}
        existing_sample_count = (
            len([f for f in os.listdir(samples_dir) if f.startswith("sample_")]) if append else 0
        )

        # Save all face sample images as JPEGs, numbered after any existing ones
        for idx, sample in enumerate(samples, start=existing_sample_count + 1):
            sample_name = f"sample_{idx:03d}.jpg"
            sample_path = os.path.join(samples_dir, sample_name)
            success = cv2.imwrite(sample_path, sample)
            if not success:
                logger.error("Failed to write image sample to %s", sample_path)
                raise IOError(f"Failed to write image sample: {sample_path}")
            logger.debug("Saved sample image: %s", sample_path)

        # Save embeddings in profile.json
        if embeddings:
            previous_embeddings = existing_profile.get("embeddings", [])
            previous_poses = existing_profile.get("poses") or [None] * len(previous_embeddings)
            all_embeddings = previous_embeddings + embeddings
            all_poses = previous_poses + (poses or [None] * len(embeddings))

            profile_data = {
                "user": username,
                "embeddings": all_embeddings,
                "embedding_model": EMBEDDING_MODEL,
                "embedding_dimension": EMBEDDING_DIMENSION,
                "embedding_version": EMBEDDING_VERSION,
            }
            if any(pose is not None for pose in all_poses):
                profile_data["poses"] = all_poses
            try:
                emb_array = np.array(all_embeddings, dtype=np.float32)
                centroid = np.mean(emb_array, axis=0)
                centroid_norm = np.linalg.norm(centroid)
                if centroid_norm > 0.0:
                    centroid = centroid / centroid_norm
                profile_data["centroid"] = centroid.tolist()
            except Exception as e:
                logger.error("Failed to calculate centroid embedding for %s: %s", username, e)

            profile_path = os.path.join(user_path, "profile.json")
            try:
                with open(profile_path, "w", encoding="utf-8") as f:
                    json.dump(profile_data, f, indent=4)
                logger.info("Saved profile.json successfully for user '%s'", username)
            except OSError as e:
                logger.error("Failed to write profile.json to %s: %s", profile_path, e)
                raise IOError(f"Failed to write profile JSON: {profile_path}") from e

        # Generate metadata dict
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        metadata: dict[str, str | int] = {
            "name": username,
            "created_at": existing_metadata.get("created_at", now),
            "sample_count": existing_sample_count + len(samples),
            "model_version": "v0.0.0",
            "format_version": "1.0",
        }
        if append:
            metadata["updated_at"] = now

        metadata_path = os.path.join(user_path, "metadata.json")
        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4)
            logger.info("Saved metadata.json successfully for user '%s'", username)
        except OSError as e:
            logger.error("Failed to write metadata JSON to %s: %s", metadata_path, e)
            raise IOError(f"Failed to write metadata JSON: {metadata_path}") from e

        return metadata

    @staticmethod
    def _load_json(path: str) -> dict | None:
        """Reads a JSON file, returning None if it is missing or unreadable."""
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Failed to read %s: %s", path, e)
            return None

    def load_user_profile(self, username: str) -> dict | None:
        """Loads a user's profile.json containing their enrolled embeddings and centroid.

        Args:
            username: The unique name of the user.

        Returns:
            A dictionary of the profile if exists, None otherwise.
        """
        user_path = os.path.join(self.users_dir, username)
        profile_path = os.path.join(user_path, "profile.json")
        if not os.path.isfile(profile_path):
            return None
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except OSError as e:
            logger.error("Failed to read profile.json for %s: %s", username, e)
            return None
