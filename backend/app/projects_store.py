"""Единый доступ к проектам: конфиговые (config.yaml) + созданные через UI.

Создание нового проекта — только внутри workspace, с валидацией имени и границ.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .config import get_app_config, get_project_map
from .database import repo
from .security import SecurityError, resolve_within_root

# Имя проекта: слаг из латиницы/цифр/-/_ (без точек, слэшей, пробелов).
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Папки, которые не показываем в обзоре (мусор/служебное).
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              ".idea", ".vscode", ".cache", ".pytest_cache", ".mypy_cache"}


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


# --- Обзор папок сервера и добавление существующей папки как проекта --------

def browse_roots() -> list[Path]:
    """Корни, доступные для обзора в UI.

    Явно заданы в config.yaml (browse_roots) — используем их. Иначе берём
    родителей существующих проектов + сам workspace. Это ограничивает обзор
    областями, где реально лежат проекты (не весь диск).
    """
    cfg = get_app_config()
    roots: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            return
        if str(rp) not in seen and rp.is_dir():
            seen.add(str(rp))
            roots.append(rp)

    if cfg.browse_roots:
        for r in cfg.browse_roots:
            _add(Path(r))
    else:
        for proj in all_projects():
            parent = Path(proj["path"]).parent
            _add(parent)
        if cfg.workspace:
            _add(Path(cfg.workspace))
    return roots


def _within_roots(path: Path, roots: list[Path]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def _existing_paths() -> set[str]:
    return {str(Path(p["path"]).resolve()) for p in all_projects()}


def browse_dirs(path: str | None) -> dict:
    """Листинг подпапок для выбора проекта.

    Без path — показываем список корней. С path — подпапки внутри него (строго
    в границах корней). Для каждой папки отмечаем доступность для пользователя,
    под которым работает сервис, и является ли она уже проектом.
    """
    roots = browse_roots()
    if not roots:
        return {"current": None, "parent": None, "roots": [], "entries": [],
                "error": "Обзор папок не настроен (browse_roots / workspace в config.yaml)."}

    existing = _existing_paths()

    # Верхний уровень: перечень корней как «папок».
    if not path:
        entries = [_entry(r, existing) for r in roots]
        return {"current": None, "parent": None,
                "roots": [str(r) for r in roots], "entries": entries}

    try:
        cur = Path(path).resolve()
    except OSError as exc:
        raise ProjectError(f"Некорректный путь: {exc}") from exc
    if not _within_roots(cur, roots):
        raise ProjectError("Путь вне разрешённых для обзора папок.")
    if not cur.is_dir():
        raise ProjectError("Папка не найдена.")

    entries: list[dict] = []
    try:
        for child in sorted(cur.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name in _SKIP_DIRS:
                continue
            entries.append(_entry(child, existing))
    except PermissionError:
        raise ProjectError("Нет доступа к папке (нужен setfacl для пользователя сервиса).")

    # Родитель — только если не поднимаемся выше корня.
    parent = None if cur in roots else str(cur.parent)
    return {"current": _entry(cur, existing), "parent": parent,
            "roots": [str(r) for r in roots], "entries": entries}


def _entry(p: Path, existing: set[str]) -> dict:
    accessible = os.access(p, os.R_OK | os.X_OK)
    return {
        "name": p.name or str(p),
        "path": str(p),
        "accessible": accessible,
        "writable": accessible and os.access(p, os.W_OK),
        "is_project": str(p) in existing,
    }


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", (text or "").strip().lower()).strip("-_")
    s = re.sub(r"-{2,}", "-", s)[:64]
    if not s or not re.match(r"^[a-z0-9]", s):
        s = ("p-" + s).strip("-")[:64] or "project"
    return s


def _unique_name(base: str) -> str:
    existing = {p["name"] for p in all_projects()}
    if base not in existing:
        return base
    for i in range(2, 1000):
        cand = f"{base}-{i}"[:64]
        if cand not in existing:
            return cand
    raise ProjectError("Не удалось подобрать уникальное имя проекта.")


def add_existing_project(path: str, name: str | None = None) -> dict:
    """Добавить уже существующую папку сервера как проект (без создания файлов)."""
    roots = browse_roots()
    if not roots:
        raise ProjectError("Обзор папок не настроен (browse_roots / workspace в config.yaml).")
    try:
        target = Path(path).resolve()
    except OSError as exc:
        raise ProjectError(f"Некорректный путь: {exc}") from exc
    if not _within_roots(target, roots):
        raise ProjectError("Путь вне разрешённых для обзора папок.")
    if not target.is_dir():
        raise ProjectError(f"Папка не существует: {target}")
    if not os.access(target, os.R_OK | os.X_OK):
        raise ProjectError(
            "Нет доступа к папке у пользователя сервиса. Дай доступ на сервере:\n"
            f"  sudo setfacl -R -m u:aiagent:rwX \"{target}\"\n"
            f"  sudo setfacl -m u:aiagent:x \"{target.parent}\""
        )

    if str(target) in _existing_paths():
        raise ProjectError("Эта папка уже добавлена как проект.")

    # Имя: заданное пользователем или из названия папки.
    if name and name.strip():
        slug = (name.strip().lower()
                if _NAME_RE.match(name.strip().lower()) else _slugify(name))
        if slug in {p["name"] for p in all_projects()}:
            raise ProjectError(f"Проект '{slug}' уже существует.")
    else:
        slug = _unique_name(_slugify(target.name))

    repo.add_project(slug, str(target))
    return {"name": slug, "path": str(target), "available": True, "kind": "custom"}


def remove_project(name: str) -> None:
    """Убрать проект, добавленный через UI (конфиговые удалить нельзя)."""
    if name in get_project_map():
        raise ProjectError("Проект задан в config.yaml — его нельзя удалить из интерфейса.")
    if not repo.remove_project(name):
        raise ProjectError(f"Проект '{name}' не найден.")
