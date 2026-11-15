"""Tests for the service configuration file and its settings."""

import json

import pytest

from visionauth.settings import (
    SettingError,
    configured_account,
    load_config,
    match_threshold,
    save_config,
    set_setting,
)


def test_load_config_reads_powershell_bom(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"account": "joaqu", "camera": 0}), encoding="utf-8-sig")
    assert load_config(path) == {"account": "joaqu", "camera": 0}


def test_load_missing_config_is_empty(tmp_path) -> None:
    assert load_config(tmp_path / "missing.json") == {}


def test_save_then_load_round_trips_accents(tmp_path) -> None:
    path = tmp_path / "config.json"
    save_config(path, {"account": "joaqu", "x": "Joaquín"})
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert load_config(path) == {"account": "joaqu", "x": "Joaquín"}


@pytest.mark.parametrize(
    "config, account",
    [({"account": "joaqu"}, "joaqu"), ({"profiles": {"joaqu": "Zaccone"}}, "joaqu"), ({}, None)],
)
def test_configured_account_new_and_old_formats(config: dict, account: str | None) -> None:
    assert configured_account(config) == account


@pytest.mark.parametrize(
    "config, threshold",
    [
        ({"sensitivity": "estricta"}, 0.55),
        ({"sensitivity": "normal"}, 0.45),
        ({"sensitivity": "permisiva"}, 0.38),
        ({}, 0.45),
    ],
)
def test_match_threshold_levels(config: dict, threshold: float) -> None:
    assert match_threshold(config) == threshold


def test_set_setting_valid() -> None:
    assert set_setting({}, "camera", "1") == {"camera": 1}
    assert set_setting({"camera": 0}, "sensitivity", "permisiva") == {"camera": 0, "sensitivity": "permisiva"}


@pytest.mark.parametrize(
    "key, value", [("camera", "abc"), ("camera", "12"), ("sensitivity", "alta"), ("account", "otro")]
)
def test_set_setting_rejects(key: str, value: str) -> None:
    config = {"camera": 0}
    with pytest.raises(SettingError):
        set_setting(config, key, value)
    assert config == {"camera": 0}
