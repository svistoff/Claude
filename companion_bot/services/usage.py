"""Дневной бесплатный лимит сообщений + бонусные сообщения, купленные за Stars."""
from __future__ import annotations

import logging

from companion_bot.config import config
from companion_bot.database.database import get_conn
from companion_bot.utils import now_str

logger = logging.getLogger(__name__)


def _today() -> str:
    return now_str()[:10]


async def ensure_user(user_id: int) -> None:
    conn = get_conn()
    await conn.execute(
        "INSERT INTO users (user_id, free_messages_date) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO NOTHING",
        (user_id, _today()),
    )
    await conn.commit()


async def try_consume_message(user_id: int) -> bool:
    """Списывает одно сообщение (бесплатное или бонусное).

    Возвращает True, если персонажу разрешено ответить, False — если
    бесплатный дневной лимит исчерпан и бонусных сообщений не осталось.
    """
    conn = get_conn()
    today = _today()

    cur = await conn.execute(
        "SELECT free_messages_used, free_messages_date, bonus_messages "
        "FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = await cur.fetchone()
    if row is None:
        await ensure_user(user_id)
        free_used, free_date, bonus = 0, today, 0
    else:
        free_used, free_date, bonus = (
            row["free_messages_used"],
            row["free_messages_date"],
            row["bonus_messages"],
        )

    if free_date != today:
        free_used = 0
        free_date = today

    if free_used < config.free_messages_per_day:
        await conn.execute(
            "UPDATE users SET free_messages_used = ?, free_messages_date = ? WHERE user_id = ?",
            (free_used + 1, free_date, user_id),
        )
        await conn.commit()
        return True

    if bonus > 0:
        await conn.execute(
            "UPDATE users SET bonus_messages = ?, free_messages_date = ? WHERE user_id = ?",
            (bonus - 1, free_date, user_id),
        )
        await conn.commit()
        return True

    await conn.execute(
        "UPDATE users SET free_messages_date = ? WHERE user_id = ?",
        (free_date, user_id),
    )
    await conn.commit()
    return False


async def record_payment(
    user_id: int, stars_amount: int, bonus_messages_granted: int, charge_id: str | None
) -> None:
    conn = get_conn()
    await conn.execute(
        "INSERT INTO payments (user_id, stars_amount, bonus_messages_granted, "
        "telegram_payment_charge_id) VALUES (?, ?, ?, ?)",
        (user_id, stars_amount, bonus_messages_granted, charge_id),
    )
    await conn.execute(
        "UPDATE users SET total_stars_paid = total_stars_paid + ? WHERE user_id = ?",
        (stars_amount, user_id),
    )
    await conn.commit()


async def add_bonus_messages(
    user_id: int, amount: int, stars_amount: int, charge_id: str | None
) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE users SET bonus_messages = bonus_messages + ? WHERE user_id = ?",
        (amount, user_id),
    )
    await record_payment(user_id, stars_amount, amount, charge_id)
    logger.info(
        "Пользователю %s начислено +%s бонусных сообщений за %s Stars",
        user_id, amount, stars_amount,
    )
