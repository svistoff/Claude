"""Общие фикстуры тестов."""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from posmon.db import Base
import posmon.models  # noqa: F401  -- регистрирует таблицы в метаданных


@pytest_asyncio.fixture
async def db_maker():
    """Фабрика сессий с общей in-memory БД (StaticPool держит одно соединение)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db_maker):
    """Одна сессия поверх общей in-memory БД."""
    async with db_maker() as s:
        yield s
