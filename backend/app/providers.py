"""Каталог LLM-провайдеров и моделей (мультимодельность, раздел 43 ТЗ).

Провайдеры OpenAI-совместимые (DeepSeek, OpenAI, OpenRouter). OpenRouter одним
ключом даёт доступ к Claude/GPT/Gemini и др. Модель видна в UI, только если задан
ключ её провайдера.
"""

from __future__ import annotations

from .config import get_app_config, get_settings

# Профили провайдеров: base_url + поле ключа в Settings + доп. заголовки.
PROVIDERS: dict[str, dict] = {
    "deepseek":   {"key": "deepseek_api_key",   "base_url": None,  # из settings.deepseek_base_url
                   "headers": {}},
    "openai":     {"key": "openai_api_key",     "base_url": "https://api.openai.com/v1",
                   "headers": {}},
    "openrouter": {"key": "openrouter_api_key", "base_url": "https://openrouter.ai/api/v1",
                   "headers": {"HTTP-Referer": "https://ai.svistoff.ru", "X-Title": "AI Coder"}},
}

# Встроенный каталог. Модель появляется в переключателе, если задан ключ провайдера.
DEFAULT_CATALOG: list[dict] = [
    {"id": "deepseek-flash",  "provider": "deepseek",   "label": "DeepSeek Flash"},
    {"id": "deepseek-v4-pro", "provider": "deepseek",   "label": "DeepSeek V4 Pro"},
    {"id": "gpt-5",           "provider": "openai",     "label": "GPT-5"},
    {"id": "gpt-5-mini",      "provider": "openai",     "label": "GPT-5 mini"},
    {"id": "anthropic/claude-sonnet-5-5", "provider": "openrouter", "label": "Claude Sonnet 5.5"},
    {"id": "anthropic/claude-opus-5-5",   "provider": "openrouter", "label": "Claude Opus 5.5"},
    {"id": "google/gemini-2.5-pro",       "provider": "openrouter", "label": "Gemini 2.5 Pro"},
]


def catalog() -> list[dict]:
    cfg_models = get_app_config().llm.models
    return cfg_models if cfg_models else DEFAULT_CATALOG


def _key_for(provider: str) -> str:
    prof = PROVIDERS.get(provider)
    if not prof:
        return ""
    return getattr(get_settings(), prof["key"], "") or ""


def available_models() -> list[dict]:
    """Модели, у провайдеров которых задан ключ."""
    out = [m for m in catalog() if _key_for(m.get("provider", "deepseek"))]
    return out


def available_model_ids() -> list[str]:
    return [m["id"] for m in available_models()]


def label_for(model_id: str) -> str:
    for m in catalog():
        if m["id"] == model_id:
            return m.get("label", model_id)
    return model_id


def resolve(model_id: str) -> dict | None:
    """Вернуть параметры подключения для модели, либо None."""
    settings = get_settings()
    entry = next((m for m in catalog() if m["id"] == model_id), None)
    provider = (entry or {}).get("provider", "deepseek")
    prof = PROVIDERS.get(provider)
    if prof is None:
        return None
    key = _key_for(provider)
    if not key:
        return None
    base_url = prof["base_url"] or settings.deepseek_base_url
    return {"provider": provider, "model": model_id, "api_key": key,
            "base_url": base_url, "headers": dict(prof.get("headers", {}))}
