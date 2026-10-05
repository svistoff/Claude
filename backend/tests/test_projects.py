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


# --- Обзор папок и добавление существующей папки как проекта ----------------

@pytest.fixture
def browse(tmp_path: Path, monkeypatch):
    """browse_roots = tmp_path; конфиговых проектов нет."""
    cfg = AppConfig(browse_roots=[str(tmp_path)], workspace=str(tmp_path))
    monkeypatch.setattr(projects_store, "get_app_config", lambda: cfg)
    monkeypatch.setattr(projects_store, "get_project_map", lambda: {})
    return tmp_path


def test_browse_root_level_lists_roots(browse: Path):
    data = projects_store.browse_dirs(None)
    assert data["current"] is None
    assert str(browse.resolve()) in data["roots"]
    assert any(e["path"] == str(browse.resolve()) for e in data["entries"])


def test_browse_lists_subdirs_and_skips_noise(browse: Path):
    (browse / "shop").mkdir()
    (browse / ".git").mkdir()
    (browse / "node_modules").mkdir()
    data = projects_store.browse_dirs(str(browse))
    names = {e["name"] for e in data["entries"]}
    assert "shop" in names
    assert ".git" not in names and "node_modules" not in names
    assert data["parent"] is None  # корень — выше не поднимаемся


def test_browse_outside_roots_rejected(browse: Path):
    with pytest.raises(projects_store.ProjectError):
        projects_store.browse_dirs(str(browse.parent))


def test_add_existing_project(browse: Path):
    (browse / "My Legacy App").mkdir()
    proj = projects_store.add_existing_project(str(browse / "My Legacy App"))
    assert proj["kind"] == "custom"
    assert proj["name"] == "my-legacy-app"  # слаг из имени папки
    assert projects_store.project_root("my-legacy-app") == (browse / "My Legacy App").resolve()
    # Теперь в обзоре эта папка помечена как проект.
    data = projects_store.browse_dirs(str(browse))
    assert any(e["is_project"] for e in data["entries"] if e["name"] == "My Legacy App")


def test_add_existing_custom_name(browse: Path):
    (browse / "svc").mkdir()
    proj = projects_store.add_existing_project(str(browse / "svc"), name="Backend API")
    assert proj["name"] == "backend-api"


def test_add_existing_rejects_outside(browse: Path):
    with pytest.raises(projects_store.ProjectError):
        projects_store.add_existing_project(str(browse.parent))


def test_add_existing_rejects_missing(browse: Path):
    with pytest.raises(projects_store.ProjectError):
        projects_store.add_existing_project(str(browse / "nope"))


def test_add_existing_duplicate_path(browse: Path):
    (browse / "once").mkdir()
    projects_store.add_existing_project(str(browse / "once"))
    with pytest.raises(projects_store.ProjectError):
        projects_store.add_existing_project(str(browse / "once"))


def test_remove_custom_project(browse: Path):
    (browse / "temp").mkdir()
    projects_store.add_existing_project(str(browse / "temp"), name="temp-proj")
    projects_store.remove_project("temp-proj")
    assert projects_store.project_root("temp-proj") is None


def test_remove_config_project_forbidden(tmp_path: Path, monkeypatch):
    cfg = AppConfig(browse_roots=[str(tmp_path)])
    monkeypatch.setattr(projects_store, "get_app_config", lambda: cfg)
    monkeypatch.setattr(projects_store, "get_project_map", lambda: {"fixed": tmp_path})
    with pytest.raises(projects_store.ProjectError):
        projects_store.remove_project("fixed")
