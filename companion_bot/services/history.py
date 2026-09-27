"""Хранение и выборка истории переписки для контекста AI."""
from __future__ import annotations

from companion_bot.config import config
from companion_bot.database.database import get_conn


async def get_recent_history(user_id: int) -> list[dict[str, str]]:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, config.history_limit),
    )
    rows = await cur.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def save_message(user_id: int, role: str, content: str) -> None:
    conn = get_conn()
    await conn.execute(
        "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content),
    )
    await conn.commit()
