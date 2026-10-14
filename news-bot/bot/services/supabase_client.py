"""Доступ к Supabase REST через service_role: новости и их медиа. Ключ
service_role живёт только в .env на сервере и никогда не попадает в клиентские
файлы."""
from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from bot.config import config

logger = logging.getLogger(__name__)


class DuplicateError(RuntimeError):
    """Нарушение уникальности (origin_key/slug) — 409 от PostgREST."""


def _check(resp: httpx.Response) -> None:
    """Как raise_for_status(), но с телом ответа в сообщении — иначе причину
    4xx/5xx от PostgREST не видно в логах, только код статуса."""
    if resp.status_code == 409:
        raise DuplicateError(f"Supabase {resp.request.method} {resp.request.url} -> 409: {resp.text}")
    if resp.status_code >= 400:
        raise RuntimeError(f"Supabase {resp.request.method} {resp.request.url} -> {resp.status_code}: {resp.text}")


_REST_HEADERS = {
    "apikey": config.supabase_service_key,
    "Authorization": f"Bearer {config.supabase_service_key}",
    "Content-Type": "application/json",
}
_REST = f"{config.supabase_url}/rest/v1"


async def _request(method: str, path: str, *, json=None, prefer: str | None = None, timeout: float = 15):
    headers = dict(_REST_HEADERS)
    if prefer:
        headers["Prefer"] = prefer
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(method, f"{_REST}/{path}", headers=headers, json=json)
    _check(resp)
    return resp.json() if resp.content else None


async def find_by_origin(origin_key: str) -> dict | None:
    rows = await _request("GET", f"news?origin_key=eq.{quote(origin_key)}&select=id,slug,title,status&limit=1")
    return rows[0] if rows else None


async def insert_news(payload: dict) -> dict:
    rows = await _request("POST", "news", json=payload, prefer="return=representation")
    return rows[0]


async def insert_media(rows: list[dict]) -> None:
    if rows:
        await _request("POST", "news_media", json=rows, prefer="return=minimal")


async def get_news(news_id: str) -> dict | None:
    rows = await _request(
        "GET",
        f"news?id=eq.{news_id}&select=id,slug,title,summary,status,"
        f"news_media(kind,channel_message_id)&limit=1",
    )
    return rows[0] if rows else None


async def set_status(news_id: str, status: str) -> None:
    await _request("PATCH", f"news?id=eq.{news_id}", json={"status": status}, prefer="return=minimal")


async def delete_news(news_id: str) -> None:
    # news_media удалятся каскадом (on delete cascade)
    await _request("DELETE", f"news?id=eq.{news_id}", prefer="return=minimal")


async def list_latest(limit: int = 10) -> list[dict]:
    return await _request(
        "GET", f"news?select=id,slug,title,status,published_at&order=published_at.desc&limit={limit}",
    )


async def get_media_by_token(token: str) -> dict | None:
    """Для медиа-прокси: file_id + статус новости (скрытая → 404)."""
    rows = await _request(
        "GET",
        f"news_media?token=eq.{quote(token)}&select=kind,file_id,news(status)&limit=1",
        timeout=10,
    )
    return rows[0] if rows else None
