"""Розыгрыш по отметкам в Instagram ("отметил нас на фото") — другая механика,
чем чтение комментариев (adapters/instagram_adapter.py): используется метод
GET /<ig-id>/tags, который показывает ЧУЖИЕ посты, где отметили аккаунт —
но только для аккаунта, чей токен у нас есть (см. README.md, «Розыгрыш по
отметкам в Instagram»). Поэтому механика требует, чтобы каждый аккаунт,
отметку которого нужно засчитывать, сам прошёл разовую авторизацию по
ссылке /api/instagram/connect/start — чужой аккаунт без этого не проверить,
Instagram не отдаёт такие данные без согласия владельца.

Если розыгрыш требует отметки сразу нескольких аккаунтов (settings.
instagram_tag_account_ids), участником становится только тот, чей пост
нашёлся в списке /tags **у всех** указанных аккаунтов одновременно
(сверяем по permalink — он один и тот же независимо от того, через чей
токен получен).
"""
from __future__ import annotations

from datetime import datetime

import httpx

from randomgiveaway.adapters.base import RawComment, SourceAdapterError
from randomgiveaway.database.models import InstagramConnectedAccount
from randomgiveaway.services import giveaways as giveaway_service
from randomgiveaway.services import instagram_accounts

GRAPH_API_VERSION = "v26.0"
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"


def _parse_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


async def _fetch_tagged_media(
    account: InstagramConnectedAccount, since: datetime, client: httpx.AsyncClient
) -> dict[str, dict]:
    """Возвращает {permalink: {username, caption, timestamp}} — отметки этого
    аккаунта не раньше since. /tags отдаёт сначала самые свежие, поэтому
    останавливаемся, как только встретили более старую запись."""
    result: dict[str, dict] = {}
    url = f"{GRAPH_BASE}/me/tags"
    params: dict | None = {
        "fields": "id,caption,username,permalink,timestamp",
        "access_token": account.access_token,
        "limit": 50,
    }
    while url:
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise SourceAdapterError(
                f"Instagram временно недоступен (аккаунт @{account.username}): {exc}"
            ) from exc
        if resp.status_code != 200:
            raise SourceAdapterError(
                f"Instagram API вернул ошибку {resp.status_code} для @{account.username}: {resp.text[:300]}"
            )
        data = resp.json()
        stop = False
        for item in data.get("data", []):
            permalink = item.get("permalink")
            timestamp = item.get("timestamp")
            if not permalink or not timestamp:
                continue
            if _parse_timestamp(timestamp) < since:
                stop = True
                break
            result[permalink] = {
                "username": item.get("username"),
                "caption": item.get("caption", ""),
                "timestamp": timestamp,
            }
        if stop:
            break
        url = data.get("paging", {}).get("next")
        params = None  # "next" уже содержит все параметры
    return result


async def compute_tagged_participants(giveaway_id: int) -> list[RawComment]:
    giveaway = await giveaway_service.get_giveaway(giveaway_id)
    account_ids = giveaway.settings.instagram_tag_account_ids
    if not account_ids:
        raise SourceAdapterError(
            "Не выбрано ни одного аккаунта, отметку которого нужно проверять "
            "(настройки розыгрыша → подключённые Instagram-аккаунты)."
        )
    accounts = await instagram_accounts.get_accounts_by_ids(account_ids)
    if len(accounts) != len(account_ids):
        raise SourceAdapterError(
            "Один или несколько выбранных Instagram-аккаунтов больше не подключены — "
            "переподключите их и обновите настройки розыгрыша."
        )

    since = _parse_timestamp(giveaway.created_at)

    async with httpx.AsyncClient(timeout=15) as client:
        per_account = [await _fetch_tagged_media(acc, since, client) for acc in accounts]

    common_permalinks = set(per_account[0])
    for mapping in per_account[1:]:
        common_permalinks &= set(mapping)

    comments: list[RawComment] = []
    for permalink in sorted(common_permalinks):
        info = per_account[0][permalink]
        username = info["username"]
        comments.append(
            RawComment(
                comment_id=permalink,
                source_user_id=username or permalink,
                username=username,
                display_name=None,
                text=info.get("caption") or "",
                is_reply=False,
            )
        )
    return comments
