"""Рантайм-настройки: выбранная LLM-модель (переключается в UI, хранится в БД).

Доступные модели берутся из каталога провайдеров (providers.py) — только те,
у чьих провайдеров задан ключ. Выбор не требует правки .env и перезапуска.
"""

from __future__ import annotations

from . import providers
from .config import get_app_config
from .database import repo

_MODEL_KEY = "llm_model"


def available_models() -> list[str]:
    ids = providers.available_model_ids()
    default = get_app_config().llm.model
    if default and default not in ids:
        ids.insert(0, default)
    return ids


def available_models_detailed() -> list[dict]:
    """[{id, label, provider}] доступных моделей — для UI."""
    detailed = providers.available_models()
    default = get_app_config().llm.model
    if default and not any(m["id"] == default for m in detailed):
        detailed.insert(0, {"id": default, "label": default, "provider": "deepseek"})
    return detailed


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
