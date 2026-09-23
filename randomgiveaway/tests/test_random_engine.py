"""Тесты ядра случайного выбора (§9, §14 ТЗ): криптостойкость, честность, хэши."""
from __future__ import annotations

import secrets as secrets_module

import pytest

from randomgiveaway.database.models import Participant
from randomgiveaway.services import random_engine


def make_participant(uid: str, comment_count: int = 1) -> Participant:
    return Participant(
        id=abs(hash(uid)) % 100000,
        giveaway_id=1,
        source_user_id=uid,
        username=uid,
        display_name=None,
        comment_count=comment_count,
        comment_ids=[f"c-{uid}-{i}" for i in range(comment_count)],
        is_excluded=False,
        exclusion_reason=None,
    )


def test_draw_picks_requested_number_of_winners_and_backups():
    participants = [make_participant(f"user{i}") for i in range(10)]
    result = random_engine.draw(participants, winners_count=3, backup_winners_count=2, unique_user=True)
    assert len(result.winners) == 3
    assert len(result.backups) == 2
    all_ids = {p.source_user_id for p in result.winners + result.backups}
    assert len(all_ids) == 5  # без повторов одного и того же участника


def test_draw_uses_csprng(monkeypatch):
    """secrets.randbelow должен реально вызываться — не time-seeded random."""
    calls = {"count": 0}
    original = secrets_module.randbelow

    def spy(n):
        calls["count"] += 1
        return original(n)

    monkeypatch.setattr(random_engine.secrets, "randbelow", spy)
    participants = [make_participant(f"user{i}") for i in range(5)]
    random_engine.draw(participants, winners_count=1, backup_winners_count=0, unique_user=True)
    assert calls["count"] > 0


def test_unique_user_mode_gives_comparable_chance_regardless_of_comment_count():
    heavy = make_participant("heavy", comment_count=1000)
    light = make_participant("light", comment_count=1)
    wins = {"heavy": 0, "light": 0}
    for _ in range(200):
        result = random_engine.draw([heavy, light], winners_count=1, backup_winners_count=0, unique_user=True)
        wins[result.winners[0].source_user_id] += 1
    assert wins["light"] > 40  # при равном шансе ожидается ~100 из 200


def test_weighted_mode_favors_participants_with_more_comments():
    heavy = make_participant("heavy", comment_count=50)
    light = make_participant("light", comment_count=1)
    trials = 100
    heavy_wins = 0
    for _ in range(trials):
        result = random_engine.draw([heavy, light], winners_count=1, backup_winners_count=0, unique_user=False)
        if result.winners[0].source_user_id == "heavy":
            heavy_wins += 1
    assert heavy_wins > trials * 0.8


def test_participants_hash_is_deterministic_and_order_independent():
    participants = [make_participant(f"user{i}") for i in range(5)]
    h1 = random_engine.compute_participants_hash(participants)
    h2 = random_engine.compute_participants_hash(list(reversed(participants)))
    assert h1 == h2


def test_result_fixes_participants_hash_independent_of_draw_outcome():
    participants = [make_participant(f"user{i}") for i in range(20)]
    result = random_engine.draw(participants, winners_count=3, backup_winners_count=1, unique_user=True)
    assert result.participants_hash == random_engine.compute_participants_hash(participants)
    assert result.result_hash != result.participants_hash


def test_raises_friendly_error_on_empty_participants():
    with pytest.raises(random_engine.DrawError, match="Не найдено участников"):
        random_engine.draw([], winners_count=1, backup_winners_count=0, unique_user=True)


def test_raises_friendly_error_when_not_enough_participants():
    participants = [make_participant("only_one")]
    with pytest.raises(random_engine.DrawError, match="Недостаточно участников"):
        random_engine.draw(participants, winners_count=3, backup_winners_count=0, unique_user=True)
