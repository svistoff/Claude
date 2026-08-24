"""Точка входа: инициализация диспетчера aiogram и запуск long-polling.

Запуск из корня проекта afisha-bot: python -m bot.bot
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.config import config
from bot.handlers import commands, messages

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def main() -> None:
    setup_logging()
    logger.info("Запуск afisha-bot...")

    bot = Bot(token=config.bot_token)
    dp = Dispatcher()

    dp.include_router(commands.router)
    dp.include_router(messages.router)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
