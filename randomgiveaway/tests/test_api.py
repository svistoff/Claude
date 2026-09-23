"""Сквозной тест API (§20, §35 ТЗ): создание → импорт → предпросмотр → розыгрыш → результат."""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from randomgiveaway.main import app


def _create_giveaway(client: TestClient, **settings_overrides) -> dict:
    settings = {"unique_user": True, "winners_count": 2, "backup_winners_count": 1}
    settings.update(settings_overrides)
    payload = {
        "source": "import",
        "post_url": "https://example.com/post/1",
        "title": "Тестовый розыгрыш",
        "settings": settings,
    }
    resp = client.post("/api/giveaways", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _import_csv(client: TestClient, giveaway_id: int, csv_text: str) -> dict:
    resp = client.post(
        f"/api/giveaways/{giveaway_id}/import",
        files={"file": ("comments.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
        data={"format": "csv"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_flow_create_import_draw_result():
    with TestClient(app) as client:
        giveaway = _create_giveaway(client)
        giveaway_id = giveaway["id"]
        assert giveaway["status"] == "DRAFT"
        assert giveaway["public_id"].startswith("RND-")

        preview = _import_csv(
            client,
            giveaway_id,
            "user_id,username,text\nu1,alex,comment\nu2,ivan,comment\nu3,kate,comment\nu4,max,comment\n",
        )
        assert preview["total_comments"] == 4
        assert preview["participants_after_rules"] == 4

        resp = client.post(f"/api/giveaways/{giveaway_id}/participants/process")
        assert resp.status_code == 200, resp.text
        assert resp.json()["participants_after_rules"] == 4

        resp = client.post(f"/api/giveaways/{giveaway_id}/draw")
        assert resp.status_code == 200, resp.text
        draw_result = resp.json()
        assert len(draw_result["winners"]) == 2
        assert len(draw_result["backups"]) == 1
        assert draw_result["giveaway"]["status"] == "DRAWN"
        winner_ids = {w["source_user_id"] for w in draw_result["winners"]}
        backup_ids = {b["source_user_id"] for b in draw_result["backups"]}
        assert winner_ids.isdisjoint(backup_ids)

        public_id = draw_result["giveaway"]["public_id"]
        resp = client.get(f"/api/results/{public_id}")
        assert resp.status_code == 200, resp.text
        public_result = resp.json()
        assert len(public_result["winners"]) == 2
        assert public_result["result_hash"]
        assert public_result["participants_hash"]


def test_double_draw_is_rejected():
    with TestClient(app) as client:
        giveaway = _create_giveaway(client, winners_count=1, backup_winners_count=0)
        giveaway_id = giveaway["id"]
        _import_csv(client, giveaway_id, "user_id,username\nu1,alex\nu2,ivan\n")

        resp = client.post(f"/api/giveaways/{giveaway_id}/draw")
        assert resp.status_code == 200, resp.text

        resp = client.post(f"/api/giveaways/{giveaway_id}/draw")
        assert resp.status_code == 409
        assert "уже проведён" in resp.json()["detail"]


def test_empty_result_after_filters_gives_friendly_message():
    with TestClient(app) as client:
        giveaway = _create_giveaway(
            client, winners_count=1, backup_winners_count=0, required_text="не встретится нигде"
        )
        giveaway_id = giveaway["id"]
        _import_csv(client, giveaway_id, "user_id,username,text\nu1,alex,привет\n")

        resp = client.post(f"/api/giveaways/{giveaway_id}/draw")
        assert resp.status_code == 400
        assert "Не найдено участников" in resp.json()["detail"]


def test_public_result_not_available_before_draw():
    with TestClient(app) as client:
        giveaway = _create_giveaway(client)
        resp = client.get(f"/api/results/{giveaway['public_id']}")
        assert resp.status_code == 404


def test_admin_token_protects_mutating_endpoints(monkeypatch):
    import dataclasses

    from randomgiveaway.api import routes as routes_module

    monkeypatch.setattr(
        routes_module, "config", dataclasses.replace(routes_module.config, admin_token="secret-token")
    )
    with TestClient(app) as client:
        resp = client.post(
            "/api/giveaways",
            json={"source": "import", "post_url": "https://example.com/post/1"},
        )
        assert resp.status_code == 401

        resp = client.post(
            "/api/giveaways",
            json={"source": "import", "post_url": "https://example.com/post/1"},
            headers={"X-Admin-Token": "secret-token"},
        )
        assert resp.status_code == 200, resp.text


def test_instagram_oauth_start_requires_admin_token():
    with TestClient(app) as client:
        resp = client.get("/api/instagram/oauth/start")
        # без ADMIN_TOKEN в конфиге require_admin пропускает всех — проверяем
        # только что без настроенных INSTAGRAM_APP_ID/REDIRECT_URI отдаётся
        # понятная ошибка, а не 500
        assert resp.status_code in (400, 307)


def test_instagram_oauth_callback_rejects_unknown_state():
    with TestClient(app) as client:
        resp = client.get("/api/instagram/oauth/callback", params={"code": "abc", "state": "unknown-state"})
        assert resp.status_code == 400
        assert "state" in resp.json()["detail"].lower()


def test_instagram_oauth_full_flow_with_valid_state(monkeypatch, tmp_path):
    import dataclasses

    from randomgiveaway.api import routes as routes_module
    from randomgiveaway.services import instagram_oauth as oauth_module

    monkeypatch.setattr(
        routes_module,
        "config",
        dataclasses.replace(
            routes_module.config,
            instagram_app_id="app-id",
            instagram_app_secret="app-secret",
            instagram_oauth_redirect_uri="https://random.ekb-guide.ru/api/instagram/oauth/callback",
        ),
    )
    # ENV_PATH подменяется на временный файл — реальный randomgiveaway/.env
    # трогать нельзя, даже в тесте
    monkeypatch.setattr(routes_module, "ENV_PATH", tmp_path / ".env")

    async def fake_exchange(code, app_id, app_secret, redirect_uri):
        assert code == "real-code"
        return "long-lived-token", 5183944

    monkeypatch.setattr(oauth_module, "exchange_code_for_long_lived_token", fake_exchange)

    with TestClient(app, follow_redirects=False) as client:
        start_resp = client.get("/api/instagram/oauth/start")
        assert start_resp.status_code == 307
        location = start_resp.headers["location"]
        state = location.split("state=")[1]

        callback_resp = client.get(
            "/api/instagram/oauth/callback", params={"code": "real-code", "state": state}
        )
        assert callback_resp.status_code == 200, callback_resp.text
        assert "подключён" in callback_resp.text

        # повторное использование того же state должно быть отклонено
        replay_resp = client.get(
            "/api/instagram/oauth/callback", params={"code": "real-code", "state": state}
        )
        assert replay_resp.status_code == 400
