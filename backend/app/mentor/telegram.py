"""Отправка сообщений в Telegram через Bot API (без зависимостей, httpx)."""

from __future__ import annotations

import httpx

from ..config import get_settings


def configured() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def send_message(text: str) -> tuple[bool, str]:
    """Отправить текст в заданный чат. Возвращает (ok, error)."""
    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        return False, "Telegram не настроен (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)."
    url = f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage"
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(url, json={"chat_id": s.telegram_chat_id, "text": text[:4000],
                                  "disable_web_page_preview": True})
        if r.status_code != 200:
            return False, f"Telegram API {r.status_code}: {r.text[:300]}"
        return True, ""
    except httpx.HTTPError as exc:
        return False, f"Сетевая ошибка Telegram: {exc}"
