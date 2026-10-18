"""Приём форвардов (текст/фото/альбом/видео) от пользователей из ALLOWED_USER_ID
и передача в буфер альбомов (см. 3.1 ТЗ)."""
from __future__ import annotations

import html
import logging
import re

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


# Посты aireposter оформлены так: <b>заголовок</b>, следом строкой <i>подзаголовок</i>
# (хук до ~70 символов), дальше текст. Подзаголовок берём как есть в краткое описание.
_SUBTITLE_RE = re.compile(r"^\s*<b>.*?</b>\s*\n\s*<i>(.+?)</i>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _extract_subtitle(message: Message) -> str | None:
    try:
        rendered = message.html_text  # text/caption + entities → HTML
    except Exception:
        return None
    m = _SUBTITLE_RE.match(rendered or "")
    if not m:
        return None
    subtitle = " ".join(html.unescape(_TAG_RE.sub("", m.group(1))).split())
    return subtitle or None


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
    subtitle = _extract_subtitle(message) if text else None
    photo = _extract_photo(message)
    video = _extract_video(message)

    if text is None and photo is None and video is None:
        logger.info("Сообщение %s пропущено: нет ни текста, ни фото/видео", message.message_id)
        return

    if message.media_group_id:
        await album_buffer.handle_album_part(
            message=message, media_group_id=message.media_group_id, text=text, photo=photo, video=video,
            subtitle=subtitle,
        )
    else:
        await album_buffer.handle_single(message=message, text=text, photo=photo, video=video, subtitle=subtitle)
