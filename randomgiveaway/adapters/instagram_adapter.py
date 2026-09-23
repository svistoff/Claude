"""Instagram-адаптер: Instagram API with Instagram Login (graph.instagram.com).

Решение по скоупу (принято в обсуждении задачи, см. randomgiveaway/README.md):

Instagram Graph API не даёт доступа к комментариям ЧУЖИХ постов, даже если
у нас есть свой подключённый Business/Creator-аккаунт — Business Discovery
отдаёт только агрегированные метрики (счётчики), а не сами комментарии.
Прочитать содержимое комментариев с username автора можно только для медиа,
которым владеет сам авторизованный аккаунт.

Поэтому этот адаптер умеет читать комментарии только к постам самого
ekb_guide. Доступ — через собственный long-lived access-токен, полученный
один раз через /api/instagram/oauth/start (см. services/instagram_oauth.py),
без App Review и без OAuth-экрана для внешних организаторов.

Ограничение API: Graph API не отдаёт числовой user_id автора комментария —
только username. Поэтому здесь username используется как source_user_id
(в отличие от VK/Telegram, где обычно доступен числовой id).
"""
from __future__ import annotations

import re

import httpx

from randomgiveaway.adapters.base import RawComment, SourceAdapter, SourceAdapterError

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"

# Instagram отдаёт один и тот же пост по разным путям в зависимости от типа
# медиа и того, откуда скопирована ссылка: /p/<code>/, /reel/<code>/,
# /tv/<code>/ — Graph API в поле permalink возвращает канонический вариант
# (для Reels — всегда /reel/), который может не совпадать с тем, что
# реально скопировал человек. Сравнивать нужно по shortcode, не по URL
# целиком.
_SHORTCODE_RE = re.compile(r"/(?:p|reel|tv)/([^/?#]+)")


def _extract_shortcode(url: str) -> str | None:
    match = _SHORTCODE_RE.search(url)
    return match.group(1) if match else None


class InstagramAdapter(SourceAdapter):
    name = "instagram"

    def __init__(self, access_token: str | None):
        self._access_token = access_token

    async def fetch_comments(self, post_url: str) -> list[RawComment]:
        if not self._access_token:
            raise SourceAdapterError(
                "Instagram не подключён: не задан INSTAGRAM_ACCESS_TOKEN. "
                "Пройдите разовую авторизацию через /api/instagram/oauth/start "
                "(см. randomgiveaway/README.md)."
            )

        media_id = await self._find_media_id_by_permalink(post_url)
        if media_id is None:
            raise SourceAdapterError(
                "Пост не найден среди публикаций ekb_guide. Адаптер умеет читать "
                "комментарии только к постам самого ekb_guide — проверьте ссылку."
            )
        return await self._fetch_all_comments(media_id)

    async def _find_media_id_by_permalink(self, post_url: str) -> str | None:
        target_shortcode = _extract_shortcode(post_url)
        target_url = post_url.strip().rstrip("/")
        url = f"{GRAPH_BASE}/me/media"
        params: dict | None = {"fields": "id,permalink", "access_token": self._access_token, "limit": 50}
        async with httpx.AsyncClient(timeout=15) as client:
            while url:
                data = await self._get(client, url, params)
                for item in data.get("data", []):
                    permalink = item.get("permalink", "")
                    if target_shortcode is not None:
                        if _extract_shortcode(permalink) == target_shortcode:
                            return item["id"]
                    elif permalink.rstrip("/") == target_url:
                        # ссылка нестандартного вида, без /p//reel//tv/ — сравниваем как есть
                        return item["id"]
                url = data.get("paging", {}).get("next")
                params = None  # "next" уже содержит все параметры в самой ссылке
        return None

    async def _fetch_all_comments(self, media_id: str) -> list[RawComment]:
        comments: list[RawComment] = []
        url = f"{GRAPH_BASE}/{media_id}/comments"
        params: dict | None = {
            "fields": "id,text,username,timestamp,replies{id,text,username,timestamp}",
            "access_token": self._access_token,
            "limit": 50,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            while url:
                data = await self._get(client, url, params)
                for item in data.get("data", []):
                    comments.append(self._to_raw_comment(item, is_reply=False))
                    for reply in item.get("replies", {}).get("data", []):
                        comments.append(
                            self._to_raw_comment(reply, is_reply=True, parent_id=item["id"])
                        )
                url = data.get("paging", {}).get("next")
                params = None
        return comments

    @staticmethod
    def _to_raw_comment(item: dict, is_reply: bool, parent_id: str | None = None) -> RawComment:
        username = item.get("username")
        return RawComment(
            comment_id=item["id"],
            source_user_id=username or item["id"],
            username=username,
            display_name=None,
            text=item.get("text", ""),
            is_reply=is_reply,
            parent_comment_id=parent_id,
        )

    @staticmethod
    async def _get(client: httpx.AsyncClient, url: str, params: dict | None) -> dict:
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise SourceAdapterError(f"Instagram временно недоступен: {exc}") from exc
        if resp.status_code != 200:
            raise SourceAdapterError(
                f"Instagram API вернул ошибку {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()
