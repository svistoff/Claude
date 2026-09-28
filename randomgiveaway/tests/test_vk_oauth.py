"""Тесты обмена OAuth code -> пользовательский токен VK через VK ID
(id.vk.ru), OAuth 2.1 + PKCE.

httpx.AsyncClient подменяется на фейковый объект с post() — реальные
сетевые вызовы к VK не делаются.
"""
from __future__ import annotations

import base64
import hashlib

import pytest

from randomgiveaway.services import vk_oauth


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, post_response: FakeResponse):
        self._post_response = post_response
        self.post_calls: list[dict] = []

    async def post(self, url, data=None):
        self.post_calls.append({"url": url, "data": data})
        return self._post_response


def test_generate_pkce_pair_challenge_matches_verifier():
    code_verifier, code_challenge = vk_oauth.generate_pkce_pair()
    assert 43 <= len(code_verifier) <= 128
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert code_challenge == expected


def test_generate_pkce_pair_is_random():
    pair_a = vk_oauth.generate_pkce_pair()
    pair_b = vk_oauth.generate_pkce_pair()
    assert pair_a != pair_b


async def test_exchange_code_for_token_returns_access_and_refresh():
    client = FakeClient(
        FakeResponse(
            200,
            {"access_token": "user-token", "expires_in": 3600, "refresh_token": "refresh-abc"},
        )
    )
    token, expires_in, refresh_token = await vk_oauth.exchange_code_for_token(
        "the-code",
        "client-id",
        "https://example.com/callback",
        "verifier",
        "device-1",
        "state-1",
        client=client,
    )
    assert token == "user-token"
    assert expires_in == 3600
    assert refresh_token == "refresh-abc"
    sent = client.post_calls[0]["data"]
    assert sent["code"] == "the-code"
    assert sent["client_id"] == "client-id"
    assert sent["redirect_uri"] == "https://example.com/callback"
    assert sent["code_verifier"] == "verifier"
    assert sent["device_id"] == "device-1"
    assert sent["state"] == "state-1"
    assert sent["grant_type"] == "authorization_code"


async def test_exchange_code_for_token_without_refresh_token():
    client = FakeClient(FakeResponse(200, {"access_token": "user-token", "expires_in": 3600}))
    token, expires_in, refresh_token = await vk_oauth.exchange_code_for_token(
        "the-code", "client-id", "https://example.com/callback", "verifier", "device-1", "state-1", client=client
    )
    assert token == "user-token"
    assert refresh_token is None


async def test_exchange_code_raises_friendly_error_on_failure():
    client = FakeClient(FakeResponse(400, {"error": "invalid_grant", "error_description": "code expired"}))
    with pytest.raises(vk_oauth.VKOAuthError, match="code expired"):
        await vk_oauth.exchange_code_for_token(
            "bad-code", "client-id", "https://example.com/callback", "verifier", "device-1", "state-1", client=client
        )


async def test_refresh_access_token_returns_new_pair():
    client = FakeClient(
        FakeResponse(200, {"access_token": "new-token", "expires_in": 3600, "refresh_token": "new-refresh"})
    )
    token, expires_in, refresh_token = await vk_oauth.refresh_access_token(
        "old-refresh", "client-id", "device-1", client=client
    )
    assert token == "new-token"
    assert expires_in == 3600
    assert refresh_token == "new-refresh"
    sent = client.post_calls[0]["data"]
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == "old-refresh"
    assert sent["client_id"] == "client-id"
    assert sent["device_id"] == "device-1"


async def test_refresh_access_token_raises_friendly_error_on_failure():
    client = FakeClient(FakeResponse(400, {"error": "invalid_grant", "error_description": "refresh token expired"}))
    with pytest.raises(vk_oauth.VKOAuthError, match="refresh token expired"):
        await vk_oauth.refresh_access_token("old-refresh", "client-id", "device-1", client=client)
