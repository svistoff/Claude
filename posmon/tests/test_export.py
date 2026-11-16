"""Экспорт для CRM: только локальные запросы, полный состав данных."""
from datetime import date

import httpx
import pytest_asyncio

from posmon import db
from posmon.bootstrap import init_db_and_admin
from posmon.config import get_settings
from posmon.web import create_app


@pytest_asyncio.fixture
async def app_and_maker(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'exp.db'}")
    monkeypatch.setenv("POSMON_ENV", "development")
    monkeypatch.setenv("POSMON_SECRET_KEY", "test-secret")
    get_settings.cache_clear()
    db.reset_engine_state()
    settings = get_settings()
    await init_db_and_admin(settings)
    yield create_app(settings), db.get_sessionmaker()
    db.reset_engine_state()
    get_settings.cache_clear()


def _client(app, host="127.0.0.1"):
    transport = httpx.ASGITransport(app=app, client=(host, 12345))
    return httpx.AsyncClient(transport=transport, base_url="http://t")


async def _seed(maker):
    from posmon.models import PositionHistory, Profile, Project, Query, Site

    async with maker() as s:
        p = Project(name="Массаж ЕКБ", depth=50)
        s.add(p)
        await s.flush()
        q = Query(project_id=p.id, query="массаж екатеринбург")
        site = Site(project_id=p.id, name="VIP", domain="xmassage.vip")
        prof = Profile(project_id=p.id, name="Desktop", settings_json='{"cookie":"secret"}')
        s.add_all([q, site, prof])
        await s.flush()
        for d, pos in ((date(2026, 11, 1), 7), (date(2026, 11, 10), 4)):
            s.add(PositionHistory(project_id=p.id, query_id=q.id, site_id=site.id,
                                  profile_id=prof.id, date=d, mode="seo", position=pos, status="SUCCESS"))
        await s.commit()


async def test_export_local_returns_everything(app_and_maker):
    app, maker = app_and_maker
    await _seed(maker)
    async with _client(app) as c:
        r = await c.get("/api/export")
    assert r.status_code == 200
    data = r.json()
    assert [p["name"] for p in data["projects"]] == ["Массаж ЕКБ"]
    assert data["sites"][0]["domain"] == "xmassage.vip"
    assert data["queries"][0]["query"] == "массаж екатеринбург"
    assert "settings_json" not in data["profiles"][0]
    assert [h["position"] for h in data["history"]] == [7, 4]
    assert data["history"][0]["date"] == "2026-11-01"


async def test_export_since_filters_history(app_and_maker):
    app, maker = app_and_maker
    await _seed(maker)
    async with _client(app) as c:
        r = await c.get("/api/export", params={"since": "2026-11-05"})
    assert [h["position"] for h in r.json()["history"]] == [4]


async def test_export_forbidden_through_proxy_or_remote(app_and_maker):
    app, _ = app_and_maker
    async with _client(app) as c:
        r = await c.get("/api/export", headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 403
    async with _client(app, host="8.8.8.8") as c:
        r = await c.get("/api/export")
    assert r.status_code == 403
