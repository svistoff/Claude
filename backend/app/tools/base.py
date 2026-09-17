"""Базовые типы для инструментов агента."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import AppConfig

if TYPE_CHECKING:
    from ..agent.runtime import RunState


@dataclass
class ToolContext:
    """Контекст исполнения инструмента внутри одного запуска агента."""

    project_name: str
    project_root: Path
    config: AppConfig
    run: "RunState | None" = None  # для регистрации процессов / проверки stop


@dataclass
class ToolResult:
    """Результат инструмента, возвращаемый модели и в UI."""

    ok: bool
    # content — то, что уходит модели (текст).
    content: str
    # summary — короткая строка для UI-лога (без секретов).
    summary: str = ""
    # extra — структурные данные для фронтенда (diff, список файлов и т.п.).
    extra: dict[str, Any] = field(default_factory=dict)

    def to_model_string(self) -> str:
        return self.content
