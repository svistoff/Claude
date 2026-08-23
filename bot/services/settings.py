"""Хранилище простых настроек key/value в SQLite (используется для системного промта)."""
from __future__ import annotations

from bot.database.database import get_conn


async def get_setting(key: str) -> str | None:
    conn = get_conn()
    cur = await conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    conn = get_conn()
    await conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await conn.commit()


async def get_prompt() -> str:
    prompt = await get_setting("prompt")
    return prompt or ""


async def set_prompt(prompt: str) -> None:
    await set_setting("prompt", prompt)
