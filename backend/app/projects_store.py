"""Единый доступ к проектам: конфиговые (config.yaml) + созданные через UI.

Создание нового проекта — только внутри workspace, с валидацией имени и границ.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import get_app_config, get_project_map
from .database import repo
from .security import SecurityError, resolve_within_root

# Имя проекта: слаг из латиницы/цифр/-/_ (без точек, слэшей, пробелов).
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ProjectError(Exception):
    """Ошибка операции с проектом (валидация, конфликт имён и т.п.)."""


def all_projects() -> list[dict]:
    """Список всех проектов: конфиговые + пользовательские."""
    result: list[dict] = []
    seen: set[str] = set()
    for proj in get_app_config().projects:
        result.append({"name": proj.name, "path": proj.path,
                       "available": Path(proj.path).is_dir(), "kind": "config"})
        seen.add(proj.name)
    for proj in repo.list_custom_projects():
        if proj["name"] in seen:
            continue
        result.append({"name": proj["name"], "path": proj["path"],
                       "available": Path(proj["path"]).is_dir(), "kind": "custom"})
    return result


def project_root(name: str) -> Path | None:
    """Абсолютный root проекта по имени (конфиг имеет приоритет), либо None."""
    cfg_map = get_project_map()
    if name in cfg_map:
        return cfg_map[name]
    custom = repo.get_custom_project_path(name)
    return Path(custom).resolve() if custom else None


def workspace_root() -> Path | None:
    ws = get_app_config().workspace
    return Path(ws).resolve() if ws else None


def create_project(name: str, git_init: bool = True) -> dict:
    """Создать новый проект внутри workspace. Возвращает описание проекта."""
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise ProjectError(
            "Имя: латиница/цифры/дефис/подчёркивание, 1–64 символа, без пробелов и точек."
        )

    ws = workspace_root()
    if ws is None:
        raise ProjectError("Workspace не настроен (поле 'workspace' в config.yaml).")
    if not ws.is_dir():
        raise ProjectError(f"Папка workspace не существует: {ws}")

    # Конфликт имён с существующими проектами.
    existing = {p["name"] for p in all_projects()}
    if name in existing:
        raise ProjectError(f"Проект '{name}' уже существует.")

    # Путь строго внутри workspace.
    try:
        target = resolve_within_root(ws, name)
    except SecurityError as exc:
        raise ProjectError(str(exc)) from exc
    if target.exists():
        raise ProjectError(f"Папка уже существует: {target}")

    target.mkdir(parents=True, exist_ok=False)
    if git_init:
        try:
            subprocess.run(["git", "init"], cwd=str(target),
                           capture_output=True, timeout=30)
            (target / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        except (OSError, subprocess.TimeoutExpired):
            pass  # git может отсутствовать — не критично

    repo.add_project(name, str(target))
    return {"name": name, "path": str(target), "available": True, "kind": "custom"}
