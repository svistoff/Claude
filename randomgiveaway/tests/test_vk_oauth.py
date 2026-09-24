"""Тесты обмена OAuth code -> пользовательский токен VK.

httpx.AsyncClient подменяется на фейковый объект с get() — реальные
сетевые вызовы к VK не делаются.
"""
from __future__ import annotations

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
    def __init__(self, get_response: FakeResponse):
        self._get_response = get_response
        self.get_calls: list[dict] = []

    async def get(self, url, params=None):
        self.get_calls.append({"url": url, "params": params})
        return self._get_response


async def test_exchange_code_for_token_with_offline_scope_has_no_expiry():
    client = FakeClient(FakeResponse(200, {"access_token": "user-token", "user_id": 42}))
    token, expires_in = await vk_oauth.exchange_code_for_token(
        "the-code", "app-id", "app-secret", "https://example.com/callback", client=client
    )
    assert token == "user-token"
    assert expires_in is None
    assert client.get_calls[0]["params"]["code"] == "the-code"


async def test_exchange_code_for_token_with_expiry():
    client = FakeClient(FakeResponse(200, {"access_token": "user-token", "expires_in": 86400, "user_id": 42}))
    token, expires_in = await vk_oauth.exchange_code_for_token(
        "the-code", "app-id", "app-secret", "https://example.com/callback", client=client
    )
    assert token == "user-token"
    assert expires_in == 86400


async def test_exchange_code_raises_friendly_error_on_failure():
    client = FakeClient(FakeResponse(400, {"error": "invalid_grant", "error_description": "code expired"}))
    with pytest.raises(vk_oauth.VKOAuthError, match="code expired"):
        await vk_oauth.exchange_code_for_token(
            "bad-code", "app-id", "app-secret", "https://example.com/callback", client=client
        )
