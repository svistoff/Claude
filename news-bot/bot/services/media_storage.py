"""Медиа-хранилище на Telegram: копирование фото/видео (по file_id, без
скачивания и перезаливки) в приватный канал-хранилище, общий с афишей
(см. 4.3 ТЗ). Байты браузеру потом отдаёт прокси /m/<token>."""
from __future__ import annotations

import asyncio
import logging
import secrets

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InputMediaPhoto, InputMediaVideo, Message

from bot.config import config

logger = logging.getLogger(__name__)


async def _retry_on_flood(call, attempts: int = 3):
    """Антифлуд Telegram: ждём сколько попросили и повторяем."""
    for i in range(attempts):
        try:
            return await call()
        except TelegramRetryAfter as exc:
            if i == attempts - 1:
                raise
            logger.warning("Антифлуд Telegram, ждём %s с", exc.retry_after)
            await asyncio.sleep(exc.retry_after + 1)


def _stored(msg: Message, kind: str) -> dict:
    if kind == "photo":
        p = msg.photo[-1]
        meta = {"file_id": p.file_id, "width": p.width, "height": p.height, "duration": None}
    else:
        v = msg.video
        meta = {"file_id": v.file_id, "width": v.width, "height": v.height, "duration": v.duration}
    return {"kind": kind, "channel_message_id": msg.message_id, **meta}


async def copy_to_channel(bot: Bot, items: list[dict]) -> list[dict]:
    """items: [{'kind': 'photo'|'video', 'file_id': ...}] в порядке поста (≤10).
    Возвращает те же элементы с file_id копии, channel_message_id и токеном."""
    if not items:
        return []
    chat = config.storage_channel_id
    if len(items) == 1:
        it = items[0]
        if it["kind"] == "photo":
            msg = await _retry_on_flood(lambda: bot.send_photo(chat_id=chat, photo=it["file_id"]))
        else:
            msg = await _retry_on_flood(lambda: bot.send_video(chat_id=chat, video=it["file_id"]))
        sent = [msg]
    else:
        group = [
            InputMediaPhoto(media=it["file_id"]) if it["kind"] == "photo" else InputMediaVideo(media=it["file_id"])
            for it in items
        ]
        sent = await _retry_on_flood(lambda: bot.send_media_group(chat_id=chat, media=group))

    stored = []
    for it, msg in zip(items, sent):
        if (it["kind"] == "photo" and not msg.photo) or (it["kind"] == "video" and not msg.video):
            await delete_from_channel(bot, [m.message_id for m in sent])
            raise RuntimeError(f"Telegram вернул в канале не {it['kind']} (message_id={msg.message_id})")
        stored.append({**_stored(msg, it["kind"]), "token": secrets.token_urlsafe(9)})
    return stored


async def delete_from_channel(bot: Bot, message_ids: list[int]) -> None:
    """Удаляет сообщения из канала-хранилища; ошибки не фатальны (уже удалено и т.п.)."""
    for mid in message_ids:
        try:
            await _retry_on_flood(lambda: bot.delete_message(chat_id=config.storage_channel_id, message_id=mid))
        except TelegramBadRequest as exc:
            logger.warning("Не удалось удалить сообщение %s из канала-хранилища: %s", mid, exc)


def public_url(token: str) -> str:
    return f"{config.media_public_base}/m/{token}"
