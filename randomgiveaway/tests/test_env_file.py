"""Тесты точечного обновления .env-файла (env_file.py)."""
from __future__ import annotations

from randomgiveaway.env_file import set_env_var


def test_updates_existing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=old\nBAR=keep\n", encoding="utf-8")

    set_env_var(env_path, "FOO", "new")

    assert env_path.read_text(encoding="utf-8") == "FOO=new\nBAR=keep\n"


def test_appends_missing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=old\n", encoding="utf-8")

    set_env_var(env_path, "NEW_KEY", "value")

    assert env_path.read_text(encoding="utf-8") == "FOO=old\nNEW_KEY=value\n"


def test_creates_file_if_missing(tmp_path):
    env_path = tmp_path / ".env"

    set_env_var(env_path, "FOO", "bar")

    assert env_path.read_text(encoding="utf-8") == "FOO=bar\n"


def test_appends_when_last_line_has_no_trailing_newline(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=old", encoding="utf-8")

    set_env_var(env_path, "NEW_KEY", "value")

    assert env_path.read_text(encoding="utf-8") == "FOO=old\nNEW_KEY=value\n"
