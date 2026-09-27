"""Команда /start — приветствие и честное раскрытие того, что это AI."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from companion_bot.persona import DEFAULT_PERSONA
from companion_bot.services.usage import ensure_user

router = Router(name="commands")


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await ensure_user(message.from_user.id)
    await message.answer(DEFAULT_PERSONA.greeting)
