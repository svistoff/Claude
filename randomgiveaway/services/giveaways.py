"""Жизненный цикл розыгрыша: создание, загрузка участников, розыгрыш, результат.

Реализует §17 (модель данных), §20 (API), §24 (защита от повторного запуска
одного и того же розыгрыша) ТЗ.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from randomgiveaway.adapters.base import RawComment
from randomgiveaway.database.database import get_conn
from randomgiveaway.database.models import (
    Giveaway,
    GiveawaySettings,
    GiveawayStatus,
    Participant,
    Winner,
)
from randomgiveaway.services import random_engine
from randomgiveaway.services.participants import ParticipantsPreview, build_participants

VALID_SOURCES = {"instagram", "vk", "telegram", "import"}


class GiveawayError(Exception):
    """Сообщение уже готово для показа пользователю (§26 ТЗ)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_public_id() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = secrets.token_hex(3).upper()
    return f"RND-{today}-{suffix}"


async def create_giveaway(
    source: str,
    post_url: str,
    title: str | None,
    settings: GiveawaySettings,
    post_author_user_id: str | None = None,
) -> Giveaway:
    if source not in VALID_SOURCES:
        raise GiveawayError(f"Неизвестный источник: {source}")
    if not post_url.strip():
        raise GiveawayError("Укажите ссылку на пост")
    if settings.winners_count < 1:
        raise GiveawayError("Количество победителей должно быть не меньше 1")
    if settings.backup_winners_count < 0:
        raise GiveawayError("Количество запасных победителей не может быть отрицательным")

    conn = get_conn()
    cur = await conn.execute(
        """
        INSERT INTO giveaways (
            public_id, source, post_url, title, status,
            comments_count, participants_count, winners_count, backup_winners_count,
            algorithm_version, participants_hash, result_hash, settings_json,
            post_author_user_id, created_at, drawn_at
        ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, NULL, NULL, NULL, ?, ?, ?, NULL)
        """,
        (
            generate_public_id(),
            source,
            post_url.strip(),
            title,
            GiveawayStatus.DRAFT,
            settings.winners_count,
            settings.backup_winners_count,
            settings.to_json(),
            post_author_user_id,
            _now(),
        ),
    )
    await conn.commit()
    return await get_giveaway(cur.lastrowid)


async def get_giveaway(giveaway_id: int) -> Giveaway:
    conn = get_conn()
    cur = await conn.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
    row = await cur.fetchone()
    if row is None:
        raise GiveawayError("Розыгрыш не найден")
    return Giveaway.from_row(row)


async def get_giveaway_by_public_id(public_id: str) -> Giveaway:
    conn = get_conn()
    cur = await conn.execute("SELECT * FROM giveaways WHERE public_id = ?", (public_id,))
    row = await cur.fetchone()
    if row is None:
        raise GiveawayError("Розыгрыш не найден")
    return Giveaway.from_row(row)


