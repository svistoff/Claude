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
        self.buttons: list[list[list[dict]] | None] = []
        self.answers: list[tuple[str, str]] = []
        self.markups: list[tuple[int, list[list[dict]]]] = []

    async def send(self, chat_id: int, text: str, buttons=None) -> int:
        mid = len(self.sent) + 1000
        self.sent.append((chat_id, text, mid))
        self.buttons.append(buttons)
        return mid

    async def download_file(self, file_id: str) -> bytes:
        return b"ogg"

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.answers.append((callback_id, text))

    async def set_buttons(self, chat_id: int, message_id: int, buttons) -> None:
        self.markups.append((message_id, buttons))

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
        if "организатор" in system:
            return "🗓 План на сегодня\n⭐ Главное: #1"
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
    run(h.handle(msg(f"/add Shop {tmp_path}")))
    p = db.get_project("shop")
    assert p and p["path"] == str(tmp_path) and p["time_local"] == "09:00"

    run(h.handle(msg("/goal shop первый платёж за подписку")))
    assert "подписку" in db.get_project("shop")["goal"]

    run(h.handle(msg("/time shop 08:30 будни")))
    p = db.get_project("shop")
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


def test_plain_message_becomes_task(env):
    _, db, tg, h, _ = env
    run(h.handle(msg("позвонить бухгалтеру")))
    run(h.handle(msg("ответить клиенту")))
    assert [t["text"] for t in db.open_tasks()] == ["позвонить бухгалтеру", "ответить клиенту"]
    assert "#2" in tg.last


def test_done_and_drop(env):
    _, db, tg, h, _ = env
    a = db.add_task("a")
    b = db.add_task("b")
    run(h.handle(msg(f"/done {a}")))
    run(h.handle(msg(f"/drop #{b}")))
    assert db.open_tasks() == []
    run(h.handle(msg("/done 99")))
    assert "нет" in tg.last


def test_reply_to_advice_is_report_not_task(env):
    _, db, tg, h, _ = env
    db.add_project("app")
    run(h.handle(msg("/now app")))
    run(h.handle(msg("сделал", reply_to=tg.sent[-1][2])))
    assert db.open_tasks() == [] and db.recent_reports("app")[0]["text"] == "сделал"


def test_plan_uses_open_tasks(env):
    _, db, tg, h, prompts = env
    db.add_task("доделать оплату")
    run(h.handle(msg("/plan")))
    assert "Главное" in tg.last
    assert "#1 [обычная] доделать оплату" in prompts[-1]


def test_morning_plan_and_evening_summary(env, monkeypatch):
    cfg, db, tg, h, _ = env
    t1 = db.add_task("задача раз")
    db.add_task("задача два")
    monkeypatch.setattr(scheduler, "local_now", lambda c: datetime.now().replace(hour=8, minute=30))
    run(scheduler.tick(cfg, db, tg))
    run(scheduler.tick(cfg, db, tg))
    assert sum("План на сегодня" in t for _, t, _ in tg.sent) == 1
    run(h.handle(msg(f"/done {t1}")))
    monkeypatch.setattr(scheduler, "local_now", lambda c: datetime.now().replace(hour=20, minute=0))
    run(scheduler.tick(cfg, db, tg))
    assert "Сделано: задача раз" in tg.last and "#2 задача два" in tg.last


# --- Срочность, порция на день, кнопки ---------------------------------------

def cb(data: str, rows=None, chat_id: int = OWNER) -> dict:
    m = {"chat": {"id": chat_id}, "message_id": 77}
    if rows is not None:
        m["reply_markup"] = {"inline_keyboard": rows}
    return {"id": "cb1", "data": data, "message": m}


def test_priority_prefixes_parsed():
    from mentor_bot.tasks import parse_priority
    assert parse_priority("! позвонить") == ("urgent", "позвонить")
    assert parse_priority("Срочно: оплатить") == ("urgent", "оплатить")
    assert parse_priority("потом разобрать почту") == ("later", "разобрать почту")
    assert parse_priority("потомство") == ("normal", "потомство")
    assert parse_priority("!") == ("normal", "!")


def test_message_sets_priority_and_offers_buttons(env):
    _, db, tg, h, _ = env
    run(h.handle(msg("!! сдать отчёт")))
    t = db.open_tasks()[0]
    assert t["priority"] == "urgent" and t["text"] == "сдать отчёт"
    assert tg.buttons[-1][0][0]["callback_data"] == f"urgent:{t['id']}"


