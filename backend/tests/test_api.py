"""Интеграционные тесты HTTP API (auth, health, защита роутов)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import TEST_PASSWORD

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_projects_require_auth():
    r = client.get("/api/projects")
    assert r.status_code == 401


def test_login_wrong_password():
    r = client.post("/api/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
    assert r.json()["ok"] is False


def test_login_and_access():
    r = client.post("/api/login", json={"username": "admin", "password": TEST_PASSWORD})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True and data["csrf"]

    # После входа cookie сохраняется в client — защищённый роут доступен.
    r2 = client.get("/api/projects")
    assert r2.status_code == 200
    assert "projects" in r2.json()


def test_csrf_required_for_mutation():
    client.post("/api/login", json={"username": "admin", "password": TEST_PASSWORD})
    # Без CSRF-заголовка stop должен вернуть 403.
    r = client.post("/api/agent/stop", json={"conversation_id": "x"})
    assert r.status_code == 403


def test_me_endpoint():
    fresh = TestClient(app)
    r = fresh.get("/api/me")
    assert r.json()["authenticated"] is False
