"""Инициализация БД и первичного администратора."""
from __future__ import annotations

import logging

from sqlalchemy import func, select

from .config import Settings
from .db import Base, get_engine, get_sessionmaker
from .models import User
from .security import hash_password

logger = logging.getLogger("posmon.bootstrap")


async def init_db_and_admin(settings: Settings) -> None:
    """Создать таблицы (для SQLite/первого запуска) и админа, если нет пользователей.

    В проде на PostgreSQL схемой управляет Alembic; ``create_all`` безопасен —
    существующие таблицы он не трогает.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with get_sessionmaker()() as session:
        count = await session.scalar(select(func.count()).select_from(User))
        if not count:
            session.add(
                User(
                    login=settings.admin_login,
                    password_hash=hash_password(settings.admin_password),
                    role="Admin",
                )
            )
            await session.commit()
            logger.info("Создан первичный админ: %s", settings.admin_login)
