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

-- Сырые события участия в Telegram-розыгрышах (кнопка "Участвую" +
-- реферальные приглашения) — накапливаются по мере поступления вебхуков,
-- на их основе participants периодически пересчитывается целиком заново
-- (см. services/telegram_giveaway.rebuild_participants), как и для
-- остальных источников. 'join' — на пользователя не больше одной записи
-- (см. уникальный индекс ниже), 'referral' — по одной на каждое
-- засчитанное приглашение (с потолком, см. TELEGRAM_MAX_REFERRALS).
CREATE TABLE IF NOT EXISTS telegram_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id INTEGER NOT NULL REFERENCES giveaways(id) ON DELETE CASCADE,
    telegram_user_id TEXT NOT NULL,
    username TEXT,
    display_name TEXT,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telegram_entries_giveaway ON telegram_entries(giveaway_id);

-- Один "join" на пользователя на розыгрыш; "referral" не ограничен этим
-- индексом — на них считает потолок сам сервис при вставке.
CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_entries_unique_join
    ON telegram_entries(giveaway_id, telegram_user_id)
    WHERE kind = 'join';
"""

# giveaways создавалась до Telegram-интеграции — на уже развёрнутых базах
# столбцов ниже нет, добавляем через ALTER TABLE (CREATE TABLE IF NOT EXISTS
# столбцы в существующую таблицу не добавляет). SQLite не даёт
# "ADD COLUMN IF NOT EXISTS" — ловим и игнорируем "duplicate column".
_GIVEAWAYS_MIGRATIONS = (
    "ALTER TABLE giveaways ADD COLUMN telegram_chat_id TEXT",
    "ALTER TABLE giveaways ADD COLUMN telegram_message_id INTEGER",
)


async def init_db() -> aiosqlite.Connection:
    global _conn
    Path(config.db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(config.db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA busy_timeout=5000;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    await conn.executescript(SCHEMA)
    for stmt in _GIVEAWAYS_MIGRATIONS:
        try:
            await conn.execute(stmt)
        except aiosqlite.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
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
