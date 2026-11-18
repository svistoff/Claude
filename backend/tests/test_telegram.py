"""Тесты Telegram-двери: разметка, задачи, шлюз (Telegram и LLM — фейки)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.database import repo
from app.llm.base import ToolCall
from app.telegram import gateway
from app.telegram.format import md_to_html, split_markdown
from app.tools import tasks as tasks_tool
from app.tools.base import ToolContext
from app.config import AppConfig

OWNER = "777"


# --- Разметка -----------------------------------------------------------------

def test_md_to_html_basic():
    out = md_to_html("# Итог\n**жирно** и `код <x>` и [ссылка](https://a.b)\n- пункт")
    assert "<b>Итог</b>" in out and "<b>жирно</b>" in out
    assert "<code>код &lt;x&gt;</code>" in out
    assert '<a href="https://a.b">ссылка</a>' in out and "• пункт" in out


def test_md_to_html_code_block_and_table():
    out = md_to_html("```py\nif a < b:\n    pass\n```\n| A | B |\n|---|---|\n| 1 | 2 |")
    assert "<pre>if a &lt; b:\n    pass</pre>" in out
    assert "<pre>| A | B |\n| 1 | 2 |</pre>" in out


def test_split_keeps_code_fences():
    text = "```\n" + "\n".join(f"строка {i}" for i in range(400)) + "\n```"
    chunks = split_markdown(text, limit=500)
    assert len(chunks) > 1
    assert all(c.count("```") % 2 == 0 for c in chunks)


# --- Инструмент задач -----------------------------------------------------------

def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(project_name="t", project_root=tmp_path, config=AppConfig())


def test_tasks_tool_flow(tmp_path):
    for t in repo.open_tasks():
        repo.delete_task(t["id"])
    r = tasks_tool.tasks_tool(_ctx(tmp_path), "add", "позвонить бухгалтеру")
    assert r.ok
    tid = repo.open_tasks()[0]["id"]
    assert "позвонить бухгалтеру" in tasks_tool.tasks_tool(_ctx(tmp_path), "list").content
    assert tasks_tool.tasks_tool(_ctx(tmp_path), "done", task_id=tid).ok
    assert repo.open_tasks() == []
    assert not tasks_tool.tasks_tool(_ctx(tmp_path), "done", task_id=tid).ok


# --- Шлюз -----------------------------------------------------------------------

class FakeTG:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.edits: list[str] = []
        self.photos: list[Path] = []

    async def send(self, chat_id, text, html=False, buttons=None):
        self.sent.append({"chat": str(chat_id), "text": text, "html": html, "buttons": buttons})
        return len(self.sent)

    async def edit(self, chat_id, message_id, text):
        self.edits.append(text)

    async def answer_callback(self, cid, text=""):
        pass

    async def typing(self, chat_id):
        pass

    async def send_photo(self, chat_id, path, caption=""):
        self.photos.append(path)

    async def close(self):
        pass

    def texts(self) -> list[str]:
        return [m["text"] for m in self.sent]


class FakeProvider:
    """Сценарий ответов модели: список «ходов» (текст или вызов инструмента)."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.model = "fake"

    async def stream(self, messages, tools=None):
        turn = self.turns.pop(0)
        if isinstance(turn, ToolCall):
            yield {"type": "tool_calls", "calls": [turn]}
        else:
            yield {"type": "text", "delta": turn}
        yield {"type": "finish", "reason": "stop"}


@pytest.fixture
def gw(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway.projects_store, "all_projects",
                        lambda: [{"name": "proj", "path": str(tmp_path), "available": True, "kind": "custom"}])
    monkeypatch.setattr(gateway.projects_store, "project_root", lambda name: tmp_path)
    repo.set_setting(gateway.KEY_PROJECT, "")
    repo.set_setting(gateway.KEY_CONVERSATION, "")
    g = gateway.Gateway("token", OWNER)
    g.tg = FakeTG()
    return g


def msg(text: str, chat: str = OWNER) -> dict:
    return {"chat": {"id": int(chat)}, "text": text}


def run(coro):
    return asyncio.run(coro)


