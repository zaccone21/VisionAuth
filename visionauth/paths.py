"""Project paths that must not depend on the directory the app is launched from."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_data_dir(data_dir: str) -> str:
    """Resolves a relative data directory against the project root.

    Enrollment launched from examples/ and authentication launched from
    anywhere else must read and write the same user profiles.
    """
    path = Path(data_dir)
    return str(path if path.is_absolute() else PROJECT_ROOT / path)
