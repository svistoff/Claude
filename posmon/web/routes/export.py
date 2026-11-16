"""Экспорт данных для CRM (crm.xmassage.vip).

CRM на том же сервере забирает отсюда проекты, сайты, запросы, профили и
историю позиций и хранит у себя копию — для раздела «Позиции» и отчётов
по сайтам. Доступ только с самого сервера: запрос должен прийти напрямую на
127.0.0.1 (не через nginx — у проксированных запросов есть X-Forwarded-For /
X-Real-IP). Настройки профилей (cookies и т.п.) не отдаются.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...models import PositionHistory, Profile, Project, Query, Site

router = APIRouter()

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")


def is_local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host not in LOCAL_HOSTS:
        return False
    return not any(h in request.headers for h in PROXY_HEADERS)


def _iso(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _row(obj, fields: tuple[str, ...]) -> dict:
    return {f: _iso(getattr(obj, f)) for f in fields}


PROJECT_FIELDS = ("id", "name", "description", "active", "depth", "created_at")
SITE_FIELDS = ("id", "project_id", "name", "url", "domain", "match_mode", "active", "comment", "created_at")
QUERY_FIELDS = ("id", "project_id", "query", "group_name", "priority", "active", "is_local", "comment", "created_at")
PROFILE_FIELDS = ("id", "project_id", "name", "type", "region", "device", "source", "active", "last_checked_at")
HISTORY_FIELDS = (
    "project_id", "query_id", "site_id", "profile_id", "date", "mode",
    "position", "business_position", "visual_position", "ads_above", "status",
)


@router.get("/api/export")
async def export_all(
    request: Request,
    since: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Все проекты/сайты/запросы/профили + история позиций с даты ``since``."""
    if not is_local_request(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    since_date: date | None = None
    if since:
        try:
            since_date = date.fromisoformat(since)
        except ValueError:
            return JSONResponse({"error": "bad since"}, status_code=400)

    async def all_of(model, fields):
        rows = (await session.execute(select(model).order_by(model.id))).scalars().all()
        return [_row(r, fields) for r in rows]

    hq = select(PositionHistory).order_by(PositionHistory.date, PositionHistory.id)
    if since_date is not None:
        hq = hq.where(PositionHistory.date >= since_date)
    history = [_row(r, HISTORY_FIELDS) for r in (await session.execute(hq)).scalars().all()]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": request.app.state.settings.base_url,
        "projects": await all_of(Project, PROJECT_FIELDS),
        "sites": await all_of(Site, SITE_FIELDS),
        "queries": await all_of(Query, QUERY_FIELDS),
        "profiles": await all_of(Profile, PROFILE_FIELDS),
        "history": history,
    }
