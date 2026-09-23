"""Фабрика FastAPI-приложения: middleware, аутентификация, подключение роутеров."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from ..bootstrap import init_db_and_admin
from ..config import Settings, get_settings
from ..db import get_session
from ..models import Profile, Project, Query, Site, User
from ..security import verify_password
from .deps import current_user, redirect, render
from .routes import analytics, projects

WEB_DIR = Path(__file__).resolve().parent


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db_and_admin(settings)
        yield

    app = FastAPI(title="posmon", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        https_only=settings.env == "production",
        max_age=60 * 60 * 24 * 14,
    )
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request):
        return render(request, "login.html")

    @app.post("/login")
    async def login_submit(
        request: Request,
        login: str = Form(...),
        password: str = Form(...),
        session: AsyncSession = Depends(get_session),
    ):
        user = (
            await session.execute(select(User).where(User.login == login))
        ).scalar_one_or_none()
        if user is None or not user.active or not verify_password(password, user.password_hash):
            return render(request, "login.html", error="Неверный логин или пароль")
        request.session["user_id"] = user.id
        return redirect("/")

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return redirect("/login")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        user: User | None = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ):
        if user is None:
            return redirect("/login")

        async def count(model, *where):
            return await session.scalar(select(func.count()).select_from(model).where(*where))

        stats = {
            "projects": await count(Project),
            "queries": await count(Query, Query.active.is_(True)),
            "sites": await count(Site, Site.active.is_(True)),
            "profiles": await count(Profile, Profile.active.is_(True)),
        }
        return render(request, "dashboard.html", user=user, stats=stats)

    app.include_router(projects.router)
    app.include_router(analytics.router)
    return app
