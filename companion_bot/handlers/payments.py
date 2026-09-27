"""Приём оплаты Telegram Stars: продление дневного лимита или мгновенный ответ вне очереди."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery

from companion_bot.config import config
from companion_bot.database.database import get_conn
from companion_bot.services import usage as usage_service
from companion_bot.services.payments import PRIORITY_REPLY_PAYLOAD
from companion_bot.worker.scheduler import deliver_pending_reply

logger = logging.getLogger(__name__)

router = Router(name="payments")


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    user_id = message.from_user.id

    if payment.invoice_payload == PRIORITY_REPLY_PAYLOAD:
        await usage_service.record_payment(
            user_id=user_id,
            stars_amount=payment.total_amount,
            bonus_messages_granted=0,
            charge_id=payment.telegram_payment_charge_id,
        )
        logger.info("Оплата %s Stars (priority_reply) от пользователя %s", payment.total_amount, user_id)

        conn = get_conn()
        cur = await conn.execute(
            "SELECT id FROM pending_replies WHERE user_id = ? AND status = 'PENDING' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cur.fetchone()
        if row is not None:
            await deliver_pending_reply(message.bot, row["id"])
        else:
            await message.answer("Спасибо! 💛 Но ждать сейчас нечего — напиши мне что-нибудь 🙂")
        return

    await usage_service.add_bonus_messages(
        user_id=user_id,
        amount=config.donate_bonus_messages,
        stars_amount=payment.total_amount,
        charge_id=payment.telegram_payment_charge_id,
    )
    logger.info("Оплата %s Stars (extra_messages) от пользователя %s", payment.total_amount, user_id)

    await message.answer(
        f"Спасибо! 💛 Добавила тебе +{config.donate_bonus_messages} сообщений на сегодня — пиши 🙂"
    )
