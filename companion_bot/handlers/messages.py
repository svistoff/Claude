"""Обработка входящих текстовых сообщений: лимит, "занятость", AI-ответ, память."""
from __future__ import annotations

import logging
import random

from aiogram import F, Router
from aiogram.types import Message

from companion_bot.config import config
from companion_bot.database.database import get_conn
from companion_bot.persona import DEFAULT_PERSONA
from companion_bot.services import history as history_service
from companion_bot.services import memory as memory_service
from companion_bot.services import payments as payments_service
from companion_bot.services import usage as usage_service
from companion_bot.services.ai import generate_reply
from companion_bot.utils import now_str_plus_minutes

logger = logging.getLogger(__name__)

router = Router(name="messages")

_LIMIT_REACHED_TEXT = (
    "Ой, у меня на сегодня закончилось время для бесплатного общения 🙈\n\n"
    "Если хочешь пообщаться ещё сегодня, а не ждать до завтра — можешь "
    "закинуть донат ⭐, и я отвечу прямо сейчас."
)

_BUSY_TEXT = (
    "Ой, извини, сейчас не могу сразу ответить — занята 🙈 Отвечу, как только "
    "освобожусь. Если не хочешь ждать — можно закинуть донат ⭐, и я отвечу сейчас."
)


async def _schedule_busy_reply(user_id: int, chat_id: int, user_message: str) -> None:
    delay_minutes = random.uniform(config.busy_delay_min_minutes, config.busy_delay_max_minutes)
    send_at = now_str_plus_minutes(delay_minutes)

    conn = get_conn()
    await conn.execute(
        "INSERT INTO pending_replies (user_id, chat_id, user_message, send_at) "
        "VALUES (?, ?, ?, ?)",
        (user_id, chat_id, user_message, send_at),
    )
    await conn.commit()


@router.message(F.text, ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text

    await usage_service.ensure_user(user_id)

    allowed = await usage_service.try_consume_message(user_id)
    if not allowed:
        await message.answer(_LIMIT_REACHED_TEXT)
        await payments_service.send_extra_messages_invoice(message.bot, chat_id)
        return

    if random.random() < config.busy_probability:
        await message.answer(_BUSY_TEXT)
        await _schedule_busy_reply(user_id, chat_id, text)
        await payments_service.send_priority_reply_invoice(message.bot, chat_id)
        return

    history = await history_service.get_recent_history(user_id)
    memory_summary = await memory_service.get_memory_summary(user_id)

    try:
        reply = await generate_reply(DEFAULT_PERSONA, history, text, memory_summary)
    except Exception:
        logger.exception("Ошибка генерации ответа для пользователя %s", user_id)
        await message.answer("Ой, что-то пошло не так, напиши ещё раз чуть позже 🙏")
        return

    await history_service.save_message(user_id, "user", text)
    await history_service.save_message(user_id, "assistant", reply)

    await message.answer(reply)

    await memory_service.maybe_update_memory(DEFAULT_PERSONA, user_id)
