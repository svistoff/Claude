"""Рантайм-настройки: выбранная LLM-модель (переключается в UI, хранится в БД).

Приоритет: значение из БД (выбор пользователя) → config.llm.model (env/yaml).
Переключение не требует правки .env и перезапуска.
"""

from __future__ import annotations

from .config import get_app_config
from .database import repo

_MODEL_KEY = "llm_model"


def available_models() -> list[str]:
    cfg = get_app_config().llm
    models = list(cfg.available_models)
    # Гарантируем, что текущая модель из конфига тоже есть в списке.
    if cfg.model and cfg.model not in models:
        models.insert(0, cfg.model)
    return models


def current_model() -> str:
    override = repo.get_setting(_MODEL_KEY)
    if override and override in available_models():
        return override
    return get_app_config().llm.model


def set_model(name: str) -> str:
    if name not in available_models():
        raise ValueError(f"Модель '{name}' недоступна. Доступны: {available_models()}")
    repo.set_setting(_MODEL_KEY, name)
    return name
