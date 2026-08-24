"""Загрузка и валидация конфигурации из .env"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# .env лежит рядом с этим файлом (bot/.env), независимо от текущей рабочей директории
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


def _get_int(name: str, default: int | None = None, required: bool = False) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        if required:
            raise RuntimeError(f"Переменная окружения {name} обязательна")
        return default  # type: ignore[return-value]
    return int(val)


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val and val.strip() else default


def _get_str(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        if required:
            raise RuntimeError(f"Переменная окружения {name} обязательна")
        return default  # type: ignore[return-value]
    return val


def _get_int_list(name: str, required: bool = False) -> tuple[int, ...]:
    """Парсит один ID или несколько через запятую: '123' или '123,456,789'."""
    val = os.getenv(name)
    if val is None or val.strip() == "":
        if required:
            raise RuntimeError(f"Переменная окружения {name} обязательна")
        return ()
    try:
        return tuple(int(part.strip()) for part in val.split(",") if part.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"Переменная окружения {name} должна содержать числовые Telegram ID через запятую, получено: {val!r}"
        ) from exc


@dataclass(frozen=True)
class Config:
    bot_token: str
    allowed_user_ids: tuple[int, ...]
    storage_channel_id: str  # приватный канал-хранилище видео, -100...

    openai_api_key: str
    openai_model: str

    supabase_url: str
    supabase_service_key: str
    media_base_url: str

    video_public_base: str
    video_proxy_port: int
    max_video_mb: int
    event_grace_days: int
    fallback_ttl_days: int

    admin_url: str
    album_window_seconds: float
    max_concurrent_submissions: int
    tz_offset_hours: int
    log_level: str


def _parse_tz_offset(raw: str) -> int:
    # ожидаем формат '+05:00' / '-03:00'
    sign = -1 if raw.strip().startswith("-") else 1
    hours = raw.strip().lstrip("+-").split(":")[0]
    return sign * int(hours)


def load_config() -> Config:
    return Config(
        bot_token=_get_str("TELEGRAM_BOT_TOKEN", required=True),
        allowed_user_ids=_get_int_list("ALLOWED_USER_ID", required=True),
        storage_channel_id=_get_str("TELEGRAM_STORAGE_CHANNEL_ID", required=True),
        openai_api_key=_get_str("OPENAI_API_KEY", required=True),
        openai_model=_get_str("OPENAI_MODEL", default="gpt-4o-mini"),
        supabase_url=_get_str("SUPABASE_URL", required=True).rstrip("/"),
        supabase_service_key=_get_str("SUPABASE_SERVICE_KEY", required=True),
        media_base_url=_get_str("MEDIA_BASE_URL", required=True).rstrip("/"),
        video_public_base=_get_str("VIDEO_PUBLIC_BASE", required=True).rstrip("/"),
        video_proxy_port=_get_int("VIDEO_PROXY_PORT", default=8092),
        max_video_mb=_get_int("MAX_VIDEO_MB", default=20),
        event_grace_days=_get_int("EVENT_GRACE_DAYS", default=3),
        fallback_ttl_days=_get_int("FALLBACK_TTL_DAYS", default=30),
        admin_url=_get_str("ADMIN_URL", default="https://afisha.ekb-guide.ru/admin.html"),
        album_window_seconds=_get_float("ALBUM_WINDOW_SECONDS", default=3.0),
        max_concurrent_submissions=_get_int("MAX_CONCURRENT_SUBMISSIONS", default=3),
        tz_offset_hours=_parse_tz_offset(_get_str("TZ_OFFSET", default="+05:00")),
        log_level=_get_str("LOG_LEVEL", default="INFO"),
    )


config = load_config()
