"""Точка входа: инициализация диспетчера aiogram и запуск long-polling.

Запуск из корня проекта news-bot: python -m bot.bot
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.config import config
from bot.handlers import callbacks, commands, messages

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def main() -> None:
    setup_logging()
    logger.info("Запуск news-bot...")

    bot = Bot(token=config.bot_token)
    dp = Dispatcher()

    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(messages.router)

    try:
        await bot.set_my_commands([
            BotCommand(command="last", description="Последние 10 новостей"),
            BotCommand(command="help", description="Как пользоваться"),
        ])
    except Exception:
        logger.warning("Не удалось установить меню команд", exc_info=True)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