def test_setup_mode_reveals_chat_id():
    g = gateway.Gateway("token", "")
    g.tg = FakeTG()
    run(g.handle_message(msg("/start", chat="555")))
    assert "TELEGRAM_CHAT_ID=555" in g.tg.texts()[-1]


def test_stranger_refused(gw):
    run(gw.handle_message(msg("удали всё", chat="999")))
    assert "только владельцу" in gw.tg.texts()[-1]


def test_task_commands(gw):
    for t in repo.open_tasks():
        repo.delete_task(t["id"])
    t = repo.add_task("купить билеты")
    run(gw.handle_message(msg("/tasks")))
    assert f"#{t['id']} купить билеты" in gw.tg.texts()[-1]
    run(gw.handle_message(msg(f"/done {t['id']}")))
    assert "Сделал: купить билеты" in gw.tg.texts()[-1]


def test_plain_text_goes_to_agent_and_history(gw, monkeypatch):
    monkeypatch.setattr(gateway, "get_provider", lambda: FakeProvider(["**Привет!** Всё работает."]))

    async def scenario():
        await gw.handle_message(msg("как дела?"))
        await gw.busy[OWNER]

    run(scenario())
    final = gw.tg.sent[-1]
    assert final["html"] and "<b>Привет!</b>" in final["text"]
    conv_id = repo.get_setting(gateway.KEY_CONVERSATION)
    conv = repo.get_conversation(conv_id)
    assert conv["project"] == "proj" and conv["title"].startswith("📱")
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]


def test_dangerous_action_confirmed_by_button(gw, monkeypatch, tmp_path):
    victim = tmp_path / "junk"
    victim.mkdir()
    provider = FakeProvider([
        ToolCall(id="call_1", name="terminal", arguments={"command": f"rm -rf {victim}"}),
        "Удалил папку.",
    ])
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)

    async def scenario():
        await gw.handle_message(msg("удали папку junk"))
        for _ in range(200):  # ждём, пока агент попросит подтверждение
            if gw.pending:
                break
            await asyncio.sleep(0.01)
        assert gw.pending, "агент не запросил подтверждение"
        confirm = next(m for m in gw.tg.sent if m["buttons"])
        assert "rm -rf" in confirm["text"]
        short = next(iter(gw.pending))
        await gw.handle_callback({"id": "cb", "data": f"c:{short}:1",
                                  "message": {"chat": {"id": int(OWNER)}, "message_id": 1,
                                              "text": confirm["text"]}})
        await gw.busy[OWNER]

    run(scenario())
    assert not victim.exists()
    assert "Удалил папку." in gw.tg.texts()[-1]


def test_cancelled_action_not_executed(gw, monkeypatch, tmp_path):
    victim = tmp_path / "keep"
    victim.mkdir()
    provider = FakeProvider([
        ToolCall(id="call_2", name="terminal", arguments={"command": f"rm -rf {victim}"}),
        "Хорошо, не удаляю.",
    ])
    monkeypatch.setattr(gateway, "get_provider", lambda: provider)

    async def scenario():
        await gw.handle_message(msg("удали keep"))
        for _ in range(200):
            if gw.pending:
                break
            await asyncio.sleep(0.01)
        short = next(iter(gw.pending))
        await gw.handle_callback({"id": "cb", "data": f"c:{short}:0",
                                  "message": {"chat": {"id": int(OWNER)}, "message_id": 1, "text": "?"}})
        await gw.busy[OWNER]

    run(scenario())
    assert victim.exists()


def test_switch_project_starts_new_conversation(gw, monkeypatch, tmp_path):
    monkeypatch.setattr(gateway.projects_store, "all_projects", lambda: [
        {"name": "a", "path": str(tmp_path), "available": True, "kind": "custom"},
        {"name": "b", "path": str(tmp_path), "available": True, "kind": "custom"}])
    repo.set_setting(gateway.KEY_CONVERSATION, "something")
    run(gw.handle_callback({"id": "cb", "data": "p:1", "message": {"chat": {"id": int(OWNER)}}}))
    assert repo.get_setting(gateway.KEY_PROJECT) == "b"
    assert repo.get_setting(gateway.KEY_CONVERSATION) == ""
