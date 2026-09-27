"""Фоновые задачи: доставка отложенных ("занята") ответов и проактивные сообщения.

Оба цикла реализованы через периодический опрос БД (как очередь в bot/), а
не через asyncio.sleep на каждое сообщение — так отложенные ответы
переживают перезапуск бота: непросроченные задания просто ждут следующего
опроса, просроченные (send_at уже в прошлом) доставляются на первом же тике.
"""
from __future__ import annotations

import asyncio
import logging
import random

from aiogram import Bot

from companion_bot.config import config
from companion_bot.database.database import get_conn
from companion_bot.persona import DEFAULT_PERSONA
from companion_bot.services import history as history_service
from companion_bot.services import memory as memory_service
from companion_bot.services.ai import generate_proactive_message, generate_reply
from companion_bot.utils import hours_ago_str, now_str

logger = logging.getLogger(__name__)


async def deliver_pending_reply(bot: Bot, pending_id: int) -> None:
    """Генерирует и отправляет отложенный ответ. Используется циклом и оплатой 'ответить сейчас'."""
    conn = get_conn()
    cur = await conn.execute(
        "SELECT user_id, chat_id, user_message, status FROM pending_replies WHERE id = ?",
        (pending_id,),
    )
    row = await cur.fetchone()
    if row is None or row["status"] != "PENDING":
        return

    user_id, chat_id, user_message = row["user_id"], row["chat_id"], row["user_message"]
    persona = DEFAULT_PERSONA

    history = await history_service.get_recent_history(user_id)
    memory_summary = await memory_service.get_memory_summary(user_id)

    try:
        reply = await generate_reply(persona, history, user_message, memory_summary)
    except Exception:
        logger.exception("Не удалось сгенерировать отложенный ответ для пользователя %s", user_id)
        return

    await history_service.save_message(user_id, "user", user_message)
    await history_service.save_message(user_id, "assistant", reply)

    await conn.execute("UPDATE pending_replies SET status = 'SENT' WHERE id = ?", (pending_id,))
    await conn.commit()

    await bot.send_message(chat_id, reply)
    await memory_service.maybe_update_memory(persona, user_id)


async def _pending_replies_loop(bot: Bot) -> None:
    while True:
        try:
            conn = get_conn()
            cur = await conn.execute(
                "SELECT id FROM pending_replies WHERE status = 'PENDING' AND send_at <= ?",
                (now_str(),),
            )
            due = await cur.fetchall()
            for row in due:
                await deliver_pending_reply(bot, row["id"])
        except Exception:
            logger.exception("Ошибка в цикле доставки отложенных ответов")
        await asyncio.sleep(config.pending_reply_poll_seconds)


async def _run_proactive_check(bot: Bot) -> None:
    conn = get_conn()
    earliest_allowed = hours_ago_str(config.proactive_max_hours_since_last_message)
    latest_allowed = hours_ago_str(config.proactive_min_hours_since_last_message)
    cooldown_before = hours_ago_str(24)

    cur = await conn.execute(
        """
        SELECT u.user_id, u.memory_summary, MAX(m.created_at) AS last_message_at
        FROM users u
        JOIN messages m ON m.user_id = u.user_id AND m.role = 'user'
        WHERE u.last_proactive_at IS NULL OR u.last_proactive_at <= ?
        GROUP BY u.user_id
        HAVING last_message_at <= ? AND last_message_at >= ?
        """,
        (cooldown_before, latest_allowed, earliest_allowed),
    )
    candidates = await cur.fetchall()

    for row in candidates:
        if random.random() > config.proactive_probability:
            continue

        user_id = row["user_id"]
        persona = DEFAULT_PERSONA
        try:
            text = await generate_proactive_message(persona, row["memory_summary"] or "")
        except Exception:
            logger.exception("Не удалось сгенерировать проактивное сообщение для %s", user_id)
            continue

        try:
            await bot.send_message(user_id, text)
        except Exception:
            logger.exception("Не удалось отправить проактивное сообщение пользователю %s", user_id)
            continue

        await history_service.save_message(user_id, "assistant", text)
        await conn.execute(
            "UPDATE users SET last_proactive_at = ? WHERE user_id = ?",
            (now_str(), user_id),
        )
        await conn.commit()


async def _proactive_messages_loop(bot: Bot) -> None:
    while True:
        try:
            await _run_proactive_check(bot)
        except Exception:
            logger.exception("Ошибка в цикле проактивных сообщений")
        await asyncio.sleep(config.proactive_check_interval_seconds)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    return [
        asyncio.create_task(_pending_replies_loop(bot)),
        asyncio.create_task(_proactive_messages_loop(bot)),
    ]
