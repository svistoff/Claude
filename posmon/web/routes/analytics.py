"""Аналитика: страница запроса (график истории) и страница сайта (метрики)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...domain.results import RunMode
from ...models import Profile, Project, Query, Site, User
from ...services.analytics import heatmap_matrix, history_series, site_metrics
from ..charts import SERIES_COLORS, ChartOptions, Series, line_chart
from ..deps import current_user, redirect, render

router = APIRouter()


@router.get("/queries/{query_id}")
async def query_page(
    query_id: int,
    request: Request,
    site: int | None = None,
    mode: str = RunMode.SEO.value,
    days: int = 30,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    q = await session.get(Query, query_id)
    if q is None:
        return redirect("/projects")

    sites = (await session.execute(
        select(Site).where(Site.project_id == q.project_id, Site.active.is_(True)).order_by(Site.name)
    )).scalars().all()
    profiles = (await session.execute(
        select(Profile).where(Profile.project_id == q.project_id, Profile.active.is_(True)).order_by(Profile.id)
    )).scalars().all()

    site_id = site or (sites[0].id if sites else None)
    field = "visual_position" if mode == RunMode.BATTLE.value else "position"

    chart_svg = ""
    today_positions = []
    if site_id is not None:
        hist = await history_series(session, query_id=query_id, site_id=site_id, mode=mode, days=days, field=field)
        series = []
        for i, p in enumerate(profiles):
            rows = hist.get(p.id, [])
            if rows:
                series.append(Series(label=p.name, points=rows, color=SERIES_COLORS[i % len(SERIES_COLORS)]))
                today_positions.append({"profile": p.name, "value": rows[-1][1]})
        project = await session.get(Project, q.project_id)
        depth = project.depth if project else 50
        chart_svg = line_chart(series, ChartOptions(y_max=depth))

    return render(
        request, "query.html", user=user, query=q, sites=sites, profiles=profiles,
        site_id=site_id, mode=mode, days=days, chart_svg=chart_svg,
        today_positions=today_positions,
    )


@router.get("/sites/{site_id}")
async def site_page(
    site_id: int,
    request: Request,
    profile: int | None = None,
    mode: str = RunMode.SEO.value,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    s = await session.get(Site, site_id)
    if s is None:
        return redirect("/projects")

    profiles = (await session.execute(
        select(Profile).where(Profile.project_id == s.project_id, Profile.active.is_(True)).order_by(Profile.id)
    )).scalars().all()
    profile_id = profile or (profiles[0].id if profiles else None)

    metrics = None
    hm_dates: list = []
    hm_queries: list = []
    hm_matrix: dict = {}
    if profile_id is not None:
        metrics = (await site_metrics(session, site_id=site_id, profile_id=profile_id, mode=mode)).as_dict()
        hm_dates, hm_queries, hm_matrix = await heatmap_matrix(
            session, site_id=site_id, profile_id=profile_id, mode=mode, days=14
        )

    return render(
        request, "site.html", user=user, site=s, profiles=profiles,
        profile_id=profile_id, mode=mode, metrics=metrics,
        hm_dates=hm_dates, hm_queries=hm_queries, hm_matrix=hm_matrix,
    )
