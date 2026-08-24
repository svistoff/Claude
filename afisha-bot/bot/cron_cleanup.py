"""Крон (раз в сутки): удаляет из хранилища видео прошедших событий и просроченные
по запасному TTL (см. 4.6 ТЗ). Запись в event_videos не удаляется физически —
только помечается deleted=true, прокси по такому токену отдаёт 404.

Запуск: python -m bot.cron_cleanup
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import httpx

from bot.config import config
from bot.services import supabase_client

logger = logging.getLogger(__name__)


async def _delete_telegram_message(channel_message_id: int) -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{config.bot_token}/deleteMessage",
            json={"chat_id": config.storage_channel_id, "message_id": channel_message_id},
        )
    data = resp.json()
    if not data.get("ok"):
        logger.warning("deleteMessage не удался для %s: %s", channel_message_id, data)


async def run() -> None:
    today = date.today()
    event_cutoff = today - timedelta(days=config.event_grace_days)
    fallback_cutoff = today - timedelta(days=config.fallback_ttl_days)

    rows = await supabase_client.get_videos_to_cleanup(event_cutoff, fallback_cutoff)
    logger.info("К удалению: %d видео", len(rows))
    for row in rows:
        try:
            await _delete_telegram_message(row["channel_message_id"])
        except Exception:
            logger.exception("Не удалось удалить сообщение %s в канале-хранилище", row["channel_message_id"])
        await supabase_client.mark_video_deleted(row["id"])
        logger.info("Видео %s (token=%s) помечено удалённым", row["id"], row["token"])


if __name__ == "__main__":
    logging.basicConfig(
        level=config.log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(run())
