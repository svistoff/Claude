"""Разовый OAuth-обмен для получения пользовательского токена VK
(классический flow oauth.vk.com — не путать с новым VK ID/id.vk.com,
который используется VK для потребительского "Войти через VK ID").

Почему пользовательский токен, а не токен сообщества: wall.getComments
отдаёт ошибку 27 "Group authorization failed: method is unavailable with
group auth" при вызове с токеном сообщества, независимо от выданных прав —
проверено вживую (см. randomgiveaway/README.md, «Подключение VK»).
Читать комментарии можно только с пользовательским токеном.

При запросе scope с "offline" токен не истекает — отдельного
автопродления по cron, в отличие от Instagram, не требуется.
"""
from __future__ import annotations

import httpx

AUTHORIZE_URL = "https://oauth.vk.com/authorize"
TOKEN_URL = "https://oauth.vk.com/access_token"
VK_API_VERSION = "5.199"


class VKOAuthError(Exception):
    """Сообщение уже готово для показа администратору."""


async def exchange_code_for_token(
    code: str,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, int | None]:
    """Возвращает (access_token, expires_in_seconds | None).

    expires_in отсутствует в ответе (None), если запрошенный scope включал
    "offline" — токен в этом случае бессрочный."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(
            TOKEN_URL,
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        payload = resp.json()
        if resp.status_code != 200 or "error" in payload:
            detail = payload.get("error_description") or payload.get("error") or resp.text[:300]
            raise VKOAuthError(f"Не удалось обменять code на токен: {detail}")
        return payload["access_token"], payload.get("expires_in")
    finally:
        if owns_client:
            await client.aclose()
