"""Генерация изображений через fal.ai (раздел — сверх ТЗ).

Инструмент generate_image: отправляет промпт в fal.ai, скачивает результат в
WORKSPACE_TMP/generated и возвращает URL для показа в чате (как скриншоты браузера).
Модель текстовая картинку «не видит»; изображение показывается пользователю.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from ..config import BACKEND_DIR, get_app_config, get_settings
from .base import ToolContext, ToolResult


def media_dir() -> Path:
    tmp = get_settings().workspace_tmp
    p = Path(tmp)
    if not p.is_absolute():
        p = BACKEND_DIR / p
    d = (p / "generated").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_image(ctx: ToolContext, prompt: str, image_size: str = "landscape_4_3") -> ToolResult:
    key = get_settings().fal_key
    if not key:
        return ToolResult(False, "FAL_KEY не задан — генерация изображений недоступна.",
                          summary="image: no key")
    if not (prompt or "").strip():
        return ToolResult(False, "Пустой промпт.", summary="image: empty prompt")

    cfg = get_app_config().image
    url = f"{cfg.base_url.rstrip('/')}/{cfg.model}"
    try:
        with httpx.Client(timeout=180) as c:
            r = c.post(url, headers={"Authorization": f"Key {key}",
                                     "Content-Type": "application/json"},
                       json={"prompt": prompt, "image_size": image_size})
        if r.status_code != 200:
            return ToolResult(False, f"fal.ai {r.status_code}: {r.text[:300]}", summary="image: error")
        data = r.json()
        img = (data.get("images") or [{}])[0]
        img_url = img.get("url")
        if not img_url:
            return ToolResult(False, "fal.ai не вернул изображение.", summary="image: no result")
        with httpx.Client(timeout=120) as c:
            ib = c.get(img_url)
        ct = ib.headers.get("content-type", "image/png")
        ext = "jpg" if ("jpeg" in ct or "jpg" in ct) else ("webp" if "webp" in ct else "png")
        sid = uuid.uuid4().hex[:16]
        (media_dir() / f"{sid}.{ext}").write_bytes(ib.content)
        return ToolResult(
            True, f"Сгенерировано изображение по запросу: «{prompt}»",
            summary="image: готово",
            extra={"screenshot_url": f"/api/files/media/{sid}", "prompt": prompt, "source_url": img_url},
        )
    except httpx.HTTPError as exc:
        return ToolResult(False, f"Сетевая ошибка fal.ai: {exc}", summary="image: neterr")
