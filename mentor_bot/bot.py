"""Точка входа: long polling Telegram + фоновое расписание в одном процессе."""

from __future__ import annotations

import asyncio
import logging

from . import config
from .db import DB
from .handlers import Handler
from .scheduler import tick
from .telegram import Telegram

log = logging.getLogger("mentor_bot")


async def polling_loop(handler: Handler, tg: Telegram) -> None:
    offset = None
    while True:
        try:
            updates = await tg.get_updates(offset)
        except Exception as exc:  # noqa: BLE001 — сеть/Telegram, просто повторяем
            log.warning("getUpdates: %s", exc)
            await asyncio.sleep(5)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            msg, cb = upd.get("message"), upd.get("callback_query")
            if not msg and not cb:
                continue
            try:
                if cb:
                    await handler.handle_callback(cb)
                else:
                    await handler.handle(msg)
            except Exception:  # noqa: BLE001 — одна ошибка не роняет бота
                log.exception("ошибка обработки сообщения")


async def schedule_loop(cfg, db: DB, tg: Telegram) -> None:
    while True:
        try:
            await tick(cfg, db, tg)
        except Exception:  # noqa: BLE001
            log.exception("ошибка планировщика")
        await asyncio.sleep(30)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = config.load()
    db = DB(cfg.db_path)
    tg = Telegram(cfg.bot_token)
    handler = Handler(cfg, db, tg)
    if cfg.owner_chat_id:
        log.info("Наставник запущен. Владелец: %s, пояс UTC%+d", cfg.owner_chat_id, cfg.tz_offset_hours)
    else:
        log.info("Режим настройки: напиши боту /start — он пришлёт твой chat_id")
    try:
        await asyncio.gather(polling_loop(handler, tg), schedule_loop(cfg, db, tg))
    finally:
        await tg.close()


if __name__ == "__main__":
    asyncio.run(main())
