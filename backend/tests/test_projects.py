"""Тесты создания проектов в workspace (валидация имени и границ)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import projects_store
from app.config import AppConfig


@pytest.fixture
def ws(tmp_path: Path, monkeypatch):
    """Настроить workspace = tmp_path и пустой список конфиговых проектов."""
    cfg = AppConfig(workspace=str(tmp_path))
    monkeypatch.setattr(projects_store, "get_app_config", lambda: cfg)
    monkeypatch.setattr(projects_store, "get_project_map", lambda: {})
    return tmp_path


def test_create_project_success(ws: Path):
    proj = projects_store.create_project("my-shop")
    assert proj["name"] == "my-shop"
    assert (ws / "my-shop").is_dir()
    assert projects_store.project_root("my-shop") == (ws / "my-shop").resolve()
    names = {p["name"] for p in projects_store.all_projects()}
    assert "my-shop" in names


def test_reject_bad_names(ws: Path):
    for bad in ["../etc", "a/b", "Проект", "with space", ".hidden", ""]:
        with pytest.raises(projects_store.ProjectError):
            projects_store.create_project(bad)


def test_reject_duplicate(ws: Path):
    projects_store.create_project("dup")
    with pytest.raises(projects_store.ProjectError):
        projects_store.create_project("dup")


def test_no_workspace_configured(tmp_path: Path, monkeypatch):
    cfg = AppConfig(workspace=None)
    monkeypatch.setattr(projects_store, "get_app_config", lambda: cfg)
    monkeypatch.setattr(projects_store, "get_project_map", lambda: {})
    with pytest.raises(projects_store.ProjectError):
        projects_store.create_project("x")
