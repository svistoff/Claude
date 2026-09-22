"""Ежедневный планировщик проверок (APScheduler).

Запуск отдельным процессом Supervisor:
    python -m posmon.scheduler

Раздел 12 ТЗ: ежедневный запуск в настраиваемое время (по TZ проекта) со
случайным небольшим смещением (jitter), чтобы не создавать одинаковый паттерн.
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from .bootstrap import init_db_and_admin
from .config import get_settings
from .db import get_sessionmaker
from .models import Project
from .services.runner import run_project_batch

logger = logging.getLogger("posmon.scheduler")


async def run_all_active_projects() -> None:
    """Прогнать ежедневную проверку по всем активным проектам."""
    settings = get_settings()
    maker = get_sessionmaker()
    async with maker() as session:
        project_ids = (
            await session.execute(select(Project.id).where(Project.active.is_(True)))
        ).scalars().all()

    logger.info("Ежедневный прогон: проектов=%s", len(project_ids))
    for pid in project_ids:
        try:
            summary = await run_project_batch(maker, settings, pid)
            logger.info(
                "Проект %s: всего=%s успех=%s не найдено=%s ошибок=%s",
                pid, summary.total, summary.success, summary.not_found, summary.failed,
            )
        except Exception:  # noqa: BLE001 — один проект не должен ронять остальные
            logger.exception("Проект %s: прогон упал", pid)


def _parse_hh_mm(value: str) -> tuple[int, int]:
    hh, mm = value.split(":", 1)
    return int(hh), int(mm)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await init_db_and_admin(settings)

    if not settings.daily_check_enabled:
        logger.warning("Ежедневная проверка выключена (DAILY_CHECK_ENABLED=false). Ожидание.")
        await asyncio.Event().wait()
        return

    hour, minute = _parse_hh_mm(settings.daily_check_time)
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        run_all_active_projects,
        CronTrigger(
            hour=hour,
            minute=minute,
            timezone=settings.timezone,
            jitter=settings.daily_check_jitter_seconds,
        ),
        id="daily_check",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Планировщик запущен: ежедневно в %02d:%02d %s (jitter=%ss)",
        hour, minute, settings.timezone, settings.daily_check_jitter_seconds,
    )
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
