"""Команды /start /help /last (см. 4.6 ТЗ)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import LinkPreviewOptions, Message

from bot.config import config
from bot.services import cards, supabase_client

router = Router(name="commands")
router.message.filter(F.from_user.id.in_(config.allowed_user_ids))

HELP_TEXT = (
    "Перешли мне готовую новость из «На выкладку» (текст, фото, альбом или видео) — "
    "я сразу опубликую её в «Новости одной строкой»: "
    f"{config.news_site_url}\n\n"
    "• Жирная первая строка — заголовок, курсив под ней — описание, остальное — полный текст. "
    "Если разметки нет, разберу текст через AI.\n"
    f"• Видео крупнее {config.max_video_mb} МБ не добавляю (ограничение Telegram).\n"
    "• Повторно тот же пост не опубликуется.\n"
    "• Под ответом кнопки «Скрыть» и «Удалить». Исправить новость — удали и перешли заново.\n\n"
    "/last — последние 10 новостей."
)


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT, link_preview_options=LinkPreviewOptions(is_disabled=True))


@router.message(Command("last"))
async def cmd_last(message: Message) -> None:
    rows = await supabase_client.list_latest(10)
    text, kb = cards.last_list(rows)
    await message.answer(text, reply_markup=kb, link_preview_options=LinkPreviewOptions(is_disabled=True))
