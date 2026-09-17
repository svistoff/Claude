"""Тест agent loop с фейковым провайдером (без сети).

Проверяет: цикл вызывает инструмент, кладёт результат в историю, затем выдаёт
финальный ответ; подтверждение опасного действия приостанавливает и продолжает цикл.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import AppConfig, TerminalPolicy
from app.llm.base import LLMProvider, ToolCall
from app.agent.loop import run_agent
from app.agent.runtime import RunState
from app.tools.base import ToolContext


class FakeProvider(LLMProvider):
    """Возвращает заранее заданные ответы по очереди."""

    def __init__(self, script):
        self.model = "fake"
        self.script = list(script)
        self.calls = 0

    async def stream(self, messages, tools=None):
        step = self.script[self.calls]
        self.calls += 1
        for ev in step:
            yield ev


def _ctx(root: Path) -> ToolContext:
    cfg = AppConfig(terminal_policy=TerminalPolicy(confirm=["rm -rf"]))
    cfg.secret_patterns = [".env"]
    return ToolContext(project_name="t", project_root=root, config=cfg)


def _collect(agen):
    async def run():
        return [ev async for ev in agen]
    return asyncio.run(run())


def test_loop_calls_tool_then_finishes(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('hi')\n")
    run = RunState(session_id="s1")
    ctx = _ctx(tmp_path)
    provider = FakeProvider([
        # шаг 1: модель просит прочитать файл
        [{"type": "tool_calls", "calls": [ToolCall("c1", "read_file", {"path": "main.py"})]}],
        # шаг 2: финальный ответ
        [{"type": "text", "delta": "Готово, файл прочитан."}],
    ])
    history = [{"role": "system", "content": "sys"},
               {"role": "user", "content": "прочитай main.py"}]
    events = _collect(run_agent(run=run, provider=provider, ctx=ctx,
                                history=history, config=ctx.config))
    types = [e["type"] for e in events]
    assert "tool_start" in types
    assert "tool_result" in types
    assert any(e["type"] == "final" and "Готово" in e["content"] for e in events)
    # результат инструмента попал в историю
    assert any(m.get("role") == "tool" for m in history)


def test_loop_pauses_for_confirmation(tmp_path: Path):
    run = RunState(session_id="s2")
    ctx = _ctx(tmp_path)
    provider = FakeProvider([
        [{"type": "tool_calls", "calls": [ToolCall("c1", "terminal", {"command": "rm -rf build"})]}],
        [{"type": "text", "delta": "ок"}],
    ])
    history = [{"role": "user", "content": "удали build"}]

    async def run_and_confirm():
        events = []
        agen = run_agent(run=run, provider=provider, ctx=ctx, history=history, config=ctx.config)
        async for ev in agen:
            events.append(ev)
            if ev["type"] == "confirm_required":
                # имитируем отмену пользователем
                run.resolve_confirmation(ev["id"], False)
        return events

    events = asyncio.run(run_and_confirm())
    types = [e["type"] for e in events]
    assert "confirm_required" in types
    # после отмены — инструмент не выполнялся, а модель получила tool-ответ об отмене
    assert any(m.get("role") == "tool" and "отменен" in m["content"].lower() for m in history)


def test_stop_halts_loop(tmp_path: Path):
    run = RunState(session_id="s3")
    run.request_stop()
    ctx = _ctx(tmp_path)
    provider = FakeProvider([[{"type": "text", "delta": "не должно дойти"}]])
    history = [{"role": "user", "content": "hi"}]
    events = _collect(run_agent(run=run, provider=provider, ctx=ctx,
                                history=history, config=ctx.config))
    assert events and events[0]["type"] == "stopped"
