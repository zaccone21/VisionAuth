"""Enrolled faces: their names and the operations to list, rename and remove them.

A face is a profile folder under <data_dir>/users/<name>/. Its name is what the
sign-in screen shows in the greeting ("Hola, <name>"), so it may have accents
and spaces; it only has to be a valid folder name.
"""

import json
import os
import shutil
from dataclasses import dataclass

from visionauth.paths import resolve_data_dir

MAX_NAME_LENGTH = 40
FORBIDDEN_CHARACTERS = set('\\/:*?"<>|')


class InvalidFaceName(ValueError):
    """The name cannot be used for a face."""


class FaceNotFound(LookupError):
    """No face is enrolled with that name."""


class FaceExists(FileExistsError):
    """A face with that name is already enrolled."""


@dataclass(frozen=True)
class FaceInfo:
    name: str
    samples: int
    created: str | None


def validate_face_name(name: str) -> str:
    """Checks a face name and returns it without surrounding spaces.

    Raises:
        InvalidFaceName: With a message in Spanish saying what is wrong.
    """
    stripped = (name or "").strip()
    if not stripped:
        raise InvalidFaceName("El nombre no puede estar vacío.")
    if len(stripped) > MAX_NAME_LENGTH:
        raise InvalidFaceName(f"El nombre puede tener hasta {MAX_NAME_LENGTH} caracteres.")
    if any(c in FORBIDDEN_CHARACTERS or ord(c) < 32 for c in stripped):
        raise InvalidFaceName('El nombre no puede tener \\ / : * ? " < > | ni tabulaciones.')
    if stripped.endswith("."):
        raise InvalidFaceName("El nombre no puede terminar en punto.")
    return stripped


def _users_dir(data_dir: str) -> str:
    return os.path.join(resolve_data_dir(data_dir), "users")


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def list_faces(data_dir: str) -> list[FaceInfo]:
    """Lists the enrolled faces, sorted by name. Folders without a profile are skipped."""
    users = _users_dir(data_dir)
    if not os.path.isdir(users):
        return []
    faces = []
    for name in os.listdir(users):
        folder = os.path.join(users, name)
        if not os.path.isfile(os.path.join(folder, "profile.json")):
            continue
        metadata = _read_json(os.path.join(folder, "metadata.json"))
        faces.append(FaceInfo(name, int(metadata.get("sample_count", 0)), metadata.get("created_at")))
    return sorted(faces, key=lambda face: face.name.casefold())


def _existing_folder(data_dir: str, name: str) -> str:
    # A valid name has no path separators, so it cannot reach outside users\
    folder = os.path.join(_users_dir(data_dir), validate_face_name(name))
    if not os.path.isfile(os.path.join(folder, "profile.json")):
        raise FaceNotFound(f"No hay ninguna cara registrada como '{name}'.")
    return folder


def rename_face(data_dir: str, old: str, new: str) -> None:
    """Renames a face: its folder and the user recorded in its profile and metadata."""
    folder = _existing_folder(data_dir, old)
    new = validate_face_name(new)
    target = os.path.join(_users_dir(data_dir), new)
    # A change of case only is the same folder on NTFS
    if old.casefold() != new.casefold() and os.path.exists(target):
        raise FaceExists(f"Ya hay una cara registrada como '{new}'.")
    os.rename(folder, target)
    for file_name in ("profile.json", "metadata.json"):
        path = os.path.join(target, file_name)
        if not os.path.isfile(path):
            continue
        data = _read_json(path)
        data["user"] = new
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)


def remove_face(data_dir: str, name: str) -> None:
    """Deletes a face and its samples."""
    shutil.rmtree(_existing_folder(data_dir, name))
