"""«Где я остановился»: какой чат открывать при входе в веб-интерфейс.

Раньше выбранный чат жил только в памяти вкладки (`state.conversationId`), поэтому
каждый вход на сайт открывал пустой чат — со стороны это выглядело как потеря
контекста. Теперь выбор хранится в БД (`app_settings.web_active_chats`):

- `last` — последний открытый чат (его и восстанавливаем);
- `last_project` — последний выбранный проект (нужен, если в проекте ещё нет чата);
- `by_project` — последний чат каждого проекта (вернулся в проект — вернулся в чат).

Хранится на сервере, а не в localStorage, чтобы одинаково работать с телефона,
с компьютера и из другого браузера. Ссылки на удалённые чаты вычищаются при чтении.
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


def current() -> dict[str, Any]:
    """Что открыть при входе: чат, его проект и последний выбранный проект.

    Если чат успели удалить — подставляем другой чат того же проекта, чтобы
    пользователь всё равно попал в привычное место, а не в пустоту.
    """
    state = _load()
    by_project: dict[str, str] = {}
    for project, conv_id in state["by_project"].items():
        meta = repo.get_conversation_meta(conv_id) if conv_id else None
        if meta is not None and meta["project"] == project:
            by_project[project] = conv_id

    meta = repo.get_conversation_meta(state["last"]) if state["last"] else None
    last_project = state["last_project"] or (meta["project"] if meta else None)
    conv_id = meta["id"] if meta else None
    project = meta["project"] if meta else None

    if meta is None and state["last"] and last_project and not conv_id:
        # Последний чат удалён/недоступен — ведём в чат того же проекта.
        pick = by_project.get(last_project)
        picked = repo.get_conversation_meta(pick) if pick else None
        if picked is None:
            picked = repo.latest_conversation_for_project(last_project)
        if picked is not None:
            conv_id, project = picked["id"], picked["project"]
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
    """Запомнить открытый чат (или «начал новый чат в проекте»).

    `conversation_id=None` — пользователь начал новый чат: для проекта забываем
    прошлый чат, чтобы следующий вход тоже открывал чистый чат.
    """
    state = _load()

    if conversation_id:
        meta = repo.get_conversation_meta(conversation_id)
        if meta is None:
            return current()          # чужой/удалённый id — ничего не меняем
        project = meta["project"]
        state["last"] = meta["id"]
        state["last_project"] = project
        state["by_project"][project] = meta["id"]
    else:
        state["last"] = None
        if project:
            state["last_project"] = project
            state["by_project"].pop(project, None)

    _save(state)
    return current()
