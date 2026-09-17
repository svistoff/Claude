"""Абстрактный интерфейс LLM-провайдера.

Провайдер получает историю сообщений и схемы инструментов, а отдаёт поток событий:
    {"type": "text", "delta": str}                     — фрагмент текста ответа
    {"type": "tool_calls", "calls": [ToolCall, ...]}   — модель просит вызвать инструменты
    {"type": "usage", "input": int, "output": int,
                      "cache_hit": int}                 — потреблённые токены
    {"type": "finish", "reason": str}                  — конец ответа

Такой контракт одинаков для DeepSeek/OpenAI/Anthropic; agent loop работает с ним,
не зная деталей конкретного API (раздел 43 ТЗ).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, AsyncIterator


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


class LLMProvider(abc.ABC):
    """Базовый интерфейс провайдера."""

    model: str

    @abc.abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Асинхронный генератор событий (см. модульный docstring)."""
        raise NotImplementedError
