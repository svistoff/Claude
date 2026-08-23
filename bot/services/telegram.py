"""Публикация задания в целевой канал: вложения без изменений + новый текст."""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from bot.config import config
from bot.database.models import Job
from bot.services.formatting import format_ai_text

logger = logging.getLogger(__name__)

_PARSE_MODE = "HTML"

# Типы, которые Telegram допускает объединять в альбом (media group)
_ALBUM_MEDIA_TYPES = {"photo", "video", "document", "audio"}

_INPUT_MEDIA_CLS = {
    "photo": InputMediaPhoto,
    "video": InputMediaVideo,
    "document": InputMediaDocument,
    "audio": InputMediaAudio,
}


async def publish_job(bot: Bot, job: Job, text: str | None) -> list[int]:
    """Публикует задание в TARGET_CHANNEL_ID. Возвращает список id опубликованных сообщений.

    `text` — это уже переписанный AI текст (или None, если исходного текста не было).
    Заголовок/подзаголовок в нём оформляются жирным/курсивом автоматически (см. formatting.py).
    """
    chat_id = config.target_channel_id
    attachments = job.attachments
    text = format_ai_text(text) if text else None

    if not attachments:
        if not text:
            raise RuntimeError("Нет ни текста, ни вложений для публикации")
        msg = await bot.send_message(chat_id, text, parse_mode=_PARSE_MODE)
        return [msg.message_id]

    if len(attachments) == 1:
        return await _publish_single(bot, chat_id, attachments[0], text)

    # Несколько вложений: если все типы допускают альбом — публикуем одним media group,
    # иначе (например стикеры вперемешку) — публикуем каждое отдельно, текст последним.
    if all(a["type"] in _ALBUM_MEDIA_TYPES for a in attachments):
        return await _publish_album(bot, chat_id, attachments, text)

    return await _publish_mixed(bot, chat_id, attachments, text)


async def _publish_single(bot: Bot, chat_id: str, attachment: dict[str, Any], text: str | None) -> list[int]:
    a_type = attachment["type"]
    file_id = attachment["file_id"]
    ids: list[int] = []

    if a_type == "sticker":
        # Стикеры не поддерживают caption — публикуем стикер, затем (если есть) текст отдельным сообщением
        msg = await bot.send_sticker(chat_id, file_id)
        ids.append(msg.message_id)
        if text:
            text_msg = await bot.send_message(chat_id, text, parse_mode=_PARSE_MODE)
            ids.append(text_msg.message_id)
        return ids

    send_map = {
        "photo": bot.send_photo,
        "video": bot.send_video,
        "animation": bot.send_animation,
        "document": bot.send_document,
        "audio": bot.send_audio,
        "voice": bot.send_voice,
        "video_note": None,  # video_note не поддерживает caption
    }

    if a_type == "video_note":
        msg = await bot.send_video_note(chat_id, file_id)
        ids.append(msg.message_id)
        if text:
            text_msg = await bot.send_message(chat_id, text, parse_mode=_PARSE_MODE)
            ids.append(text_msg.message_id)
        return ids

    send_func = send_map.get(a_type)
    if send_func is None:
        raise RuntimeError(f"Неизвестный тип вложения: {a_type}")

    msg: Message = await send_func(chat_id, file_id, caption=text, parse_mode=_PARSE_MODE if text else None)
    ids.append(msg.message_id)
    return ids


async def _publish_album(bot: Bot, chat_id: str, attachments: list[dict[str, Any]], text: str | None) -> list[int]:
    media = []
    for idx, a in enumerate(attachments):
        cls = _INPUT_MEDIA_CLS[a["type"]]
        caption = text if idx == 0 else None
        media.append(cls(media=a["file_id"], caption=caption, parse_mode=_PARSE_MODE if caption else None))

    messages = await bot.send_media_group(chat_id, media)
    return [m.message_id for m in messages]


async def _publish_mixed(bot: Bot, chat_id: str, attachments: list[dict[str, Any]], text: str | None) -> list[int]:
    ids: list[int] = []
    for a in attachments:
        sub_ids = await _publish_single(bot, chat_id, a, None)
        ids.extend(sub_ids)
    if text:
        msg = await bot.send_message(chat_id, text, parse_mode=_PARSE_MODE)
        ids.append(msg.message_id)
    return ids
