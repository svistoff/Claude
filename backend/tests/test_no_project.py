"""Чат без проекта: пустой старт, разговор без доступа к коду, привязка позже."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import chat_state
from app.database import repo
from app.main import app
from app.tools import registry
from app.tools.base import ToolContext
from tests.conftest import TEST_PASSWORD


def _client() -> tuple[TestClient, dict]:
    c = TestClient(app)
    c.post("/api/login", json={"username": "admin", "password": TEST_PASSWORD})
    return c, {"x-csrf-token": c.get("/api/me").json()["csrf"]}


# --- Данные ---------------------------------------------------------------

def test_conversation_without_project():
    conv = repo.create_conversation(None, "просто чат")
    meta = repo.get_conversation_meta(conv)
    assert meta["project"] == ""          # пустая строка = «без проекта»


def test_attach_project_later():
    conv = repo.create_conversation(None, "чат")
    assert repo.set_conversation_project(conv, "ai-agent") is True
    assert repo.get_conversation_meta(conv)["project"] == "ai-agent"


# --- Инструменты ----------------------------------------------------------

def test_project_tools_refuse_without_project():
    ctx = ToolContext(project_name=None, project_root=None, config=None)
    for name in ("read_file", "list_files", "write_file", "edit_file",
                 "terminal", "git", "github"):
        res = registry.dispatch(ctx, name, {"path": "x", "query": "x"})
        assert res.ok is False, name
        assert "Проект не выбран" in res.content, name


def test_non_project_tools_work_without_project(monkeypatch):
    """Поиск в интернете и задачи не должны требовать проект."""
    ctx = ToolContext(project_name=None, project_root=None, config=None)

    def fake_search(_ctx, args):
        from app.tools.base import ToolResult
        return ToolResult(True, "найдено: 1", summary="поиск")

    monkeypatch.setitem(registry._DISPATCH, "web_search", fake_search)
    res = registry.dispatch(ctx, "web_search", {"query": "погода"})
    assert res.ok is True and "найдено" in res.content


def test_tasks_tool_works_without_project():
    ctx = ToolContext(project_name=None, project_root=None, config=None)
    res = registry.dispatch(ctx, "tasks", {"action": "list"})
    assert res.ok is True


def test_system_prompt_has_no_project_note():
    from app.agent.prompts import NO_PROJECT_NOTE
    assert "проект пока НЕ выбран" in NO_PROJECT_NOTE
    assert "read_file" in NO_PROJECT_NOTE


# --- API ------------------------------------------------------------------

def test_chat_accepts_missing_project():
    """Проект не указан — запрос не падает 400 (проверяем валидацию, не запуск LLM)."""
    from app.api.chat import ChatBody
    body = ChatBody(message="привет")
    assert body.project is None
    assert ChatBody(message="привет", project="ai-agent").project == "ai-agent"


def test_active_chat_api_without_project():
    repo.set_setting(chat_state.KEY, "")
    c, headers = _client()

    r = c.post("/api/chats/active", json={"conversation_id": None, "project": None},
               headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["conversation_id"] is None
    assert data["last_project"] is None      # прошлый проект не тянем

    conv = repo.create_conversation(None, "без проекта")
    r2 = c.post("/api/chats/active", json={"conversation_id": conv}, headers=headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["conversation_id"] == conv
    assert d2["project"] is None             # чат без проекта
    assert d2["by_project"] == {}            # и в память проектов не попал


def test_state_clears_project_when_new_chat_without_project():
    repo.set_setting(chat_state.KEY, "")
    conv = repo.create_conversation("ai-agent", "в проекте")
    chat_state.set_active(conv)
    assert chat_state.current()["last_project"] == "ai-agent"

    cur = chat_state.set_active(None, None)
    assert cur["conversation_id"] is None
    assert cur["last_project"] is None       # следующий вход — чистый старт
    assert cur["by_project"] == {"ai-agent": conv}   # но чат проекта помним


def test_chats_list_allows_empty_project():
    c, _ = _client()
    conv = repo.create_conversation(None, "без проекта")
    r = c.get("/api/chats")
    assert r.status_code == 200
    chats = {x["id"]: x for x in r.json()["chats"]}
    assert chats[conv]["project"] == ""
