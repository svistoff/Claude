"""Тесты нормализации комментариев и правил отбора (§6, §7 ТЗ)."""
from __future__ import annotations

from randomgiveaway.adapters.base import RawComment
from randomgiveaway.database.models import GiveawaySettings
from randomgiveaway.services.participants import build_participants


def make_comment(uid: str, comment_id: str, text: str = "", is_reply: bool = False) -> RawComment:
    return RawComment(
        comment_id=comment_id,
        source_user_id=uid,
        username=uid,
        display_name=None,
        text=text,
        is_reply=is_reply,
    )


def test_counts_total_unique_and_repeated_comments():
    comments = [
        make_comment("a", "1"),
        make_comment("a", "2"),
        make_comment("b", "3"),
    ]
    preview = build_participants(comments, GiveawaySettings(), post_author_user_id=None)
    assert preview.total_comments == 3
    assert preview.unique_users == 2
    assert preview.repeated_comments == 1


def test_repeated_comments_from_same_user_are_grouped_into_one_participant():
    comments = [make_comment("a", str(i)) for i in range(5)]
    preview = build_participants(comments, GiveawaySettings(), post_author_user_id=None)
    assert len(preview.participants) == 1
    assert preview.participants[0].comment_count == 5


def test_excludes_replies_when_disabled():
    comments = [
        make_comment("a", "1", is_reply=False),
        make_comment("b", "2", is_reply=True),
    ]
    settings = GiveawaySettings(include_replies=False)
    preview = build_participants(comments, settings, post_author_user_id=None)
    active = {p.source_user_id for p in preview.participants if not p.is_excluded}
    assert active == {"a"}


def test_required_text_filter():
    comments = [
        make_comment("a", "1", text="я хочу выиграть @друг"),
        make_comment("b", "2", text="просто комментарий"),
    ]
    settings = GiveawaySettings(required_text="@друг")
    preview = build_participants(comments, settings, post_author_user_id=None)
    assert preview.participants_after_rules == 1


def test_require_mention_filter():
    comments = [
        make_comment("a", "1", text="отметил @friend1"),
        make_comment("b", "2", text="без отметки"),
    ]
    settings = GiveawaySettings(require_mention=True)
    preview = build_participants(comments, settings, post_author_user_id=None)
    assert preview.participants_after_rules == 1


def test_excludes_post_author():
    comments = [make_comment("author", "1"), make_comment("user", "2")]
    settings = GiveawaySettings(exclude_post_author=True)
    preview = build_participants(comments, settings, post_author_user_id="author")
    active = {p.source_user_id for p in preview.participants if not p.is_excluded}
    assert active == {"user"}
    excluded = [p for p in preview.participants if p.is_excluded]
    assert excluded[0].exclusion_reason == "автор поста"


def test_excludes_explicit_username_list():
    comments = [make_comment("spammer", "1"), make_comment("user", "2")]
    settings = GiveawaySettings(excluded_users=["@spammer"])
    preview = build_participants(comments, settings, post_author_user_id=None)
    active = {p.source_user_id for p in preview.participants if not p.is_excluded}
    assert active == {"user"}


def test_empty_comments_gives_zero_participants():
    preview = build_participants([], GiveawaySettings(), post_author_user_id=None)
    assert preview.participants_after_rules == 0
    assert preview.total_comments == 0
