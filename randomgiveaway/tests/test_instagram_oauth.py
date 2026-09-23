"""Тесты обмена OAuth code -> long-lived токен и продления токена.

httpx.AsyncClient подменяется на фейковый объект с post()/get() — реальные
сетевые вызовы в Instagram не делаются.
"""
from __future__ import annotations

import pytest

from randomgiveaway.services import instagram_oauth


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, post_response: FakeResponse, get_response: FakeResponse):
        self._post_response = post_response
        self._get_response = get_response
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    async def post(self, url, data=None):
        self.post_calls.append({"url": url, "data": data})
        return self._post_response

    async def get(self, url, params=None):
        self.get_calls.append({"url": url, "params": params})
        return self._get_response


async def test_exchange_code_for_long_lived_token_happy_path():
    client = FakeClient(
        post_response=FakeResponse(200, {"access_token": "short-token", "user_id": 123}),
        get_response=FakeResponse(200, {"access_token": "long-token", "expires_in": 5183944}),
    )
    token, expires_in = await instagram_oauth.exchange_code_for_long_lived_token(
        "the-code", "app-id", "app-secret", "https://example.com/callback", client=client
    )
    assert token == "long-token"
    assert expires_in == 5183944
    assert client.post_calls[0]["data"]["code"] == "the-code"
    assert client.get_calls[0]["params"]["access_token"] == "short-token"


async def test_exchange_code_handles_wrapped_data_response():
    client = FakeClient(
        post_response=FakeResponse(200, {"data": [{"access_token": "short-token", "user_id": 123}]}),
        get_response=FakeResponse(200, {"access_token": "long-token", "expires_in": 5183944}),
    )
    token, _ = await instagram_oauth.exchange_code_for_long_lived_token(
        "code", "app-id", "app-secret", "https://example.com/callback", client=client
    )
    assert token == "long-token"


async def test_exchange_code_raises_friendly_error_on_failure():
    client = FakeClient(
        post_response=FakeResponse(400, {"error": "invalid_grant"}),
        get_response=FakeResponse(200, {}),
    )
    with pytest.raises(instagram_oauth.InstagramOAuthError, match="обменять"):
        await instagram_oauth.exchange_code_for_long_lived_token(
            "bad-code", "app-id", "app-secret", "https://example.com/callback", client=client
        )


async def test_refresh_long_lived_token_happy_path():
    client = FakeClient(
        post_response=FakeResponse(200, {}),
        get_response=FakeResponse(200, {"access_token": "refreshed-token", "expires_in": 5183944}),
    )
    token, expires_in = await instagram_oauth.refresh_long_lived_token("old-token", client=client)
    assert token == "refreshed-token"
    assert expires_in == 5183944
    assert client.get_calls[0]["params"]["access_token"] == "old-token"


async def test_refresh_raises_friendly_error_on_failure():
    client = FakeClient(
        post_response=FakeResponse(200, {}),
        get_response=FakeResponse(401, {"error": "token expired"}),
    )
    with pytest.raises(instagram_oauth.InstagramOAuthError, match="обновить токен"):
        await instagram_oauth.refresh_long_lived_token("old-token", client=client)
