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
from .domain.results import RunMode
from .models import Project
from .services.runner import run_project_batch

logger = logging.getLogger("posmon.scheduler")


async def run_all_active_projects(mode: str = RunMode.SEO.value) -> None:
    """Прогнать проверку по всем активным проектам в режиме ``mode``."""
    settings = get_settings()
    maker = get_sessionmaker()
    async with maker() as session:
        project_ids = (
            await session.execute(select(Project.id).where(Project.active.is_(True)))
        ).scalars().all()

    logger.info("Прогон (%s): проектов=%s", mode, len(project_ids))
    for pid in project_ids:
        try:
            summary = await run_project_batch(maker, settings, pid, mode=mode)
            logger.info(
                "Проект %s (%s): всего=%s успех=%s не найдено=%s ошибок=%s",
                pid, mode, summary.total, summary.success, summary.not_found, summary.failed,
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

    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    if settings.daily_check_enabled:
        hh, mm = _parse_hh_mm(settings.daily_check_time)
        scheduler.add_job(
            run_all_active_projects, kwargs={"mode": RunMode.SEO.value},
            trigger=CronTrigger(hour=hh, minute=mm, timezone=settings.timezone,
                                jitter=settings.daily_check_jitter_seconds),
            id="daily_seo", max_instances=1, coalesce=True,
        )
        logger.info("SEO-прогон: ежедневно в %02d:%02d %s", hh, mm, settings.timezone)

    if settings.battle_check_enabled:
        hh, mm = _parse_hh_mm(settings.battle_check_time)
        scheduler.add_job(
            run_all_active_projects, kwargs={"mode": RunMode.BATTLE.value},
            trigger=CronTrigger(hour=hh, minute=mm, timezone=settings.timezone,
                                jitter=settings.daily_check_jitter_seconds),
            id="daily_battle", max_instances=1, coalesce=True,
        )
        logger.info("Боевой прогон: ежедневно в %02d:%02d %s", hh, mm, settings.timezone)

    if not scheduler.get_jobs():
        logger.warning("Все автопрогоны выключены. Ожидание.")
        await asyncio.Event().wait()
        return

    scheduler.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
