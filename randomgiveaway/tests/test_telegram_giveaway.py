"""Тесты регистрации участников/рефералки Telegram-розыгрыша (§ обсуждение
в README, «Подключение Telegram») — Telegram Bot API замокан, реальных
сетевых вызовов нет."""
from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient

from randomgiveaway.database.database import get_conn
from randomgiveaway.main import app
from randomgiveaway.services import giveaways as giveaway_service
from randomgiveaway.services import telegram_giveaway


def _create_telegram_giveaway(client: TestClient, **settings_overrides) -> dict:
    settings = {"unique_user": False, "winners_count": 1}
    settings.update(settings_overrides)
    resp = client.post(
        "/api/giveaways",
        json={"source": "telegram", "post_url": "", "title": "TG", "settings": settings},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _patch_config(monkeypatch, **overrides):
    patched = dataclasses.replace(telegram_giveaway.config, **overrides)
    monkeypatch.setattr(telegram_giveaway, "config", patched)
    return patched


async def test_register_join_is_idempotent_and_refreshes_profile():
    with TestClient(app) as client:
        gid = _create_telegram_giveaway(client)["id"]

        first = await telegram_giveaway.register_join(gid, "111", "alex", "Alex A")
        assert first is True
        second = await telegram_giveaway.register_join(gid, "111", "alex_new", "Alex B")
        assert second is False

        conn = get_conn()
        cur = await conn.execute(
            "SELECT username FROM telegram_entries WHERE giveaway_id = ? AND telegram_user_id = ? AND kind = 'join'",
            (gid, "111"),
        )
        rows = await cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["username"] == "alex_new"


async def test_register_referral_requires_referrer_to_have_joined():
    with TestClient(app) as client:
        gid = _create_telegram_giveaway(client)["id"]
        credited = await telegram_giveaway.register_referral(gid, "999")
        assert credited is False


async def test_register_referral_respects_cap(monkeypatch):
    with TestClient(app) as client:
        gid = _create_telegram_giveaway(client)["id"]
        _patch_config(monkeypatch, telegram_max_referrals=2)

        await telegram_giveaway.register_join(gid, "referrer", "ref", "Referrer")
        assert await telegram_giveaway.register_referral(gid, "referrer") is True
        assert await telegram_giveaway.register_referral(gid, "referrer") is True
        assert await telegram_giveaway.register_referral(gid, "referrer") is False


async def test_rebuild_participants_weights_by_referrals(monkeypatch):
    with TestClient(app) as client:
        gid = _create_telegram_giveaway(client)["id"]
        _patch_config(monkeypatch, telegram_max_referrals=10)

        await telegram_giveaway.register_join(gid, "referrer", "ref", "Referrer")
        await telegram_giveaway.register_join(gid, "friend1", "f1", "Friend1")
        await telegram_giveaway.register_referral(gid, "referrer")
        await telegram_giveaway.register_referral(gid, "referrer")

        await telegram_giveaway.rebuild_participants(gid)

        participants = await giveaway_service.get_active_participants(gid)
        by_id = {p.source_user_id: p for p in participants}
        assert by_id["referrer"].comment_count == 3  # 1 join + 2 referral
        assert by_id["friend1"].comment_count == 1
        assert by_id["referrer"].username == "ref"  # взято из более раннего join-события


async def test_resync_membership_excludes_users_who_left(monkeypatch):
    with TestClient(app) as client:
        gid = _create_telegram_giveaway(client)["id"]
        _patch_config(monkeypatch, telegram_bot_token="TOKEN", telegram_channel="@chan")

        await telegram_giveaway.register_join(gid, "stays", "a", "A")
        await telegram_giveaway.register_join(gid, "left", "b", "B")
        await telegram_giveaway.rebuild_participants(gid)

        async def fake_is_member(token, chat_id, user_id, client=None):
            return user_id != "left"

        monkeypatch.setattr(telegram_giveaway.telegram_api, "is_channel_member", fake_is_member)

        excluded = await telegram_giveaway.resync_membership_and_exclude(gid)
        assert excluded == 1

        active = await giveaway_service.get_active_participants(gid)
        assert {p.source_user_id for p in active} == {"stays"}


async def test_publish_giveaway_post_sets_post_url_and_rejects_double_publish(monkeypatch):
    with TestClient(app) as client:
        gid = _create_telegram_giveaway(client)["id"]
        _patch_config(monkeypatch, telegram_bot_token="TOKEN", telegram_channel="@chan")

        async def fake_get_me(token, client=None):
            return {"username": "mybot"}

        sent = {}

        async def fake_send_message(token, chat_id, text, reply_markup=None, client=None):
            sent.update(chat_id=chat_id, text=text, reply_markup=reply_markup)
            return {"chat": {"id": -100123}, "message_id": 42}

        monkeypatch.setattr(telegram_giveaway.telegram_api, "get_me", fake_get_me)
        monkeypatch.setattr(telegram_giveaway.telegram_api, "send_message", fake_send_message)

        giveaway = await telegram_giveaway.publish_giveaway_post(gid, "Розыгрыш!")
        assert giveaway.post_url == "https://t.me/chan/42"
        assert giveaway.telegram_message_id == 42
        assert sent["chat_id"] == "@chan"
        assert sent["text"] == "Розыгрыш!"

        try:
            await telegram_giveaway.publish_giveaway_post(gid, "Ещё раз")
        except giveaway_service.GiveawayError as exc:
            assert "уже опубликован" in str(exc)
        else:
            raise AssertionError("Повторная публикация должна была отклониться")


async def test_handle_update_join_then_referral(monkeypatch):
    with TestClient(app) as client:
        gid = _create_telegram_giveaway(client)["id"]
        _patch_config(monkeypatch, telegram_bot_token="TOKEN", telegram_channel="@chan", telegram_max_referrals=5)

        async def fake_get_me(token, client=None):
            return {"username": "mybot"}

        async def fake_is_member(token, chat_id, user_id, client=None):
            return True

        sent_messages = []

        async def fake_send_message(token, chat_id, text, reply_markup=None, client=None):
            sent_messages.append({"chat_id": chat_id, "text": text})
            return {"message_id": 1, "chat": {"id": chat_id}}

        monkeypatch.setattr(telegram_giveaway.telegram_api, "get_me", fake_get_me)
        monkeypatch.setattr(telegram_giveaway.telegram_api, "is_channel_member", fake_is_member)
        monkeypatch.setattr(telegram_giveaway.telegram_api, "send_message", fake_send_message)

        await telegram_giveaway.handle_update(
            {"message": {"text": f"/start join_{gid}", "from": {"id": 111, "username": "alex", "first_name": "Alex"}}}
        )
        await telegram_giveaway.handle_update(
            {
                "message": {
                    "text": f"/start ref_{gid}_111",
                    "from": {"id": 222, "username": "friend", "first_name": "Friend"},
                }
            }
        )

        participants = await giveaway_service.get_active_participants(gid)
        by_id = {p.source_user_id: p for p in participants}
        assert by_id["111"].comment_count == 2  # join + credited referral
        assert by_id["222"].comment_count == 1
        assert len(sent_messages) == 2
        assert "t.me/mybot?start=ref_" in sent_messages[0]["text"]


async def test_handle_update_asks_to_subscribe_when_not_member(monkeypatch):
    with TestClient(app) as client:
        gid = _create_telegram_giveaway(client)["id"]
        _patch_config(monkeypatch, telegram_bot_token="TOKEN", telegram_channel="@chan")

        async def fake_is_member(token, chat_id, user_id, client=None):
            return False

        sent_messages = []

        async def fake_send_message(token, chat_id, text, reply_markup=None, client=None):
            sent_messages.append(text)
            return {"message_id": 1, "chat": {"id": chat_id}}

        monkeypatch.setattr(telegram_giveaway.telegram_api, "is_channel_member", fake_is_member)
        monkeypatch.setattr(telegram_giveaway.telegram_api, "send_message", fake_send_message)

        await telegram_giveaway.handle_update(
            {"message": {"text": f"/start join_{gid}", "from": {"id": 111, "username": "alex"}}}
        )

        assert len(sent_messages) == 1
        assert "подпишись" in sent_messages[0]

        participants = await giveaway_service.get_active_participants(gid)
        assert participants == []
