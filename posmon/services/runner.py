"""Оркестрация пакетного прогона проверок.

Прогоняет все активные запросы × активные профили проекта с ограничением
параллелизма (пул воркеров) и retry при временных ошибках (разделы 12-13, 33, 35
ТЗ). Каждая пара обрабатывается в своей сессии БД; ошибка одной пары не
останавливает остальные (раздел 35).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..config import Settings
from ..domain.results import CheckStatus
from ..models import CheckRun, Profile, Project, Query, Site
from ..providers.base import SearchProvider
from .collector import run_query_check
from .providers import build_provider

logger = logging.getLogger("posmon.runner")

DEFAULT_RETRY_DELAYS: tuple[int, ...] = (30, 120, 600)

ProviderFactory = Callable[[Profile, Settings], SearchProvider]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass
class BatchSummary:
    total: int = 0
    success: int = 0
    not_found: int = 0
    failed: int = 0
    run_ids: list[int] = field(default_factory=list)

    def register(self, status: str, run_id: int | None) -> None:
        self.total += 1
        if run_id is not None:
            self.run_ids.append(run_id)
        if status == CheckStatus.SUCCESS.value:
            self.success += 1
        elif status == CheckStatus.NOT_FOUND.value:
            self.not_found += 1
        else:
            self.failed += 1


async def run_project_batch(
    maker: async_sessionmaker,
    settings: Settings,
    project_id: int,
    *,
    provider_factory: ProviderFactory = build_provider,
    retry_delays: tuple[int, ...] = DEFAULT_RETRY_DELAYS,
    sleeper: Sleeper = asyncio.sleep,
) -> BatchSummary:
    """Прогнать все активные запросы × профили проекта."""
    async with maker() as s:
        project = await s.get(Project, project_id)
        if project is None or not project.active:
            return BatchSummary()
        depth = project.depth
        query_ids = (
            await s.execute(
                select(Query.id).where(Query.project_id == project_id, Query.active.is_(True))
            )
        ).scalars().all()
        profile_ids = (
            await s.execute(
                select(Profile.id).where(Profile.project_id == project_id, Profile.active.is_(True))
            )
        ).scalars().all()

    summary = BatchSummary()
    if not query_ids or not profile_ids:
        return summary

    sem = asyncio.Semaphore(max(1, settings.workers))
    lock = asyncio.Lock()

    async def worker(query_id: int, profile_id: int) -> None:
        async with sem:
            status, run_id = await _run_pair_with_retry(
                maker, settings, project_id, query_id, profile_id, depth,
                provider_factory=provider_factory, retry_delays=retry_delays, sleeper=sleeper,
            )
        async with lock:
            summary.register(status, run_id)

    tasks = [
        asyncio.create_task(worker(q, p))
        for q in query_ids
        for p in profile_ids
    ]
    await asyncio.gather(*tasks)
    return summary


async def _run_pair_with_retry(
    maker: async_sessionmaker,
    settings: Settings,
    project_id: int,
    query_id: int,
    profile_id: int,
    depth: int,
    *,
    provider_factory: ProviderFactory,
    retry_delays: tuple[int, ...],
    sleeper: Sleeper,
) -> tuple[str, int | None]:
    """Обработать одну пару (запрос × профиль) с повторами при ошибке."""
    async with maker() as s:
        query = await s.get(Query, query_id)
        profile = await s.get(Profile, profile_id)
        if query is None or profile is None:
            return CheckStatus.ERROR.value, None
        sites = (
            await s.execute(
                select(Site).where(Site.project_id == project_id, Site.active.is_(True))
            )
        ).scalars().all()

        try:
            provider = provider_factory(profile, settings)
        except Exception as exc:  # noqa: BLE001 — провайдер не настроен -> явная ERROR-запись
            run = await _record_provider_error(s, project_id, query, profile, str(exc))
            await s.commit()
            return run.status, run.id

        last_run: CheckRun | None = None
        for attempt in range(1, settings.max_attempts + 1):
            last_run = await run_query_check(
                s, project_id=project_id, query=query, profile=profile, sites=list(sites),
                provider=provider, depth=depth, region_lr=settings.region_lr,
                timezone_name=settings.timezone, attempt=attempt,
            )
            status = CheckStatus(last_run.status)
            if status.is_confirmed:
                break
            if attempt < settings.max_attempts:
                delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
                logger.warning(
                    "Пара q=%s p=%s: %s, повтор %s/%s через %ss",
                    query_id, profile_id, last_run.status, attempt, settings.max_attempts, delay,
                )
                await sleeper(delay)

        await s.commit()
        return (last_run.status, last_run.id) if last_run else (CheckStatus.ERROR.value, None)


async def _record_provider_error(
    s, project_id: int, query: Query, profile: Profile, message: str
) -> CheckRun:
    from .collector import _now

    run = CheckRun(
        project_id=project_id,
        query_id=query.id,
        profile_id=profile.id,
        source=profile.source,
        status=CheckStatus.ERROR.value,
        started_at=_now(),
        finished_at=_now(),
        error_code="provider_unconfigured",
        error_message=message,
    )
    s.add(run)
    await s.flush()
    return run
