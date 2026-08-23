"""Команды управления: /status /prompt /retry /errors"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.config import config
from bot.database.models import JobStatus
from bot.services import queue as queue_service
from bot.services import settings

logger = logging.getLogger(__name__)

router = Router(name="commands")
router.message.filter(F.from_user.id.in_(config.allowed_user_ids))

_STATUS_LABELS = {
    JobStatus.RECEIVED: "получено",
    JobStatus.QUEUED: "в очереди",
    JobStatus.PROCESSING: "обрабатывается",
    JobStatus.AI_DONE: "AI готов (публикация)",
    JobStatus.PUBLISHED: "опубликовано",
    JobStatus.ERROR: "ошибка",
    JobStatus.WAITING_RETRY: "ожидает повтора",
}


_WELCOME_TEXT = (
    "👋 Привет! Я переписываю пересланные посты через AI и публикую их в канал.\n\n"
    "Как пользоваться:\n"
    "1. Перешли мне пост (текст, фото, альбом, видео, документ — что угодно)\n"
    "2. Я поставлю его в очередь, перепишу текст через AI и опубликую в целевой канал\n\n"
    "Команды:\n"
    "/prompt — показать текущий системный промт для AI\n"
    "/prompt <текст> — задать новый промт\n"
    "/status — сводка по очереди\n"
    "/retry — повторно поставить в очередь задания с ошибками\n"
    "/errors — последние ошибки"
)


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.reply(_WELCOME_TEXT)


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    stats = await queue_service.get_stats()
    total = stats.pop("TOTAL", 0)

    lines = [f"📊 Всего заданий: {total}"]
    in_progress = sum(
        stats.get(s, 0) for s in (JobStatus.RECEIVED, JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.AI_DONE, JobStatus.WAITING_RETRY)
    )
    lines.append(f"⏳ Ожидают/обрабатываются: {in_progress}")
    lines.append(f"✅ Опубликовано: {stats.get(JobStatus.PUBLISHED, 0)}")
    lines.append(f"❌ Ошибок: {stats.get(JobStatus.ERROR, 0)}")
    lines.append("")
    lines.append("Подробно:")
    for status_key, label in _STATUS_LABELS.items():
        count = stats.get(status_key, 0)
        if count:
            lines.append(f"  • {label}: {count}")

    await message.reply("\n".join(lines))


@router.message(Command("prompt"))
async def cmd_prompt(message: Message, command: CommandObject) -> None:
    if command.args and command.args.strip():
        new_prompt = command.args.strip()
        await settings.set_prompt(new_prompt)
        logger.info("Промт обновлён пользователем %s", message.from_user.id)
        await message.reply(f"✅ Промт обновлён:\n\n{new_prompt}")
        return

    current = await settings.get_prompt()
    if current:
        await message.reply(f"Текущий промт:\n\n{current}")
    else:
        await message.reply("Промт не задан. Используйте /prompt <текст> чтобы установить.")


@router.message(Command("retry"))
async def cmd_retry(message: Message) -> None:
    count = await queue_service.retry_all_errors()
    logger.info("Пользователь %s повторно поставил в очередь %s заданий", message.from_user.id, count)
    await message.reply(f"🔁 Повторно поставлено в очередь: {count}")


@router.message(Command("errors"))
async def cmd_errors(message: Message) -> None:
    errors = await queue_service.get_recent_errors(limit=10)
    if not errors:
        await message.reply("Ошибок нет 🎉")
        return

    lines = ["❌ Последние ошибочные задания:"]
    for job in errors:
        reason = (job.error_message or "неизвестная ошибка")[:300]
        lines.append(f"\n#{job.id} — {job.updated_at}\nПопыток: {job.attempts}/{job.max_attempts}\nПричина: {reason}")

    await message.reply("\n".join(lines))
