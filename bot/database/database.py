"""Подключение к SQLite и миграции (CREATE TABLE IF NOT EXISTS)."""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from bot.config import config

logger = logging.getLogger(__name__)

_conn: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_group_id TEXT,
    source_chat_id INTEGER NOT NULL,
    source_message_ids TEXT NOT NULL,      -- JSON-массив id исходных сообщений
    user_id INTEGER NOT NULL,
    original_text TEXT,                    -- caption/text исходного поста (NULL если не было)
    new_text TEXT,                         -- текст, полученный от AI
    attachments TEXT NOT NULL DEFAULT '[]',-- JSON-массив вложений [{type, file_id, ...}]
    status TEXT NOT NULL DEFAULT 'RECEIVED',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TEXT,                  -- ISO timestamp, когда можно повторить
    error_message TEXT,
    published_message_ids TEXT,            -- JSON-массив id опубликованных сообщений
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_media_group ON jobs(media_group_id);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_PROMPT = (
    "Перепиши следующий текст поста для Telegram-канала: сохрани смысл и факты, "
    "сделай текст более живым и грамотным, не добавляй ничего от себя, "
    "не используй хэштеги, если их не было в оригинале."
)


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

    # Инициализируем промт по умолчанию, если ещё не задан
    cur = await conn.execute("SELECT value FROM settings WHERE key = 'prompt'")
    row = await cur.fetchone()
    if row is None:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('prompt', ?)", (DEFAULT_PROMPT,)
        )
        await conn.commit()

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
