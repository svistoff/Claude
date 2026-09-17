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
