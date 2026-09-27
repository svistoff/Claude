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


@dataclass(frozen=True)
class Config:
    bot_token: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    db_path: str
    free_messages_per_day: int
    donate_stars_price: int
    donate_bonus_messages: int
    history_limit: int
    log_level: str


def load_config() -> Config:
    return Config(
        bot_token=_get_str("BOT_TOKEN", required=True),
        openai_api_key=_get_str("OPENAI_API_KEY", required=True),
        openai_model=_get_str("OPENAI_MODEL", default="gpt-4o-mini"),
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        db_path=_get_str(
            "DB_PATH", default=str(Path(__file__).resolve().parent / "data" / "bot.db")
        ),
        free_messages_per_day=_get_int("FREE_MESSAGES_PER_DAY", default=15),
        donate_stars_price=_get_int("DONATE_STARS_PRICE", default=50),
        donate_bonus_messages=_get_int("DONATE_BONUS_MESSAGES", default=20),
        history_limit=_get_int("HISTORY_LIMIT", default=20),
        log_level=_get_str("LOG_LEVEL", default="INFO"),
    )


config = load_config()
