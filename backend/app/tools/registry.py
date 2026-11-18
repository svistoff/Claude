"""Реестр инструментов: схемы (OpenAI function-calling формат) и диспетчер.

Схемы уходят модели DeepSeek как `tools`. Диспетчер исполняет вызов по имени.
"""

from __future__ import annotations

from typing import Any, Callable

from . import browser, filesystem, git, github, image, tasks, terminal, web
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
            "name": "browser",
            "description": ("Управление браузером (Playwright). Действия: open (перейти на url), "
                            "click (по selector или text), type (ввести text в selector), select "
                            "(выбрать value в selector), get_text (текст страницы/элемента — так ты "
                            "«видишь» страницу), screenshot (снимок для пользователя + OCR), scroll, "
                            "back, wait (selector или ms). Опасные действия (удаление/оплата/публикация/"
                            "отправка) требуют подтверждения."),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string",
                               "enum": ["open", "click", "type", "select", "get_text",
                                        "screenshot", "scroll", "back", "wait"]},
                    "url": {"type": "string"},
                    "selector": {"type": "string", "description": "CSS-селектор"},
                    "text": {"type": "string", "description": "Текст для ввода или поиска элемента"},
                    "value": {"type": "string", "description": "Значение для select"},
                    "ms": {"type": "integer"}, "dy": {"type": "integer"},
                    "full_page": {"type": "boolean"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": ("Поиск в интернете (DeepSeek Search API). Возвращает заголовки, URL, "
                            "даты и краткое содержание страниц. Поддерживает операторы: "
                            "'site:example.com', '-site:example.com', '\"точная фраза\"', "
                            "'lang:ru,en', 'after:2026-01-01', 'before:2026'. Используй, когда нужны "
                            "свежие факты, цены, новости, документация — вместо догадок. "
                            "Чтобы прочитать страницу целиком — затем web_fetch(url)."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Поисковый запрос (до 128 символов)"},
                    "count": {"type": "integer", "description": "Сколько результатов, 1–50 (по умолчанию 8)"},
                    "need_content": {"type": "boolean",
                                     "description": "Вернуть и текст страниц (дороже по контексту)"},
                    "ori_question": {"type": "string",
                                     "description": "Исходный вопрос пользователя — улучшает поиск"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": ("Прочитать веб-страницу и получить её содержимое в Markdown "
                            "(DeepSeek Fetch API). Используй после web_search или когда "
                            "пользователь дал ссылку. Для сайтов с логином/JS — инструмент browser."),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Полный URL, http:// или https://"},
                    "max_chars": {"type": "integer",
                                  "description": "Лимит символов текста (по умолчанию из конфига)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": ("Сгенерировать изображение по текстовому описанию (fal.ai). "
                            "Картинка показывается пользователю в чате. Используй, когда просят "
                            "нарисовать/сгенерировать изображение, иллюстрацию, логотип и т.п."),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Что нарисовать (можно по-английски для качества)"},
                    "image_size": {"type": "string",
                                   "enum": ["square", "square_hd", "landscape_4_3", "landscape_16_9",
                                            "portrait_4_3", "portrait_16_9"]},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tasks",
            "description": ("Личные задачи пользователя (входящие). action: add (записать задачу text), "
                            "list (открытые задачи), done (отметить выполненной task_id), drop (удалить "
                            "task_id). Используй, когда просят «запиши задачу», «что у меня в задачах», "
                            "«я сделал #3»."),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "list", "done", "drop"]},
                    "text": {"type": "string", "description": "Текст задачи (для add)"},
                    "task_id": {"type": "integer", "description": "Номер задачи (для done/drop)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github",
            "description": ("Операции с GitHub через API: info (remote/ветка), branches (список веток), "
                            "ci_status (статус проверок CI по HEAD), create_pr (создать Pull Request — "
                            "требует подтверждения). Работает, если у проекта есть remote на GitHub и задан токен."),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["info", "branches", "ci_status", "create_pr"]},
                    "title": {"type": "string", "description": "Заголовок PR (для create_pr)"},
                    "body": {"type": "string", "description": "Описание PR (для create_pr)"},
                    "head": {"type": "string", "description": "Ветка-источник (по умолчанию текущая)"},
                    "base": {"type": "string", "description": "Базовая ветка (по умолчанию default)"},
                    "ref": {"type": "string", "description": "Ссылка/SHA для ci_status"},
                },
                "required": ["action"],
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


def _dispatch_github(ctx: ToolContext, a: dict) -> ToolResult:
    action = a.get("action", "info")
    kwargs = {k: a[k] for k in ("title", "body", "head", "base", "ref") if k in a}
    return github.github_tool(ctx, action, **kwargs)


def _dispatch_browser(ctx: ToolContext, a: dict) -> ToolResult:
    action = a.get("action", "get_text")
    kwargs = {k: a[k] for k in ("url", "selector", "text", "value", "ms", "dy", "full_page") if k in a}
    return browser.browser_tool(ctx, action, **kwargs)


def _dispatch_tasks(ctx: ToolContext, a: dict) -> ToolResult:
    return tasks.tasks_tool(ctx, a.get("action", "list"), a.get("text", ""), a.get("task_id"))


def _dispatch_generate_image(ctx: ToolContext, a: dict) -> ToolResult:
    return image.generate_image(ctx, a["prompt"], a.get("image_size", "landscape_4_3"))


def _dispatch_web_search(ctx: ToolContext, a: dict) -> ToolResult:
    return web.web_search(ctx, a["query"], a.get("count"), bool(a.get("need_content", False)),
                          a.get("ori_question"))


def _dispatch_web_fetch(ctx: ToolContext, a: dict) -> ToolResult:
    return web.web_fetch(ctx, a["url"], a.get("max_chars"))


_DISPATCH: dict[str, Callable[[ToolContext, dict], ToolResult]] = {
    "read_file": _dispatch_read,
    "list_files": _dispatch_list,
    "search_files": _dispatch_search,
    "write_file": _dispatch_write,
    "edit_file": _dispatch_edit,
    "terminal": _dispatch_terminal,
    "git": _dispatch_git,
    "github": _dispatch_github,
    "browser": _dispatch_browser,
    "generate_image": _dispatch_generate_image,
    "web_search": _dispatch_web_search,
    "web_fetch": _dispatch_web_fetch,
    "tasks": _dispatch_tasks,
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
