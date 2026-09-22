"""Хеширование паролей и проверка (без нативных зависимостей).

Используется pbkdf2_sha256 — чистый Python, не требует сборки bcrypt.
"""
from __future__ import annotations

from passlib.context import CryptContext

_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return _ctx.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ctx.verify(password, password_hash)
    except ValueError:
        return False
