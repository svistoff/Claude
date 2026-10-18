"""Буферизация альбомов (media_group): собираем части в одну заявку перед обработкой,
с окном ожидания и сбросом таймера на каждый новый элемент — тот же подход, что и в
repost-bot (bot/services/albums.py), адаптированный под прямую обработку без очереди."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.types import Message

from bot.config import config
from bot.services import pipeline

logger = logging.getLogger(__name__)

# Ограничивает число одновременно обрабатываемых заявок (AI + заливка видео в
# канал-хранилище + запись в Supabase) — при массовой пересылке анонсов пачкой
# защищает от антифлуда Telegram на канале-хранилище и всплеска запросов к OpenAI.
# Лишние заявки просто ждут своей очереди в памяти, ничего не теряется.
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

    async def handle_single(
        self, *, message: Message, text: str | None, photo: dict | None, video: dict | None,
        subtitle: str | None = None,
    ) -> None:
        await self._finalize(
            message.bot, message.chat.id, message.from_user.id,
            [{"text": text, "photo": photo, "video": video, "subtitle": subtitle}],
        )

    async def handle_album_part(
        self, *, message: Message, media_group_id: str,
        text: str | None, photo: dict | None, video: dict | None, subtitle: str | None = None,
    ) -> None:
        part = {"text": text, "photo": photo, "video": video, "subtitle": subtitle}
        async with self._lock:
            pending = self._pending.get(media_group_id)
            if pending is None:
                pending = _PendingAlbum(bot=message.bot, chat_id=message.chat.id, user_id=message.from_user.id)
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
            except Exception as exc:
                logger.exception("Ошибка обработки анонса от пользователя %s", user_id)
                reply = "⚠️ Не получилось обработать анонс.\n" + _failure_reason(exc)
        await bot.send_message(chat_id, reply)


def _failure_reason(exc: Exception) -> str:
    """Причина сбоя человеческими словами + короткая техническая деталь — чтобы
    админ сразу видел, что пошло не так, а не лез в логи. Бот отвечает только
    админам из whitelist, так что текст ошибки показывать можно (ключей в нём нет)."""
    text = str(exc)
    detail = text
    if text.startswith("Supabase "):
        # формат _check(): "Supabase <METHOD> <url> -> <code>: <тело ответа>"
        head, _, body = text.partition(": ")
        try:
            data = json.loads(body)
            detail = data.get("message") or data.get("error") or body
        except ValueError:
            detail = body or head
        if "/storage/" in head:
            where = "Хранилище картинок не приняло обложку"
        elif "event_submissions" in head:
            where = "База афиши не приняла заявку"
        elif "event_videos" in head:
            where = "База не приняла запись о видео"
        else:
            where = "Ошибка базы афиши (Supabase)"
    elif type(exc).__module__.startswith("openai"):
        where = "AI (OpenAI) не ответил — возможно, кончился баланс или сбой сервиса"
    elif type(exc).__module__.startswith("aiogram"):
        where = "Telegram не дал скачать или переслать медиа"
    elif type(exc).__module__.startswith(("httpx", "httpcore")):
        where = "Сеть: не удалось достучаться до сервиса"
    else:
        where = "Внутренняя ошибка бота"
    detail = " ".join(detail.split())[:300]
    return f"Причина: {where}.\nДетали: {type(exc).__name__}: {detail}\nПопробуйте ещё раз; если повторяется — перешлите это сообщение разработчику."
