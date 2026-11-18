"""Тесты «где я остановился»: активный чат сохраняется между сессиями."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import chat_state
from app.database import repo
from app.main import app
from tests.conftest import TEST_PASSWORD


def _client() -> tuple[TestClient, dict]:
    c = TestClient(app)
    c.post("/api/login", json={"username": "admin", "password": TEST_PASSWORD})
    return c, {"x-csrf-token": c.get("/api/me").json()["csrf"]}


def test_current_empty_by_default():
    repo.set_setting(chat_state.KEY, "")
    cur = chat_state.current()
    assert cur["conversation_id"] is None
    assert cur["last_project"] is None
    assert cur["by_project"] == {}


def test_set_active_remembers_chat_and_project():
    repo.set_setting(chat_state.KEY, "")
    conv = repo.create_conversation("proj-a", "задача")
    cur = chat_state.set_active(conv)
    assert cur["conversation_id"] == conv
    assert cur["project"] == "proj-a"
    assert cur["last_project"] == "proj-a"
    assert cur["by_project"] == {"proj-a": conv}
    # сохранено в БД — переживает перезапуск процесса
    assert chat_state.current()["conversation_id"] == conv


def test_by_project_remembers_each_project():
    repo.set_setting(chat_state.KEY, "")
    a = repo.create_conversation("proj-a", "в a")
    b = repo.create_conversation("proj-b", "в b")
    chat_state.set_active(a)
    chat_state.set_active(b)
    cur = chat_state.current()
    assert cur["conversation_id"] == b            # последний открытый
    assert cur["by_project"] == {"proj-a": a, "proj-b": b}


def test_deleted_chat_is_dropped():
    repo.set_setting(chat_state.KEY, "")
    old = repo.create_conversation("proj-a", "удалят")
    other = repo.create_conversation("proj-a", "останется")
    chat_state.set_active(old)
    repo.delete_conversation(old)
    cur = chat_state.current()
    # Чат удалён из другого окна — подставляем другой чат того же проекта.
    assert cur["conversation_id"] == other
    assert cur["project"] == "proj-a"


def test_deleted_chat_without_siblings_falls_back_to_project():
    repo.set_setting(chat_state.KEY, "")
    conv = repo.create_conversation("proj-empty", "единственный")
    chat_state.set_active(conv)
    repo.delete_conversation(conv)
    cur = chat_state.current()
    assert cur["conversation_id"] is None
    assert cur["last_project"] == "proj-empty"   # проект помним, чат — новый


def test_new_chat_forgets_project_chat_but_keeps_project():
    repo.set_setting(chat_state.KEY, "")
    conv = repo.create_conversation("proj-a", "старый")
    chat_state.set_active(conv)
    cur = chat_state.set_active(None, "proj-a")
    assert cur["conversation_id"] is None
    assert cur["last_project"] == "proj-a"
    assert "proj-a" not in cur["by_project"]


def test_unknown_chat_id_is_ignored():
    repo.set_setting(chat_state.KEY, "")
    conv = repo.create_conversation("proj-a", "ok")
    chat_state.set_active(conv)
    cur = chat_state.set_active("нет-такого-чата")
    assert cur["conversation_id"] == conv


def test_broken_setting_is_survived():
    repo.set_setting(chat_state.KEY, "не json")
    cur = chat_state.current()
    assert cur["conversation_id"] is None and cur["by_project"] == {}


def test_api_get_and_post_active():
    repo.set_setting(chat_state.KEY, "")
    c, headers = _client()
    conv = repo.create_conversation("proj-api", "через http")

    r = c.post("/api/chats/active", json={"conversation_id": conv}, headers=headers)
    assert r.status_code == 200
    assert r.json()["conversation_id"] == conv

    r2 = c.get("/api/chats/active")
    assert r2.status_code == 200
    data = r2.json()
    assert data["conversation_id"] == conv and data["last_project"] == "proj-api"

    # «Начал новый чат» — чат забыт, проект остался.
    r3 = c.post("/api/chats/active", json={"conversation_id": None, "project": "proj-api"},
                headers=headers)
    assert r3.status_code == 200
    assert r3.json()["conversation_id"] is None


def test_api_requires_auth_and_csrf():
    fresh = TestClient(app)
    assert fresh.get("/api/chats/active").status_code == 401

    c, _ = _client()
    # Без CSRF-заголовка менять состояние нельзя.
    assert c.post("/api/chats/active", json={"conversation_id": None}).status_code == 403
