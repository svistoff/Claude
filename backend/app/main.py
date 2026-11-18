"""FastAPI-приложение: сборка роутеров, статика фронтенда, заголовки безопасности."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .api import (auth_routes, browser_routes, chat, files, git_routes,
                  github_routes, mentor, projects, settings, uploads)
from .config import BACKEND_DIR, get_settings
from .database import init_db
from .mentor import scheduler as mentor_scheduler
from .telegram import gateway as telegram_gateway

FRONTEND_DIR = BACKEND_DIR.parent / "frontend"

# Приложение может быть установлено с одного адреса, а API брать с другого
# (например, иконка на телефоне смотрит на VPS, но выбран локальный запуск).
# По умолчанию разрешаем только «свой» домен и локальные адреса.
DEFAULT_CORS_ORIGINS = [
    "https://ai.svistoff.ru",
    "http://localhost:8770",
    "http://127.0.0.1:8770",
    "http://localhost:8000",
]


def _cors_origins() -> list[str]:
    raw = get_settings().cors_origins.strip()
    extra = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()] if raw else []
    out = []
    for origin in [*DEFAULT_CORS_ORIGINS, *extra]:
        if origin not in out:
            out.append(origin)
    return out


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    mentor_scheduler.start()  # фоновый планировщик напоминаний (наставник)
    telegram_gateway.start()  # Telegram-дверь к агенту (если задан токен)
    try:
        yield
    finally:
        mentor_scheduler.stop()
        await telegram_gateway.stop()


app = FastAPI(title="AI Coding Agent", version="0.1.0",
              docs_url=None, redoc_url=None, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,   # кросс-серверный режим работает на Bearer-токене
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "x-csrf-token"],
    expose_headers=["Content-Disposition"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


# API-роутеры
app.include_router(auth_routes.router)
app.include_router(projects.router)
app.include_router(chat.router)
app.include_router(git_routes.router)
app.include_router(github_routes.router)
app.include_router(files.router)
app.include_router(settings.router)
app.include_router(uploads.router)
app.include_router(browser_routes.router)
app.include_router(mentor.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "ai-agent"}


@app.exception_handler(500)
async def _500(request: Request, exc: Exception):
    # Не раскрываем детали/секреты пользователю.
    return JSONResponse(status_code=500, content={"error": "Внутренняя ошибка."})


# --- Статика фронтенда (mobile-first SPA) -----------------------------------
def _asset_version() -> str:
    """Версия статики по mtime — чтобы браузер не держал старые CSS/JS в кэше."""
    try:
        mt = max((FRONTEND_DIR / f).stat().st_mtime
                 for f in ("app.js", "styles.css", "index.html"))
        return str(int(mt))
    except OSError:
        return "1"


if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    def _render(name: str) -> str:
        """Отдать файл фронта с подставленной версией статики."""
        html = (FRONTEND_DIR / name).read_text(encoding="utf-8")
        return html.replace("{{V}}", _asset_version())

    @app.get("/")
    def index():
        # index.html не кэшируем — он подставляет свежую версию ассетов.
        return HTMLResponse(_render("index.html"), headers={"Cache-Control": "no-store"})

    @app.get("/manifest.webmanifest")
    def manifest():
        """Манифест PWA: имя, иконки, standalone-режим (иконка на рабочем столе)."""
        body = (FRONTEND_DIR / "manifest.webmanifest").read_text(encoding="utf-8")
        return Response(body, media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js")
    def service_worker():
        """Service worker из корня — иначе область действия ограничится /static/."""
        return Response(_render("sw.js"), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache",
                                 "Service-Worker-Allowed": "/"})

    @app.get("/favicon.ico")
    def favicon():
        icon = FRONTEND_DIR / "icons" / "favicon.ico"
        if not icon.exists():
            raise HTTPException(404, "Нет иконки.")
        return FileResponse(str(icon), headers={"Cache-Control": "public, max-age=86400"})
