"""Unit tests for user persistence."""

import json
import os

import numpy as np

from visionauth.persistence.persistence import UserPersistence


def make_samples(count: int) -> list[np.ndarray]:
    return [np.full((20, 20, 3), i * 10, dtype=np.uint8) for i in range(count)]


def unit(index: int) -> list[float]:
    vec = [0.0] * 4
    vec[index] = 1.0
    return vec


def read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_save_user_stores_poses(tmp_path) -> None:
    persistence = UserPersistence(data_dir=str(tmp_path))
    poses = [{"label": "CENTER", "yaw": 0.0, "pitch": 0.0}, {"label": "LEFT", "yaw": 0.3, "pitch": 0.0}]

    persistence.save_user("ana", make_samples(2), embeddings=[unit(0), unit(1)], poses=poses)

    profile = persistence.load_user_profile("ana")
    assert profile["poses"] == poses
    assert len(profile["embeddings"]) == 2


def test_save_user_without_poses_omits_them(tmp_path) -> None:
    persistence = UserPersistence(data_dir=str(tmp_path))
    persistence.save_user("ana", make_samples(1), embeddings=[unit(0)])
    assert "poses" not in persistence.load_user_profile("ana")


def test_append_adds_samples_and_embeddings(tmp_path) -> None:
    persistence = UserPersistence(data_dir=str(tmp_path))
    first = persistence.save_user(
        "ana", make_samples(2), embeddings=[unit(0), unit(0)], poses=[{"label": "CENTER"}] * 2
    )

    second = persistence.save_user(
        "ana", make_samples(3), embeddings=[unit(1)] * 3, poses=[{"label": "LEFT"}] * 3, append=True
    )

    samples_dir = os.path.join(str(tmp_path), "users", "ana", "samples")
    assert sorted(os.listdir(samples_dir)) == [f"sample_{i:03d}.jpg" for i in range(1, 6)]

    profile = persistence.load_user_profile("ana")
    assert profile["embeddings"] == [unit(0)] * 2 + [unit(1)] * 3
    assert [p["label"] for p in profile["poses"]] == ["CENTER"] * 2 + ["LEFT"] * 3
    # Centroid covers both sessions
    assert profile["centroid"][0] > 0.0 and profile["centroid"][1] > 0.0

    assert second["sample_count"] == 5
    assert second["created_at"] == first["created_at"]
    assert "updated_at" in second
    assert read_json(os.path.join(str(tmp_path), "users", "ana", "metadata.json")) == second


def test_append_to_profile_without_poses_pads_them(tmp_path) -> None:
    persistence = UserPersistence(data_dir=str(tmp_path))
    persistence.save_user("ana", make_samples(1), embeddings=[unit(0)])

    persistence.save_user("ana", make_samples(1), embeddings=[unit(1)], poses=[{"label": "LEFT"}], append=True)

    assert persistence.load_user_profile("ana")["poses"] == [None, {"label": "LEFT"}]


def test_save_without_append_replaces_profile(tmp_path) -> None:
    persistence = UserPersistence(data_dir=str(tmp_path))
    persistence.save_user("ana", make_samples(2), embeddings=[unit(0), unit(0)])

    metadata = persistence.save_user("ana", make_samples(1), embeddings=[unit(1)])

    assert persistence.load_user_profile("ana")["embeddings"] == [unit(1)]
    assert metadata["sample_count"] == 1
