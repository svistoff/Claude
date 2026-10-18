"""Тесты наставника: команды, отчёты, память, расписание (Telegram и LLM — фейки)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from mentor_bot import advisor, scheduler
from mentor_bot.config import Config
from mentor_bot.db import DB
from mentor_bot.handlers import Handler

OWNER = 111


class FakeTG:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, int]] = []

    async def send(self, chat_id: int, text: str) -> int:
        mid = len(self.sent) + 1000
        self.sent.append((chat_id, text, mid))
        return mid

    @property
    def last(self) -> str:
        return self.sent[-1][1]


@pytest.fixture
def env(monkeypatch):
    cfg = Config(bot_token="t", owner_chat_id=OWNER, llm_api_key="k", tz_offset_hours=5)
    db = DB(":memory:")
    tg = FakeTG()
    prompts: list[str] = []

    async def fake_complete(api_key, base_url, model, system, user, max_tokens=800):
        prompts.append(user)
        return "🎯 Фокус: тест\n✅ Задача на сегодня (2–4ч): написать 3 клиентам"

    monkeypatch.setattr(advisor.llm, "complete", fake_complete)
    return cfg, db, tg, Handler(cfg, db, tg), prompts


def msg(text: str, chat_id: int = OWNER, reply_to: int | None = None) -> dict:
    m = {"chat": {"id": chat_id}, "text": text}
    if reply_to is not None:
        m["reply_to_message"] = {"message_id": reply_to}
    return m


def run(coro):
    return asyncio.run(coro)


def test_setup_mode_reveals_chat_id(env):
    cfg, db, tg, _, _ = env
    cfg.owner_chat_id = 0
    run(Handler(cfg, db, tg).handle(msg("/start", chat_id=555)))
    assert "555" in tg.last and "OWNER_CHAT_ID=555" in tg.last


def test_stranger_is_refused(env):
    _, db, tg, h, _ = env
    run(h.handle(msg("/add hack", chat_id=999)))
    assert db.list_projects() == []
    assert "только владельцу" in tg.last


def test_add_goal_time_flow(env, tmp_path):
    _, db, tg, h, _ = env
    run(h.handle(msg(f"/add Companion {tmp_path}")))
    p = db.get_project("companion")
    assert p and p["path"] == str(tmp_path) and p["time_local"] == "09:00"

    run(h.handle(msg("/goal companion Бот Лиза, первый платёж в Stars")))
    assert "Stars" in db.get_project("companion")["goal"]

    run(h.handle(msg("/time companion 08:30 будни")))
    p = db.get_project("companion")
    assert p["time_local"] == "08:30" and p["weekdays_only"] == 1


def test_add_rejects_missing_folder(env):
    _, db, tg, h, _ = env
    run(h.handle(msg("/add x /no/such/dir")))
    assert db.get_project("x") is None and "не найдена" in tg.last


def test_now_sends_and_remembers(env):
    _, db, tg, h, _ = env
    db.add_project("app")
    run(h.handle(msg("/now")))  # единственный проект — имя не нужно
    assert "написать 3 клиентам" in tg.last
    assert len(db.recent_advice("app")) == 1


def test_reply_to_advice_becomes_report(env):
    _, db, tg, h, _ = env
    db.add_project("a")
    db.add_project("b")
    run(h.handle(msg("/now a")))
    advice_mid = tg.sent[-1][2]
    run(h.handle(msg("/now b")))
    # Ответ на совет по «a» должен попасть в «a», хотя последним был «b».
    run(h.handle(msg("сделал, 2 отклика", reply_to=advice_mid)))
    assert db.recent_reports("a")[0]["text"] == "сделал, 2 отклика"
    assert db.recent_reports("b") == []


def test_memory_goes_into_next_prompt(env):
    _, db, tg, h, prompts = env
    db.add_project("app")
    db.update_project("app", goal="продать подписку")
    run(h.handle(msg("/now app")))
    run(h.handle(msg("/report app написал 3 клиентам, 1 заинтересовался")))
    run(h.handle(msg("/now app")))
    last_prompt = prompts[-1]
    assert "продать подписку" in last_prompt
    assert "1 заинтересовался" in last_prompt
    assert "написать 3 клиентам" in last_prompt  # прошлый совет в памяти


def test_scheduler_morning_once_per_day(env, monkeypatch):
    cfg, db, tg, _, _ = env
    fixed = datetime(2026, 10, 20, 9, 0)  # вторник
    monkeypatch.setattr(scheduler, "local_now", lambda c: fixed)
    db.add_project("app", time_local="09:00")
    run(scheduler.tick(cfg, db, tg))
    run(scheduler.tick(cfg, db, tg))
    assert sum("написать 3 клиентам" in t for _, t, _ in tg.sent) == 1


def test_scheduler_weekdays_only_skips_weekend(env, monkeypatch):
    cfg, db, tg, _, _ = env
    monkeypatch.setattr(scheduler, "local_now", lambda c: datetime(2026, 10, 18, 9, 0))  # вс
    db.add_project("app", time_local="09:00")
    db.update_project("app", weekdays_only=1)
    run(scheduler.tick(cfg, db, tg))
    assert tg.sent == []


def test_evening_asks_only_without_report(env, monkeypatch):
    cfg, db, tg, h, _ = env
    db.add_project("a", time_local="09:00")
    db.add_project("b", time_local="09:00")
    monkeypatch.setattr(scheduler, "local_now", lambda c: datetime.now().replace(hour=9, minute=0))
    run(scheduler.tick(cfg, db, tg))
    run(h.handle(msg("/report a всё сделал")))
    sent_before = len(tg.sent)
    monkeypatch.setattr(scheduler, "local_now", lambda c: datetime.now().replace(hour=20, minute=0))
    run(scheduler.tick(cfg, db, tg))
    evening = [t for _, t, _ in tg.sent[sent_before:]]
    assert len(evening) == 1 and "«b»" in evening[0]
    # Вечерний вопрос не попадает в память советов.
    assert all(a["kind"] == "advice" for a in db.recent_advice("b"))
