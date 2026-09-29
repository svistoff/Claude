"""Тонкая обёртка над Telegram Bot API (без aiogram — нужно всего 4 метода,
отдельный фреймворк ради этого не оправдан). См. services/telegram_giveaway.py
и README.md, «Подключение Telegram»."""
from __future__ import annotations

from typing import Any

import httpx

API_BASE = "https://api.telegram.org/bot{token}"


class TelegramAPIError(Exception):
    """Сообщение уже готово для показа администратору/в логах."""


async def _call(
    token: str, method: str, payload: dict[str, Any], client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(f"{API_BASE.format(token=token)}/{method}", json=payload)
        try:
            data = resp.json()
        except ValueError as exc:
            raise TelegramAPIError(f"Не удалось разобрать ответ Telegram: {resp.text[:300]}") from exc
        if not data.get("ok"):
            raise TelegramAPIError(data.get("description") or f"Telegram API вернул ошибку: {data}")
        return data["result"]
    finally:
        if owns_client:
            await client.aclose()


async def get_me(token: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    return await _call(token, "getMe", {}, client)


async def send_message(
    token: str,
    chat_id: str,
    text: str,
    reply_markup: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return await _call(token, "sendMessage", payload, client)


async def get_chat_member(
    token: str, chat_id: str, user_id: str | int, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    return await _call(token, "getChatMember", {"chat_id": chat_id, "user_id": user_id}, client)


MEMBER_STATUSES = {"creator", "administrator", "member", "restricted"}


async def is_channel_member(
    token: str, chat_id: str, user_id: str | int, client: httpx.AsyncClient | None = None
) -> bool:
    """restricted тоже считается участником (§ Bot API) — исключены только
    left/kicked. Ошибку запроса (например, пользователь никогда не писал
    боту) трактуем как "не участник", а не падаем — это ожидаемый случай."""
    try:
        member = await get_chat_member(token, chat_id, user_id, client)
    except TelegramAPIError:
        return False
    return member.get("status") in MEMBER_STATUSES


async def set_webhook(
    token: str, url: str, secret_token: str | None, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": url}
    if secret_token:
        payload["secret_token"] = secret_token
    return await _call(token, "setWebhook", payload, client)


def join_deep_link(bot_username: str, giveaway_id: int) -> str:
    return f"https://t.me/{bot_username}?start=join_{giveaway_id}"


def referral_deep_link(bot_username: str, giveaway_id: int, referrer_user_id: str) -> str:
    return f"https://t.me/{bot_username}?start=ref_{giveaway_id}_{referrer_user_id}"


def join_button_markup(bot_username: str, giveaway_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "Участвую 🎉", "url": join_deep_link(bot_username, giveaway_id)}]
        ]
    }
