"""Тесты песочницы путей и фильтра секретов — критично для безопасности."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.security import (
    SecurityError,
    ensure_not_secret,
    is_secret_path,
    resolve_within_root,
)

PATTERNS = [".env", ".env.*", "*.pem", "*.key", "id_rsa", "credentials*", ".git/config"]


def test_resolve_inside_root(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    p = resolve_within_root(tmp_path, "sub/file.txt")
    assert str(p).startswith(str(tmp_path.resolve()))


def test_resolve_blocks_parent_escape(tmp_path: Path):
    with pytest.raises(SecurityError):
        resolve_within_root(tmp_path, "../../etc/passwd")


def test_resolve_blocks_absolute_outside(tmp_path: Path):
    with pytest.raises(SecurityError):
        resolve_within_root(tmp_path, "/etc/passwd")


def test_resolve_blocks_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside_secret"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks недоступны")
    with pytest.raises(SecurityError):
        resolve_within_root(tmp_path, "link/secret.txt")


@pytest.mark.parametrize("path", [
    ".env", ".env.production", "config/id_rsa", "certs/server.pem",
    "app.key", "credentials.json", ".git/config",
])
def test_secret_detected(path):
    assert is_secret_path(path, PATTERNS)


@pytest.mark.parametrize("path", ["main.py", "src/app.js", "README.md", "envelope.txt"])
def test_non_secret_allowed(path):
    assert not is_secret_path(path, PATTERNS)


def test_ensure_not_secret_raises():
    with pytest.raises(SecurityError):
        ensure_not_secret(".env", PATTERNS)
