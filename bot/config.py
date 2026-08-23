"""Загрузка и валидация конфигурации из .env"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# .env лежит рядом с этим файлом (bot/.env), независимо от текущей рабочей директории
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int | None = None, required: bool = False) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        if required:
            raise RuntimeError(f"Переменная окружения {name} обязательна")
        return default  # type: ignore[return-value]
    return int(val)


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
    target_channel_id: str  # ID (например -100123..) либо @username
    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    db_path: str
    duplicate_protection: bool
    album_window_seconds: float
    max_attempts: int
    retry_delays_seconds: tuple[int, ...]
    poll_interval_seconds: float
    log_level: str


def load_config() -> Config:
    return Config(
        bot_token=_get_str("BOT_TOKEN", required=True),
        allowed_user_ids=_get_int_list("ALLOWED_USER_ID", required=True),
        target_channel_id=_get_str("TARGET_CHANNEL_ID", required=True),
        openai_api_key=_get_str("OPENAI_API_KEY", required=True),
        openai_model=_get_str("OPENAI_MODEL", default="gpt-4o-mini"),
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        db_path=_get_str("DB_PATH", default=str(Path(__file__).resolve().parent / "data" / "bot.db")),
        duplicate_protection=_get_bool("DUPLICATE_PROTECTION", default=False),
        album_window_seconds=float(_get_str("ALBUM_WINDOW_SECONDS", default="1.5")),
        max_attempts=_get_int("MAX_ATTEMPTS", default=3),
        retry_delays_seconds=(30, 120, 600),
        poll_interval_seconds=float(_get_str("POLL_INTERVAL_SECONDS", default="2")),
        log_level=_get_str("LOG_LEVEL", default="INFO"),
    )


config = load_config()
