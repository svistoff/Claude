"""Сбор одной выборки выдачи и расчёт позиций всех сайтов проекта.

Единица работы — выборка выдачи (запрос × профиль). По одной скачанной выдаче
матчатся ВСЕ активные сайты проекта, без повторных запросов к Яндексу
(раздел 2 ТЗ v2).

Гарантии (разделы 14, 36 ТЗ):
- при статусе ERROR/BLOCKED/CAPTCHA позиция НЕ записывается;
- полная выдача сохраняется всегда, когда она получена.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.position import match_site
from ..domain.results import CheckStatus
from ..models import Check, CheckRun, PositionHistory, Profile, Query, SearchResult, Site
from ..providers.base import SearchProvider, SearchRequest


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _local_date(tz_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:  # noqa: BLE001 — некорректная TZ не должна ронять сбор
        return datetime.now(timezone.utc).date()


async def run_query_check(
    session: AsyncSession,
    *,
    project_id: int,
    query: Query,
    profile: Profile,
    sites: list[Site],
    provider: SearchProvider,
    depth: int,
    region_lr: int,
    timezone_name: str = "Asia/Yekaterinburg",
    attempt: int = 1,
) -> CheckRun:
    """Выполнить одну выборку выдачи и записать позиции сайтов.

    Возвращает сохранённый :class:`CheckRun` с проставленным статусом.
    """
    run = CheckRun(
        project_id=project_id,
        query_id=query.id,
        profile_id=profile.id,
        source=getattr(provider, "source", "unknown"),
        status=CheckStatus.RUNNING.value,
        started_at=_now(),
        attempt=attempt,
    )
    session.add(run)
    await session.flush()

    request = SearchRequest(
        query=query.query,
        region_lr=region_lr,
        device=profile.device,
        depth=depth,
    )
    fetch = await provider.fetch(request)

    run.finished_at = _now()
    run.duration_ms = fetch.duration_ms
    run.search_url = fetch.search_url
    run.parser_version = fetch.parser_version
    run.error_code = fetch.error_code
    run.error_message = fetch.error_message
    run.raw_html_path = None  # запись HTML на диск — отдельный опциональный шаг

    # Техническая ошибка/блокировка/капча — позиция НЕ записывается.
    if not fetch.ok:
        run.status = fetch.status.value
        profile.last_checked_at = _now()
        await session.flush()
        return run

    # Успешная выдача: сохраняем полный список результатов.
    for r in fetch.results:
        session.add(
            SearchResult(
                check_run_id=run.id,
                position=r.raw_position or 0,
                url=r.url,
                domain=r.host,
                title=r.title,
                snippet=r.snippet,
                result_type=r.result_type.value,
            )
        )

    run.status = fetch.status.value  # SUCCESS или NOT_FOUND (пустая выдача)
    today = _local_date(timezone_name)
    checked_at = _now()

    for site in sites:
        if not site.active:
            continue
        matched = match_site(
            fetch.results,
            site.domain,
            site.match_mode,
            with_business=query.is_local,
        )
        site_status = CheckStatus.SUCCESS if matched.found else CheckStatus.NOT_FOUND
        session.add(
            Check(
                check_run_id=run.id,
                project_id=project_id,
                query_id=query.id,
                site_id=site.id,
                profile_id=profile.id,
                checked_at=checked_at,
                position=matched.position,
                business_position=matched.business_position,
                status=site_status.value,
            )
        )
        await _upsert_history(
            session,
            project_id=project_id,
            query_id=query.id,
            site_id=site.id,
            profile_id=profile.id,
            day=today,
            position=matched.position,
            business_position=matched.business_position,
            status=site_status,
        )

    profile.last_checked_at = checked_at
    await session.flush()
    return run


async def _upsert_history(
    session: AsyncSession,
    *,
    project_id: int,
    query_id: int,
    site_id: int,
    profile_id: int,
    day: date,
    position: int | None,
    business_position: int | None,
    status: CheckStatus,
) -> None:
    """Обновить/создать дневную запись истории позиции.

    Одна запись на (запрос × сайт × профиль × дата): последняя проверка за день
    перезаписывает значение. История прошлых дней не трогается (раздел 49 ТЗ).
    """
    existing = (
        await session.execute(
            select(PositionHistory).where(
                PositionHistory.query_id == query_id,
                PositionHistory.site_id == site_id,
                PositionHistory.profile_id == profile_id,
                PositionHistory.date == day,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        session.add(
            PositionHistory(
                project_id=project_id,
                query_id=query_id,
                site_id=site_id,
                profile_id=profile_id,
                date=day,
                position=position,
                business_position=business_position,
                status=status.value,
            )
        )
    else:
        existing.position = position
        existing.business_position = business_position
        existing.status = status.value
