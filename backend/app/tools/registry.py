"""Реестр инструментов: схемы (OpenAI function-calling формат) и диспетчер.

Схемы уходят модели DeepSeek как `tools`. Диспетчер исполняет вызов по имени.
"""

from __future__ import annotations

from typing import Any, Callable

from . import filesystem, git, terminal
from .base import ToolContext, ToolResult

# --- Схемы инструментов (function calling) ----------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Прочитать текстовый файл проекта. Путь — относительно root проекта.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу, например 'main.py'"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Показать структуру файлов и папок. Секретные файлы скрыты.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Директория, по умолчанию '.'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Поиск текста по проекту (ripgrep, если доступен). Возвращает совпадения с номерами строк.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Что искать, например 'megafon'"},
                    "path": {"type": "string", "description": "Где искать, по умолчанию '.'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Создать или полностью перезаписать файл. Проверяет путь на границы проекта.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "Полное новое содержимое файла"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": ("Точечно заменить фрагмент файла. old_str должен уникально встречаться "
                            "в файле. Возвращает unified diff."),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_str": {"type": "string", "description": "Точный фрагмент для замены"},
                    "new_str": {"type": "string", "description": "Новый фрагмент"},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": ("Выполнить shell-команду в корне проекта. Есть timeout. Опасные команды "
                            "(rm -rf, git push, перезапуск сервисов и т.п.) требуют подтверждения пользователя."),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Команда, например 'pytest -q'"},
                    "timeout": {"type": "integer", "description": "Timeout в секундах (опц.)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git",
            "description": ("Git-операции: status, diff, log, branch, checkout, add, commit, push, remote, show. "
                            "push требует подтверждения. Передавайте args как массив, например ['status'] "
                            "или ['commit','-m','fix: ...']."),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Аргументы git, например ['diff'] или ['commit','-m','msg']",
                    },
                },
                "required": ["args"],
            },
        },
    },
]


# --- Диспетчер --------------------------------------------------------------

def _dispatch_read(ctx: ToolContext, a: dict) -> ToolResult:
    return filesystem.read_file(ctx, a["path"])


def _dispatch_list(ctx: ToolContext, a: dict) -> ToolResult:
    return filesystem.list_files(ctx, a.get("path", "."))


def _dispatch_search(ctx: ToolContext, a: dict) -> ToolResult:
    return filesystem.search_files(ctx, a["query"], a.get("path", "."))


def _dispatch_write(ctx: ToolContext, a: dict) -> ToolResult:
    return filesystem.write_file(ctx, a["path"], a["content"])


def _dispatch_edit(ctx: ToolContext, a: dict) -> ToolResult:
    return filesystem.edit_file(ctx, a["path"], a["old_str"], a["new_str"])


def _dispatch_terminal(ctx: ToolContext, a: dict) -> ToolResult:
    return terminal.terminal(ctx, a["command"], a.get("timeout"))


def _dispatch_git(ctx: ToolContext, a: dict) -> ToolResult:
    return git.git_tool(ctx, a["args"])


_DISPATCH: dict[str, Callable[[ToolContext, dict], ToolResult]] = {
    "read_file": _dispatch_read,
    "list_files": _dispatch_list,
    "search_files": _dispatch_search,
    "write_file": _dispatch_write,
    "edit_file": _dispatch_edit,
    "terminal": _dispatch_terminal,
    "git": _dispatch_git,
}


def dispatch(ctx: ToolContext, name: str, args: dict) -> ToolResult:
    handler = _DISPATCH.get(name)
    if handler is None:
        return ToolResult(False, f"Неизвестный инструмент: {name}", summary=f"{name}: unknown")
    try:
        return handler(ctx, args or {})
    except KeyError as exc:
        return ToolResult(False, f"Не хватает аргумента {exc} для {name}.",
                          summary=f"{name}: bad args")
    except Exception as exc:  # noqa: BLE001 — ошибку инструмента возвращаем модели, не роняем цикл
        return ToolResult(False, f"Ошибка инструмента {name}: {exc}",
                          summary=f"{name}: error")
