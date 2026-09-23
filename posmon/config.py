"""Конфигурация приложения из окружения / .env (pydantic-settings)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Приложение
    env: str = Field(default="production", alias="POSMON_ENV")
    secret_key: str = Field(default="dev-insecure-secret-change-me", alias="POSMON_SECRET_KEY")
    base_url: str = Field(default="https://stat.xmassage.vip", alias="POSMON_BASE_URL")
    timezone: str = Field(default="Asia/Yekaterinburg", alias="POSMON_TIMEZONE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # БД
    database_url: str = Field(
        default="sqlite+aiosqlite:///./posmon.db", alias="DATABASE_URL"
    )

    # Первичный админ
    admin_login: str = Field(default="admin", alias="POSMON_ADMIN_LOGIN")
    admin_password: str = Field(default="change-me", alias="POSMON_ADMIN_PASSWORD")

    # Сбор: регион и глубина
    region_lr: int = Field(default=54, alias="YANDEX_REGION_LR")
    default_depth: int = Field(default=50, alias="DEFAULT_DEPTH")

    # Yandex Search API
    yandex_api_folder_id: str = Field(default="", alias="YANDEX_API_FOLDER_ID")
    yandex_api_key: str = Field(default="", alias="YANDEX_API_KEY")
    yandex_api_endpoint: str = Field(default="", alias="YANDEX_API_ENDPOINT")

    # Капча
    captcha_provider: str = Field(default="", alias="CAPTCHA_PROVIDER")
    captcha_api_key: str = Field(default="", alias="CAPTCHA_API_KEY")

    # Прокси
    browser_proxy: str = Field(default="", alias="BROWSER_PROXY")

    # Планировщик и воркеры
    daily_check_enabled: bool = Field(default=True, alias="DAILY_CHECK_ENABLED")
    daily_check_time: str = Field(default="02:00", alias="DAILY_CHECK_TIME")
    daily_check_jitter_seconds: int = Field(default=900, alias="DAILY_CHECK_JITTER_SECONDS")
    workers: int = Field(default=3, alias="WORKERS")
    max_attempts: int = Field(default=3, alias="MAX_ATTEMPTS")

    @property
    def yandex_api_configured(self) -> bool:
        return bool(self.yandex_api_folder_id and self.yandex_api_key)

    @property
    def captcha_configured(self) -> bool:
        return bool(self.captcha_provider and self.captcha_api_key)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
