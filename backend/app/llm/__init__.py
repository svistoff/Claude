"""LLM-провайдеры. Абстракция: agent loop не знает про конкретный API."""

from __future__ import annotations

from ..config import get_app_config, get_settings
from .base import LLMProvider
from .deepseek import DeepSeekProvider


def get_provider() -> LLMProvider:
    """Фабрика провайдера по конфигу. Добавление OpenAI/Anthropic — здесь."""
    from ..settings_store import current_model

    cfg = get_app_config()
    settings = get_settings()
    provider = cfg.llm.provider.lower()
    if provider == "deepseek":
        return DeepSeekProvider(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=current_model(),
            temperature=cfg.llm.temperature,
            max_tokens=cfg.llm.max_tokens,
            request_timeout=cfg.llm.request_timeout,
        )
    raise ValueError(f"Неизвестный LLM-провайдер: {cfg.llm.provider}")


__all__ = ["LLMProvider", "DeepSeekProvider", "get_provider"]
