"""Тесты механики розыгрыша по отметкам в Instagram (GET /tags) — см.
services/instagram_tags.py. Запросы к Instagram полностью замоканы."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from randomgiveaway.adapters.base import SourceAdapterError
from randomgiveaway.database.models import InstagramConnectedAccount
from randomgiveaway.main import app
from randomgiveaway.services import giveaways as giveaway_service
from randomgiveaway.services import instagram_accounts
from randomgiveaway.services import instagram_tags
from randomgiveaway.database.models import GiveawaySettings


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeClient:
    """pages_by_token: token -> список "страниц" (каждая — список сырых
    item-объектов /tags); следующая страница запрашивается через params=None
    (как и реальный httpx-клиент в _fetch_tagged_media, который кладёт всё
    в саму ссылку "next")."""

    def __init__(self, pages_by_token: dict[str, list[list[dict]]]):
        self._pages_by_token = pages_by_token
        self._next_index: dict[str, int] = {}
        self._current_token: str | None = None

    async def get(self, url, params=None):
        if params is not None:
            self._current_token = params["access_token"]
            self._next_index[self._current_token] = 0
        token = self._current_token
        pages = self._pages_by_token.get(token, [[]])
        idx = self._next_index.get(token, 0)
        items = pages[idx] if idx < len(pages) else []
        has_more = idx + 1 < len(pages)
        self._next_index[token] = idx + 1
        paging = {"next": "https://graph.instagram.com/next-page"} if has_more else {}
        return FakeResponse(200, {"data": items, "paging": paging})


class FakeAsyncClientCM:
    def __init__(self, client: FakeClient):
        self._client = client

    async def __aenter__(self) -> FakeClient:
        return self._client

    async def __aexit__(self, *exc) -> bool:
        return False


def make_account(ig_user_id: str, username: str, token: str) -> InstagramConnectedAccount:
    return InstagramConnectedAccount(
        id=None,
        ig_user_id=ig_user_id,
        username=username,
        access_token=token,
        connected_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def tag_item(permalink: str, username: str, timestamp: str, caption: str = "") -> dict:
    return {"id": permalink, "permalink": permalink, "username": username, "timestamp": timestamp, "caption": caption}


async def test_fetch_tagged_media_stops_at_first_item_older_than_since(monkeypatch):
    account = make_account("ig-1", "ekb_guide", "tok-1")
    client = FakeClient(
        {
            "tok-1": [
                [
                    tag_item("https://instagram.com/p/new", "alex", "2026-02-10T12:00:00+00:00"),
                    tag_item("https://instagram.com/p/old", "ivan", "2026-01-01T12:00:00+00:00"),
                ]
            ]
        }
    )
    import datetime

    since = datetime.datetime.fromisoformat("2026-02-01T00:00:00+00:00")
    result = await instagram_tags._fetch_tagged_media(account, since, client)
    assert set(result) == {"https://instagram.com/p/new"}


async def test_fetch_tagged_media_follows_pagination(monkeypatch):
    account = make_account("ig-1", "ekb_guide", "tok-1")
    client = FakeClient(
        {
            "tok-1": [
                [tag_item("https://instagram.com/p/page1", "alex", "2026-02-10T12:00:00+00:00")],
                [tag_item("https://instagram.com/p/page2", "kate", "2026-02-09T12:00:00+00:00")],
            ]
        }
    )
    import datetime

    since = datetime.datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    result = await instagram_tags._fetch_tagged_media(account, since, client)
    assert set(result) == {"https://instagram.com/p/page1", "https://instagram.com/p/page2"}


async def test_compute_tagged_participants_intersects_across_required_accounts(monkeypatch):
    with TestClient(app) as test_client:
        giveaway = await giveaway_service.create_giveaway(
            source="instagram_tags",
            post_url="",
            title=None,
            settings=GiveawaySettings(winners_count=1),
        )
        acc1 = await instagram_accounts.upsert_account("ig-ekb", "ekb_guide", "tok-ekb")
        acc2 = await instagram_accounts.upsert_account("ig-dacha", "dacha_ekb", "tok-dacha")

        conn_settings = GiveawaySettings(winners_count=1, instagram_tag_account_ids=[acc1.id, acc2.id])
        from randomgiveaway.database.database import get_conn

        conn = get_conn()
        await conn.execute(
            "UPDATE giveaways SET settings_json = ? WHERE id = ?",
            (conn_settings.to_json(), giveaway.id),
        )
        await conn.commit()

        since_str = giveaway.created_at
        both = tag_item("https://instagram.com/p/both", "winner_user", since_str)
        only_ekb = tag_item("https://instagram.com/p/only_ekb", "not_a_winner", since_str)

        fake_client = FakeClient(
            {
                "tok-ekb": [[both, only_ekb]],
                "tok-dacha": [[both]],
            }
        )
        monkeypatch.setattr(
            instagram_tags.httpx, "AsyncClient", lambda **kwargs: FakeAsyncClientCM(fake_client)
        )

        comments = await instagram_tags.compute_tagged_participants(giveaway.id)
        assert len(comments) == 1
        assert comments[0].username == "winner_user"
        assert comments[0].comment_id == "https://instagram.com/p/both"


async def test_compute_tagged_participants_requires_at_least_one_account():
    with TestClient(app):
        giveaway = await giveaway_service.create_giveaway(
            source="instagram_tags",
            post_url="",
            title=None,
            settings=GiveawaySettings(winners_count=1),
        )
        with pytest.raises(SourceAdapterError, match="Не выбрано"):
            await instagram_tags.compute_tagged_participants(giveaway.id)


async def test_compute_tagged_participants_rejects_missing_connected_account():
    with TestClient(app):
        giveaway = await giveaway_service.create_giveaway(
            source="instagram_tags",
            post_url="",
            title=None,
            settings=GiveawaySettings(winners_count=1, instagram_tag_account_ids=[999999]),
        )
        with pytest.raises(SourceAdapterError, match="больше не подключены"):
            await instagram_tags.compute_tagged_participants(giveaway.id)
