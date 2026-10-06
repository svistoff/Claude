"""Фоновый планировщик напоминаний (лёгкий asyncio-цикл, без доп. зависимостей).

Раз в ~30 секунд проверяет напоминания: если локальное время совпало с заданным
и сегодня ещё не отправляли — генерирует совет и шлёт в Telegram. Рассчитан на
один рабочий процесс uvicorn (в systemd так и есть).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from ..config import get_app_config
from ..database import repo
from . import advisor, telegram

_task: asyncio.Task | None = None


def _local_now() -> datetime:
    offset = get_app_config().mentor.tz_offset_hours
    return datetime.now(timezone.utc) + timedelta(hours=offset)


async def _fire(reminder: dict, today: str) -> None:
    """Сгенерировать совет и отправить. Помечает отправку до send, чтобы при
    ошибке не спамить повторными попытками в тот же день."""
    repo.mark_reminder_sent(reminder["id"], today)
    try:
        advice = await advisor.generate_advice(reminder.get("project"), reminder.get("goal", ""))
    except Exception as exc:  # noqa: BLE001
        advice = f"(не удалось сгенерировать совет: {exc})"
    ok, err = await asyncio.to_thread(telegram.send_message, advice)
    repo.add_reminder_log(reminder["id"], reminder.get("project"),
                          advice if ok else f"{advice}\n\n[не отправлено: {err}]", ok)


async def tick() -> None:
    cfg = get_app_config().mentor
    if not cfg.enabled or not telegram.configured():
        return
    now = _local_now()
    hhmm = now.strftime("%H:%M")
    today = now.strftime("%Y-%m-%d")
    is_weekend = now.weekday() >= 5
    for r in repo.list_reminders():
        if not r["enabled"] or r["time_local"] != hhmm or r["last_sent_date"] == today:
            continue
        if r["weekdays_only"] and is_weekend:
            continue
        await _fire(r, today)


async def _loop() -> None:
    while True:
        try:
            await tick()
        except Exception:  # noqa: BLE001 — планировщик не должен падать
            pass
        await asyncio.sleep(30)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
