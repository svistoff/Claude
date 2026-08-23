"""Логика очереди заданий поверх SQLite: создание, выборка FIFO, обновление статусов."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from bot.config import config
from bot.database.database import get_conn
from bot.database.models import Job, JobStatus

logger = logging.getLogger(__name__)


async def create_job(
    *,
    media_group_id: str | None,
    source_chat_id: int,
    source_message_id: int,
    user_id: int,
    text: str | None,
    attachment: dict[str, Any] | None,
) -> int:
    """Создаёт новое задание в статусе RECEIVED и возвращает его id."""
    conn = get_conn()
    attachments = [attachment] if attachment else []
    cur = await conn.execute(
        """
        INSERT INTO jobs (
            media_group_id, source_chat_id, source_message_ids, user_id,
            original_text, attachments, status, max_attempts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            media_group_id,
            source_chat_id,
            json.dumps([source_message_id]),
            user_id,
            text,
            json.dumps(attachments),
            JobStatus.RECEIVED,
            config.max_attempts,
        ),
    )
    await conn.commit()
    job_id = cur.lastrowid
    logger.info("[job %s] получено (chat=%s, msg=%s, album=%s)", job_id, source_chat_id, source_message_id, media_group_id)
    return job_id


async def append_to_job(job_id: int, *, source_message_id: int, text: str | None, attachment: dict[str, Any] | None) -> None:
    """Добавляет ещё один элемент альбома к уже созданному заданию."""
    conn = get_conn()
    cur = await conn.execute("SELECT source_message_ids, original_text, attachments FROM jobs WHERE id = ?", (job_id,))
    row = await cur.fetchone()
    if row is None:
        logger.warning("[job %s] append_to_job: задание не найдено", job_id)
        return

    message_ids = json.loads(row["source_message_ids"])
    message_ids.append(source_message_id)

    attachments = json.loads(row["attachments"])
    if attachment:
        attachments.append(attachment)

    original_text = row["original_text"]
    if not original_text and text:
        original_text = text

    await conn.execute(
        """
        UPDATE jobs
        SET source_message_ids = ?, attachments = ?, original_text = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (json.dumps(message_ids), json.dumps(attachments), original_text, job_id),
    )
    await conn.commit()
    logger.info("[job %s] добавлен элемент альбома (msg=%s), всего вложений: %s", job_id, source_message_id, len(attachments))


async def mark_queued(job_id: int) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (JobStatus.QUEUED, job_id),
    )
    await conn.commit()
    logger.info("[job %s] добавлено в очередь", job_id)


async def get_next_job() -> Job | None:
    """Возвращает следующее задание строго FIFO: QUEUED/AI_DONE сразу,
    WAITING_RETRY — если наступило время повтора."""
    conn = get_conn()
    now = datetime.utcnow().isoformat(sep=" ")
    cur = await conn.execute(
        """
        SELECT * FROM jobs
        WHERE status IN (?, ?)
           OR (status = ? AND (next_attempt_at IS NULL OR next_attempt_at <= ?))
        ORDER BY id ASC
        LIMIT 1
        """,
        (JobStatus.QUEUED, JobStatus.AI_DONE, JobStatus.WAITING_RETRY, now),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return Job.from_row(row)


async def set_status(job_id: int, status: str) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, job_id),
    )
    await conn.commit()


async def set_ai_result(job_id: int, new_text: str) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE jobs SET new_text = ?, status = ?, updated_at = datetime('now') WHERE id = ?",
        (new_text, JobStatus.AI_DONE, job_id),
    )
    await conn.commit()


async def set_published(job_id: int, published_message_ids: list[int]) -> None:
    conn = get_conn()
    await conn.execute(
        """
        UPDATE jobs
        SET status = ?, published_message_ids = ?, error_message = NULL, updated_at = datetime('now')
        WHERE id = ?
        """,
        (JobStatus.PUBLISHED, json.dumps(published_message_ids), job_id),
    )
    await conn.commit()


async def handle_failure(job_id: int, error_message: str) -> None:
    """Инкрементирует счётчик попыток и либо планирует повтор, либо переводит в ERROR."""
    conn = get_conn()
    cur = await conn.execute("SELECT attempts, max_attempts FROM jobs WHERE id = ?", (job_id,))
    row = await cur.fetchone()
    if row is None:
        return
    attempts = row["attempts"] + 1
    max_attempts = row["max_attempts"]

    if attempts < max_attempts:
        delay_idx = min(attempts - 1, len(config.retry_delays_seconds) - 1)
        delay = config.retry_delays_seconds[delay_idx]
        next_attempt_at = (datetime.utcnow() + timedelta(seconds=delay)).isoformat(sep=" ")
        await conn.execute(
            """
            UPDATE jobs
            SET attempts = ?, status = ?, next_attempt_at = ?, error_message = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (attempts, JobStatus.WAITING_RETRY, next_attempt_at, error_message, job_id),
        )
        await conn.commit()
        logger.warning("[job %s] ошибка (попытка %s/%s), повтор через %sс: %s", job_id, attempts, max_attempts, delay, error_message)
    else:
        await conn.execute(
            """
            UPDATE jobs
            SET attempts = ?, status = ?, error_message = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (attempts, JobStatus.ERROR, error_message, job_id),
        )
        await conn.commit()
        logger.error("[job %s] попытки исчерпаны (%s/%s), статус ERROR: %s", job_id, attempts, max_attempts, error_message)


async def get_stats() -> dict[str, int]:
    conn = get_conn()
    cur = await conn.execute("SELECT status, COUNT(*) AS cnt FROM jobs GROUP BY status")
    rows = await cur.fetchall()
    stats = {row["status"]: row["cnt"] for row in rows}
    stats["TOTAL"] = sum(stats.values())
    return stats


async def get_recent_errors(limit: int = 10) -> list[Job]:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT * FROM jobs WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
        (JobStatus.ERROR, limit),
    )
    rows = await cur.fetchall()
    return [Job.from_row(r) for r in rows]


async def retry_all_errors() -> int:
    conn = get_conn()
    cur = await conn.execute(
        """
        UPDATE jobs
        SET status = ?, attempts = 0, next_attempt_at = NULL, error_message = NULL, updated_at = datetime('now')
        WHERE status = ?
        """,
        (JobStatus.QUEUED, JobStatus.ERROR),
    )
    await conn.commit()
    return cur.rowcount


async def find_duplicate(*, media_group_id: str | None, source_message_id: int, user_id: int) -> Job | None:
    """Ищет уже существующее задание с тем же источником (для DUPLICATE_PROTECTION)."""
    conn = get_conn()
    if media_group_id:
        cur = await conn.execute(
            "SELECT * FROM jobs WHERE media_group_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
            (media_group_id, user_id),
        )
    else:
        cur = await conn.execute(
            """
            SELECT * FROM jobs
            WHERE user_id = ? AND media_group_id IS NULL
              AND source_message_ids = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, json.dumps([source_message_id])),
        )
    row = await cur.fetchone()
    return Job.from_row(row) if row else None


async def recover_on_startup() -> None:
    """Восстанавливает незавершённые задания после рестарта."""
    conn = get_conn()

    # Задания, зависшие в PROCESSING из-за краша: если AI уже отработал — на публикацию,
    # иначе — обратно в очередь.
    await conn.execute(
        """
        UPDATE jobs SET status = ?, updated_at = datetime('now')
        WHERE status = ? AND new_text IS NOT NULL
        """,
        (JobStatus.AI_DONE, JobStatus.PROCESSING),
    )
    await conn.execute(
        """
        UPDATE jobs SET status = ?, updated_at = datetime('now')
        WHERE status = ? AND new_text IS NULL
        """,
        (JobStatus.QUEUED, JobStatus.PROCESSING),
    )

    # Задания, застрявшие в RECEIVED (не успели дособраться в альбом до краша) —
    # ставим в очередь как есть (best-effort).
    cur = await conn.execute(
        "UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE status = ?",
        (JobStatus.QUEUED, JobStatus.RECEIVED),
    )
    await conn.commit()

    if cur.rowcount:
        logger.info("Восстановлено после рестарта: %s заданий из RECEIVED переведено в QUEUED", cur.rowcount)
    logger.info("Восстановление очереди после рестарта завершено")
