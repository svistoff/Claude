"""Фабрика FastAPI-приложения и маршруты админки."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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

WEB_DIR = Path(__file__).resolve().parent


async def current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return await session.get(User, uid)


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


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
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    app.state.settings = settings
    app.state.templates = templates

    def render(request: Request, name: str, user: User | None = None, **ctx) -> HTMLResponse:
        return templates.TemplateResponse(
            request, name, {"user": user, "settings": settings, **ctx}
        )

    # ── Здоровье ────────────────────────────────────────────────────────────
    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    # ── Авторизация ─────────────────────────────────────────────────────────
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
        return _redirect("/")

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return _redirect("/login")

    # ── Дашборд ─────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        user: User | None = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ):
        if user is None:
            return _redirect("/login")

        async def count(model, *where):
            return await session.scalar(select(func.count()).select_from(model).where(*where))

        stats = {
            "projects": await count(Project),
            "queries": await count(Query, Query.active.is_(True)),
            "sites": await count(Site, Site.active.is_(True)),
            "profiles": await count(Profile, Profile.active.is_(True)),
        }
        return render(request, "dashboard.html", user=user, stats=stats)

    # ── Проекты ──────────────────────────────────────────────────────────────
    @app.get("/projects", response_class=HTMLResponse)
    async def projects_list(
        request: Request,
        user: User | None = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ):
        if user is None:
            return _redirect("/login")
        projects = (
            await session.execute(select(Project).order_by(Project.created_at.desc()))
        ).scalars().all()
        return render(request, "projects.html", user=user, projects=projects)

    @app.post("/projects")
    async def projects_create(
        request: Request,
        user: User | None = Depends(current_user),
        session: AsyncSession = Depends(get_session),
        name: str = Form(...),
        depth: int = Form(50),
        description: str = Form(""),
    ):
        if user is None:
            return _redirect("/login")
        if user.role != "Admin":
            return _redirect("/projects")
        name = name.strip()
        if name:
            session.add(Project(name=name, depth=depth, description=description.strip() or None))
            await session.commit()
        return _redirect("/projects")

    @app.post("/projects/{project_id}/toggle")
    async def projects_toggle(
        project_id: int,
        user: User | None = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ):
        if user is None:
            return _redirect("/login")
        if user.role == "Admin":
            project = await session.get(Project, project_id)
            if project:
                project.active = not project.active
                await session.commit()
        return _redirect("/projects")

    return app
