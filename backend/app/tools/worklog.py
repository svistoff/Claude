"""Журнал выполненной работы — инструмент агента (основа отчёта шефу).

Разница с tasks:
- ``tasks``   — «что надо сделать» (входящие задачи, ещё не сделано);
- ``worklog`` — «что уже сделано» (факт работы с датой) — из него собирается
  отчёт о проделанной работе за неделю/месяц.

Запись попадает в журнал, когда владелец говорит «запиши: сделал …», когда
закрывается задача (tasks done) и когда агент завершил заметную работу.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..database import repo
from .base import ToolContext, ToolResult

MAX_TEXT = 4000
DEFAULT_DAYS = 7


def _fmt_entry(e: dict) -> str:
    date = e["created_at"][:10]
    proj = f"[{e['project']}] " if e.get("project") else ""
    return f"{date} · {proj}{e['text']}"


def _fmt_list(entries: list[dict]) -> str:
    if not entries:
        return "Записей о выполненной работе за этот период нет."
    return "\n".join(_fmt_entry(e) for e in entries)


def worklog_tool(
    ctx: ToolContext,
    action: str = "list",
    text: str = "",
    days: int | None = None,
    project: str | None = None,
) -> ToolResult:
    action = (action or "list").lower()

    if action == "add":
        body = (text or "").strip()
        if not body:
            return ToolResult(False, "Пустой текст записи.", summary="worklog: empty")
        # Проект по умолчанию — текущий, если он есть в контексте.
        proj = project or (ctx.project_name if ctx.project_name not in ("", "-") else None)
        entry = repo.add_work(body[:MAX_TEXT], project=proj, source="owner")
        return ToolResult(
            True,
            f"Записал в журнал работы: {entry['text']}"
            + (f" (проект: {entry['project']})" if entry.get("project") else ""),
            summary=f"worklog: +{entry['id']}",
        )

    if action == "list":
        n = int(days or DEFAULT_DAYS)
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=n)
        entries = repo.work_since(since)
        return ToolResult(True, f"Выполненная работа за {n} дн.:\n" + _fmt_list(entries),
                          summary=f"worklog: {len(entries)} за {n} дн.")

    if action == "report":
        n = int(days or DEFAULT_DAYS)
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=n)
        entries = repo.work_since(since)
        if not entries:
            return ToolResult(
                True,
                f"За последние {n} дн. записей о работе нет. Скажи владельцу, что "
                f"нечего включать в отчёт, и предложи записать сделанное.",
                summary="worklog: пусто",
            )
        # Сырьё для отчёта: агент сам переформулирует человеческим языком.
        body = "\n".join(f"- {e['created_at'][:10]}: {e['text']}" for e in entries)
        return ToolResult(
            True,
            f"Материал для отчёта за {n} дн. ({len(entries)} записей):\n{body}\n\n"
            f"Сформулируй отчёт для шефа: что сделано, какой результат, что дальше. "
            f"Простым языком, без технического жаргона.",
            summary=f"worklog: отчёт за {n} дн. ({len(entries)})",
            extra={"days": n, "count": len(entries)},
        )

    return ToolResult(False, f"Неизвестное действие: {action}", summary="worklog: bad action")
