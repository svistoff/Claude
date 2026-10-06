"""Тесты наставника: CRUD напоминаний, Telegram-клиент, планировщик (с моками)."""

from __future__ import annotations

import asyncio

from app.config import AppConfig
from app.database import repo
from app.mentor import scheduler, telegram


def test_reminder_crud():
    r = repo.create_reminder("fuck-app", "продать первому клиенту", "09:30", True)
    rid = r["id"]
    assert r["time_local"] == "09:30" and r["weekdays_only"] is True and r["enabled"]

    got = repo.get_reminder(rid)
    assert got and got["project"] == "fuck-app"

    repo.update_reminder(rid, enabled=False, goal="новая цель")
    got = repo.get_reminder(rid)
    assert got["enabled"] is False and got["goal"] == "новая цель"

    assert any(x["id"] == rid for x in repo.list_reminders())
    assert repo.delete_reminder(rid) is True
    assert repo.get_reminder(rid) is None


def test_telegram_not_configured(monkeypatch):
    monkeypatch.setattr(telegram, "get_settings",
                        lambda: type("S", (), {"telegram_bot_token": "", "telegram_chat_id": ""})())
    assert telegram.configured() is False
    ok, err = telegram.send_message("привет")
    assert ok is False and "Telegram" in err


def test_scheduler_tick_sends_due(monkeypatch):
    # Напоминание на «сейчас» по локальному времени → должно отправиться один раз.
    cfg = AppConfig()  # mentor.enabled=True, tz_offset_hours=3
    monkeypatch.setattr(scheduler, "get_app_config", lambda: cfg)
    monkeypatch.setattr(scheduler.telegram, "configured", lambda: True)

    now_local = scheduler._local_now()
    hhmm = now_local.strftime("%H:%M")
    r = repo.create_reminder("proj", "цель", hhmm, False)

    sent: list[str] = []
    monkeypatch.setattr(scheduler.telegram, "send_message", lambda text: (True, ""))

    async def fake_advice(project, goal):
        sent.append(project or "")
        return "🎯 Фокус: proj\n✅ Задача: позвонить клиенту"
    monkeypatch.setattr(scheduler.advisor, "generate_advice", fake_advice)

    asyncio.run(scheduler.tick())
    # Отправлено ровно один раз и помечено отправленным сегодня.
    assert sent == ["proj"]
    got = repo.get_reminder(r["id"])
    assert got["last_sent_date"] == now_local.strftime("%Y-%m-%d")

    # Повторный tick в тот же день — не дублирует.
    asyncio.run(scheduler.tick())
    assert sent == ["proj"]
    repo.delete_reminder(r["id"])


def test_scheduler_skips_disabled_telegram(monkeypatch):
    cfg = AppConfig()
    monkeypatch.setattr(scheduler, "get_app_config", lambda: cfg)
    monkeypatch.setattr(scheduler.telegram, "configured", lambda: False)
    calls: list[str] = []
    monkeypatch.setattr(scheduler.telegram, "send_message", lambda text: calls.append(text) or (True, ""))
    hhmm = scheduler._local_now().strftime("%H:%M")
    r = repo.create_reminder("p2", "g", hhmm, False)
    asyncio.run(scheduler.tick())
    assert calls == []  # без Telegram ничего не шлём
    repo.delete_reminder(r["id"])
