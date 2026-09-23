"""Загрузка и валидация конфигурации из .env"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# .env лежит рядом с этим файлом (randomgiveaway/.env), независимо от cwd
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
    db_path: str
    host: str
    port: int
    log_level: str
    # Простая защита административных/мутирующих ручек без полноценной
    # регистрации пользователей (см. §17 ТЗ: для MVP допустима замена
    # полноценной auth простой авторизацией администратора).
    admin_token: str | None
    # Плейсхолдеры под Этап 4 (см. randomgiveaway/adapters/*).
    # На Этапе 1 не используются — источники живые не реализованы.
    instagram_access_token: str | None
    vk_community_token: str | None
    telegram_session: str | None


def load_config() -> Config:
    return Config(
        db_path=_get_str(
            "DB_PATH", default=str(Path(__file__).resolve().parent / "data" / "randomgiveaway.db")
        ),
        host=_get_str("HOST", default="127.0.0.1"),
        port=_get_int("PORT", default=8001),
        log_level=_get_str("LOG_LEVEL", default="INFO"),
        admin_token=os.getenv("ADMIN_TOKEN") or None,
        instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN") or None,
        vk_community_token=os.getenv("VK_COMMUNITY_TOKEN") or None,
        telegram_session=os.getenv("TELEGRAM_SESSION") or None,
    )


config = load_config()
