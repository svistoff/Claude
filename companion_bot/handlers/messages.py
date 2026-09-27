"""Обработка входящих текстовых сообщений: лимит, AI-ответ, история."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from companion_bot.persona import DEFAULT_PERSONA
from companion_bot.services import history as history_service
from companion_bot.services import payments as payments_service
from companion_bot.services import usage as usage_service
from companion_bot.services.ai import generate_reply

logger = logging.getLogger(__name__)

router = Router(name="messages")

_LIMIT_REACHED_TEXT = (
    "Ой, у меня на сегодня закончилось время для бесплатного общения 🙈\n\n"
    "Если хочешь пообщаться ещё сегодня, а не ждать до завтра — можешь "
    "закинуть донат ⭐, и я отвечу прямо сейчас."
)


@router.message(F.text, ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    user_id = message.from_user.id
    await usage_service.ensure_user(user_id)

    allowed = await usage_service.try_consume_message(user_id)
    if not allowed:
        await message.answer(_LIMIT_REACHED_TEXT)
        await payments_service.send_donate_invoice(message.bot, message.chat.id)
        return

    history = await history_service.get_recent_history(user_id)

    try:
        reply = await generate_reply(DEFAULT_PERSONA, history, message.text)
    except Exception:
        logger.exception("Ошибка генерации ответа для пользователя %s", user_id)
        await message.answer("Ой, что-то пошло не так, напиши ещё раз чуть позже 🙏")
        return

    await history_service.save_message(user_id, "user", message.text)
    await history_service.save_message(user_id, "assistant", reply)

    await message.answer(reply)
