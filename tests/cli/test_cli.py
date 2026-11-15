"""Tests for the visionauth command line (faces and settings)."""

import json

from tests.faces.test_faces import make_face
from visionauth.cli import main


def run(tmp_path, *args: str) -> int:
    return main(["--config", str(tmp_path / "config.json"), "--data-dir", str(tmp_path), *args])


def test_faces_list_prints_tab_separated_rows(tmp_path, capsys) -> None:
    make_face(tmp_path, "Joaquín")
    make_face(tmp_path, "Ana")
    assert run(tmp_path, "faces", "list") == 0
    assert capsys.readouterr().out.splitlines() == [
        "Ana\t8\t2026-11-14T10:00:00",
        "Joaquín\t8\t2026-11-14T10:00:00",
    ]


def test_faces_rename_and_remove(tmp_path, capsys) -> None:
    make_face(tmp_path, "Zaccone")
    assert run(tmp_path, "faces", "rename", "Zaccone", "Joaquín") == 0
    assert (tmp_path / "users" / "Joaquín").is_dir()
    assert run(tmp_path, "faces", "remove", "Joaquín") == 0
    assert not (tmp_path / "users" / "Joaquín").exists()
    assert "Listo." in capsys.readouterr().out


def test_invalid_name_exits_1_with_spanish_message(tmp_path, capsys) -> None:
    make_face(tmp_path, "Ana")
    assert run(tmp_path, "faces", "rename", "Ana", "a/b") == 1
    assert "nombre" in capsys.readouterr().err


def test_config_set_and_show(tmp_path, capsys) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"account": "joaqu", "camera": 0}), encoding="utf-8-sig")
    assert run(tmp_path, "config", "set", "sensitivity", "estricta") == 0
    assert run(tmp_path, "config", "show") == 0
    lines = capsys.readouterr().out.splitlines()
    assert "account\tjoaqu" in lines
    assert "camera\t0" in lines
    assert "sensitivity\testricta" in lines


def test_config_set_invalid_leaves_file_unchanged(tmp_path, capsys) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"account": "joaqu", "camera": 0}), encoding="utf-8-sig")
    before = path.read_bytes()
    assert run(tmp_path, "config", "set", "camera", "abc") == 1
    assert path.read_bytes() == before
    assert "cámara" in capsys.readouterr().err


def test_config_show_reads_the_account_of_an_old_config(tmp_path, capsys) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"profiles": {"joaqu": "Zaccone"}}), encoding="utf-8")
    assert run(tmp_path, "config", "show") == 0
    assert "account\tjoaqu" in capsys.readouterr().out.splitlines()
