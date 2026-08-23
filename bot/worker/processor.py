"""Асинхронный воркер: последовательно (FIFO) обрабатывает задания из очереди."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from bot.config import config
from bot.database.models import Job, JobStatus
from bot.services import ai, queue as queue_service, settings, telegram as telegram_service

logger = logging.getLogger(__name__)


async def process_job(bot: Bot, job: Job) -> None:
    logger.info("[job %s] обработка начата (статус=%s, попытка=%s)", job.id, job.status, job.attempts + 1)
    await queue_service.set_status(job.id, JobStatus.PROCESSING)

    try:
        new_text = job.new_text

        if job.status != JobStatus.AI_DONE:
            if job.original_text:
                prompt = await settings.get_prompt()
                new_text = await ai.rewrite_text(job.original_text, prompt)
                await queue_service.set_ai_result(job.id, new_text)
                logger.info("[job %s] AI переписал текст", job.id)
            else:
                new_text = None
                logger.info("[job %s] исходный текст отсутствует — AI не вызывается", job.id)
                await queue_service.set_status(job.id, JobStatus.AI_DONE)

        published_ids = await telegram_service.publish_job(bot, job, new_text)
        await queue_service.set_published(job.id, published_ids)
        logger.info("[job %s] успешно опубликовано (сообщения: %s)", job.id, published_ids)

    except Exception as exc:  # noqa: BLE001 - логируем и уходим в retry/ERROR
        logger.exception("[job %s] ошибка при обработке: %s", job.id, exc)
        await queue_service.handle_failure(job.id, str(exc))


async def run_worker(bot: Bot) -> None:
    logger.info("Воркер запущен")
    while True:
        try:
            job = await queue_service.get_next_job()
            if job is None:
                await asyncio.sleep(config.poll_interval_seconds)
                continue
            await process_job(bot, job)
        except asyncio.CancelledError:
            logger.info("Воркер остановлен")
            raise
        except Exception:  # noqa: BLE001 - воркер не должен падать целиком
            logger.exception("Непредвиденная ошибка в цикле воркера")
            await asyncio.sleep(config.poll_interval_seconds)
