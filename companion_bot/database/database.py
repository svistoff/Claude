"""Подключение к SQLite и миграции (CREATE TABLE IF NOT EXISTS)."""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from companion_bot.config import config

logger = logging.getLogger(__name__)

_conn: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    persona_code TEXT NOT NULL DEFAULT 'universal',
    free_messages_used INTEGER NOT NULL DEFAULT 0,
    free_messages_date TEXT NOT NULL DEFAULT '',
    bonus_messages INTEGER NOT NULL DEFAULT 0,
    total_stars_paid INTEGER NOT NULL DEFAULT 0,
    memory_summary TEXT NOT NULL DEFAULT '',
    last_summary_message_id INTEGER NOT NULL DEFAULT 0,
    last_proactive_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,            -- 'user' | 'assistant'
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stars_amount INTEGER NOT NULL,
    bonus_messages_granted INTEGER NOT NULL,
    telegram_payment_charge_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pending_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    user_message TEXT NOT NULL,
    send_at TEXT NOT NULL,         -- когда доставить ("занята" -> отложенный ответ)
    status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | SENT
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pending_replies_status ON pending_replies(status, send_at);
"""


async def init_db() -> aiosqlite.Connection:
    global _conn
    Path(config.db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(config.db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA busy_timeout=5000;")
    await conn.executescript(SCHEMA)
    await conn.commit()
    _conn = conn
    logger.info("База данных инициализирована: %s", config.db_path)
    return conn


def get_conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("База данных не инициализирована — вызовите init_db() при старте")
    return _conn


async def close_db() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None
