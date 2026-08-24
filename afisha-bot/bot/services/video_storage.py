"""Видео-хранилище на Telegram: пересылка видео (по file_id, без скачивания и
перезаливки) в приватный канал-хранилище, токен, запись в event_videos (см. 4.2 ТЗ)."""
from __future__ import annotations

import logging
import secrets

from aiogram import Bot

from bot.config import config
from bot.services import supabase_client

logger = logging.getLogger(__name__)


async def store_video(bot: Bot, file_id: str, event_date: str | None, telegram_user_id: int) -> str:
    """Копирует видео в канал-хранилище и возвращает публичную ссылку на прокси."""
    sent = await bot.send_video(chat_id=config.storage_channel_id, video=file_id)
    if sent.video is None:
        raise RuntimeError("Telegram не вернул video в скопированном сообщении")

    token = secrets.token_urlsafe(9)  # ~12 символов, см. 4.2 ТЗ
    await supabase_client.insert_event_video({
        "token": token,
        "file_id": sent.video.file_id,
        "channel_message_id": sent.message_id,
        "telegram_user_id": telegram_user_id,
        "event_date": event_date,
    })
    return f"{config.video_public_base}/v/{token}"
