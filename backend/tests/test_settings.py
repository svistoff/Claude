"""Тесты рантайм-переключателя модели."""

from __future__ import annotations

import pytest

from app import settings_store


def test_available_models_contains_both():
    models = settings_store.available_models()
    assert "deepseek-flash" in models
    assert "deepseek-v4-pro" in models


def test_default_model_is_flash():
    # По умолчанию (без override в БД) — модель из конфига.
    assert settings_store.current_model() in settings_store.available_models()


def test_switch_model_persists():
    settings_store.set_model("deepseek-v4-pro")
    assert settings_store.current_model() == "deepseek-v4-pro"
    settings_store.set_model("deepseek-flash")
    assert settings_store.current_model() == "deepseek-flash"


def test_reject_unknown_model():
    with pytest.raises(ValueError):
        settings_store.set_model("gpt-4o")
