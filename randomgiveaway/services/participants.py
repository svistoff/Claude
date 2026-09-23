"""Нормализация комментариев в участников и применение правил отбора (§6, §7, §8 ТЗ)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from randomgiveaway.adapters.base import RawComment
from randomgiveaway.database.models import GiveawaySettings, Participant

MENTION_RE = re.compile(r"@[A-Za-z0-9_.]{2,}")


@dataclass
class ParticipantsPreview:
    total_comments: int
    unique_users: int
    repeated_comments: int
    participants_before_rules: int
    participants_after_rules: int
    participants: list[Participant]  # включая исключённых (is_excluded=True), не выбрасываем


def build_participants(
    comments: list[RawComment],
    settings: GiveawaySettings,
    post_author_user_id: str | None,
) -> ParticipantsPreview:
    """Считает "Всего комментариев/Уникальных пользователей/Повторных" (§6 ТЗ) по
    исходным данным, затем применяет фильтры правил (§7) и помечает исключённых,
    не удаляя их — чтобы предпросмотр (§8) мог показать оба числа."""
    total_comments = len(comments)
    unique_users_raw = len({c.source_user_id for c in comments})
    repeated_comments = total_comments - unique_users_raw

    filtered = [c for c in comments if settings.include_replies or not c.is_reply]

    if settings.required_text:
        needle = settings.required_text.strip().lower()
        filtered = [c for c in filtered if needle in c.text.lower()]

    if settings.require_mention:
        filtered = [c for c in filtered if MENTION_RE.search(c.text)]

    grouped: dict[str, Participant] = {}
    for c in filtered:
        p = grouped.get(c.source_user_id)
        if p is None:
            p = Participant(
                id=None,
                giveaway_id=0,
                source_user_id=c.source_user_id,
                username=c.username,
                display_name=c.display_name,
                comment_count=0,
                comment_ids=[],
                is_excluded=False,
                exclusion_reason=None,
            )
            grouped[c.source_user_id] = p
        p.comment_count += 1
        p.comment_ids.append(c.comment_id)

    participants_before_rules = len(grouped)

    excluded_usernames = {u.lstrip("@").strip().lower() for u in settings.excluded_users if u.strip()}

    for p in grouped.values():
        if settings.exclude_post_author and post_author_user_id and p.source_user_id == post_author_user_id:
            p.is_excluded = True
            p.exclusion_reason = "автор поста"
        elif p.username and p.username.lstrip("@").lower() in excluded_usernames:
            p.is_excluded = True
            p.exclusion_reason = "в списке исключений"
        elif p.source_user_id.lstrip("@").lower() in excluded_usernames:
            p.is_excluded = True
            p.exclusion_reason = "в списке исключений"

    all_participants = list(grouped.values())
    active_count = sum(1 for p in all_participants if not p.is_excluded)

    return ParticipantsPreview(
        total_comments=total_comments,
        unique_users=unique_users_raw,
        repeated_comments=repeated_comments,
        participants_before_rules=participants_before_rules,
        participants_after_rules=active_count,
        participants=all_participants,
    )
