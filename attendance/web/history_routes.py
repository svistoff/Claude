from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request

from attendance.database import repository as repo
from attendance.services import settings_service, tz as tz_service
from attendance.web.deps import require_login, templates

router = APIRouter()


def _period_bounds(period: str, date_from: str | None, date_to: str | None, tz_name: str):
    tzinfo = ZoneInfo(tz_name)
    today = datetime.now(tzinfo).date()

    if period == "yesterday":
        start = today - timedelta(days=1)
        end = today
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        end = today + timedelta(days=1)
    elif period == "month":
        start = today.replace(day=1)
        end = today + timedelta(days=1)
    elif period == "custom" and date_from and date_to:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to) + timedelta(days=1)
    else:
        period = "today"
        start = today
        end = today + timedelta(days=1)

    start_dt = datetime.combine(start, time.min, tzinfo=tzinfo).astimezone(ZoneInfo("UTC"))
    end_dt = datetime.combine(end, time.min, tzinfo=tzinfo).astimezone(ZoneInfo("UTC"))
    return period, start, end, start_dt, end_dt


@router.get("/history")
async def history(
    request: Request,
    period: str = "today",
    date_from: str | None = None,
    date_to: str | None = None,
    employee_id: int | None = None,
    status: str | None = None,
    username: str = Depends(require_login),
):
    settings = await settings_service.get_settings()
    tz_name = settings.timezone

    period, start_date, end_date, start_dt, end_dt = _period_bounds(
        period, date_from, date_to, tz_name
    )

    sessions = await repo.list_sessions_in_period(start_dt, end_dt, employee_id=employee_id)
    if status:
        sessions = [s for s in sessions if s.status == status]

    employees = await repo.list_employees(include_inactive=True)
    employees_by_id = {e.id: e for e in employees}

    rows = []
    durations = []
    arrival_times = []
    departure_times = []
    for s in sessions:
        employee = employees_by_id.get(s.employee_id)
        started = tz_service.parse_utc(s.started_at)
        ended = tz_service.parse_utc(s.ended_at) if s.ended_at else None
        duration_seconds = (ended - started).total_seconds() if ended else None
        if duration_seconds is not None:
            durations.append(duration_seconds)
        arrival_times.append(started)
        if ended:
            departure_times.append(ended)
        rows.append(
            {
                "date": tz_service.format_local_date(s.started_at, tz_name),
                "employee_name": employee.name if employee else f"#{s.employee_id}",
                "started": tz_service.format_local_time(s.started_at, tz_name),
                "ended": tz_service.format_local_time(s.ended_at, tz_name) if s.ended_at else "—",
                "duration": tz_service.format_duration(duration_seconds) if duration_seconds else "—",
                "status": "🟢 На работе" if s.status == "active" else "🔴 Завершено",
            }
        )

    summary = {
        "work_days": len({r["date"] for r in rows}),
        "sessions_count": len(rows),
        "total_duration": tz_service.format_duration(sum(durations)) if durations else "—",
        "avg_arrival": _average_time_of_day(arrival_times, tz_name),
        "avg_departure": _average_time_of_day(departure_times, tz_name),
    }

    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "username": username,
            "rows": rows,
            "summary": summary,
            "employees": employees,
            "period": period,
            "date_from": start_date.isoformat(),
            "date_to": (end_date - timedelta(days=1)).isoformat(),
            "selected_employee_id": employee_id,
            "selected_status": status,
        },
    )


def _average_time_of_day(moments: list[datetime], tz_name: str) -> str:
    if not moments:
        return "—"
    tzinfo = ZoneInfo(tz_name)
    total_seconds = 0
    for m in moments:
        local = m.astimezone(tzinfo)
        total_seconds += local.hour * 3600 + local.minute * 60 + local.second
    avg_seconds = total_seconds // len(moments)
    hours, remainder = divmod(avg_seconds, 3600)
    minutes = remainder // 60
    return f"{hours:02d}:{minutes:02d}"
