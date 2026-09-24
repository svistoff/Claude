"""Инструмент браузер-агента (Фаза 3).

Действия: open, click, type, select, get_text, scroll, back, wait, screenshot.
Модель текстовая: страницу «видит» через get_text и OCR скриншотов; сами скриншоты
показываются пользователю в UI (extra.screenshot_url).
"""

from __future__ import annotations

from pathlib import Path

from ..browser import manager
from .base import ToolContext, ToolResult


def browser_tool(ctx: ToolContext, action: str, **kwargs) -> ToolResult:
    ok, reason = manager.available()
    if not ok:
        return ToolResult(False, f"Браузер недоступен: {reason}", summary="browser: unavailable")

    res = manager.execute(action, kwargs)
    if not res.get("ok"):
        return ToolResult(False, res.get("error", "Ошибка браузера."),
                          summary=f"browser {action}: error")

    if action == "open":
        return ToolResult(True, f"Открыто: {res.get('title','')} ({res.get('url','')})",
                          summary=f"browser: open {res.get('url','')[:50]}", extra=res)
    if action == "get_text":
        return ToolResult(True, f"Текст страницы {res.get('url','')}:\n{res.get('text','')}",
                          summary="browser: get_text", extra={"url": res.get("url")})
    if action == "screenshot":
        sid = res.get("screenshot_id")
        # OCR для модели (если доступен tesseract).
        ocr = _ocr(Path(res["path"])) if res.get("path") else None
        content = f"Скриншот {res.get('url','')} сохранён."
        if ocr and ocr.strip():
            content += f"\nРаспознанный текст:\n{ocr.strip()[:4000]}"
        else:
            content += " (текст не распознан; пользователь видит изображение в чате)"
        return ToolResult(True, content, summary="browser: screenshot",
                          extra={"screenshot_url": f"/api/browser/screenshot/{sid}",
                                 "url": res.get("url")})
    # click/type/select/scroll/back/wait
    return ToolResult(True, f"OK ({action})" + (f" · {res.get('url')}" if res.get("url") else ""),
                      summary=f"browser: {action}", extra=res)


def _ocr(path: Path) -> str | None:
    from ..uploads_store import _ocr_image
    return _ocr_image(path)
