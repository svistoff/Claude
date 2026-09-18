"""Тест санитайзера истории: assistant.tool_calls всегда со всеми tool-ответами."""

from __future__ import annotations

from app.database.repo import ensure_tool_results


def test_missing_tool_result_filled():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            {"id": "b", "type": "function", "function": {"name": "terminal", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "a", "content": "результат a"},
        # ответа на 'b' нет — санитайзер должен добавить заглушку
    ]
    out = ensure_tool_results(msgs)
    tool_ids = [m["tool_call_id"] for m in out if m.get("role") == "tool"]
    assert set(tool_ids) == {"a", "b"}


def test_complete_history_unchanged():
    msgs = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "content": "ok"},
    ]
    out = ensure_tool_results(msgs)
    assert len(out) == 2


def test_no_tool_calls_passthrough():
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert ensure_tool_results(msgs) == msgs
