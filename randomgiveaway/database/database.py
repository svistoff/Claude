"""Подключение к SQLite и миграции (CREATE TABLE IF NOT EXISTS) — по образцу bot/database/database.py."""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from randomgiveaway.config import config

logger = logging.getLogger(__name__)

_conn: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    post_url TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    comments_count INTEGER NOT NULL DEFAULT 0,
    participants_count INTEGER NOT NULL DEFAULT 0,
    winners_count INTEGER NOT NULL DEFAULT 1,
    backup_winners_count INTEGER NOT NULL DEFAULT 0,
    algorithm_version TEXT,
    participants_hash TEXT,
    result_hash TEXT,
    settings_json TEXT NOT NULL,
    post_author_user_id TEXT,
    created_at TEXT NOT NULL,
    drawn_at TEXT
);

CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id INTEGER NOT NULL REFERENCES giveaways(id) ON DELETE CASCADE,
    source_user_id TEXT NOT NULL,
    username TEXT,
    display_name TEXT,
    comment_count INTEGER NOT NULL DEFAULT 0,
    comment_ids TEXT NOT NULL DEFAULT '[]',
    is_excluded INTEGER NOT NULL DEFAULT 0,
    exclusion_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_participants_giveaway ON participants(giveaway_id);

CREATE TABLE IF NOT EXISTS winners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id INTEGER NOT NULL REFERENCES giveaways(id) ON DELETE CASCADE,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    position INTEGER NOT NULL,
    is_backup INTEGER NOT NULL DEFAULT 0,
    selected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_winners_giveaway ON winners(giveaway_id);
"""


async def init_db() -> aiosqlite.Connection:
    global _conn
    Path(config.db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(config.db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA busy_timeout=5000;")
    await conn.execute("PRAGMA foreign_keys=ON;")
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
