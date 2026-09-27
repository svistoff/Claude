"""Общие вспомогательные функции для работы со временем.

Единый формат — совпадает с выводом SQLite `datetime('now')` (UTC,
'YYYY-MM-DD HH:MM:SS', без буквы 'T' и без смещения часового пояса), чтобы
сравнение таких строк в SQL совпадало с хронологическим порядком.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_FMT = "%Y-%m-%d %H:%M:%S"


def now_str() -> str:
    return datetime.now(timezone.utc).strftime(_FMT)


def now_str_plus_minutes(minutes: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime(_FMT)


def hours_ago_str(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(_FMT)
