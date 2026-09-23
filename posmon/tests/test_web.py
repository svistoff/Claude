import httpx
import pytest_asyncio
from sqlalchemy import select

from posmon import db
from posmon.bootstrap import init_db_and_admin
from posmon.config import get_settings
from posmon.web import create_app


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    dbfile = tmp_path / "web.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{dbfile}")
    monkeypatch.setenv("POSMON_ENV", "development")          # https_only=False для http-теста
    monkeypatch.setenv("POSMON_SECRET_KEY", "test-secret")
    monkeypatch.setenv("POSMON_ADMIN_LOGIN", "admin")
    monkeypatch.setenv("POSMON_ADMIN_PASSWORD", "secret")
    get_settings.cache_clear()
    db.reset_engine_state()

    settings = get_settings()
    await init_db_and_admin(settings)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c

    db.reset_engine_state()
    get_settings.cache_clear()


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_dashboard_requires_login(client):
    r = await client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


async def test_bad_login_shows_error(client):
    r = await client.post("/login", data={"login": "admin", "password": "wrong"})
    assert r.status_code == 200
    assert "Неверный" in r.text


async def _login(client):
    await client.post("/login", data={"login": "admin", "password": "secret"})


async def test_login_then_create_project(client):
    r = await client.get("/login")
    assert r.status_code == 200 and "Вход" in r.text

    r = await client.post("/login", data={"login": "admin", "password": "secret"})
    assert r.status_code == 303 and r.headers["location"] == "/"

    r = await client.get("/")
    assert r.status_code == 200 and "Мониторинг позиций" in r.text

    r = await client.post("/projects", data={"name": "ЕКБ ГИД", "depth": "50", "description": ""})
    assert r.status_code == 303

    r = await client.get("/projects")
    assert r.status_code == 200 and "ЕКБ ГИД" in r.text


async def test_full_config_flow_and_analytics(client):
    from datetime import date

    from posmon.db import get_sessionmaker
    from posmon.models import PositionHistory, Profile, Query, Site

    await _login(client)
    await client.post("/projects", data={"name": "Проект1", "depth": "50", "description": ""})

    # проект №1
    r = await client.get("/projects/1")
    assert r.status_code == 200 and "Проект1" in r.text

    # добавляем запрос (массово), сайт, профиль
    await client.post("/projects/1/queries", data={"queries_text": "ресторан екб\nбар екб", "group_name": "", "is_local": "true"})
    await client.post("/projects/1/sites", data={"name": "Сайт A", "url": "https://a.ru/", "match_mode": "domain"})
    await client.post("/projects/1/profiles", data={"name": "Desktop", "device": "desktop", "source": "api", "region": "Екатеринбург"})

    r = await client.get("/projects/1")
    assert "ресторан екб" in r.text and "Сайт A" in r.text and "Desktop" in r.text

    # засеем историю позиции напрямую, затем проверим график
    async with get_sessionmaker()() as s:
        q = (await s.execute(select(Query))).scalars().first()
        site = (await s.execute(select(Site))).scalars().first()
        prof = (await s.execute(select(Profile))).scalars().first()
        s.add(PositionHistory(project_id=1, query_id=q.id, site_id=site.id, profile_id=prof.id,
                              date=date.today(), mode="seo", position=4, status="SUCCESS"))
        await s.commit()
        qid, sid = q.id, site.id

    r = await client.get(f"/queries/{qid}?site={sid}&mode=seo")
    assert r.status_code == 200 and "<svg" in r.text and "Desktop" in r.text

    r = await client.get(f"/sites/{sid}?mode=seo")
    assert r.status_code == 200 and "Средняя позиция" in r.text


async def test_run_now_redirects(client):
    await _login(client)
    await client.post("/projects", data={"name": "P", "depth": "50", "description": ""})
    r = await client.post("/projects/1/run", data={"mode": "seo"})
    assert r.status_code == 303
    assert "/projects/1" in r.headers["location"]
