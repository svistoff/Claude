"""Подключение к SQLite и схема (CREATE TABLE IF NOT EXISTS)."""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from attendance.config import config

logger = logging.getLogger(__name__)

_conn: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL UNIQUE REFERENCES employees(id) ON DELETE CASCADE,
    device_identifier TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT,
    last_seen_hostname TEXT
);

CREATE TABLE IF NOT EXISTS attendance_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    last_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_sessions_employee ON attendance_sessions(employee_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON attendance_sessions(status);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 1,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_created ON system_events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_type ON system_events(event_type);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
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
