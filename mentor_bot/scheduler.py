"""Расписание: утренний совет по каждому проекту и вечерний вопрос «как прошло?»."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import advisor
from .config import Config
from .db import DB
from .llm import LLMError


def local_now(cfg: Config) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=cfg.tz_offset_hours)


def day_start_utc_iso(cfg: Config, now_local: datetime) -> str:
    """Начало текущих локальных суток в UTC (для поиска сегодняшних отчётов)."""
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return (start_local - timedelta(hours=cfg.tz_offset_hours)).isoformat(timespec="seconds")


async def send_advice(cfg: Config, db: DB, tg, project: dict) -> str:
    """Сгенерировать совет, отправить владельцу и сохранить в историю."""
    try:
        text = await advisor.generate(cfg, db, project)
    except LLMError as exc:
        text = f"⚠ Не смог подготовить совет по «{project['name']}»: {exc}"
        await tg.send(cfg.owner_chat_id, text)
        return text
    if not text:
        text = "Модель вернула пустой ответ — попробуй /now ещё раз."
    footer = "\n\n↩ Ответь на это сообщение, когда сделаешь (или не сделаешь) — учту завтра."
    message_id = await tg.send(cfg.owner_chat_id, text + footer)
    db.add_advice(project["name"], text, message_id)
    db.set_state("last_project", project["name"])
    return text


async def tick(cfg: Config, db: DB, tg) -> None:
    if not cfg.owner_chat_id:
        return  # режим настройки: владельца ещё нет
    now = local_now(cfg)
    hhmm = now.strftime("%H:%M")
    today = now.strftime("%Y-%m-%d")
    is_weekend = now.weekday() >= 5

    # Утро: совет по каждому проекту в его время.
    for p in db.list_projects():
        if not p["enabled"] or p["time_local"] != hhmm or p["last_sent_date"] == today:
            continue
        if p["weekdays_only"] and is_weekend:
            continue
        # Помечаем до отправки — при сбое не спамим повторами в тот же день.
        db.update_project(p["name"], last_sent_date=today)
        await send_advice(cfg, db, tg, p)

    # Вечер: спросить про задачи, по которым сегодня не было отчёта.
    if hhmm == cfg.evening_time and db.get_state("evening_date") != today:
        db.set_state("evening_date", today)
        since = day_start_utc_iso(cfg, now)
        pending = [p["name"] for p in db.list_projects()
                   if p["last_sent_date"] == today and not db.has_report_since(p["name"], since)]
        for name in pending:
            mid = await tg.send(cfg.owner_chat_id,
                                f"🌙 Как прошло с задачей по «{name}»? "
                                "Ответь на это сообщение парой слов: что сделал, что мешало.")
            if mid:
                db.add_advice(name, "вечерний вопрос", mid, kind="evening")
