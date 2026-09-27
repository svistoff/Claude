"""Загрузка и валидация конфигурации из .env"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# .env лежит рядом с этим файлом (companion_bot/.env), независимо от текущей
# рабочей директории
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


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return float(val)


@dataclass(frozen=True)
class Config:
    bot_token: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    db_path: str
    log_level: str

    # Дневной бесплатный лимит + донат за продление
    free_messages_per_day: int
    donate_stars_price: int
    donate_bonus_messages: int
    history_limit: int

    # "Занятость" — иногда персонаж отвечает не сразу, а с задержкой
    busy_probability: float
    busy_delay_min_minutes: float
    busy_delay_max_minutes: float
    priority_reply_stars_price: int
    pending_reply_poll_seconds: float

    # Долгосрочная память (сводка фактов о пользователе)
    memory_summary_every_n_messages: int

    # Проактивные сообщения персонажа ("как дела?")
    proactive_check_interval_seconds: float
    proactive_min_hours_since_last_message: float
    proactive_max_hours_since_last_message: float
    proactive_probability: float


def load_config() -> Config:
    return Config(
        bot_token=_get_str("BOT_TOKEN", required=True),
        openai_api_key=_get_str("OPENAI_API_KEY", required=True),
        openai_model=_get_str("OPENAI_MODEL", default="gpt-4o-mini"),
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        db_path=_get_str(
            "DB_PATH", default=str(Path(__file__).resolve().parent / "data" / "bot.db")
        ),
        log_level=_get_str("LOG_LEVEL", default="INFO"),
        free_messages_per_day=_get_int("FREE_MESSAGES_PER_DAY", default=15),
        donate_stars_price=_get_int("DONATE_STARS_PRICE", default=50),
        donate_bonus_messages=_get_int("DONATE_BONUS_MESSAGES", default=20),
        history_limit=_get_int("HISTORY_LIMIT", default=20),
        busy_probability=_get_float("BUSY_PROBABILITY", default=0.15),
        busy_delay_min_minutes=_get_float("BUSY_DELAY_MIN_MINUTES", default=5),
        busy_delay_max_minutes=_get_float("BUSY_DELAY_MAX_MINUTES", default=25),
        priority_reply_stars_price=_get_int("PRIORITY_REPLY_STARS_PRICE", default=30),
        pending_reply_poll_seconds=_get_float("PENDING_REPLY_POLL_SECONDS", default=20),
        memory_summary_every_n_messages=_get_int("MEMORY_SUMMARY_EVERY_N_MESSAGES", default=12),
        proactive_check_interval_seconds=_get_float(
            "PROACTIVE_CHECK_INTERVAL_SECONDS", default=3600
        ),
        proactive_min_hours_since_last_message=_get_float(
            "PROACTIVE_MIN_HOURS_SINCE_LAST_MESSAGE", default=20
        ),
        proactive_max_hours_since_last_message=_get_float(
            "PROACTIVE_MAX_HOURS_SINCE_LAST_MESSAGE", default=72
        ),
        proactive_probability=_get_float("PROACTIVE_PROBABILITY", default=0.5),
    )


config = load_config()
