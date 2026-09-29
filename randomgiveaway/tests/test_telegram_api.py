"""Тесты тонкой обёртки над Telegram Bot API — без реальных сетевых вызовов."""
from __future__ import annotations

import pytest

from randomgiveaway.services import telegram_api


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, payload: dict):
        self._payload = payload
        self.post_calls: list[dict] = []

    async def post(self, url, json=None):
        self.post_calls.append({"url": url, "json": json})
        return FakeResponse(self._payload)


async def test_call_returns_result_on_ok():
    client = FakeClient({"ok": True, "result": {"id": 1}})
    result = await telegram_api._call("TOKEN", "getMe", {}, client)
    assert result == {"id": 1}
    assert client.post_calls[0]["url"] == "https://api.telegram.org/botTOKEN/getMe"


async def test_call_raises_friendly_error_on_not_ok():
    client = FakeClient({"ok": False, "description": "Unauthorized"})
    with pytest.raises(telegram_api.TelegramAPIError, match="Unauthorized"):
        await telegram_api._call("TOKEN", "getMe", {}, client)


async def test_is_channel_member_true_for_member_statuses():
    for status in ("creator", "administrator", "member", "restricted"):
        client = FakeClient({"ok": True, "result": {"status": status}})
        assert await telegram_api.is_channel_member("TOKEN", "@chan", 1, client) is True


async def test_is_channel_member_false_for_left():
    client = FakeClient({"ok": True, "result": {"status": "left"}})
    assert await telegram_api.is_channel_member("TOKEN", "@chan", 1, client) is False


async def test_is_channel_member_false_on_api_error():
    client = FakeClient({"ok": False, "description": "user not found"})
    assert await telegram_api.is_channel_member("TOKEN", "@chan", 1, client) is False


def test_join_deep_link_format():
    assert telegram_api.join_deep_link("mybot", 5) == "https://t.me/mybot?start=join_5"


def test_referral_deep_link_format():
    assert telegram_api.referral_deep_link("mybot", 5, "123") == "https://t.me/mybot?start=ref_5_123"


def test_join_button_markup_shape():
    markup = telegram_api.join_button_markup("mybot", 5)
    assert markup == {
        "inline_keyboard": [[{"text": "Участвую 🎉", "url": "https://t.me/mybot?start=join_5"}]]
    }
