"""LLM-провайдеры. Абстракция: agent loop не знает про конкретный API."""

from __future__ import annotations

from ..config import get_app_config, get_settings
from .base import LLMProvider
from .deepseek import DeepSeekProvider


def get_provider() -> LLMProvider:
    """Фабрика провайдера по активной модели (мультимодельность).

    Все провайдеры OpenAI-совместимые (DeepSeek/OpenAI/OpenRouter) — один класс
    с разными base_url/ключом/заголовками.
    """
    from .. import providers
    from ..settings_store import current_model

    cfg = get_app_config()
    model = current_model()
    conn = providers.resolve(model)
    if conn is None:
        # Fallback на DeepSeek по умолчанию.
        settings = get_settings()
        conn = {"api_key": settings.deepseek_api_key, "base_url": settings.deepseek_base_url,
                "model": cfg.llm.model, "headers": {}}
    return DeepSeekProvider(
        api_key=conn["api_key"],
        base_url=conn["base_url"],
        model=conn["model"],
        temperature=cfg.llm.temperature,
        max_tokens=cfg.llm.max_tokens,
        request_timeout=cfg.llm.request_timeout,
        extra_headers=conn.get("headers"),
    )


__all__ = ["LLMProvider", "DeepSeekProvider", "get_provider"]
