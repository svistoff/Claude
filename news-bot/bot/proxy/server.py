"""aiohttp-прокси GET /m/<token>: отдаёт фото и видео новостей из приватного
Telegram-канала-хранилища (см. 5 ТЗ). Копия afisha-bot/bot/proxy/server.py:
файл (≤20 МБ) целиком в памяти, Range для видео раздаём сами — Telegram
отдаёт Range ненадёжно. На диск ничего не пишем.
Запуск: python -m bot.proxy.server
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass

import httpx
from aiohttp import web

from bot.config import config
from bot.services import supabase_client

logger = logging.getLogger(__name__)

_FILE_PATH_TTL = 50 * 60  # file_path у Telegram живёт ~1 час, кэшируем с запасом
_BODY_CACHE_TTL = 5 * 60
_BODY_CACHE_MAX_ITEMS = 8
_ROW_CACHE_TTL = 30  # видео запрашивается кусками — не ходим в Supabase на каждый Range

_VIDEO_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
_PHOTO_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


@dataclass
class _CachedBody:
    data: bytes
    content_type: str
    expires_at: float


_body_cache: "OrderedDict[str, _CachedBody]" = OrderedDict()
_file_path_cache: dict[str, tuple[str, float]] = {}
_row_cache: dict[str, tuple[dict | None, float]] = {}


async def _get_row(token: str) -> dict | None:
    now = time.monotonic()
    cached = _row_cache.get(token)
    if cached and cached[1] > now:
        return cached[0]
    row = await supabase_client.get_media_by_token(token)
    if len(_row_cache) > 1000:
        _row_cache.clear()
    _row_cache[token] = (row, now + _ROW_CACHE_TTL)
    return row


async def _get_file_path(file_id: str) -> str | None:
    cached = _file_path_cache.get(file_id)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{config.bot_token}/getFile",
            params={"file_id": file_id},
        )
    data = resp.json()
    if not data.get("ok"):
        logger.warning("getFile не удался: %s", data.get("description"))
        return None
    file_path = data["result"]["file_path"]
    _file_path_cache[file_id] = (file_path, time.monotonic() + _FILE_PATH_TTL)
    return file_path


def _content_type(kind: str, file_path: str) -> str:
    ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    if kind == "video":
        return _VIDEO_TYPES.get(ext, "video/mp4")
    return _PHOTO_TYPES.get(ext, "image/jpeg")


async def _get_body(token: str, kind: str, file_id: str) -> _CachedBody | None:
    now = time.monotonic()
    cached = _body_cache.get(token)
    if cached and cached.expires_at > now:
        _body_cache.move_to_end(token)
        return cached

    file_path = await _get_file_path(file_id)
    if file_path is None:
        return None

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(f"https://api.telegram.org/file/bot{config.bot_token}/{file_path}")
    if resp.status_code != 200:
        logger.warning("Скачивание файла %s вернуло %s", file_path, resp.status_code)
        _file_path_cache.pop(file_id, None)
        return None

    body = _CachedBody(data=resp.content, content_type=_content_type(kind, file_path), expires_at=now + _BODY_CACHE_TTL)
    _body_cache[token] = body
    _body_cache.move_to_end(token)
    while len(_body_cache) > _BODY_CACHE_MAX_ITEMS:
        _body_cache.popitem(last=False)
    return body


def _parse_range(range_header: str | None, size: int) -> tuple[int, int] | None:
    if not range_header or not range_header.startswith("bytes="):
        return None
    spec = range_header[len("bytes="):].split(",")[0].strip()
    start_s, _, end_s = spec.partition("-")
    try:
        if start_s == "":
            suffix = int(end_s)
            start, end = max(size - suffix, 0), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    end = min(end, size - 1)
    if start < 0 or start > end:
        return None
    return start, end


_NOT_FOUND = {"Cache-Control": "no-store"}


async def handle_media(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    if not (8 <= len(token) <= 32) or not all(c.isalnum() or c in "-_" for c in token):
        return web.Response(status=404, text="Not found", headers=_NOT_FOUND)

    row = await _get_row(token)
    if row is None or (row.get("news") or {}).get("status") != "published":
        return web.Response(status=404, text="Not found", headers=_NOT_FOUND)

    kind = row["kind"]
    body = await _get_body(token, kind, row["file_id"])
    if body is None:
        return web.Response(status=404, text="Not found", headers=_NOT_FOUND)

    data, size = body.data, len(body.data)
    headers = {
        "Content-Type": body.content_type,
        "Cache-Control": "public, max-age=86400" if kind == "photo" else "public, max-age=3600",
        "Access-Control-Allow-Origin": "*",
    }
    if kind == "video":
        headers["Accept-Ranges"] = "bytes"
        rng = _parse_range(request.headers.get("Range"), size)
        if rng is not None:
            start, end = rng
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            headers["Content-Length"] = str(end - start + 1)
            return web.Response(status=206, body=data[start : end + 1], headers=headers)
        if request.headers.get("Range"):
            headers["Content-Range"] = f"bytes */{size}"
            return web.Response(status=416, headers=headers)

    headers["Content-Length"] = str(size)
    return web.Response(status=200, body=data, headers=headers)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/m/{token}", handle_media)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=config.log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    web.run_app(create_app(), host="127.0.0.1", port=config.media_proxy_port)