async def load_comments(
    giveaway_id: int, comments: list[RawComment]
) -> ParticipantsPreview:
    """Нормализует полученные/импортированные комментарии в участников,
    применяет правила (§7) и сохраняет предпросмотр (§8)."""
    giveaway = await get_giveaway(giveaway_id)
    if giveaway.status == GiveawayStatus.DRAWN:
        raise GiveawayError("Розыгрыш уже проведён — повторная загрузка участников недоступна.")

    preview = build_participants(comments, giveaway.settings, giveaway.post_author_user_id)

    conn = get_conn()
    await conn.execute("DELETE FROM participants WHERE giveaway_id = ?", (giveaway_id,))
    for p in preview.participants:
        await conn.execute(
            """
            INSERT INTO participants (
                giveaway_id, source_user_id, username, display_name,
                comment_count, comment_ids, is_excluded, exclusion_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                giveaway_id,
                p.source_user_id,
                p.username,
                p.display_name,
                p.comment_count,
                json.dumps(p.comment_ids, ensure_ascii=False),
                int(p.is_excluded),
                p.exclusion_reason,
            ),
        )
    await conn.execute(
        """
        UPDATE giveaways
        SET comments_count = ?, participants_count = ?, status = ?
        WHERE id = ?
        """,
        (
            preview.total_comments,
            preview.participants_after_rules,
            GiveawayStatus.PARTICIPANTS_READY,
            giveaway_id,
        ),
    )
    await conn.commit()
    return preview


async def get_active_participants(giveaway_id: int) -> list[Participant]:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT * FROM participants WHERE giveaway_id = ? AND is_excluded = 0",
        (giveaway_id,),
    )
    rows = await cur.fetchall()
    return [Participant.from_row(r) for r in rows]


async def count_all_participants(giveaway_id: int) -> int:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM participants WHERE giveaway_id = ?", (giveaway_id,)
    )
    row = await cur.fetchone()
    return row["cnt"] if row else 0


async def perform_draw(giveaway_id: int) -> tuple[Giveaway, list[Winner], list[Winner]]:
    """Выполняет розыгрыш и сразу сохраняет результат (§9, §24 ТЗ:
    защита от повторного запуска — повторный вызов для уже проведённого
    розыгрыша отклоняется)."""
    giveaway = await get_giveaway(giveaway_id)
    if giveaway.status == GiveawayStatus.DRAWN:
        raise GiveawayError("Розыгрыш уже проведён и не может быть запущен повторно.")

    participants = await get_active_participants(giveaway_id)
    settings = giveaway.settings

    try:
        result = random_engine.draw(
            participants=participants,
            winners_count=settings.winners_count,
            backup_winners_count=settings.backup_winners_count,
            unique_user=settings.unique_user,
        )
    except random_engine.DrawError as exc:
        raise GiveawayError(str(exc)) from exc

    conn = get_conn()
    now = _now()
    winners: list[Winner] = []
    backups: list[Winner] = []

    for position, p in enumerate(result.winners, start=1):
        cur = await conn.execute(
            """
            INSERT INTO winners (giveaway_id, participant_id, position, is_backup, selected_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (giveaway_id, p.id, position, now),
        )
        winners.append(
            Winner(id=cur.lastrowid, giveaway_id=giveaway_id, participant_id=p.id,
                   position=position, is_backup=False, selected_at=now)
        )

    for position, p in enumerate(result.backups, start=1):
        cur = await conn.execute(
            """
            INSERT INTO winners (giveaway_id, participant_id, position, is_backup, selected_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (giveaway_id, p.id, position, now),
        )
        backups.append(
            Winner(id=cur.lastrowid, giveaway_id=giveaway_id, participant_id=p.id,
                   position=position, is_backup=True, selected_at=now)
        )

    await conn.execute(
        """
        UPDATE giveaways
        SET status = ?, algorithm_version = ?, participants_hash = ?,
            result_hash = ?, drawn_at = ?
        WHERE id = ?
        """,
        (
            GiveawayStatus.DRAWN,
            result.algorithm_version,
            result.participants_hash,
            result.result_hash,
            now,
            giveaway_id,
        ),
    )
    await conn.commit()

    updated = await get_giveaway(giveaway_id)
    return updated, winners, backups


async def get_winners_with_participants(
    giveaway_id: int,
) -> list[tuple[Winner, Participant]]:
    conn = get_conn()
    cur = await conn.execute(
        """
        SELECT w.*, p.source_user_id AS p_source_user_id, p.username AS p_username,
               p.display_name AS p_display_name, p.comment_count AS p_comment_count,
               p.comment_ids AS p_comment_ids, p.is_excluded AS p_is_excluded,
               p.exclusion_reason AS p_exclusion_reason
        FROM winners w JOIN participants p ON p.id = w.participant_id
        WHERE w.giveaway_id = ?
        ORDER BY w.is_backup ASC, w.position ASC
        """,
        (giveaway_id,),
    )
    rows = await cur.fetchall()
    result: list[tuple[Winner, Participant]] = []
    for row in rows:
        winner = Winner(
            id=row["id"],
            giveaway_id=row["giveaway_id"],
            participant_id=row["participant_id"],
            position=row["position"],
            is_backup=bool(row["is_backup"]),
            selected_at=row["selected_at"],
        )
        participant = Participant(
            id=row["participant_id"],
            giveaway_id=row["giveaway_id"],
            source_user_id=row["p_source_user_id"],
            username=row["p_username"],
            display_name=row["p_display_name"],
            comment_count=row["p_comment_count"],
            comment_ids=json.loads(row["p_comment_ids"]),
            is_excluded=bool(row["p_is_excluded"]),
            exclusion_reason=row["p_exclusion_reason"],
        )
        result.append((winner, participant))
    return result
