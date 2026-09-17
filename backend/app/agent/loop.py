"""Agent loop: DeepSeek ↔ инструменты, до решения задачи (разделы 8, 37 ТЗ).

Асинхронный генератор событий. Приостанавливается на подтверждении опасных
действий и продолжается после ответа из UI. Останавливается по Stop Agent или
по достижении лимита итераций.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from ..config import AppConfig
from ..llm.base import LLMProvider, ToolCall
from ..tools.base import ToolContext
from ..tools.registry import TOOL_SCHEMAS, dispatch
from . import permissions
from .pricing import estimate_cost
from .runtime import RunState

# Таймаут ожидания подтверждения из UI (сек). По истечении — считаем отменой.
CONFIRM_TIMEOUT = 600


async def run_agent(
    *,
    run: RunState,
    provider: LLMProvider,
    ctx: ToolContext,
    history: list[dict[str, Any]],
    config: AppConfig,
) -> AsyncIterator[dict[str, Any]]:
    """history уже содержит system-промпт и сообщение пользователя.

    Мутирует history (добавляет assistant/tool-сообщения) — вызывающая сторона
    может сохранить его в БД после завершения.
    """
    max_iter = config.agent.max_iterations

    for iteration in range(1, max_iter + 1):
        if run.stop_requested:
            yield {"type": "stopped"}
            return

        yield {"type": "iteration", "n": iteration}

        # --- Запрос к модели (стриминг) ---
        assistant_text = ""
        tool_calls: list[ToolCall] = []
        got_error = False

        async for ev in provider.stream(history, TOOL_SCHEMAS):
            if run.stop_requested:
                yield {"type": "stopped"}
                return
            etype = ev.get("type")
            if etype == "text":
                assistant_text += ev["delta"]
                yield {"type": "text", "delta": ev["delta"]}
            elif etype == "tool_calls":
                tool_calls = ev["calls"]
            elif etype == "usage":
                run.usage.add(ev.get("input", 0), ev.get("output", 0), ev.get("cache_hit", 0))
                yield {"type": "usage", **estimate_cost(run.usage)}
            elif etype == "error":
                got_error = True
                yield {"type": "error", "message": ev["message"]}
            # finish — игнорируем, конец потока определяется завершением генератора

        if got_error:
            return

        # --- Записываем ход ассистента в историю (в формате OpenAI tools) ---
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": assistant_text or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                }
                for tc in tool_calls
            ]
        history.append(assistant_msg)
        yield {
            "type": "assistant_message",
            "content": assistant_text,
            "tool_calls": [{"id": tc.id, "name": tc.name, "args": tc.arguments} for tc in tool_calls],
        }

        # Нет вызовов инструментов -> это финальный ответ.
        if not tool_calls:
            yield {"type": "final", "content": assistant_text}
            return

        # --- Исполняем инструменты ---
        for tc in tool_calls:
            if run.stop_requested:
                yield {"type": "stopped"}
                return

            decision = permissions.classify(tc.name, tc.arguments, config)

            if decision.action == permissions.BLOCK:
                yield {"type": "blocked", "id": tc.id, "name": tc.name,
                       "reason": decision.reason, "preview": decision.preview}
                _append_tool_result(history, tc.id,
                                    f"ЗАБЛОКИРОВАНО политикой безопасности: {decision.reason}")
                continue

            if decision.action == permissions.CONFIRM:
                # Создаём future ДО отправки события, чтобы очень быстрый ответ
                # из UI не пришёл раньше, чем появится ожидание (гонка).
                fut = run.create_confirmation(tc.id)
                yield {"type": "confirm_required", "id": tc.id, "name": tc.name,
                       "preview": decision.preview, "reason": decision.reason}
                approved = await _await_confirmation(fut)
                if not approved:
                    yield {"type": "tool_result", "id": tc.id, "name": tc.name,
                           "ok": False, "summary": "отменено пользователем", "content": ""}
                    _append_tool_result(history, tc.id,
                                        "Действие отменено пользователем. Предложи альтернативу или спроси.")
                    continue
                yield {"type": "confirmed", "id": tc.id}

            # allow (или подтверждено) -> выполняем в отдельном потоке (tools синхронные).
            yield {"type": "tool_start", "id": tc.id, "name": tc.name,
                   "args": tc.arguments, "preview": decision.preview}
            result = await asyncio.to_thread(dispatch, ctx, tc.name, tc.arguments)

            yield {
                "type": "tool_result", "id": tc.id, "name": tc.name,
                "ok": result.ok, "summary": result.summary,
                "content": result.content, "extra": result.extra,
            }
            _append_tool_result(history, tc.id, result.to_model_string())

    # Лимит итераций.
    yield {"type": "limit", "message": f"Agent stopped: iteration limit reached ({max_iter})."}


def _append_tool_result(history: list[dict], call_id: str, content: str) -> None:
    history.append({"role": "tool", "tool_call_id": call_id, "content": content})


async def _await_confirmation(fut: "asyncio.Future") -> bool:
    try:
        return await asyncio.wait_for(fut, timeout=CONFIRM_TIMEOUT)
    except asyncio.TimeoutError:
        return False
