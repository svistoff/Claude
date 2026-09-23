"""Тесты Instagram-адаптера: маппинг ответов Graph API в RawComment.

Без реальных сетевых вызовов — _get подменяется, чтобы отдавать заранее
подготовленные страницы ответа (как если бы это был реальный graph.instagram.com).
"""
from __future__ import annotations

import pytest

from randomgiveaway.adapters.base import SourceAdapterError
from randomgiveaway.adapters.instagram_adapter import InstagramAdapter


async def test_raises_friendly_error_without_token():
    adapter = InstagramAdapter(access_token=None)
    with pytest.raises(SourceAdapterError, match="не подключён"):
        await adapter.fetch_comments("https://instagram.com/p/ABC/")


async def test_finds_media_by_permalink_with_pagination_and_flattens_replies(monkeypatch):
    adapter = InstagramAdapter(access_token="fake-token")

    media_pages = [
        {
            "data": [{"id": "media-1", "permalink": "https://instagram.com/p/OTHER"}],
            "paging": {"next": "https://graph.instagram.com/.../me/media?after=x"},
        },
        {"data": [{"id": "media-2", "permalink": "https://instagram.com/p/ABC"}]},
    ]
    comments_page = {
        "data": [
            {
                "id": "c1",
                "text": "Привет @friend",
                "username": "alex",
                "timestamp": "2026-01-01T00:00:00+0000",
                "replies": {"data": [{"id": "r1", "text": "ответ", "username": "ivan"}]},
            },
            {"id": "c2", "text": "и я тоже", "username": "kate"},
        ]
    }

    calls = {"media": 0, "comments": 0}

    async def fake_get(client, url, params):
        if url.endswith("/media") or "after=" in url:
            page = media_pages[calls["media"]]
            calls["media"] += 1
            return page
        calls["comments"] += 1
        return comments_page

    monkeypatch.setattr(InstagramAdapter, "_get", staticmethod(fake_get))

    comments = await adapter.fetch_comments("https://instagram.com/p/ABC/")

    assert calls["media"] == 2
    assert len(comments) == 3

    reply = next(c for c in comments if c.comment_id == "r1")
    assert reply.is_reply is True
    assert reply.parent_comment_id == "c1"
    assert reply.source_user_id == "ivan"

    top = next(c for c in comments if c.comment_id == "c1")
    assert top.is_reply is False
    assert top.username == "alex"
    assert top.source_user_id == "alex"


async def test_raises_friendly_error_when_post_not_found(monkeypatch):
    adapter = InstagramAdapter(access_token="fake-token")

    async def fake_get(client, url, params):
        return {"data": []}

    monkeypatch.setattr(InstagramAdapter, "_get", staticmethod(fake_get))

    with pytest.raises(SourceAdapterError, match="не найден"):
        await adapter.fetch_comments("https://instagram.com/p/MISSING/")


async def test_falls_back_to_comment_id_when_username_missing(monkeypatch):
    adapter = InstagramAdapter(access_token="fake-token")

    async def fake_get(client, url, params):
        if "comments" in url:
            return {"data": [{"id": "c1", "text": "..."}]}  # без username
        return {"data": [{"id": "media-1", "permalink": "https://instagram.com/p/ABC"}]}

    monkeypatch.setattr(InstagramAdapter, "_get", staticmethod(fake_get))

    comments = await adapter.fetch_comments("https://instagram.com/p/ABC")
    assert comments[0].username is None
    assert comments[0].source_user_id == "c1"  # деградация на comment_id, см. §27 ТЗ
