"""Буферизация альбомов (media_group): собираем части в одну новость перед
обработкой, с окном ожидания и сбросом таймера на каждый новый элемент — тот же
подход, что и в afisha-bot/bot/services/albums.py."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.types import LinkPreviewOptions, ReplyParameters

from bot.config import config
from bot.services import pipeline

logger = logging.getLogger(__name__)

# Ограничивает число одновременно обрабатываемых новостей (AI + копирование медиа
# в канал-хранилище + запись в Supabase) — при пересылке пачкой защищает от
# антифлуда Telegram на канале-хранилище. Лишние ждут очереди в памяти.
_processing_semaphore = asyncio.Semaphore(config.max_concurrent_submissions)


@dataclass
class _PendingAlbum:
    bot: Bot
    chat_id: int
    user_id: int
    parts: list[dict[str, Any]] = field(default_factory=list)
    timer_task: asyncio.Task | None = None


class AlbumBuffer:
    """Хранит в памяти активные окна ожидания альбомов по media_group_id."""

    def __init__(self) -> None:
        self._pending: dict[str, _PendingAlbum] = {}
        self._lock = asyncio.Lock()

    async def handle_single(self, *, bot: Bot, chat_id: int, user_id: int, part: dict[str, Any]) -> None:
        await self._finalize(bot, chat_id, user_id, [part])

    async def handle_album_part(
        self, *, bot: Bot, chat_id: int, user_id: int, media_group_id: str, part: dict[str, Any],
    ) -> None:
        async with self._lock:
            pending = self._pending.get(media_group_id)
            if pending is None:
                pending = _PendingAlbum(bot=bot, chat_id=chat_id, user_id=user_id)
                self._pending[media_group_id] = pending
            pending.parts.append(part)
            if pending.timer_task:
                pending.timer_task.cancel()
            pending.timer_task = asyncio.create_task(self._finalize_after_delay(media_group_id))

    async def _finalize_after_delay(self, media_group_id: str) -> None:
        try:
            await asyncio.sleep(config.album_window_seconds)
        except asyncio.CancelledError:
            return  # таймер сброшен — пришёл новый элемент альбома

        async with self._lock:
            pending = self._pending.pop(media_group_id, None)
        if pending is None:
            return
        await self._finalize(pending.bot, pending.chat_id, pending.user_id, pending.parts)

    async def _finalize(self, bot: Bot, chat_id: int, user_id: int, parts: list[dict[str, Any]]) -> None:
        async with _processing_semaphore:
            try:
                reply = await pipeline.process_submission(bot, user_id, parts)
            except Exception:
                logger.exception("Ошибка обработки новости от пользователя %s", user_id)
                reply = pipeline.Reply("⚠️ Не получилось опубликовать новость, попробуйте ещё раз.")
        first_id = min(p["message_id"] for p in parts)
        try:
            await bot.send_message(
                chat_id, reply.text, reply_markup=reply.keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True),
                reply_parameters=ReplyParameters(message_id=first_id, allow_sending_without_reply=True),
            )
        except Exception:
            logger.exception("Не удалось отправить ответ пользователю %s", user_id)
