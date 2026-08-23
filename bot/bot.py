"""Точка входа: инициализация БД, диспетчера aiogram и запуск воркера.

Запуск из корня репозитория: python -m bot.bot
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.config import config
from bot.database.database import close_db, init_db
from bot.handlers import commands, messages
from bot.services.queue import recover_on_startup
from bot.worker.processor import run_worker

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def main() -> None:
    setup_logging()
    logger.info("Запуск бота...")

    await init_db()
    await recover_on_startup()

    # Без parse_mode по умолчанию: текст от AI может содержать символы вроде <, >, &,
    # которые сломали бы разбор HTML/Markdown при публикации.
    bot = Bot(token=config.bot_token)
    dp = Dispatcher()

    dp.include_router(commands.router)
    dp.include_router(messages.router)

    worker_task = asyncio.create_task(run_worker(bot))

    try:
        await dp.start_polling(bot)
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        await close_db()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
