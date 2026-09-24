"""Тесты VK-адаптера: разбор ссылки на пост, пагинация, вложенные ответы,
маппинг профилей/сообществ в RawComment. Без реальных сетевых вызовов —
_call подменяется на заранее подготовленные ответы (как если бы это был
настоящий api.vk.com)."""
from __future__ import annotations

import pytest

from randomgiveaway.adapters.base import SourceAdapterError
from randomgiveaway.adapters.vk_adapter import VKAdapter, _parse_post_url


@pytest.mark.parametrize(
    "url",
    [
        "https://vk.com/wall-12345_678",
        "https://vk.com/club12345?w=wall-12345_678",
        "https://vk.com/public12345?w=wall-12345_678",
        "https://vk.com/ekb_guide?w=wall-12345_678",
        "https://vk.com/feed?w=wall-12345_678%2Fall",
    ],
)
def test_parses_various_post_url_forms(url):
    assert _parse_post_url(url) == (-12345, 678)


def test_parse_post_url_raises_friendly_error_for_unrecognized_link():
    with pytest.raises(SourceAdapterError, match="Не удалось распознать"):
        _parse_post_url("https://vk.com/some_random_page")


async def test_raises_friendly_error_without_token():
    adapter = VKAdapter(access_token=None)
    with pytest.raises(SourceAdapterError, match="не подключён"):
        await adapter.fetch_comments("https://vk.com/wall-1_1")


async def test_fetches_with_pagination_and_flattens_thread_replies(monkeypatch):
    adapter = VKAdapter(access_token="fake-token")

    page1 = {
        "count": 2,
        "items": [
            {
                "id": 1,
                "from_id": 100,
                "text": "первый комментарий",
                "thread": {
                    "items": [
                        {"id": 2, "from_id": 200, "text": "ответ на первый"},
                    ]
                },
            }
        ],
        "profiles": [
            {"id": 100, "first_name": "Иван", "last_name": "Иванов", "screen_name": "ivan_i"},
            {"id": 200, "first_name": "Пётр", "last_name": "Петров", "screen_name": "petr_p"},
        ],
        "groups": [],
    }
    page2 = {
        "count": 2,
        "items": [{"id": 3, "from_id": 300, "text": "второй комментарий"}],
        "profiles": [{"id": 300, "first_name": "Анна", "last_name": "Сидорова", "screen_name": "anna_s"}],
        "groups": [],
    }

    calls = {"n": 0}

    async def fake_call(client, method, params):
        assert method == "wall.getComments"
        calls["n"] += 1
        return page1 if params["offset"] == 0 else page2

    monkeypatch.setattr(VKAdapter, "_call", staticmethod(fake_call))

    comments = await adapter.fetch_comments("https://vk.com/wall-12345_678")

    assert calls["n"] == 2
    assert len(comments) == 3

    top = next(c for c in comments if c.comment_id == "1")
    assert top.is_reply is False
    assert top.username == "ivan_i"
    assert top.display_name == "Иван Иванов"
    assert top.source_user_id == "100"

    reply = next(c for c in comments if c.comment_id == "2")
    assert reply.is_reply is True
    assert reply.parent_comment_id == "1"
    assert reply.username == "petr_p"


async def test_maps_community_author_when_from_id_negative(monkeypatch):
    adapter = VKAdapter(access_token="fake-token")

    page = {
        "count": 1,
        "items": [{"id": 1, "from_id": -555, "text": "от имени сообщества"}],
        "profiles": [],
        "groups": [{"id": 555, "name": "Другое сообщество", "screen_name": "other_group"}],
    }

    async def fake_call(client, method, params):
        return page

    monkeypatch.setattr(VKAdapter, "_call", staticmethod(fake_call))

    comments = await adapter.fetch_comments("https://vk.com/wall-12345_678")
    assert len(comments) == 1
    assert comments[0].username == "other_group"
    assert comments[0].display_name == "Другое сообщество"
    assert comments[0].source_user_id == "-555"


async def test_skips_deleted_comments(monkeypatch):
    adapter = VKAdapter(access_token="fake-token")

    page = {
        "count": 2,
        "items": [
            {"id": 1, "from_id": 100, "text": "живой", "deleted": False},
            {"id": 2, "from_id": 200, "deleted": True},
        ],
        "profiles": [{"id": 100, "first_name": "A", "last_name": "B", "screen_name": "ab"}],
        "groups": [],
    }

    async def fake_call(client, method, params):
        return page

    monkeypatch.setattr(VKAdapter, "_call", staticmethod(fake_call))

    comments = await adapter.fetch_comments("https://vk.com/wall-12345_678")
    assert len(comments) == 1
    assert comments[0].comment_id == "1"


async def test_falls_back_when_profile_not_found(monkeypatch):
    adapter = VKAdapter(access_token="fake-token")

    page = {
        "count": 1,
        "items": [{"id": 1, "from_id": 999, "text": "..."}],
        "profiles": [],
        "groups": [],
    }

    async def fake_call(client, method, params):
        return page

    monkeypatch.setattr(VKAdapter, "_call", staticmethod(fake_call))

    comments = await adapter.fetch_comments("https://vk.com/wall-12345_678")
    assert comments[0].username is None
    assert comments[0].display_name is None
    assert comments[0].source_user_id == "999"


async def test_raises_friendly_error_on_vk_api_error(monkeypatch):
    adapter = VKAdapter(access_token="fake-token")

    async def fake_call(client, method, params):
        raise SourceAdapterError("VK API: Access denied (код 15)")

    monkeypatch.setattr(VKAdapter, "_call", staticmethod(fake_call))

    with pytest.raises(SourceAdapterError, match="Access denied"):
        await adapter.fetch_comments("https://vk.com/wall-12345_678")