def test_priority_commands(env):
    _, db, _, h, _ = env
    i = db.add_task("x")
    run(h.handle(msg(f"/later {i}")))
    assert db.get_task(i)["priority"] == "later"
    run(h.handle(msg(f"/urgent #{i}")))
    assert db.get_task(i)["priority"] == "urgent"


def test_plan_portion_is_limited_and_has_buttons(env):
    cfg, db, tg, h, prompts = env
    for n in range(5):
        db.add_task(f"позже {n}", "later")
    db.add_task("срочное", "urgent")
    run(h.handle(msg("/plan")))
    # «на потом» — максимум 2 за раз, остальное в запасе
    assert prompts[-1].count("на потом") == 2 and "в запасе" in prompts[-1]
    # в ответе фейка есть «#1» → под планом кнопки для этой задачи
    rows = tg.buttons[-1]
    assert [b["callback_data"] for b in rows[0]] == ["done:1", "snooze:1"]


def test_later_tasks_rotate(env):
    from mentor_bot.tasks import select_for_plan
    ts = [{"id": i, "priority": "later", "postponed": 0, "hidden_until": None,
           "last_shown": "2026-01-01" if i < 3 else None, "text": "t"} for i in range(1, 5)]
    picked, reserve = select_for_plan(ts, "2026-02-01")
    assert sorted(t["id"] for t in picked) == [3, 4] and reserve == 2


def test_snoozed_task_hidden_until_tomorrow(env):
    from mentor_bot.tasks import select_for_plan
    t = {"id": 1, "priority": "normal", "postponed": 1, "hidden_until": "2026-02-02",
         "last_shown": None, "text": "t"}
    assert select_for_plan([t], "2026-02-01")[0] == []
    assert select_for_plan([t], "2026-02-02")[0] == [t]


def test_callback_done_removes_task_buttons(env):
    _, db, tg, h, _ = env
    a, b = db.add_task("a"), db.add_task("b")
    from mentor_bot.tasks import plan_buttons
    run(h.handle_callback(cb(f"done:{a}", plan_buttons([a, b]))))
    assert db.get_task(a)["done"] == 1 and db.get_task(b)["done"] == 0
    assert tg.answers[-1][1] == "✅ Сделано"
    kept = tg.markups[-1][1]
    assert len(kept) == 1 and kept[0][0]["callback_data"] == f"done:{b}"


def test_callback_snooze_counts_postpone(env):
    _, db, tg, h, _ = env
    a = db.add_task("a")
    run(h.handle_callback(cb(f"snooze:{a}", [])))
    t = db.get_task(a)
    assert t["postponed"] == 1 and t["hidden_until"]


def test_callback_from_stranger_ignored(env):
    _, db, tg, h, _ = env
    a = db.add_task("a")
    run(h.handle_callback(cb(f"done:{a}", [], chat_id=999)))
    assert db.get_task(a)["done"] == 0


def test_db_migrates_old_tasks_table(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, "
              "done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, done_at TEXT)")
    c.execute("INSERT INTO tasks (text, created_at) VALUES ('старая', 'x')")
    c.commit(); c.close()
    db = DB(path)
    assert db.open_tasks()[0]["priority"] == "normal"


# --- Голосовые -----------------------------------------------------------------

def voice(reply_to: int | None = None, duration: int = 10) -> dict:
    m = {"chat": {"id": OWNER}, "voice": {"file_id": "f1", "duration": duration}}
    if reply_to is not None:
        m["reply_to_message"] = {"message_id": reply_to}
    return m


@pytest.fixture
def stt_env(env, monkeypatch):
    cfg, db, tg, h, prompts = env
    cfg.stt_api_key = "s"
    said = {"text": "срочно позвонить бухгалтеру, а ещё потом разобрать почту"}

    async def fake_stt(api_key, base_url, model, audio, **kw):
        return said["text"]

    async def fake_complete(api_key, base_url, model, system, user, max_tokens=800):
        if "диктует" in system:
            return ('```json\n[{"text": "Позвонить бухгалтеру", "priority": "urgent"},'
                    '{"text": "Разобрать почту", "priority": "later"}]\n```')
        return "ok"

    monkeypatch.setattr("mentor_bot.stt.transcribe", fake_stt)
    monkeypatch.setattr(advisor.llm, "complete", fake_complete)
    return cfg, db, tg, h, said


