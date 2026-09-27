"""Приём оплаты Telegram Stars: подтверждение и начисление бонусных сообщений."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery

from companion_bot.config import config
from companion_bot.services.usage import add_bonus_messages

logger = logging.getLogger(__name__)

router = Router(name="payments")


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    user_id = message.from_user.id

    await add_bonus_messages(
        user_id=user_id,
        amount=config.donate_bonus_messages,
        stars_amount=payment.total_amount,
        charge_id=payment.telegram_payment_charge_id,
    )
    logger.info("Оплата %s Stars от пользователя %s", payment.total_amount, user_id)

    await message.answer(
        f"Спасибо! 💛 Добавила тебе +{config.donate_bonus_messages} сообщений на сегодня — пиши 🙂"
    )
