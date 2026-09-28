"""Разовый OAuth-обмен для получения пользовательского токена через VK ID
(id.vk.ru) — OAuth 2.1 с обязательным PKCE. Это НЕ тот же протокол, что
классический oauth.vk.com — тот для новых приложений (тип «Сайт»/
«Standalone» в сервисе авторизации VK ID) больше не годится, поэтому
здесь используется id.vk.ru/authorize + id.vk.ru/oauth2/auth.

Почему пользовательский токен, а не токен сообщества: wall.getComments
отдаёт ошибку 27 "Group authorization failed: method is unavailable with
group auth" при вызове с токеном сообщества, независимо от выданных прав —
проверено вживую (см. randomgiveaway/README.md, «Подключение VK»).

client_secret в этом flow не используется вообще — вместо него PKCE
(code_verifier/code_challenge). device_id VK возвращает вместе с code в
редиректе на callback, его нужно передать обратно при обмене на токен.
"""
from __future__ import annotations

import base64
import hashlib
import secrets

import httpx

AUTHORIZE_URL = "https://id.vk.ru/authorize"
TOKEN_URL = "https://id.vk.ru/oauth2/auth"


class VKOAuthError(Exception):
    """Сообщение уже готово для показа администратору."""


def generate_pkce_pair() -> tuple[str, str]:
    """Возвращает (code_verifier, code_challenge). code_verifier нужно
    сохранить (привязанным к state) до момента обмена кода на токен."""
    code_verifier = secrets.token_urlsafe(96)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


async def exchange_code_for_token(
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    device_id: str,
    state: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, int | None, str | None]:
    """Возвращает (access_token, expires_in_seconds | None, refresh_token | None)."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "client_id": client_id,
                "device_id": device_id,
                "redirect_uri": redirect_uri,
                "state": state,
            },
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise VKOAuthError(f"Не удалось разобрать ответ VK ID: {resp.text[:300]}") from exc

        if resp.status_code != 200 or "error" in payload:
            detail = payload.get("error_description") or payload.get("error") or resp.text[:300]
            raise VKOAuthError(f"Не удалось обменять code на токен: {detail}")

        return payload["access_token"], payload.get("expires_in"), payload.get("refresh_token")
    finally:
        if owns_client:
            await client.aclose()


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    device_id: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, int | None, str | None]:
    """Продлевает токен через refresh_token (device_id должен быть тем же,
    что был получен при первом обмене кода). Возвращает (access_token,
    expires_in, refresh_token) — VK ID обычно выдаёт новый refresh_token
    вместе с access_token, старый нужно заменить сохранённым новым."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "device_id": device_id,
            },
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise VKOAuthError(f"Не удалось разобрать ответ VK ID: {resp.text[:300]}") from exc

        if resp.status_code != 200 or "error" in payload:
            detail = payload.get("error_description") or payload.get("error") or resp.text[:300]
            raise VKOAuthError(f"Не удалось обновить токен: {detail}")

        return payload["access_token"], payload.get("expires_in"), payload.get("refresh_token")
    finally:
        if owns_client:
            await client.aclose()
