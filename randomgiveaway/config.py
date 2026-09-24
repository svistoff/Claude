"""Загрузка и валидация конфигурации из .env"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# .env лежит рядом с этим файлом (randomgiveaway/.env), независимо от cwd
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)


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
    # Long-lived токен собственного аккаунта ekb_guide (Instagram API with
    # Instagram Login) — см. randomgiveaway/adapters/instagram_adapter.py и
    # README.md. Обновляется автоматически через
    # randomgiveaway/scripts/refresh_instagram_token.py (cron), либо разово
    # через /api/instagram/oauth/start.
    instagram_access_token: str | None
    instagram_app_id: str | None
    instagram_app_secret: str | None
    instagram_oauth_redirect_uri: str | None
    # Пользовательский access-токен VK (НЕ токен сообщества — wall.getComments
    # с групповым токеном отдаёт ошибку 27 "method is unavailable with group
    # auth", проверено вживую). Получается через /api/vk/oauth/start (см.
    # services/vk_oauth.py и README.md). При scope=offline токен не
    # истекает — отдельного автопродления по cron не требуется.
    vk_access_token: str | None
    vk_app_id: str | None
    vk_app_secret: str | None
    vk_oauth_redirect_uri: str | None
    # Плейсхолдер под Этап 4 — Telegram ещё не реализован.
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
        instagram_app_id=os.getenv("INSTAGRAM_APP_ID") or None,
        instagram_app_secret=os.getenv("INSTAGRAM_APP_SECRET") or None,
        instagram_oauth_redirect_uri=os.getenv("INSTAGRAM_OAUTH_REDIRECT_URI") or None,
        vk_access_token=os.getenv("VK_ACCESS_TOKEN") or None,
        vk_app_id=os.getenv("VK_APP_ID") or None,
        vk_app_secret=os.getenv("VK_APP_SECRET") or None,
        vk_oauth_redirect_uri=os.getenv("VK_OAUTH_REDIRECT_URI") or None,
        telegram_session=os.getenv("TELEGRAM_SESSION") or None,
    )


config = load_config()
