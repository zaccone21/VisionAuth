"""The service configuration (config.json) and the settings a person can change.

The installer writes C:\\ProgramData\\VisionAuth\\config.json; the service reads
it at start. The camera and the sensitivity can be changed afterwards (from
the menu, through the command line).
"""

import json
from pathlib import Path

CONFIG_PATH = Path(r"C:\ProgramData\VisionAuth\config.json")

# Cosine similarity an SFace match has to reach. The owner typically measures
# 0.67-0.78; SFace's own suggested threshold is 0.363.
SENSITIVITY_THRESHOLDS: dict[str, float] = {"estricta": 0.55, "normal": 0.45, "permisiva": 0.38}
DEFAULT_SENSITIVITY = "normal"
MAX_CAMERA_INDEX = 9


class SettingError(ValueError):
    """A setting or its value is not valid (the message is in Spanish)."""


def load_config(path: Path) -> dict:
    """Reads the configuration, or returns {} if there is none yet."""
    if not path.is_file():
        return {}
    # utf-8-sig: PowerShell 5.1 writes a byte order mark
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def configured_account(config: dict) -> str | None:
    """The Windows account VisionAuth unlocks.

    Configurations written before several faces were supported map the
    account to a profile in "profiles"; the account is its only key.
    """
    if config.get("account"):
        return config["account"]
    profiles = config.get("profiles") or {}
    return next(iter(profiles)) if len(profiles) == 1 else None


def match_threshold(config: dict) -> float:
    return SENSITIVITY_THRESHOLDS.get(config.get("sensitivity", DEFAULT_SENSITIVITY), SENSITIVITY_THRESHOLDS["normal"])


def set_setting(config: dict, key: str, value: str) -> dict:
    """Returns a copy of the configuration with one setting changed.

    Raises:
        SettingError: If the setting cannot be changed or the value is not valid.
    """
    updated = dict(config)
    if key == "camera":
        if not value.isdigit() or int(value) > MAX_CAMERA_INDEX:
            raise SettingError(f"La cámara tiene que ser un número de 0 a {MAX_CAMERA_INDEX}.")
        updated["camera"] = int(value)
    elif key == "sensitivity":
        if value not in SENSITIVITY_THRESHOLDS:
            raise SettingError("La sensibilidad tiene que ser estricta, normal o permisiva.")
        updated["sensitivity"] = value
    else:
        raise SettingError(f"'{key}' no se puede cambiar. Se pueden cambiar: camera, sensitivity.")
    return updated
