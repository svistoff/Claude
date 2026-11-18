"""Асинхронный клиент Telegram Bot API (long polling, кнопки, картинки)."""

from __future__ import annotations

from pathlib import Path

import httpx


class TelegramClient:
    def __init__(self, token: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}"
        self.http = httpx.AsyncClient(timeout=60)

    async def _call(self, method: str, **payload) -> dict | None:
        r = await self.http.post(f"{self.base}/{method}", json=payload)
        if r.status_code != 200:
            return None
        return r.json().get("result")

    async def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict]:
        params: dict = {"timeout": timeout, "allowed_updates": '["message","callback_query"]'}
        if offset is not None:
            params["offset"] = offset
        r = await self.http.get(f"{self.base}/getUpdates", params=params, timeout=timeout + 10)
        r.raise_for_status()
        return r.json().get("result", [])

    async def send(self, chat_id: int | str, text: str, html: bool = False,
                   buttons: list[list[tuple[str, str]]] | None = None) -> int | None:
        """Отправить сообщение. buttons — ряды кнопок (текст, callback_data)."""
        payload: dict = {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True}
        if html:
            payload["parse_mode"] = "HTML"
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [
                [{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
        res = await self._call("sendMessage", **payload)
        if res is None and html:
            # Разметка не прошла валидацию Telegram — шлём как обычный текст.
            payload.pop("parse_mode", None)
            res = await self._call("sendMessage", **payload)
        return res.get("message_id") if res else None

    async def edit(self, chat_id: int | str, message_id: int, text: str) -> None:
        await self._call("editMessageText", chat_id=chat_id, message_id=message_id,
                         text=text[:4096], disable_web_page_preview=True)

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self._call("answerCallbackQuery", callback_query_id=callback_id, text=text[:200])

    async def typing(self, chat_id: int | str) -> None:
        await self._call("sendChatAction", chat_id=chat_id, action="typing")

    async def send_photo(self, chat_id: int | str, path: Path, caption: str = "") -> None:
        with path.open("rb") as f:
            await self.http.post(f"{self.base}/sendPhoto",
                                 data={"chat_id": str(chat_id), "caption": caption[:1024]},
                                 files={"photo": (path.name, f)})

    async def close(self) -> None:
        await self.http.aclose()
