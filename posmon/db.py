"""Слой доступа к БД: async-движок, фабрика сессий, базовый класс моделей."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import DateTime, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


def make_engine(database_url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    url = database_url or settings.database_url
    connect_args: dict = {}
    # SQLite (aiosqlite) требует check_same_thread=False для пула
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_async_engine(url, echo=False, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        # Включаем внешние ключи, чтобы ON DELETE CASCADE работал (в SQLite он
        # по умолчанию выключен). Нужно для чистого удаления проекта со всеми
        # связанными записями.
        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_fk_on(dbapi_conn, _rec):  # pragma: no cover - тривиально
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = make_engine()
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


def reset_engine_state() -> None:
    """Сбросить кэш движка/фабрики (используется в тестах при смене DATABASE_URL)."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-зависимость: выдаёт сессию на время запроса."""
    async with get_sessionmaker()() as session:
        yield session


# Переиспользуемые определения колонок времени
def created_at_column():
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def updated_at_column():
    return mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
