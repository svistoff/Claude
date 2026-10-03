"""Тесты каталога провайдеров: фильтрация моделей по наличию ключа."""

from __future__ import annotations

from app import providers
from app.config import get_settings


def test_deepseek_models_available_with_key():
    # В conftest задан DEEPSEEK_API_KEY → модели DeepSeek доступны.
    ids = providers.available_model_ids()
    assert "deepseek-flash" in ids
    assert "deepseek-v4-pro" in ids


def test_models_without_key_are_hidden():
    settings = get_settings()
    # Без ключей OpenAI/OpenRouter их модели не показываются.
    assert not settings.openai_api_key
    assert not settings.openrouter_api_key
    ids = providers.available_model_ids()
    assert "gpt-5" not in ids
    assert "anthropic/claude-opus-5-5" not in ids


def test_resolve_deepseek_connection():
    conn = providers.resolve("deepseek-flash")
    assert conn is not None
    assert conn["provider"] == "deepseek"
    assert conn["model"] == "deepseek-flash"
    assert conn["api_key"]
    assert conn["base_url"]  # из settings.deepseek_base_url


def test_resolve_hidden_model_returns_none():
    # Нет ключа OpenAI → модель не резолвится.
    assert providers.resolve("gpt-5") is None


def test_resolve_unknown_model_falls_back_to_deepseek_provider():
    # Неизвестный id трактуется как deepseek-провайдер (есть ключ) → резолвится.
    conn = providers.resolve("some-custom-model")
    assert conn is not None
    assert conn["provider"] == "deepseek"
    assert conn["model"] == "some-custom-model"


def test_openrouter_profile_has_referer_headers():
    prof = providers.PROVIDERS["openrouter"]
    assert "HTTP-Referer" in prof["headers"]
    assert "X-Title" in prof["headers"]


def test_label_for():
    assert providers.label_for("deepseek-flash") == "DeepSeek Flash"
    assert providers.label_for("unknown-id") == "unknown-id"
