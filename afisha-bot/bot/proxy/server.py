"""aiohttp-прокси GET /v/<token>: отдаёт видео из приватного Telegram-канала
с поддержкой Range (см. 4.4 ТЗ). Полный файл (≤20 МБ) держится в памяти и
раздаётся диапазонами самостоятельно — Telegram Range отдаёт ненадёжно.
Запуск: python -m bot.proxy.server
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
from aiohttp import web

from bot.config import config
from bot.services import supabase_client

logger = logging.getLogger(__name__)

_FILE_PATH_TTL = 50 * 60  # file_path у Telegram живёт ~1 час, кэшируем с запасом
_BODY_CACHE_TTL = 5 * 60
_BODY_CACHE_MAX_ITEMS = 8


@dataclass
class _CachedBody:
    data: bytes
    expires_at: float


_body_cache: dict[str, _CachedBody] = {}
_file_path_cache: dict[str, tuple[str, float]] = {}


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
        logger.warning("getFile не удался для %s: %s", file_id, data)
        return None
    file_path = data["result"]["file_path"]
    _file_path_cache[file_id] = (file_path, time.monotonic() + _FILE_PATH_TTL)
    return file_path


async def _get_video_bytes(token: str, file_id: str) -> bytes | None:
    now = time.monotonic()
    cached = _body_cache.get(token)
    if cached and cached.expires_at > now:
        return cached.data

    file_path = await _get_file_path(file_id)
    if file_path is None:
        return None

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"https://api.telegram.org/file/bot{config.bot_token}/{file_path}")
    if resp.status_code != 200:
        logger.warning("Скачивание файла %s вернуло %s", file_path, resp.status_code)
        return None

    data = resp.content
    if len(_body_cache) >= _BODY_CACHE_MAX_ITEMS:
        oldest_token = min(_body_cache, key=lambda k: _body_cache[k].expires_at)
        _body_cache.pop(oldest_token, None)
    _body_cache[token] = _CachedBody(data=data, expires_at=now + _BODY_CACHE_TTL)
    return data


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


async def handle_video(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    row = await supabase_client.get_video_by_token(token)
    if row is None or row.get("deleted"):
        return web.Response(status=404, text="Not found")

    data = await _get_video_bytes(token, row["file_id"])
    if data is None:
        return web.Response(status=404, text="Not found")

    size = len(data)
    rng = _parse_range(request.headers.get("Range"), size)

    headers = {"Accept-Ranges": "bytes", "Content-Type": "video/mp4"}
    if rng is None:
        headers["Content-Length"] = str(size)
        return web.Response(status=200, body=data, headers=headers)

    start, end = rng
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    return web.Response(status=206, body=data[start : end + 1], headers=headers)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/v/{token}", handle_video)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=config.log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    web.run_app(create_app(), host="127.0.0.1", port=config.video_proxy_port)
