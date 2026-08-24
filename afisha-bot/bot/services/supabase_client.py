"""Доступ к Supabase (REST + Storage) через service_role — вставка заявок,
заливка медиа, чтение/запись видео-хранилища. Ключ service_role живёт только
в .env на сервере и никогда не попадает в клиентские файлы (см. п.2 ТЗ)."""
from __future__ import annotations

import logging
from datetime import date

import httpx

from bot.config import config

logger = logging.getLogger(__name__)


def _check(resp: httpx.Response) -> None:
    """Как raise_for_status(), но с телом ответа в сообщении — иначе причину
    4xx/5xx от PostgREST/Storage не видно в логах, только код статуса."""
    if resp.status_code >= 400:
        raise RuntimeError(f"Supabase {resp.request.method} {resp.request.url} -> {resp.status_code}: {resp.text}")


_REST_HEADERS = {
    "apikey": config.supabase_service_key,
    "Authorization": f"Bearer {config.supabase_service_key}",
    "Content-Type": "application/json",
}


def proxify(url: str | None) -> str | None:
    """Переписывает supabase.co-ссылки на sb.ekb-guide.ru — иначе медиа не откроется
    у посетителей из РФ (см. п.2 ТЗ)."""
    if not url:
        return url
    return url.replace(config.supabase_url, config.media_base_url)


async def upload_file(bucket: str, path: str, data: bytes, content_type: str) -> tuple[str, str]:
    """Заливает файл в Storage, возвращает (проксированный публичный url, путь в бакете)."""
    url = f"{config.supabase_url}/storage/v1/object/{bucket}/{path}"
    headers = {
        "apikey": config.supabase_service_key,
        "Authorization": f"Bearer {config.supabase_service_key}",
        "Content-Type": content_type,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, content=data)
    _check(resp)
    public_url = f"{config.supabase_url}/storage/v1/object/public/{bucket}/{path}"
    return proxify(public_url), path


async def insert_event_submission(payload: dict) -> dict:
    url = f"{config.supabase_url}/rest/v1/event_submissions"
    headers = {**_REST_HEADERS, "Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
    _check(resp)
    rows = resp.json()
    return rows[0] if rows else {}


async def count_pending_submissions() -> int:
    url = f"{config.supabase_url}/rest/v1/event_submissions?status=eq.pending&select=id"
    headers = {**_REST_HEADERS, "Prefer": "count=exact"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
    _check(resp)
    content_range = resp.headers.get("content-range", "")
    if "/" in content_range:
        total = content_range.split("/")[-1]
        if total.isdigit():
            return int(total)
    return len(resp.json())


async def insert_event_video(payload: dict) -> dict:
    url = f"{config.supabase_url}/rest/v1/event_videos"
    headers = {**_REST_HEADERS, "Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
    _check(resp)
    rows = resp.json()
    return rows[0] if rows else {}


async def get_video_by_token(token: str) -> dict | None:
    url = f"{config.supabase_url}/rest/v1/event_videos?token=eq.{token}&select=id,file_id,deleted&limit=1"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_REST_HEADERS)
    _check(resp)
    rows = resp.json()
    return rows[0] if rows else None


async def get_videos_to_cleanup(event_cutoff: date, fallback_cutoff: date) -> list[dict]:
    """Строки для удаления: событие прошло (event_date < today - EVENT_GRACE_DAYS),
    либо дата не распозналась и истёк запасной TTL (см. 4.6 ТЗ)."""
    filt = (
        f"deleted=eq.false&or=("
        f"and(event_date.not.is.null,event_date.lt.{event_cutoff.isoformat()}),"
        f"and(event_date.is.null,created_at.lt.{fallback_cutoff.isoformat()})"
        f")&select=id,token,channel_message_id"
    )
    url = f"{config.supabase_url}/rest/v1/event_videos?{filt}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_REST_HEADERS)
    _check(resp)
    return resp.json()


async def mark_video_deleted(video_id: str) -> None:
    url = f"{config.supabase_url}/rest/v1/event_videos?id=eq.{video_id}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(url, headers=_REST_HEADERS, json={"deleted": True})
    _check(resp)
