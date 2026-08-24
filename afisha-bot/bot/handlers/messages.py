"""Приём форвардов (текст/фото/альбом/видео) от пользователей из ALLOWED_USER_ID
и передача в буфер альбомов (см. 3.1 ТЗ)."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from bot.config import config
from bot.services.albums import AlbumBuffer

logger = logging.getLogger(__name__)

router = Router(name="messages")
router.message.filter(F.from_user.id.in_(config.allowed_user_ids))

album_buffer = AlbumBuffer()


def _extract_text(message: Message) -> str | None:
    text = message.text or message.caption
    return text.strip() if text and text.strip() else None


def _extract_photo(message: Message) -> dict | None:
    if not message.photo:
        return None
    largest = message.photo[-1]
    return {"file_id": largest.file_id}


def _extract_video(message: Message) -> dict | None:
    if not message.video:
        return None
    return {"file_id": message.video.file_id, "file_size": message.video.file_size}


def _is_not_command(message: Message) -> bool:
    return not (message.text and message.text.startswith("/"))


@router.message(F.content_type.in_({"text", "photo", "video"}), _is_not_command)
async def handle_incoming(message: Message) -> None:
    text = _extract_text(message)
    photo = _extract_photo(message)
    video = _extract_video(message)

    if text is None and photo is None and video is None:
        logger.info("Сообщение %s пропущено: нет ни текста, ни фото/видео", message.message_id)
        return

    if message.media_group_id:
        await album_buffer.handle_album_part(
            message=message, media_group_id=message.media_group_id, text=text, photo=photo, video=video,
        )
    else:
        await album_buffer.handle_single(message=message, text=text, photo=photo, video=video)
