"""FastAPI-приложение: сборка роутеров, статика фронтенда, заголовки безопасности."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import auth_routes, chat, files, git_routes, projects, settings, uploads
from .config import BACKEND_DIR
from .database import init_db

FRONTEND_DIR = BACKEND_DIR.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Coding Agent", version="0.1.0",
              docs_url=None, redoc_url=None, lifespan=lifespan)


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
app.include_router(files.router)
app.include_router(settings.router)
app.include_router(uploads.router)


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

    @app.get("/")
    def index():
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace("{{V}}", _asset_version())
        # index.html не кэшируем — он подставляет свежую версию ассетов.
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})
