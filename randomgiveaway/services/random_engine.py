"""Криптостойкий выбор победителей (§9 ТЗ).

Важно: выбор не зависит от анимации. Этот модуль вызывается один раз при
нажатии "ПРОВЕСТИ РОЗЫГРЫШ", результат сразу сохраняется в БД — фронтенд
затем только визуализирует уже зафиксированный результат (§9, §22 ТЗ).
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass

from randomgiveaway.database.models import Participant

ALGORITHM_VERSION = "random-engine-v1-csprng"


class DrawError(Exception):
    """Сообщение уже готово для показа пользователю (§26 ТЗ)."""


@dataclass(frozen=True)
class DrawResult:
    winners: list[Participant]
    backups: list[Participant]
    participants_hash: str
    result_hash: str
    algorithm_version: str


def _entry_pool(participants: list[Participant], unique_user: bool) -> list[Participant]:
    """§7.3 ТЗ: "один комментарий = один шанс" (вес = число комментариев)
    против "один пользователь = один шанс" (у всех ровно один билет)."""
    if unique_user:
        return list(participants)
    pool: list[Participant] = []
    for p in participants:
        pool.extend([p] * max(p.comment_count, 1))
    return pool


def _secure_shuffle(items: list) -> list:
    """Fisher–Yates на secrets.randbelow — криптостойкий ГСЧ (§9 ТЗ),
    не зависит от предсказуемых источников вроде time-seeded random."""
    shuffled = list(items)
    for i in range(len(shuffled) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
    return shuffled


def compute_participants_hash(participants: list[Participant]) -> str:
    """Фиксирует состав участников ДО розыгрыша (§14 ТЗ)."""
    payload = sorted(
        (
            {
                "source_user_id": p.source_user_id,
                "username": p.username,
                "comment_count": p.comment_count,
            }
            for p in participants
        ),
        key=lambda x: x["source_user_id"],
    )
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def draw(
    participants: list[Participant],
    winners_count: int,
    backup_winners_count: int,
    unique_user: bool,
) -> DrawResult:
    if winners_count < 1:
        raise DrawError("Количество победителей должно быть не меньше 1")
    if not participants:
        raise DrawError("Не найдено участников, соответствующих заданным условиям.")
    if len(participants) < winners_count:
        raise DrawError(
            f"Недостаточно участников: {len(participants)} доступно, "
            f"а победителей требуется {winners_count}."
        )

    p_hash = compute_participants_hash(participants)

    pool = _entry_pool(participants, unique_user)
    shuffled = _secure_shuffle(pool)

    selected: list[Participant] = []
    seen_ids: set[str] = set()
    target = winners_count + max(backup_winners_count, 0)
    for entry in shuffled:
        if entry.source_user_id in seen_ids:
            continue
        seen_ids.add(entry.source_user_id)
        selected.append(entry)
        if len(selected) >= target:
            break

    winners = selected[:winners_count]
    backups = selected[winners_count:]

    result_payload = {
        "participants_hash": p_hash,
        "winners": [w.source_user_id for w in winners],
        "backups": [b.source_user_id for b in backups],
        "algorithm_version": ALGORITHM_VERSION,
    }
    result_hash = hashlib.sha256(
        json.dumps(result_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return DrawResult(
        winners=winners,
        backups=backups,
        participants_hash=p_hash,
        result_hash=result_hash,
        algorithm_version=ALGORITHM_VERSION,
    )
