"""Тесты классификации опасных действий."""

from __future__ import annotations

from app.agent import permissions
from app.config import AppConfig, TerminalPolicy


def _cfg() -> AppConfig:
    return AppConfig(terminal_policy=TerminalPolicy(
        blocked=["mkfs", "dd if=", ":(){:|:&};:"],
        confirm=["rm -rf", "git push", "systemctl stop", "reboot"],
    ))


def test_safe_command_allowed():
    d = permissions.classify("terminal", {"command": "pytest -q"}, _cfg())
    assert d.action == permissions.ALLOW


def test_rm_rf_needs_confirm():
    d = permissions.classify("terminal", {"command": "rm -rf build/"}, _cfg())
    assert d.action == permissions.CONFIRM
    assert "rm -rf build/" == d.preview


def test_mkfs_blocked():
    d = permissions.classify("terminal", {"command": "mkfs.ext4 /dev/sda"}, _cfg())
    assert d.action == permissions.BLOCK


def test_git_push_confirm():
    d = permissions.classify("git", {"args": ["push", "origin", "feature"]}, _cfg())
    assert d.action == permissions.CONFIRM


def test_git_push_to_main_confirm_with_reason():
    d = permissions.classify("git", {"args": ["push", "origin", "main"]}, _cfg())
    assert d.action == permissions.CONFIRM
    assert "main" in d.reason


def test_git_status_allowed():
    d = permissions.classify("git", {"args": ["status"]}, _cfg())
    assert d.action == permissions.ALLOW


def test_git_reset_hard_confirm():
    d = permissions.classify("git", {"args": ["reset", "--hard", "HEAD~1"]}, _cfg())
    assert d.action == permissions.CONFIRM


def test_read_file_allowed():
    d = permissions.classify("read_file", {"path": "main.py"}, _cfg())
    assert d.action == permissions.ALLOW
