"""Тесты защиты токена бота: он не должен попадать в логи и текст ошибок.

Причина: httpx кладёт полный URL в текст исключения, а URL Telegram содержит
токен («.../bot123:AA…/getUpdates»). Лог сервиса читается не только владельцем —
значит, токен утекает.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app.mentor import telegram as mentor_tg
from app.telegram import client as tg_client
from app.telegram.client import TelegramClient, TelegramError, redact

TOKEN = "8890795666:AAELFhgJtuYnDRpCZXZlDkRYfqU8ZUowbFs"


# --- redact() -----------------------------------------------------------------

def test_redact_removes_token_from_url():
    text = f"Client error '409 Conflict' for url 'https://api.telegram.org/bot{TOKEN}/getUpdates'"
    out = redact(text)
    assert TOKEN not in out
    assert "bot<TOKEN>" in out
    assert "409 Conflict" in out  # полезная часть сохранена


def test_redact_keeps_other_bot_ids_intact():
    out = redact("написал бот 12345 и что-то ещё")
    assert out == "написал бот 12345 и что-то ещё"


def test_redact_none_and_non_string():
    assert redact(None) == "None"
    assert redact(42) == "42"


# --- Клиент: ошибка не содержит токен ----------------------------------------

class _BoomHTTP:
    """Мок httpx.AsyncClient: GET кидает ConnectError с URL, содержащим токен."""

    def __init__(self, *a, **k):
        pass

    async def get(self, url, params=None, timeout=None):
        raise httpx.ConnectError(f"сбой соединения с {url}")

    async def post(self, url, json=None, **k):
        raise httpx.ConnectError(f"сбой соединения с {url}")


def test_get_updates_error_is_redacted(monkeypatch):
    monkeypatch.setattr(tg_client.httpx, "AsyncClient", _BoomHTTP)
    c = TelegramClient(TOKEN)

    with pytest.raises(TelegramError) as ei:
        asyncio.run(c.get_updates(None))

    assert TOKEN not in str(ei.value)
    assert "bot<TOKEN>" in str(ei.value)


def test_call_error_is_redacted(monkeypatch):
    monkeypatch.setattr(tg_client.httpx, "AsyncClient", _BoomHTTP)
    c = TelegramClient(TOKEN)

    with pytest.raises(TelegramError) as ei:
        asyncio.run(c.answer_callback("id123"))

    assert TOKEN not in str(ei.value)


def test_raise_for_status_message_redacted(monkeypatch):
    """409 Conflict приходит как HTTPStatusError — токен из URL тоже вырезаем."""

    class _Resp:
        status_code = 409

        def raise_for_status(self):
            req = httpx.Request("GET", f"https://api.telegram.org/bot{TOKEN}/getUpdates")
            raise httpx.HTTPStatusError(
                f"Client error '409 Conflict' for url 'https://api.telegram.org/bot{TOKEN}/getUpdates'",
                request=req, response=httpx.Response(409, request=req))

        def json(self):
            return {"result": []}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def get(self, url, params=None, timeout=None):
            return _Resp()

    monkeypatch.setattr(tg_client.httpx, "AsyncClient", _Client)

    with pytest.raises(TelegramError) as ei:
        asyncio.run(TelegramClient(TOKEN).get_updates(None))
    assert TOKEN not in str(ei.value)
    assert "409 Conflict" in str(ei.value)


# --- Шлюз: в лог токен не попадает -------------------------------------------

def test_gateway_log_has_no_token(monkeypatch, caplog):
    """Полный цикл Gateway.run: ошибка сети логируется без токена."""
    from app.telegram import gateway as gw_mod

    class _Tg:
        async def get_updates(self, offset):
            raise TelegramError(
                f"ConnectError: сбой соединения с https://api.telegram.org/bot{TOKEN}/getUpdates")

    g = gw_mod.Gateway(TOKEN, "777")
    g.tg = _Tg()

    async def stop_after_one():
        # Первая итерация: логируется предупреждение и уходим в sleep —
        # отменяем задачу, чтобы не крутиться бесконечно.
        task = asyncio.create_task(g.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    caplog.set_level(logging.WARNING, logger="telegram")
    asyncio.run(stop_after_one())

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert logged, "ожидалось предупреждение в логе"
    assert TOKEN not in logged
    assert "bot<TOKEN>" in logged


# --- Наставник: текст ошибки для UI без токена --------------------------------

def test_mentor_error_text_redacted(monkeypatch):
    class _Resp:
        status_code = 401
        text = f'{{"ok":false,"description":"Unauthorized bot{TOKEN}"}}'

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            return _Resp()

    monkeypatch.setattr(mentor_tg, "get_settings",
                        lambda: type("S", (), {"telegram_bot_token": TOKEN,
                                               "telegram_chat_id": "777"})())
    monkeypatch.setattr(mentor_tg.httpx, "Client", _Client)

    ok, err = mentor_tg.send_message("привет")
    assert not ok
    assert TOKEN not in err
    assert "401" in err
