"""Загрузка конфигурации: секреты из окружения (.env), остальное — из config.yaml.

Единая точка доступа к настройкам. Секреты (API-ключ, хэш пароля, SECRET_KEY)
приходят ТОЛЬКО из переменных окружения и никогда не попадают в config.yaml,
логи или ответы пользователю.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень backend/ (эта папка -> app/ -> backend/).
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Секретные/окруженческие настройки из .env."""

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", str(BACKEND_DIR.parent / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    # Auth
    admin_user: str = "admin"
    admin_password_hash: str = ""
    secret_key: str = ""
    session_max_age: int = 43200
    cookie_secure: bool = True

    # Пути
    database_url: str = "sqlite:///./data/agent.db"
    config_path: str = "./config.yaml"
    workspace_tmp: str = "./data/tmp"


class ProjectConfig(BaseModel):
    name: str
    path: str


class LLMConfig(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-flash"
    # Модели, доступные для переключения в UI (раздел 43 ТЗ).
    available_models: list[str] = ["deepseek-flash", "deepseek-v4-pro"]
    temperature: float = 0.2
    max_tokens: int = 4096
    request_timeout: int = 120


class PricingConfig(BaseModel):
    currency: str = "USD"
    per_million_tokens: dict[str, float] = {}


class AgentConfig(BaseModel):
    max_iterations: int = 30
    terminal_timeout_default: int = 60
    terminal_timeout_max: int = 300
    max_read_bytes: int = 200000
    max_search_results: int = 100


class TerminalPolicy(BaseModel):
    blocked: list[str] = []
    confirm: list[str] = []


class AppConfig(BaseModel):
    """Несекретная конфигурация из config.yaml."""

    llm: LLMConfig = LLMConfig()
    pricing: PricingConfig = PricingConfig()
    agent: AgentConfig = AgentConfig()
    projects: list[ProjectConfig] = []
    # Родительская папка, внутри которой агент может создавать новые проекты
    # (кнопка «+ Новый проект»). None — создание новых проектов отключено.
    workspace: str | None = None
    secret_patterns: list[str] = []
    terminal_policy: TerminalPolicy = TerminalPolicy()


def _resolve_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (BACKEND_DIR / path)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_app_config() -> AppConfig:
    settings = get_settings()
    cfg_path = _resolve_path(settings.config_path)
    # Рабочий config.yaml (в git не хранится) имеет приоритет; при его отсутствии
    # используем config.example.yaml (шаблон в репозитории, для dev/тестов).
    if not cfg_path.exists():
        example = _resolve_path("config.example.yaml")
        if example.exists():
            cfg_path = example
    data: dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    config = AppConfig(**data)

    # Переменная окружения DEEPSEEK_MODEL переопределяет модель из yaml,
    # чтобы модель не была захардкожена в нескольких местах.
    if settings.deepseek_model:
        config.llm.model = settings.deepseek_model
    return config


def get_project_map() -> dict[str, Path]:
    """name -> абсолютный, нормализованный root проекта."""
    result: dict[str, Path] = {}
    for proj in get_app_config().projects:
        result[proj.name] = Path(proj.path).resolve()
    return result
