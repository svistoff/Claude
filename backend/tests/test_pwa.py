"""Приложение как PWA и работа «с другого сервера» (токен + CORS)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import DEFAULT_CORS_ORIGINS, app, _cors_origins
from tests.conftest import TEST_PASSWORD

client = TestClient(app)


def _login():
    r = client.post("/api/login", json={"username": "admin", "password": TEST_PASSWORD})
    assert r.status_code == 200
    return r.json()


# --- Установка на рабочий стол (манифест, иконки, service worker) -----------

def test_manifest_is_served():
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest" in r.headers["content-type"]
    data = r.json()
    assert data["name"] == "AI Coder"
    assert data["display"] == "standalone"          # без адресной строки, как приложение
    assert data["start_url"].startswith("/")
    sizes = {i["sizes"] for i in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in data["icons"])


def test_icons_exist():
    for path in ("/static/icons/icon-192.png", "/static/icons/icon-512.png",
                 "/static/icons/icon-maskable-512.png",
                 "/static/icons/apple-touch-icon-180.png"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"] == "image/png"
        assert len(r.content) > 500


def test_favicon():
    r = client.get("/favicon.ico")
    assert r.status_code == 200 and len(r.content) > 100


def test_service_worker_from_root():
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    body = r.text
    # Версия подставлена, плейсхолдеров не осталось, scope — весь сайт.
    assert "{{V}}" not in body
    assert 'const CACHE = "aicoder-' in body
    assert r.headers.get("service-worker-allowed") == "/"
    # Данные агента SW не кэширует — иначе история и ответы будут «залипать».
    assert 'if (isApi(url)) return;' in body


def test_index_has_pwa_meta():
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'rel="manifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert "apple-mobile-web-app-capable" in html


# --- Работа приложения с другим сервером ------------------------------------

def test_login_returns_token():
    data = _login()
    assert data["token"] and data["csrf"]
    assert data["token"] != data["csrf"]


def test_bearer_grants_access_without_cookie():
    token = _login()["token"]
    fresh = TestClient(app)     # без cookie вообще
    r = fresh.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200

    r2 = fresh.get("/api/chats/active", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200


def test_bearer_needs_no_csrf_for_mutations():
    token = _login()["token"]
    fresh = TestClient(app)
    r = fresh.post("/api/chats/active", json={"conversation_id": None},
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["conversation_id"] is None


def test_cookie_mode_still_requires_csrf():
    client.post("/api/login", json={"username": "admin", "password": TEST_PASSWORD})
    r = client.post("/api/chats/active", json={"conversation_id": None})
    assert r.status_code == 403


def test_bad_bearer_is_rejected():
    fresh = TestClient(app)
    for bad in ("Bearer nope", "Bearer ", "Basic abc"):
        r = fresh.get("/api/projects", headers={"Authorization": bad})
        assert r.status_code == 401, bad


def test_me_works_with_bearer():
    token = _login()["token"]
    fresh = TestClient(app)
    r = fresh.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["authenticated"] is True


def test_cors_allows_app_origin_and_blocks_others():
    allowed = "https://ai.svistoff.ru"
    r = client.get("/api/health", headers={"Origin": allowed})
    assert r.headers.get("access-control-allow-origin") == allowed

    r2 = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r2.headers


def test_cors_preflight_for_bearer():
    r = client.options("/api/projects", headers={
        "Origin": "https://ai.svistoff.ru",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    })
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "https://ai.svistoff.ru"
    assert "authorization" in r.headers.get("access-control-allow-headers", "").lower()


def test_cors_origins_include_locals():
    origins = _cors_origins()
    assert "https://ai.svistoff.ru" in DEFAULT_CORS_ORIGINS
    assert any("localhost" in o for o in origins)
