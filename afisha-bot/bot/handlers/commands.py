"""Команды /start /help /status (см. 3.6 ТЗ)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import config
from bot.services import supabase_client

router = Router(name="commands")
router.message.filter(F.from_user.id.in_(config.allowed_user_ids))

HELP_TEXT = (
    "Пришли мне пересланный анонс (текст, фото, альбом или видео) — я распознаю дату, "
    "площадку и описание через AI и положу заявку в «Предложенное» афиши.\n\n"
    "Видео крупнее 20 МБ не публикую — такой анонс придётся дополнить видео вручную в админке.\n\n"
    "/status — сколько сейчас заявок ждёт проверки."
)


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    count = await supabase_client.count_pending_submissions()
    await message.answer(f"В «Предложенное» сейчас ждут проверки: {count}")
