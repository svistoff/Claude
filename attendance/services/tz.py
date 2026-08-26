"""Хелперы часового пояса. В БД всё хранится в UTC (ISO-строки), в панели —
в часовом поясе из настроек (по умолчанию Asia/Yekaterinburg, см. ТЗ п.28)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def to_local(value: datetime | None, tz_name: str) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(ZoneInfo(tz_name))


def format_local_time(value: str | None, tz_name: str) -> str:
    dt = parse_utc(value)
    if dt is None:
        return "—"
    return to_local(dt, tz_name).strftime("%H:%M")


def format_local_datetime(value: str | None, tz_name: str) -> str:
    dt = parse_utc(value)
    if dt is None:
        return "—"
    return to_local(dt, tz_name).strftime("%d.%m.%Y %H:%M")


def format_local_date(value: str | None, tz_name: str) -> str:
    dt = parse_utc(value)
    if dt is None:
        return "—"
    return to_local(dt, tz_name).strftime("%d.%m.%Y")


def format_duration(seconds: float) -> str:
    total_minutes = int(seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours} ч {minutes:02d} мин"
