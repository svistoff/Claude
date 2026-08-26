"""Точка входа: FastAPI-приложение + фоновый Device Monitor.

Запуск: uvicorn attendance.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from attendance.config import config
from attendance.database.database import close_db, init_db
from attendance.database import repository as repo
from attendance.services import attendance, auth, settings_service
from attendance.services.monitor import run_monitor
from attendance.web.auth_routes import router as auth_router
from attendance.web.dashboard_routes import router as dashboard_router
from attendance.web.deps import NotAuthenticated
from attendance.web.employee_routes import router as employee_router
from attendance.web.history_routes import router as history_router
from attendance.web.settings_routes import router as settings_router

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def _seed_admin_user() -> None:
    if not await repo.any_admin_exists():
        await repo.create_admin(config.admin_username, auth.hash_password(config.admin_password))
        logger.info("Создан администратор по умолчанию: %s", config.admin_username)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Запуск Wi-Fi Attendance Service...")

    await init_db()
    await settings_service.seed_defaults()
    await _seed_admin_user()

    settings = await settings_service.get_settings()
    await attendance.recover_on_startup(timedelta(minutes=settings.absence_timeout_minutes))

    stop_event = asyncio.Event()
    monitor_task = asyncio.create_task(run_monitor(stop_event))

    try:
        yield
    finally:
        stop_event.set()
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        await close_db()
        logger.info("Wi-Fi Attendance Service остановлен")


app = FastAPI(title="Wi-Fi Attendance", lifespan=lifespan)

app.mount(
    "/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "web" / "static")), name="static"
)

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(employee_router)
app.include_router(history_router)
app.include_router(settings_router)


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/login")
