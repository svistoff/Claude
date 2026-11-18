"""Отправка сообщений в Telegram через Bot API (без зависимостей, httpx)."""

from __future__ import annotations

import httpx

from ..config import get_settings
from ..telegram.client import redact


def configured() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def send_message(text: str, markdown: bool = False) -> tuple[bool, str]:
    """Отправить текст в заданный чат. Возвращает (ok, error).

    markdown=True — перевести Markdown в HTML-разметку Telegram (с откатом на текст)."""
    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        return False, "Telegram не настроен (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)."
    url = f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage"
    try:
        payload = {"chat_id": s.telegram_chat_id, "text": text[:4000],
                   "disable_web_page_preview": True}
        if markdown:
            from ..telegram.format import md_to_html
            payload.update(text=md_to_html(text)[:4000], parse_mode="HTML")
        with httpx.Client(timeout=30) as c:
            r = c.post(url, json=payload)
            if r.status_code != 200 and markdown:
                payload.pop("parse_mode")
                payload["text"] = text[:4000]
                r = c.post(url, json=payload)
        if r.status_code != 200:
            return False, redact(f"Telegram API {r.status_code}: {r.text[:300]}")
        return True, ""
    except httpx.HTTPError as exc:
        return False, redact(f"Сетевая ошибка Telegram: {exc}")
