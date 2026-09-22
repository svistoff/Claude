import httpx
import pytest_asyncio

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
