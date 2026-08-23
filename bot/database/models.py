"""Модель задания (Job) и статусы."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import aiosqlite


class JobStatus:
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AI_DONE = "AI_DONE"
    PUBLISHED = "PUBLISHED"
    ERROR = "ERROR"
    WAITING_RETRY = "WAITING_RETRY"


@dataclass
class Job:
    id: int
    media_group_id: str | None
    source_chat_id: int
    source_message_ids: list[int]
    user_id: int
    original_text: str | None
    new_text: str | None
    attachments: list[dict[str, Any]]
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: str | None
    error_message: str | None
    published_message_ids: list[int] | None
    created_at: str
    updated_at: str

    @staticmethod
    def from_row(row: aiosqlite.Row) -> "Job":
        return Job(
            id=row["id"],
            media_group_id=row["media_group_id"],
            source_chat_id=row["source_chat_id"],
            source_message_ids=json.loads(row["source_message_ids"]),
            user_id=row["user_id"],
            original_text=row["original_text"],
            new_text=row["new_text"],
            attachments=json.loads(row["attachments"]),
            status=row["status"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            next_attempt_at=row["next_attempt_at"],
            error_message=row["error_message"],
            published_message_ids=(
                json.loads(row["published_message_ids"])
                if row["published_message_ids"]
                else None
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
