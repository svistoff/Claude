"""Тесты журнала выполненной работы и отчётов (отчёт шефу).

Проверяем: запись работы, попадание закрытой задачи в журнал, материал для
отчёта, команды /wlog и /report в Telegram (LLM — фейк).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import AppConfig
from app.database import repo
from app.tools.base import ToolContext
from app.tools.worklog import worklog_tool


def _ctx(root: Path, project: str = "proj") -> ToolContext:
    return ToolContext(project_name=project, project_root=root, config=AppConfig())


def _clean():
    """Очистить журнал и задачи, чтобы тесты не зависели друг от друга."""
    import sqlite3
    from app.database import db_path, init_db
    init_db()  # в тестовой БД могут быть ещё не созданы новые таблицы
    con = sqlite3.connect(db_path())
    con.execute("delete from work_log")
    con.execute("delete from tasks")
    con.commit()
    con.close()


# --- Инструмент worklog -------------------------------------------------------

def test_add_work_logs_with_current_project(tmp_path):
    _clean()
    r = worklog_tool(_ctx(tmp_path, "fuckwell-crm"), "add", "починил звонки")
    assert r.ok, r.content
    assert "починил звонки" in r.content
    entries = repo.recent_work()
    assert entries and entries[0]["text"] == "починил звонки"
    assert entries[0]["project"] == "fuckwell-crm"
    assert entries[0]["source"] == "owner"


def test_add_work_empty_text_rejected(tmp_path):
    _clean()
    r = worklog_tool(_ctx(tmp_path), "add", "   ")
    assert not r.ok and "Пустой" in r.content


def test_list_returns_entries(tmp_path):
    _clean()
    repo.add_work("сделал раз", project="p")
    r = worklog_tool(_ctx(tmp_path), "list", days=7)
    assert r.ok and "сделал раз" in r.content


def test_list_empty(monkeypatch, tmp_path):
    _clean()
    monkeypatch.setattr(repo, "work_since", lambda since: [])
    r = worklog_tool(_ctx(tmp_path), "list")
    assert r.ok and "нет" in r.content.lower()


def test_report_builds_material_for_llm(tmp_path):
    _clean()
    repo.add_work("починил звонки", project="crm")
    repo.add_work("написал письмо приставам")
    r = worklog_tool(_ctx(tmp_path), "report", days=7)
    assert r.ok
    assert "починил звонки" in r.content and "приставам" in r.content
    assert r.extra["count"] == 2
    # Провокация на человеческую формулировку, а не на дамп данных.
    assert "Простым языком" in r.content or "простым языком" in r.content


def test_report_empty_says_nothing_to_show(monkeypatch, tmp_path):
    _clean()
    monkeypatch.setattr(repo, "work_since", lambda since: [])
    r = worklog_tool(_ctx(tmp_path), "report", days=7)
    assert r.ok and "нет" in r.content.lower()


def test_unknown_action(tmp_path):
    r = worklog_tool(_ctx(tmp_path), "peek")
    assert not r.ok


# --- Закрытая задача попадает в журнал ---------------------------------------

def test_completing_task_writes_work_log():
    _clean()
    t = repo.add_task("позвонить бухгалтеру")
    assert repo.recent_work() == []
    repo.complete_task(t["id"])
    entries = repo.recent_work()
    assert len(entries) == 1
    assert entries[0]["text"] == "позвонить бухгалтеру"
    assert entries[0]["source"] == "task"


def test_completing_task_can_skip_work_log():
    _clean()
    t = repo.add_task("случайная")
    repo.complete_task(t["id"], log_work=False)
    assert repo.recent_work() == []


def test_work_since_filters_by_date():
    _clean()
    old = repo.add_work("старое")
    # Сдвигаем дату в прошлое напрямую в БД.
    import sqlite3
    from app.database import db_path
    con = sqlite3.connect(db_path())
    past = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=40))
    con.execute("update work_log set created_at=? where id=?", (past.strftime("%Y-%m-%d %H:%M:%S"), old["id"]))
    con.commit()
    con.close()
    repo.add_work("свежее")
    recent = repo.work_since(datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7))
    texts = [e["text"] for e in recent]
    assert "свежее" in texts and "старое" not in texts


# --- Команды бота -------------------------------------------------------------

@pytest.fixture
def gw(tmp_path, monkeypatch):
    from app.telegram import gateway

    class FakeTG:
        def __init__(self):
            self.sent: list[str] = []

        async def send(self, chat_id, text, html=False, buttons=None):
            self.sent.append(text)
            return len(self.sent)

        async def edit(self, chat_id, mid, text):
            self.sent.append(text)

        async def typing(self, chat_id):
            pass

        async def send_photo(self, chat_id, path, caption=""):
            pass

    monkeypatch.setattr(gateway.projects_store, "all_projects",
                        lambda: [{"name": "proj", "path": str(tmp_path), "available": True, "kind": "custom"}])
    monkeypatch.setattr(gateway.projects_store, "project_root", lambda name: tmp_path)
    repo.set_setting(gateway.KEY_PROJECT, "")
    repo.set_setting(gateway.KEY_CONVERSATION, "")
    g = gateway.Gateway("token", "777")
    g.tg = FakeTG()
    return g


def _msg(text: str) -> dict:
    return {"chat": {"id": 777}, "text": text}


def test_wlog_command_lists_entries(gw):
    _clean()
    repo.add_work("починил звонки")
    asyncio.run(gw.handle_message(_msg("/wlog")))
    assert "починил звонки" in gw.tg.sent[-1]


def test_wlog_command_empty(gw):
    _clean()
    asyncio.run(gw.handle_message(_msg("/wlog")))
    assert "нет" in gw.tg.sent[-1].lower()


def test_report_command_uses_llm(gw, monkeypatch):
    _clean()
    repo.add_work("починил звонки fuckwell")
    repo.add_work("написал ходатайство приставам")

    captured: dict = {}

    class FakeProvider:
        async def stream(self, messages, tools=None):
            captured["prompt"] = messages[-1]["content"]
            yield {"type": "text", "delta": "За неделю починил звонки и написал приставам."}

    from app.telegram import gateway as gw_mod
    monkeypatch.setattr(gw_mod, "get_provider", lambda: FakeProvider())

    asyncio.run(gw.handle_message(_msg("/report")))
    out = "\n".join(gw.tg.sent)
    assert "починил звонки и написал приставам" in out
    # Материал попал в промпт, модель просили писать простым языком.
    assert "починил звонки fuckwell" in captured["prompt"]
    assert "простым человеческим языком" in captured["prompt"]


def test_report_command_respects_days(gw, monkeypatch):
    _clean()
    old = repo.add_work("сорок дней назад")
    import sqlite3
    from app.database import db_path
    con = sqlite3.connect(db_path())
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=40)
    con.execute("update work_log set created_at=? where id=?",
                (past.strftime("%Y-%m-%d %H:%M:%S"), old["id"]))
    con.commit()
    con.close()
    repo.add_work("вчерашнее")

    captured: dict = {}

    class FakeProvider:
        async def stream(self, messages, tools=None):
            captured["prompt"] = messages[-1]["content"]
            yield {"type": "text", "delta": "отчёт"}

    from app.telegram import gateway as gw_mod
    monkeypatch.setattr(gw_mod, "get_provider", lambda: FakeProvider())

    asyncio.run(gw.handle_message(_msg("/report 7")))
    assert "вчерашнее" in captured["prompt"]
    assert "сорок дней назад" not in captured["prompt"]


def test_report_command_empty_period(gw):
    _clean()
    asyncio.run(gw.handle_message(_msg("/report")))
    assert "пусто" in gw.tg.sent[-1].lower() or "не из чего" in gw.tg.sent[-1].lower()


# --- Бот не светит «Думаю… / Шаг N» ------------------------------------------

def test_no_thinking_status_messages(gw, monkeypatch):
    """Пользователь просил: никаких сообщений о процессе, только ответ."""
    _clean()

    class FakeProvider:
        async def stream(self, messages, tools=None):
            yield {"type": "text", "delta": "Готово, всё сделал."}

    from app.telegram import gateway as gw_mod
    monkeypatch.setattr(gw_mod, "get_provider", lambda: FakeProvider())

    asyncio.run(gw.handle_message(_msg("привет")))
    sent = "\n".join(gw.tg.sent)
    assert "Думаю" not in sent
    assert "Шаг" not in sent
    assert "Готово, всё сделал." in sent
