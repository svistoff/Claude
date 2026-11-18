"""«Где я остановился»: какой чат открывать при входе в веб-интерфейс.

Выбор хранится на сервере (`app_settings.web_active_chats`), поэтому одинаково
работает с телефона, с компьютера и из другого браузера:

- `last` — последний открытый чат (нужен для режима «продолжить последний»);
- `last_project` — последний выбранный проект (None — проект не выбран);
- `by_project` — последний чат каждого проекта (вернулся в проект — вернулся в чат).

Чат может быть без проекта (в базе это пустая строка): такой чат в `by_project`
не попадает. Ссылки на удалённые чаты вычищаются при чтении.
"""

from __future__ import annotations

import json
from typing import Any

from .database import repo

KEY = "web_active_chats"


def _empty() -> dict[str, Any]:
    return {"last": None, "last_project": None, "by_project": {}}


def _load() -> dict[str, Any]:
    raw = repo.get_setting(KEY)
    if not raw:
        return _empty()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    by_project = data.get("by_project")
    return {
        "last": data.get("last") or None,
        "last_project": data.get("last_project") or None,
        "by_project": by_project if isinstance(by_project, dict) else {},
    }


def _save(state: dict[str, Any]) -> None:
    repo.set_setting(KEY, json.dumps(state, ensure_ascii=False))


def _project_of(meta: dict[str, Any] | None) -> str | None:
    """Проект чата как имя или None («без проекта» хранится пустой строкой)."""
    if not meta:
        return None
    return meta.get("project") or None


def current() -> dict[str, Any]:
    """Что открыть при входе: чат, его проект и последний выбранный проект.

    Если чат успели удалить — подставляем другой чат того же проекта, чтобы
    пользователь всё равно попал в привычное место, а не в пустоту.
    """
    state = _load()
    by_project: dict[str, str] = {}
    for project, conv_id in state["by_project"].items():
        meta = repo.get_conversation_meta(conv_id) if conv_id else None
        if _project_of(meta) == project:
            by_project[project] = conv_id

    meta = repo.get_conversation_meta(state["last"]) if state["last"] else None
    last_project = state["last_project"] or _project_of(meta)
    conv_id = meta["id"] if meta else None
    project = _project_of(meta)

    if meta is None and state["last"] and last_project and not conv_id:
        # Последний чат удалён/недоступен — ведём в чат того же проекта.
        pick = by_project.get(last_project)
        picked = repo.get_conversation_meta(pick) if pick else None
        if picked is None:
            picked = repo.latest_conversation_for_project(last_project)
        if picked is not None:
            conv_id, project = picked["id"], _project_of(picked)
            if project:
                by_project[project] = conv_id

    # Чистим устаревшие ссылки (удалённые чаты) и запоминаем нормализованное состояние.
    if (state["last"] != conv_id or state["last_project"] != last_project
            or state["by_project"] != by_project):
        _save({"last": conv_id, "last_project": last_project, "by_project": by_project})

    return {
        "conversation_id": conv_id,
        "project": project,
        "last_project": last_project,
        "by_project": by_project,
    }


def set_active(conversation_id: str | None, project: str | None = None) -> dict[str, Any]:
    """Запомнить открытый чат (или «начал новый чат»).

    `conversation_id=None, project=None` — начат пустой чат без проекта: забываем
    и прошлый чат, и прошлый проект, чтобы следующий вход тоже был чистым.
    `conversation_id=None, project="имя"` — новый чат в проекте: чат забываем,
    проект помним.
    """
    state = _load()

    if conversation_id:
        meta = repo.get_conversation_meta(conversation_id)
        if meta is None:
            return current()          # чужой/удалённый id — ничего не меняем
        chat_project = _project_of(meta)
        state["last"] = meta["id"]
        state["last_project"] = chat_project
        if chat_project:
            state["by_project"][chat_project] = meta["id"]
    else:
        state["last"] = None
        if project:
            state["last_project"] = project
            state["by_project"].pop(project, None)
        else:
            # Пустой чат без проекта — не тянем прошлый проект при следующем входе.
            state["last_project"] = None

    _save(state)
    return current()
