"""Сущности из §17 ТЗ: Giveaway, Participant, Winner, GiveawaySettings."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

import aiosqlite


@dataclass
class GiveawaySettings:
    """Хранится как JSON внутри giveaways.settings_json — отдельная таблица не нужна
    для MVP, т.к. настройки всегда читаются/пишутся целиком вместе с розыгрышем."""

    unique_user: bool = True
    include_replies: bool = True
    require_mention: bool = False
    required_text: str | None = None
    exclude_post_author: bool = True
    excluded_users: list[str] = field(default_factory=list)
    winners_count: int = 1
    backup_winners_count: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(raw: str) -> "GiveawaySettings":
        return GiveawaySettings(**json.loads(raw))


class GiveawayStatus:
    DRAFT = "DRAFT"
    COMMENTS_LOADED = "COMMENTS_LOADED"
    PARTICIPANTS_READY = "PARTICIPANTS_READY"
    DRAWN = "DRAWN"
    ERROR = "ERROR"


@dataclass
class Giveaway:
    id: int
    public_id: str
    source: str
    post_url: str
    title: str | None
    status: str
    comments_count: int
    participants_count: int
    winners_count: int
    backup_winners_count: int
    algorithm_version: str | None
    participants_hash: str | None
    result_hash: str | None
    settings_json: str
    post_author_user_id: str | None
    created_at: str
    drawn_at: str | None

    @property
    def settings(self) -> GiveawaySettings:
        return GiveawaySettings.from_json(self.settings_json)

    @staticmethod
    def from_row(row: aiosqlite.Row) -> "Giveaway":
        return Giveaway(
            id=row["id"],
            public_id=row["public_id"],
            source=row["source"],
            post_url=row["post_url"],
            title=row["title"],
            status=row["status"],
            comments_count=row["comments_count"],
            participants_count=row["participants_count"],
            winners_count=row["winners_count"],
            backup_winners_count=row["backup_winners_count"],
            algorithm_version=row["algorithm_version"],
            participants_hash=row["participants_hash"],
            result_hash=row["result_hash"],
            settings_json=row["settings_json"],
            post_author_user_id=row["post_author_user_id"],
            created_at=row["created_at"],
            drawn_at=row["drawn_at"],
        )


@dataclass
class Participant:
    id: int | None
    giveaway_id: int
    source_user_id: str
    username: str | None
    display_name: str | None
    comment_count: int
    comment_ids: list[str]
    is_excluded: bool
    exclusion_reason: str | None

    @staticmethod
    def from_row(row: aiosqlite.Row) -> "Participant":
        return Participant(
            id=row["id"],
            giveaway_id=row["giveaway_id"],
            source_user_id=row["source_user_id"],
            username=row["username"],
            display_name=row["display_name"],
            comment_count=row["comment_count"],
            comment_ids=json.loads(row["comment_ids"]),
            is_excluded=bool(row["is_excluded"]),
            exclusion_reason=row["exclusion_reason"],
        )


@dataclass
class Winner:
    id: int | None
    giveaway_id: int
    participant_id: int
    position: int
    is_backup: bool
    selected_at: str

    @staticmethod
    def from_row(row: aiosqlite.Row) -> "Winner":
        return Winner(
            id=row["id"],
            giveaway_id=row["giveaway_id"],
            participant_id=row["participant_id"],
            position=row["position"],
            is_backup=bool(row["is_backup"]),
            selected_at=row["selected_at"],
        )
