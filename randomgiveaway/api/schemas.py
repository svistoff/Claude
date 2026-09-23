"""Pydantic-схемы запросов/ответов API."""
from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel

from randomgiveaway.database.models import Giveaway, GiveawaySettings


class GiveawaySettingsIn(BaseModel):
    unique_user: bool = True
    include_replies: bool = True
    require_mention: bool = False
    required_text: str | None = None
    exclude_post_author: bool = True
    excluded_users: list[str] = []
    winners_count: int = 1
    backup_winners_count: int = 0

    def to_domain(self) -> GiveawaySettings:
        return GiveawaySettings(**self.model_dump())


class CreateGiveawayRequest(BaseModel):
    source: str
    post_url: str
    title: str | None = None
    post_author_user_id: str | None = None
    settings: GiveawaySettingsIn = GiveawaySettingsIn()


class GiveawayOut(BaseModel):
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
    created_at: str
    drawn_at: str | None
    settings: GiveawaySettingsIn

    @staticmethod
    def from_domain(g: Giveaway) -> "GiveawayOut":
        return GiveawayOut(
            id=g.id,
            public_id=g.public_id,
            source=g.source,
            post_url=g.post_url,
            title=g.title,
            status=g.status,
            comments_count=g.comments_count,
            participants_count=g.participants_count,
            winners_count=g.winners_count,
            backup_winners_count=g.backup_winners_count,
            algorithm_version=g.algorithm_version,
            participants_hash=g.participants_hash,
            result_hash=g.result_hash,
            created_at=g.created_at,
            drawn_at=g.drawn_at,
            settings=GiveawaySettingsIn(**asdict(g.settings)),
        )


class ParticipantsPreviewOut(BaseModel):
    """§6 (после загрузки) и §8 (предпросмотр перед стартом) ТЗ.

    unique_users/repeated_comments заполняются только сразу после
    импорта/загрузки — сырые комментарии не хранятся (см. README про §25 ТЗ),
    поэтому при повторном запросе предпросмотра эти два поля отсутствуют.
    """

    total_comments: int
    unique_users: int | None = None
    repeated_comments: int | None = None
    participants_before_rules: int
    participants_after_rules: int


class ParticipantOut(BaseModel):
    """Для анимации на фронтенде (§10.2 ТЗ: прокрутка реальных usernames
    участников) — не сам механизм выбора, он уже завершён к этому моменту."""

    source_user_id: str
    username: str | None
    display_name: str | None
    comment_count: int


class WinnerOut(BaseModel):
    position: int
    source_user_id: str
    username: str | None
    display_name: str | None
    comment_count: int


class DrawResultOut(BaseModel):
    giveaway: GiveawayOut
    winners: list[WinnerOut]
    backups: list[WinnerOut]


class PublicResultOut(BaseModel):
    """§12 ТЗ — публичная страница результата, без внутренних ID."""

    public_id: str
    title: str | None
    source: str
    post_url: str
    created_at: str
    drawn_at: str | None
    comments_count: int
    participants_count: int
    winners_count: int
    backup_winners_count: int
    algorithm_version: str | None
    participants_hash: str | None
    result_hash: str | None
    winners: list[WinnerOut]
    backups: list[WinnerOut]
