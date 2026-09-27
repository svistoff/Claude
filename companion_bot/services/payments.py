"""Инвойсы на Telegram Stars: продление дневного лимита и мгновенный ответ вне очереди."""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import LabeledPrice

from companion_bot.config import config

EXTRA_MESSAGES_PAYLOAD = "extra_messages"
PRIORITY_REPLY_PAYLOAD = "priority_reply"


async def send_extra_messages_invoice(bot: Bot, chat_id: int) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title="Продолжить общение",
        description=(
            f"+{config.donate_bonus_messages} сообщений сегодня — "
            "чтобы пообщаться ещё, без ожидания до завтра."
        ),
        payload=EXTRA_MESSAGES_PAYLOAD,
        # Для Telegram Stars provider_token обязателен, но пустой
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Продолжить общение", amount=config.donate_stars_price)],
    )


async def send_priority_reply_invoice(bot: Bot, chat_id: int) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title="Ответить сейчас",
        description="Не ждать, пока освобожусь — получить ответ прямо сейчас.",
        payload=PRIORITY_REPLY_PAYLOAD,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Ответить сейчас", amount=config.priority_reply_stars_price)],
    )
