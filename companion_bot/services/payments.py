"""Инвойс на Telegram Stars за продление общения сверх дневного лимита."""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import LabeledPrice

from companion_bot.config import config

DONATE_PAYLOAD = "extra_messages"


async def send_donate_invoice(bot: Bot, chat_id: int) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title="Продолжить общение",
        description=(
            f"+{config.donate_bonus_messages} сообщений сегодня — "
            "чтобы пообщаться ещё, без ожидания до завтра."
        ),
        payload=DONATE_PAYLOAD,
        # Для Telegram Stars provider_token обязателен, но пустой
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Продолжить общение", amount=config.donate_stars_price)],
    )
