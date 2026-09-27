"""Точка входа: инициализация БД, фоновых задач и запуск бота.

Запуск из корня репозитория: python -m companion_bot.bot
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from companion_bot.config import config
from companion_bot.database.database import close_db, init_db
from companion_bot.handlers import commands, messages, payments
from companion_bot.worker.scheduler import start_background_tasks

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def main() -> None:
    setup_logging()
    logger.info("Запуск AI-компаньон бота...")

    await init_db()

    bot = Bot(token=config.bot_token)
    dp = Dispatcher()

    dp.include_router(commands.router)
    dp.include_router(payments.router)
    dp.include_router(messages.router)

    background_tasks = start_background_tasks(bot)

    try:
        await dp.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        await bot.session.close()
        await close_db()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
