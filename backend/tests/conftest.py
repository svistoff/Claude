"""Общая настройка тестов: изолированное окружение и БД."""

from __future__ import annotations

import os
import tempfile

import bcrypt

# Секреты для тестов задаём до импорта app.* (pydantic-settings читает окружение).
TEST_PASSWORD = "secret123"

os.environ.setdefault("ADMIN_USER", "admin")
os.environ.setdefault(
    "ADMIN_PASSWORD_HASH",
    bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode(),
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")
# Ключ DeepSeek-провайдера, чтобы его модели были доступны в переключателе
# (available_models фильтрует по наличию ключа). Остальные провайдеры — без ключа.
os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """Тесты логинятся часто; сбрасываем счётчик попыток, иначе получим 429."""
    from app import auth as auth_mod
    auth_mod._LOGIN_ATTEMPTS.clear()
    yield
    auth_mod._LOGIN_ATTEMPTS.clear()
