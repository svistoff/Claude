"""Разовый OAuth-обмен и продление long-lived токена (Instagram API with
Instagram Login). См. randomgiveaway/README.md — раздел про подключение
Instagram, и api/routes.py — эндпоинты /instagram/oauth/start и /callback.

Поток:
  1. Администратор (мы) открывает /api/instagram/oauth/start в браузере,
     залогинившись как ekb_guide — редирект на Instagram, экран согласия.
  2. Instagram редиректит обратно на /instagram/oauth/callback?code=...
  3. code меняется на короткоживущий токен (api.instagram.com), а тот —
     на long-lived (graph.instagram.com, живёт ~60 дней).
  4. Раз в несколько дней long-lived токен нужно продлевать через
     refresh_long_lived_token — до истечения, иначе придётся повторять шаги 1-3.
"""
from __future__ import annotations

import httpx

SHORT_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
LONG_TOKEN_EXCHANGE_URL = "https://graph.instagram.com/access_token"
LONG_TOKEN_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"


class InstagramOAuthError(Exception):
    """Сообщение уже готово для показа администратору."""


async def exchange_code_for_long_lived_token(
    code: str,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, int]:
    """Возвращает (access_token, expires_in_seconds)."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(
            SHORT_TOKEN_URL,
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if resp.status_code != 200:
            raise InstagramOAuthError(
                f"Не удалось обменять code на токен: {resp.status_code} {resp.text[:300]}"
            )
        payload = resp.json()
        # Meta меняла форму ответа между версиями API: то плоский объект,
        # то {"data": [{...}]} — поддерживаем оба варианта.
        entry = payload["data"][0] if "data" in payload else payload
        short_token = entry["access_token"]

        resp = await client.get(
            LONG_TOKEN_EXCHANGE_URL,
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": app_secret,
                "access_token": short_token,
            },
        )
        if resp.status_code != 200:
            raise InstagramOAuthError(
                f"Не удалось получить long-lived токен: {resp.status_code} {resp.text[:300]}"
            )
        long_payload = resp.json()
        return long_payload["access_token"], long_payload["expires_in"]
    finally:
        if owns_client:
            await client.aclose()


async def refresh_long_lived_token(
    current_token: str, client: httpx.AsyncClient | None = None
) -> tuple[str, int]:
    """Продлевает уже полученный long-lived токен ещё примерно на 60 дней.
    Токену должно быть не меньше 24 часов и он не должен быть просрочен —
    иначе нужно заново пройти /instagram/oauth/start."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(
            LONG_TOKEN_REFRESH_URL,
            params={"grant_type": "ig_refresh_token", "access_token": current_token},
        )
        if resp.status_code != 200:
            raise InstagramOAuthError(f"Не удалось обновить токен: {resp.status_code} {resp.text[:300]}")
        payload = resp.json()
        return payload["access_token"], payload["expires_in"]
    finally:
        if owns_client:
            await client.aclose()
