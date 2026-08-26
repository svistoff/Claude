from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request

from attendance.database import repository as repo
from attendance.services import settings_service, tz as tz_service
from attendance.services.status import STATUS_LEFT, STATUS_NOT_ARRIVED, compute_status
from attendance.web.deps import require_login, templates

router = APIRouter()


async def _employee_status_for_today(employee, tz_name: str):
    device = await repo.get_device_by_employee(employee.id)
    latest = await repo.get_latest_session(employee.id)

    if latest is not None and latest.status == "completed":
        started_local = tz_service.to_local(tz_service.parse_utc(latest.started_at), tz_name)
        today_local = datetime.now(ZoneInfo(tz_name)).date()
        if started_local.date() != today_local:
            latest = None  # последняя сессия была не сегодня — сегодня ещё не приходил

    return compute_status(employee, device, latest)


@router.get("/dashboard")
async def dashboard(request: Request, username: str = Depends(require_login)):
    settings = await settings_service.get_settings()
    tz_name = settings.timezone

    employees = await repo.list_employees(include_inactive=False)
    statuses = [await _employee_status_for_today(e, tz_name) for e in employees]

    counts = {
        "on_work": sum(1 for s in statuses if s.status == "on_work"),
        "left": sum(1 for s in statuses if s.status == STATUS_LEFT),
        "not_arrived": sum(1 for s in statuses if s.status == STATUS_NOT_ARRIVED),
        "total": len(statuses),
    }

    router_unreachable = await repo.is_router_currently_unreachable()
    last_ok = await repo.last_successful_poll_at()
    hints = await repo.list_recent_events(limit=10, event_type="possible_device_mac_changed")

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "username": username,
            "statuses": statuses,
            "counts": counts,
            "today": datetime.now(ZoneInfo(tz_name)).strftime("%d.%m.%Y"),
            "router_unreachable": router_unreachable,
            "last_ok_local": tz_service.format_local_datetime(last_ok, tz_name) if last_ok else "—",
            "hints": hints,
            "tz_name": tz_name,
            "fmt_time": lambda v: tz_service.format_local_time(v, tz_name),
        },
    )


@router.get("/")
async def index():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/dashboard")
