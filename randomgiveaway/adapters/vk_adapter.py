"""VK-адаптер: wall.getComments через пользовательский access-токен.

Важно (проверено вживую): токен сообщества для этого НЕ подходит — VK
отвечает ошибкой 27 "Group authorization failed: method is unavailable
with group auth" при вызове wall.getComments с групповым токеном,
независимо от выданных прав. Нужен именно пользовательский токен,
полученный через /api/vk/oauth/start (см. services/vk_oauth.py) — с
scope=wall,offline он не истекает, отдельного продления по cron не
требуется.

Скоуп по факту совпадает с общим решением (см. README.md, «Ключевое
решение по скоупу»): розыгрыши проводятся в постах самого ekb_guide —
здесь это не enforced техническим ограничением API (в отличие от
Instagram), а просто согласованная граница использования сервиса.

Как получить токен — см. README.md, раздел «Подключение VK».

Известное ограничение: VK отдаёт вложенные ответы (thread) инлайн вместе
с родительским комментарием не более 10 штук за раз (`thread_items_count`
— максимум, который принимает API). Если под одним комментарием больше
10 ответов, лишние не попадут в список участников. Для типичного
розыгрыша это не критично; при необходимости можно дозапрашивать ветку
отдельным вызовом `wall.getComments` с параметром `comment_id`.
"""
from __future__ import annotations

import re

import httpx

from randomgiveaway.adapters.base import RawComment, SourceAdapter, SourceAdapterError

VK_API_BASE = "https://api.vk.com/method"
VK_API_VERSION = "5.199"

# Ссылка на пост VK всегда содержит фрагмент "wall<owner_id>_<post_id>" в
# каком-то виде — либо напрямую в пути (vk.com/wall-123_456), либо в
# query-параметре w= (vk.com/club123?w=wall-123_456). Достаточно найти
# этот фрагмент где угодно в строке.
_WALL_RE = re.compile(r"wall(-?\d+)_(\d+)")


def _parse_post_url(post_url: str) -> tuple[int, int]:
    match = _WALL_RE.search(post_url)
    if not match:
        raise SourceAdapterError(
            "Не удалось распознать ссылку на пост VK. Ожидается ссылка вида "
            "vk.com/wall-12345_678 или vk.com/club12345?w=wall-12345_678."
        )
    return int(match.group(1)), int(match.group(2))


class VKAdapter(SourceAdapter):
    name = "vk"

    def __init__(self, access_token: str | None):
        self._token = access_token

    async def fetch_comments(self, post_url: str) -> list[RawComment]:
        if not self._token:
            raise SourceAdapterError(
                "VK не подключён: не задан VK_ACCESS_TOKEN. "
                "Пройдите разовую авторизацию через /api/vk/oauth/start "
                "(см. randomgiveaway/README.md)."
            )

        owner_id, post_id = _parse_post_url(post_url)

        comments: list[RawComment] = []
        offset = 0
        total: int | None = None

        async with httpx.AsyncClient(timeout=15) as client:
            while total is None or offset < total:
                data = await self._call(
                    client,
                    "wall.getComments",
                    {
                        "owner_id": owner_id,
                        "post_id": post_id,
                        "offset": offset,
                        "count": 100,
                        "extended": 1,
                        "fields": "screen_name",
                        "thread_items_count": 10,
                        "sort": "asc",
                        "access_token": self._token,
                        "v": VK_API_VERSION,
                    },
                )
                total = data.get("count", 0)
                items = data.get("items", [])
                profiles_by_id = {p["id"]: p for p in data.get("profiles", [])}
                groups_by_id = {g["id"]: g for g in data.get("groups", [])}

                for item in items:
                    if item.get("deleted"):
                        continue
                    comments.append(self._to_raw_comment(item, profiles_by_id, groups_by_id, is_reply=False))
                    for reply in item.get("thread", {}).get("items", []):
                        if reply.get("deleted"):
                            continue
                        comments.append(
                            self._to_raw_comment(
                                reply,
                                profiles_by_id,
                                groups_by_id,
                                is_reply=True,
                                parent_id=str(item["id"]),
                            )
                        )

                if not items:
                    break
                offset += len(items)

        return comments

    @staticmethod
    def _to_raw_comment(
        item: dict,
        profiles_by_id: dict,
        groups_by_id: dict,
        is_reply: bool,
        parent_id: str | None = None,
    ) -> RawComment:
        from_id = item.get("from_id", 0)
        author = None
        display_name = None
        username = None
        if from_id > 0:
            author = profiles_by_id.get(from_id)
            if author:
                display_name = f"{author.get('first_name', '')} {author.get('last_name', '')}".strip() or None
                username = author.get("screen_name")
        elif from_id < 0:
            author = groups_by_id.get(-from_id)
            if author:
                display_name = author.get("name")
                username = author.get("screen_name")

        # explicit reply_to_comment у самого объекта комментария (не только
        # вложенность в thread) — на случай если VK когда-нибудь отдаст
        # ответы плоским списком без thread.items
        if item.get("reply_to_comment") and parent_id is None:
            parent_id = str(item["reply_to_comment"])
            is_reply = True

        return RawComment(
            comment_id=str(item["id"]),
            source_user_id=str(from_id) if from_id else str(item["id"]),
            username=username,
            display_name=display_name,
            text=item.get("text", ""),
            is_reply=is_reply,
            parent_comment_id=parent_id,
        )

    @staticmethod
    async def _call(client: httpx.AsyncClient, method: str, params: dict) -> dict:
        try:
            resp = await client.get(f"{VK_API_BASE}/{method}", params=params)
        except httpx.HTTPError as exc:
            raise SourceAdapterError(f"VK временно недоступен: {exc}") from exc
        if resp.status_code != 200:
            raise SourceAdapterError(f"VK API вернул ошибку {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        if "error" in payload:
            err = payload["error"]
            raise SourceAdapterError(
                f"VK API: {err.get('error_msg', 'неизвестная ошибка')} (код {err.get('error_code')})"
            )
        return payload.get("response", {})
