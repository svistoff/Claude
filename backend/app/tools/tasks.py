"""Личные задачи пользователя (входящие) — инструмент агента."""

from __future__ import annotations

from ..database import repo
from .base import ToolContext, ToolResult


def _fmt(tasks: list[dict]) -> str:
    return "\n".join(f"#{t['id']} {t['text']}" for t in tasks)


def tasks_tool(ctx: ToolContext, action: str, text: str = "", task_id: int | None = None) -> ToolResult:
    action = (action or "list").lower()
    if action == "add":
        if not text.strip():
            return ToolResult(False, "Пустой текст задачи.", summary="tasks: empty")
        t = repo.add_task(text)
        return ToolResult(True, f"Задача #{t['id']} записана: {t['text']}", summary=f"tasks: +#{t['id']}")
    if action == "list":
        tasks = repo.open_tasks()
        return ToolResult(True, _fmt(tasks) if tasks else "Открытых задач нет.",
                          summary=f"tasks: {len(tasks)} открыто")
    if action in ("done", "drop"):
        if task_id is None:
            return ToolResult(False, "Нужен task_id.", summary="tasks: no id")
        t = repo.complete_task(int(task_id)) if action == "done" else repo.delete_task(int(task_id))
        if t is None:
            return ToolResult(False, f"Открытой задачи #{task_id} нет.", summary="tasks: not found")
        verb = "выполнена" if action == "done" else "удалена"
        return ToolResult(True, f"Задача #{task_id} {verb}: {t['text']}", summary=f"tasks: #{task_id} {action}")
    return ToolResult(False, f"Неизвестное действие: {action}", summary="tasks: bad action")
