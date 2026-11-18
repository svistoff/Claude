"""Общее для запусков агента из веб-чата и Telegram: сохранение истории в БД."""

from __future__ import annotations

import json

from ..database import repo


def persist_delta(conv_id: str, messages: list[dict], preloaded: int,
                   tool_meta: dict[str, dict]) -> None:
    """Сохранить новые (assistant/tool) сообщения задачи в БД."""
    for m in messages[preloaded:]:
        role = m.get("role")
        if role == "assistant":
            tool_calls = m.get("tool_calls")
            repo.add_message(conv_id, "assistant", m.get("content", ""),
                             tool_calls=tool_calls)
            for tc in tool_calls or []:
                fn = tc.get("function", {})
                meta = tool_meta.get(tc.get("id"), {})
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                repo.log_tool_call(conv_id, fn.get("name", "?"), args,
                                   meta.get("ok", True), meta.get("summary", ""))
        elif role == "tool":
            repo.add_message(conv_id, "tool", m.get("content", ""),
                             tool_call_id=m.get("tool_call_id"))