def test_voice_splits_into_tasks_with_priorities(stt_env):
    _, db, tg, h, _ = stt_env
    run(h.handle(voice()))
    got = [(t["text"], t["priority"]) for t in db.open_tasks()]
    assert got == [("Позвонить бухгалтеру", "urgent"), ("Разобрать почту", "later")]
    assert "задачи (2)" in tg.last and "срочно позвонить" in tg.last


def test_voice_falls_back_to_single_task_on_bad_json(stt_env, monkeypatch):
    _, db, tg, h, said = stt_env

    async def junk(*a, **kw):
        return "не json"

    monkeypatch.setattr(advisor.llm, "complete", junk)
    said["text"] = "срочно оплатить хостинг"
    run(h.handle(voice()))
    t = db.open_tasks()[0]
    assert (t["text"], t["priority"]) == ("оплатить хостинг", "urgent")


def test_voice_reply_to_advice_is_report(stt_env):
    _, db, tg, h, said = stt_env
    db.add_project("app")
    db.add_advice("app", "шаг", 555)
    said["text"] = "написал трём клиентам"
    run(h.handle(voice(reply_to=555)))
    assert db.open_tasks() == [] and db.recent_reports("app")[0]["text"] == "написал трём клиентам"


def test_voice_without_stt_key(env):
    _, db, tg, h, _ = env
    run(h.handle(voice()))
    assert "STT_API_KEY" in tg.last and db.open_tasks() == []


def test_voice_too_long_and_stranger(stt_env):
    _, db, tg, h, _ = stt_env
    run(h.handle(voice(duration=900)))
    assert "покороче" in tg.last and db.open_tasks() == []
    m = voice(); m["chat"]["id"] = 999
    run(h.handle(m))
    assert "только владельцу" in tg.last and db.open_tasks() == []


def test_stt_error_is_reported(stt_env, monkeypatch):
    from mentor_bot.stt import STTError
    _, db, tg, h, _ = stt_env

    async def boom(*a, **kw):
        raise STTError("API 401")

    monkeypatch.setattr("mentor_bot.stt.transcribe", boom)
    run(h.handle(voice()))
    assert "401" in tg.last and db.open_tasks() == []


# --- Копилка мыслей ------------------------------------------------------------

def test_forwarded_message_goes_to_notes_not_tasks(env):
    _, db, tg, h, _ = env
    m = msg("Делай маленькие шаги каждый день")
    m["forward_origin"] = {"type": "channel", "chat": {"title": "Мудрость"}}
    run(h.handle(m))
    n = db.list_notes()[0]
    assert n["text"].startswith("Делай") and n["source"] == "Мудрость"
    assert db.open_tasks() == [] and "копилку" in tg.last


def test_photo_saved_with_caption_and_file_id(env):
    _, db, _, h, _ = env
    run(h.handle({"chat": {"id": OWNER}, "caption": "схема воронки",
                  "photo": [{"file_id": "small"}, {"file_id": "big"}]}))
    n = db.list_notes()[0]
    assert (n["kind"], n["file_id"], n["text"]) == ("photo", "big", "схема воронки")


def test_prefix_and_bare_link_are_notes(env):
    _, db, _, h, _ = env
    run(h.handle(msg("💡 Лучший маркетинг — продукт")))
    run(h.handle(msg("https://example.com/post")))
    run(h.handle(msg("обычная задача")))
    kinds = sorted(n["kind"] for n in db.list_notes())
    assert kinds == ["link", "text"] and len(db.open_tasks()) == 1


def test_notes_list_search_and_delete(env):
    _, db, tg, h, _ = env
    a = db.add_note("про деньги")
    db.add_note("про время")
    run(h.handle(msg("/notes деньги")))
    assert "про деньги" in tg.last and "про время" not in tg.last
    run(h.handle(msg(f"/unnote {a}")))
    assert db.count_notes() == 1


def test_voice_with_prefix_is_note(stt_env):
    _, db, _, h, said = stt_env
    said["text"] = "Мысль: делегировать рутину"
    run(h.handle(voice()))
    assert db.list_notes()[0]["text"] == "делегировать рутину" and db.open_tasks() == []
