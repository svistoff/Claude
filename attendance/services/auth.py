"""Хеширование паролей и подписанные cookie-сессии для веб-панели."""
from __future__ import annotations

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from attendance.config import config

SESSION_COOKIE_NAME = "attendance_session"

_serializer = URLSafeTimedSerializer(config.secret_key, salt="attendance-session")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_session_token(username: str) -> str:
    return _serializer.dumps({"username": username})


def read_session_token(token: str) -> str | None:
    try:
        data = _serializer.loads(token, max_age=config.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("username")
