"""Минимальный клиент Telegram Bot API (long polling) на httpx."""

from __future__ import annotations

import httpx


class Telegram:
    def __init__(self, token: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}"
        self.client = httpx.AsyncClient(timeout=60)

    async def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict]:
        params: dict = {"timeout": timeout, "allowed_updates": '["message"]'}
        if offset is not None:
            params["offset"] = offset
        r = await self.client.get(f"{self.base}/getUpdates", params=params,
                                  timeout=timeout + 10)
        r.raise_for_status()
        return r.json().get("result", [])

    async def send(self, chat_id: int, text: str) -> int | None:
        """Отправить сообщение, вернуть его message_id (или None при ошибке)."""
        r = await self.client.post(f"{self.base}/sendMessage", json={
            "chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True,
        })
        if r.status_code != 200:
            return None
        return r.json().get("result", {}).get("message_id")

    async def close(self) -> None:
        await self.client.aclose()
