"""Долгосрочная память: периодическое обновление краткой сводки фактов о пользователе.

Вместо хранения всей переписки как равнозначного контекста, раз в
`MEMORY_SUMMARY_EVERY_N_MESSAGES` новых сообщений сводка фактов о
пользователе (users.memory_summary) обновляется через отдельный вызов AI и
дальше передаётся в system prompt вместе с последними сообщениями
(services/history.py), а не вместо них.
"""
from __future__ import annotations

import logging

from companion_bot.config import config
from companion_bot.database.database import get_conn
from companion_bot.persona import Persona
from companion_bot.services.ai import summarize_memory

logger = logging.getLogger(__name__)


async def get_memory_summary(user_id: int) -> str:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT memory_summary FROM users WHERE user_id = ?", (user_id,)
    )
    row = await cur.fetchone()
    return (row["memory_summary"] or "") if row else ""


async def maybe_update_memory(persona: Persona, user_id: int) -> None:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT memory_summary, last_summary_message_id FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return
    summary, last_id = row["memory_summary"] or "", row["last_summary_message_id"] or 0

    cur = await conn.execute(
        "SELECT id, role, content FROM messages WHERE user_id = ? AND id > ? ORDER BY id",
        (user_id, last_id),
    )
    new_rows = await cur.fetchall()
    if len(new_rows) < config.memory_summary_every_n_messages:
        return

    new_messages_text = "\n".join(
        f"{'Пользователь' if r['role'] == 'user' else persona.name}: {r['content']}"
        for r in new_rows
    )
    latest_id = new_rows[-1]["id"]

    try:
        updated_summary = await summarize_memory(summary, new_messages_text)
    except Exception:
        logger.exception("Не удалось обновить долгосрочную память для пользователя %s", user_id)
        return

    await conn.execute(
        "UPDATE users SET memory_summary = ?, last_summary_message_id = ? WHERE user_id = ?",
        (updated_summary, latest_id, user_id),
    )
    await conn.commit()
    logger.info("Память пользователя %s обновлена (до сообщения #%s)", user_id, latest_id)
