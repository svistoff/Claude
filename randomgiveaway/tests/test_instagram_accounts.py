"""Тесты хранилища подключённых Instagram-аккаунтов (разовая авторизация по
ссылке /api/instagram/connect/start) — см. services/instagram_accounts.py."""
from __future__ import annotations

from fastapi.testclient import TestClient

from randomgiveaway.main import app
from randomgiveaway.services import instagram_accounts


async def test_upsert_creates_new_account():
    with TestClient(app):
        account = await instagram_accounts.upsert_account("ig-1", "alex", "token-1")
        assert account.ig_user_id == "ig-1"
        assert account.username == "alex"
        assert account.access_token == "token-1"


async def test_upsert_updates_existing_account_by_ig_user_id():
    with TestClient(app):
        first = await instagram_accounts.upsert_account("ig-2", "old_name", "token-old")
        second = await instagram_accounts.upsert_account("ig-2", "new_name", "token-new")
        assert second.id == first.id
        assert second.username == "new_name"
        assert second.access_token == "token-new"

        all_accounts = await instagram_accounts.list_accounts()
        matching = [a for a in all_accounts if a.ig_user_id == "ig-2"]
        assert len(matching) == 1


async def test_list_accounts_returns_all_in_connection_order():
    with TestClient(app):
        a = await instagram_accounts.upsert_account("ig-3", "first", "t1")
        b = await instagram_accounts.upsert_account("ig-4", "second", "t2")
        accounts = await instagram_accounts.list_accounts()
        ids = [acc.id for acc in accounts]
        assert ids.index(a.id) < ids.index(b.id)


async def test_get_accounts_by_ids_filters_correctly():
    with TestClient(app):
        a = await instagram_accounts.upsert_account("ig-5", "alex", "t")
        b = await instagram_accounts.upsert_account("ig-6", "kate", "t")
        await instagram_accounts.upsert_account("ig-7", "ivan", "t")

        result = await instagram_accounts.get_accounts_by_ids([a.id, b.id])
        usernames = {acc.username for acc in result}
        assert usernames == {"alex", "kate"}


async def test_get_accounts_by_ids_empty_list_returns_empty():
    with TestClient(app):
        result = await instagram_accounts.get_accounts_by_ids([])
        assert result == []


async def test_update_token_changes_access_token():
    with TestClient(app):
        await instagram_accounts.upsert_account("ig-8", "alex", "old-token")
        await instagram_accounts.update_token("ig-8", "new-token")
        accounts = await instagram_accounts.list_accounts()
        matching = [a for a in accounts if a.ig_user_id == "ig-8"]
        assert matching[0].access_token == "new-token"
