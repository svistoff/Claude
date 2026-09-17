"""Тесты файловых инструментов и терминала."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppConfig
from app.security import SecurityError
from app.tools import filesystem, terminal
from app.tools.base import ToolContext
from app.tools.registry import dispatch


def _ctx(root: Path) -> ToolContext:
    cfg = AppConfig()
    cfg.secret_patterns = [".env", "*.key", "id_rsa"]
    return ToolContext(project_name="test", project_root=root, config=cfg)


def test_write_read_roundtrip(tmp_path: Path):
    ctx = _ctx(tmp_path)
    w = filesystem.write_file(ctx, "hello.py", "print('hi')\n")
    assert w.ok
    r = filesystem.read_file(ctx, "hello.py")
    assert r.ok and "print('hi')" in r.content


def test_read_secret_blocked(tmp_path: Path):
    (tmp_path / ".env").write_text("SECRET=1")
    ctx = _ctx(tmp_path)
    # Прямой вызов срабатывает как guard (исключение)...
    with pytest.raises(SecurityError):
        filesystem.read_file(ctx, ".env")
    # ...а через dispatch модель получает безопасный ok=False, без утечки содержимого.
    res = dispatch(ctx, "read_file", {"path": ".env"})
    assert not res.ok
    assert "SECRET=1" not in res.content


def test_list_hides_secrets(tmp_path: Path):
    (tmp_path / "app.py").write_text("x")
    (tmp_path / ".env").write_text("S=1")
    (tmp_path / "server.key").write_text("k")
    ctx = _ctx(tmp_path)
    r = filesystem.list_files(ctx, ".")
    assert "app.py" in r.content
    assert ".env" not in r.content
    assert "server.key" not in r.content


def test_edit_unique_match(tmp_path: Path):
    (tmp_path / "f.txt").write_text("alpha\nbeta\ngamma\n")
    ctx = _ctx(tmp_path)
    r = filesystem.edit_file(ctx, "f.txt", "beta", "BETA")
    assert r.ok
    assert (tmp_path / "f.txt").read_text() == "alpha\nBETA\ngamma\n"


def test_edit_ambiguous_fails(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x\nx\n")
    ctx = _ctx(tmp_path)
    r = filesystem.edit_file(ctx, "f.txt", "x", "y")
    assert not r.ok


def test_search_finds(tmp_path: Path):
    (tmp_path / "a.py").write_text("def megafon_webhook():\n    pass\n")
    ctx = _ctx(tmp_path)
    r = filesystem.search_files(ctx, "megafon")
    assert r.ok and "megafon" in r.content.lower()


def test_terminal_exit_code(tmp_path: Path):
    ctx = _ctx(tmp_path)
    r = terminal.terminal(ctx, "echo hello && exit 3")
    assert not r.ok
    assert r.extra["exit_code"] == 3
    assert "hello" in r.extra["output"]


def test_terminal_timeout(tmp_path: Path):
    ctx = _ctx(tmp_path)
    r = terminal.terminal(ctx, "sleep 5", timeout=1)
    assert not r.ok
    assert r.extra["timed_out"] is True
