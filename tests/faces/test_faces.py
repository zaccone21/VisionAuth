"""Tests for face names and the operations on enrolled faces."""

import json
import os

import pytest

from visionauth.faces import (
    FaceExists,
    FaceInfo,
    FaceNotFound,
    InvalidFaceName,
    list_faces,
    remove_face,
    rename_face,
    validate_face_name,
)


def make_face(data_dir, name: str) -> None:
    folder = data_dir / "users" / name
    folder.mkdir(parents=True)
    (folder / "profile.json").write_text(
        json.dumps({"user": name, "embeddings": [[1.0, 0.0]]}, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "metadata.json").write_text(
        json.dumps({"user": name, "sample_count": 8, "created_at": "2026-11-14T10:00:00"}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_validate_accepts_accents_and_spaces() -> None:
    assert validate_face_name("  José María ") == "José María"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "a/b", "a\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a|b", ".", "..", "nombre.", "x" * 41, "a\tb"],
)
def test_validate_rejects(name: str) -> None:
    with pytest.raises(InvalidFaceName):
        validate_face_name(name)


def test_list_faces_reports_samples_and_skips_folders_without_profile(tmp_path) -> None:
    make_face(tmp_path, "Martín")
    make_face(tmp_path, "Ana")
    (tmp_path / "users" / "vacía").mkdir()

    assert list_faces(str(tmp_path)) == [
        FaceInfo("Ana", 8, "2026-11-14T10:00:00"),
        FaceInfo("Martín", 8, "2026-11-14T10:00:00"),
    ]


def test_list_faces_without_users_folder_is_empty(tmp_path) -> None:
    assert list_faces(str(tmp_path)) == []


def test_rename_updates_folder_and_profile_user(tmp_path) -> None:
    make_face(tmp_path, "Gomez")
    rename_face(str(tmp_path), "Gomez", "Martín")

    profile = json.loads((tmp_path / "users" / "Martín" / "profile.json").read_text(encoding="utf-8"))
    metadata = json.loads((tmp_path / "users" / "Martín" / "metadata.json").read_text(encoding="utf-8"))
    assert profile["user"] == "Martín"
    assert metadata["user"] == "Martín"
    assert not (tmp_path / "users" / "Gomez").exists()


def test_rename_case_only_is_allowed(tmp_path) -> None:
    make_face(tmp_path, "martín")
    rename_face(str(tmp_path), "martín", "Martín")
    assert [face.name for face in list_faces(str(tmp_path))] == ["Martín"]


def test_rename_to_existing_face_fails(tmp_path) -> None:
    make_face(tmp_path, "Ana")
    make_face(tmp_path, "Martín")
    with pytest.raises(FaceExists):
        rename_face(str(tmp_path), "Ana", "Martín")


def test_rename_or_remove_missing_face_fails(tmp_path) -> None:
    with pytest.raises(FaceNotFound):
        rename_face(str(tmp_path), "Nadie", "Alguien")
    with pytest.raises(FaceNotFound):
        remove_face(str(tmp_path), "Nadie")


def test_remove_deletes_the_folder(tmp_path) -> None:
    make_face(tmp_path, "Ana")
    remove_face(str(tmp_path), "Ana")
    assert not os.path.exists(tmp_path / "users" / "Ana")
