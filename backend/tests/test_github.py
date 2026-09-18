"""Тесты GitHub-инструмента: разбор remote и классификация действий."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agent import permissions
from app.config import AppConfig
from app.tools import github


def _git_repo(tmp: Path, remote_url: str) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=tmp, check=True)
    return tmp


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/svistoff/Claude.git", ("svistoff", "Claude")),
    ("https://github.com/svistoff/Claude", ("svistoff", "Claude")),
    ("git@github.com:svistoff/f_chatsbot.git", ("svistoff", "f_chatsbot")),
    ("git@github.com:owner/repo", ("owner", "repo")),
])
def test_parse_remote(tmp_path: Path, url, expected):
    root = _git_repo(tmp_path, url)
    assert github.parse_remote(root) == expected


def test_parse_remote_non_github(tmp_path: Path):
    root = _git_repo(tmp_path, "https://gitlab.com/owner/repo.git")
    assert github.parse_remote(root) is None


def test_repo_info_no_remote(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    info = github.repo_info(tmp_path)
    assert info["github"] is False


def test_permissions_create_pr_confirm():
    cfg = AppConfig()
    d = permissions.classify("github", {"action": "create_pr", "title": "fix"}, cfg)
    assert d.action == permissions.CONFIRM


def test_permissions_github_read_allow():
    cfg = AppConfig()
    for act in ("info", "branches", "ci_status"):
        d = permissions.classify("github", {"action": act}, cfg)
        assert d.action == permissions.ALLOW
