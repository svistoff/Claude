"""Приём пересланных постов (текст/фото/альбом/видео/GIF/документ/...) и постановка в очередь."""
from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import Message

from bot.config import config
from bot.services.albums import AlbumBuffer
from bot.services.queue import find_duplicate

logger = logging.getLogger(__name__)

router = Router(name="messages")
album_buffer = AlbumBuffer()


def _extract_attachment(message: Message) -> dict[str, Any] | None:
    """Определяет тип и file_id вложения сообщения (если есть)."""
    if message.photo:
        return {"type": "photo", "file_id": message.photo[-1].file_id}
    if message.video:
        return {"type": "video", "file_id": message.video.file_id}
    if message.animation:
        return {"type": "animation", "file_id": message.animation.file_id}
    if message.document:
        return {
            "type": "document",
            "file_id": message.document.file_id,
            "file_name": message.document.file_name,
        }
    if message.audio:
        return {"type": "audio", "file_id": message.audio.file_id}
    if message.voice:
        return {"type": "voice", "file_id": message.voice.file_id}
    if message.video_note:
        return {"type": "video_note", "file_id": message.video_note.file_id}
    if message.sticker:
        return {"type": "sticker", "file_id": message.sticker.file_id}
    return None


def _extract_text(message: Message) -> str | None:
    text = message.text or message.caption
    return text.strip() if text and text.strip() else None


def _is_not_command(message: Message) -> bool:
    return not (message.text and message.text.startswith("/"))


@router.message(
    F.from_user.id.in_(config.allowed_user_ids),
    F.content_type.in_({
        "text", "photo", "video", "animation", "document", "audio", "voice", "video_note", "sticker",
    }),
    _is_not_command,
)
async def handle_incoming_post(message: Message) -> None:
    text = _extract_text(message)
    attachment = _extract_attachment(message)

    if text is None and attachment is None:
        logger.info("Сообщение %s пропущено: нет ни текста, ни поддерживаемого вложения", message.message_id)
        return

    if config.duplicate_protection:
        dup = await find_duplicate(
            media_group_id=message.media_group_id,
            source_message_id=message.message_id,
            user_id=message.from_user.id,
        )
        if dup is not None:
            logger.warning(
                "Возможный дубль: сообщение %s похоже на уже существующее задание #%s (статус=%s)",
                message.message_id, dup.id, dup.status,
            )
            await message.reply(
                f"⚠️ Похоже, это уже было отправлено ранее (задание #{dup.id}, статус {dup.status}). "
                "Всё равно добавляю в очередь."
            )

    if message.media_group_id:
        job_id = await album_buffer.handle_album_part(
            media_group_id=message.media_group_id,
            source_chat_id=message.chat.id,
            source_message_id=message.message_id,
            user_id=message.from_user.id,
            text=text,
            attachment=attachment,
        )
    else:
        job_id = await album_buffer.handle_single(
            source_chat_id=message.chat.id,
            source_message_id=message.message_id,
            user_id=message.from_user.id,
            text=text,
            attachment=attachment,
        )

    logger.debug("Сообщение %s обработано, job_id=%s", message.message_id, job_id)
