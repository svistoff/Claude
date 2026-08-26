"""Загрузка конфигурации из .env.

Секреты и параметры первого запуска (админ, SECRET_KEY, начальные значения
поллинга/таймаута/роутера) читаются отсюда. После первого старта поллинг,
таймаут и параметры роутера хранятся в таблице app_settings и редактируются
через веб-панель (см. attendance/services/settings_service.py) — .env для них
используется только как значение по умолчанию при самом первом запуске.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


def _get_str(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        if required:
            raise RuntimeError(f"Переменная окружения {name} обязательна")
        return default  # type: ignore[return-value]
    return val


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return int(val)


@dataclass(frozen=True)
class Config:
    secret_key: str
    admin_username: str
    admin_password: str
    db_path: str
    session_max_age_seconds: int
    log_level: str

    # Значения по умолчанию для первого запуска (далее живут в app_settings)
    default_poll_interval_seconds: int
    default_absence_timeout_minutes: int
    default_long_absence_hint_hours: int
    default_router_adapter: str  # "xiaomi" | "fake"
    default_router_base_url: str
    default_router_username: str
    default_router_password: str
    default_timezone: str


def load_config() -> Config:
    return Config(
        secret_key=_get_str("SECRET_KEY", required=True),
        admin_username=_get_str("ADMIN_USERNAME", default="admin"),
        admin_password=_get_str("ADMIN_PASSWORD", required=True),
        db_path=_get_str(
            "DB_PATH", default=str(Path(__file__).resolve().parent / "data" / "attendance.db")
        ),
        session_max_age_seconds=_get_int("SESSION_MAX_AGE_SECONDS", default=60 * 60 * 12),
        log_level=_get_str("LOG_LEVEL", default="INFO"),
        default_poll_interval_seconds=_get_int("POLL_INTERVAL", default=60),
        default_absence_timeout_minutes=_get_int("ABSENCE_TIMEOUT_MINUTES", default=20),
        default_long_absence_hint_hours=_get_int("LONG_ABSENCE_HINT_HOURS", default=3),
        default_router_adapter=_get_str("ROUTER_ADAPTER", default="fake"),
        default_router_base_url=_get_str("ROUTER_BASE_URL", default="http://192.168.31.1"),
        default_router_username=_get_str("ROUTER_USERNAME", default="admin"),
        default_router_password=_get_str("ROUTER_PASSWORD", default=""),
        default_timezone=_get_str("TIMEZONE", default="Asia/Yekaterinburg"),
    )


config = load_config()
