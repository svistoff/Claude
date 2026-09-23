"""Выборки для аналитики: последние позиции, история для графиков, метрики.

Читает денормализованный слой ``position_history``. Все функции — простые
асинхронные запросы, чтобы роутеры оставались тонкими.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.metrics import PositionMetrics, compute_metrics
from ..domain.results import RunMode
from ..models import PositionHistory, Query


async def latest_positions(
    session: AsyncSession, project_id: int, mode: str = RunMode.SEO.value
) -> dict[tuple[int, int, int], PositionHistory]:
    """Последняя запись истории на каждый (query_id, site_id, profile_id).

    Ключ — тройка id, значение — самая свежая по дате запись данного режима.
    """
    rows = (
        await session.execute(
            select(PositionHistory)
            .where(PositionHistory.project_id == project_id, PositionHistory.mode == mode)
            .order_by(PositionHistory.date.asc())
        )
    ).scalars().all()
    latest: dict[tuple[int, int, int], PositionHistory] = {}
    for r in rows:  # порядок по возрастанию даты -> последняя перезапишет
        latest[(r.query_id, r.site_id, r.profile_id)] = r
    return latest


async def history_series(
    session: AsyncSession,
    *,
    query_id: int,
    site_id: int,
    mode: str = RunMode.SEO.value,
    days: int = 30,
    field: str = "position",
) -> dict[int, list[tuple[date, int | None]]]:
    """История значения по дням для каждого профиля (для графика).

    ``field`` — ``position`` (органика) или ``visual_position`` (боевая).
    Возвращает {profile_id: [(дата, значение|None), ...]} по возрастанию дат.
    """
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(PositionHistory)
            .where(
                PositionHistory.query_id == query_id,
                PositionHistory.site_id == site_id,
                PositionHistory.mode == mode,
                PositionHistory.date >= since,
            )
            .order_by(PositionHistory.date.asc())
        )
    ).scalars().all()
    out: dict[int, list[tuple[date, int | None]]] = {}
    for r in rows:
        out.setdefault(r.profile_id, []).append((r.date, getattr(r, field)))
    return out


async def site_metrics(
    session: AsyncSession,
    *,
    site_id: int,
    profile_id: int,
    mode: str = RunMode.SEO.value,
) -> PositionMetrics:
    """Сводные метрики сайта: последняя позиция по каждому запросу (профиль/режим)."""
    rows = (
        await session.execute(
            select(PositionHistory)
            .where(
                PositionHistory.site_id == site_id,
                PositionHistory.profile_id == profile_id,
                PositionHistory.mode == mode,
            )
            .order_by(PositionHistory.date.asc())
        )
    ).scalars().all()
    latest_by_query: dict[int, int | None] = {}
    for r in rows:
        latest_by_query[r.query_id] = r.position
    return compute_metrics(list(latest_by_query.values()))


async def heatmap_matrix(
    session: AsyncSession,
    *,
    site_id: int,
    profile_id: int,
    mode: str = RunMode.SEO.value,
    days: int = 14,
) -> tuple[list[date], list[tuple[int, str]], dict[int, dict[date, int | None]]]:
    """Матрица для тепловой карты: строки — запросы, колонки — даты.

    Возвращает (список дат, список (query_id, текст запроса), {query_id: {дата: позиция}}).
    """
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(PositionHistory, Query.query)
            .join(Query, Query.id == PositionHistory.query_id)
            .where(
                PositionHistory.site_id == site_id,
                PositionHistory.profile_id == profile_id,
                PositionHistory.mode == mode,
                PositionHistory.date >= since,
            )
            .order_by(PositionHistory.date.asc())
        )
    ).all()

    dates = sorted({ph.date for ph, _ in rows})
    names: dict[int, str] = {}
    matrix: dict[int, dict[date, int | None]] = {}
    for ph, qtext in rows:
        names[ph.query_id] = qtext
        matrix.setdefault(ph.query_id, {})[ph.date] = ph.position
    queries = sorted(names.items(), key=lambda kv: kv[1])
    return dates, queries, matrix
