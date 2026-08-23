"""Буферизация альбомов (media_group): собираем все части в одно задание
перед постановкой в очередь, с окном ожидания и сбросом таймера на каждый новый элемент."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from bot.config import config
from bot.services import queue as queue_service

logger = logging.getLogger(__name__)


@dataclass
class _PendingAlbum:
    job_id: int
    timer_task: asyncio.Task


class AlbumBuffer:
    """Хранит в памяти активные окна ожидания альбомов по media_group_id."""

    def __init__(self) -> None:
        self._pending: dict[str, _PendingAlbum] = {}
        self._lock = asyncio.Lock()

    async def handle_single(
        self,
        *,
        source_chat_id: int,
        source_message_id: int,
        user_id: int,
        text: str | None,
        attachment: dict[str, Any] | None,
    ) -> int:
        """Обычное сообщение (не альбом) — сразу создаём и ставим в очередь."""
        job_id = await queue_service.create_job(
            media_group_id=None,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            user_id=user_id,
            text=text,
            attachment=attachment,
        )
        await queue_service.mark_queued(job_id)
        return job_id

    async def handle_album_part(
        self,
        *,
        media_group_id: str,
        source_chat_id: int,
        source_message_id: int,
        user_id: int,
        text: str | None,
        attachment: dict[str, Any] | None,
    ) -> int:
        """Часть альбома: копим в буфере и (пере)запускаем таймер финализации."""
        async with self._lock:
            pending = self._pending.get(media_group_id)
            if pending is None:
                job_id = await queue_service.create_job(
                    media_group_id=media_group_id,
                    source_chat_id=source_chat_id,
                    source_message_id=source_message_id,
                    user_id=user_id,
                    text=text,
                    attachment=attachment,
                )
                timer_task = asyncio.create_task(self._finalize_after_delay(media_group_id))
                self._pending[media_group_id] = _PendingAlbum(job_id=job_id, timer_task=timer_task)
                return job_id

            job_id = pending.job_id
            await queue_service.append_to_job(
                job_id,
                source_message_id=source_message_id,
                text=text,
                attachment=attachment,
            )
            pending.timer_task.cancel()
            pending.timer_task = asyncio.create_task(self._finalize_after_delay(media_group_id))
            return job_id

    async def _finalize_after_delay(self, media_group_id: str) -> None:
        try:
            await asyncio.sleep(config.album_window_seconds)
        except asyncio.CancelledError:
            return  # таймер сброшен — пришёл новый элемент альбома

        async with self._lock:
            pending = self._pending.pop(media_group_id, None)
        if pending is None:
            return
        logger.info("[job %s] альбом %s собран, финализация", pending.job_id, media_group_id)
        await queue_service.mark_queued(pending.job_id)
