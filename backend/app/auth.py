"""Аутентификация: один админ, bcrypt-хэш, подписанная cookie, CSRF, rate limit.

Пароль хранится ТОЛЬКО как bcrypt-хэш (в .env). Сессия — подписанная cookie с
временем жизни (session expiration). Для мутирующих запросов — CSRF (double-submit).
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque

import bcrypt
from fastapi import Cookie, Header, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import get_settings

COOKIE_NAME = "session"
CSRF_HEADER = "x-csrf-token"


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY не задан — задайте в .env.")
    return URLSafeTimedSerializer(settings.secret_key, salt="session")


def verify_password(password: str) -> bool:
    settings = get_settings()
    if not settings.admin_password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"),
                              settings.admin_password_hash.encode("utf-8"))
    except ValueError:
        return False


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def issue_session(response: Response, user: str) -> str:
    """Создать сессию, установить cookie, вернуть CSRF-токен."""
    settings = get_settings()
    csrf = secrets.token_urlsafe(24)
    token = _serializer().dumps({"user": user, "csrf": csrf})
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return csrf


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _load(token: str | None) -> dict | None:
    if not token:
        return None
    settings = get_settings()
    try:
        return _serializer().loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None


def require_user(session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> str:
    """Зависимость: требует валидную сессию, возвращает имя пользователя."""
    data = _load(session)
    if data is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход.")
    return data["user"]


def require_csrf(
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    x_csrf_token: str | None = Header(default=None, alias=CSRF_HEADER),
) -> str:
    """Зависимость для мутирующих запросов: сверяет CSRF-токен."""
    data = _load(session)
    if data is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход.")
    if not x_csrf_token or not secrets.compare_digest(x_csrf_token, data.get("csrf", "")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF-токен неверный.")
    return data["user"]


def get_csrf(session: str | None) -> str | None:
    data = _load(session)
    return data.get("csrf") if data else None


# --- Rate limiting входа (in-memory, по IP) ---------------------------------

_LOGIN_ATTEMPTS: dict[str, deque] = defaultdict(deque)
_WINDOW = 300      # сек
_MAX_ATTEMPTS = 10


def check_login_rate(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    dq = _LOGIN_ATTEMPTS[ip]
    while dq and now - dq[0] > _WINDOW:
        dq.popleft()
    if len(dq) >= _MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Слишком много попыток входа. Подождите.")
    dq.append(now)
