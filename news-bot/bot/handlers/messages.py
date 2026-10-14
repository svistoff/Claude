"""Приём форвардов (текст/фото/видео/альбом) от пользователей из ALLOWED_USER_ID
и передача в буфер альбомов (см. 4.1 ТЗ). Остальных молча игнорируем."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message, MessageOriginChannel

from bot.config import config
from bot.services.albums import AlbumBuffer

logger = logging.getLogger(__name__)

router = Router(name="messages")
router.message.filter(F.from_user.id.in_(config.allowed_user_ids))

album_buffer = AlbumBuffer()

_OTHER_MEDIA = {"animation", "document", "audio", "voice", "video_note"}


def _origin_key(message: Message) -> str | None:
    origin = message.forward_origin
    if isinstance(origin, MessageOriginChannel):
        return f"{origin.chat.id}:{origin.message_id}"
    return None


def _to_part(message: Message) -> dict:
    text = message.text or message.caption
    entities = message.entities if message.text else message.caption_entities
    photo = video = None
    if message.photo:
        photo = {"file_id": message.photo[-1].file_id}
    if message.video:
        video = {"file_id": message.video.file_id, "file_size": message.video.file_size}
    return {
        "message_id": message.message_id,
        "text": text if text and text.strip() else None,
        "entities": [e.model_dump(include={"type", "offset", "length", "url"}) for e in (entities or [])],
        "photo": photo,
        "video": video,
        "other": message.content_type in _OTHER_MEDIA,
        "origin_key": _origin_key(message),
    }


def _is_not_command(message: Message) -> bool:
    return not (message.text and message.text.startswith("/"))


@router.message(F.content_type.in_({"text", "photo", "video", *_OTHER_MEDIA}), _is_not_command)
async def handle_incoming(message: Message) -> None:
    part = _to_part(message)
    kw = {"bot": message.bot, "chat_id": message.chat.id, "user_id": message.from_user.id, "part": part}
    if message.media_group_id:
        await album_buffer.handle_album_part(media_group_id=message.media_group_id, **kw)
    else:
        await album_buffer.handle_single(**kw)
