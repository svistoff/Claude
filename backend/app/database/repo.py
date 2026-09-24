"""Функции доступа к данным (CRUD поверх моделей)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from . import get_session
from .models import AppSetting, Conversation, Message, Project, ToolCallLog


def get_setting(key: str) -> str | None:
    with get_session() as db:
        s = db.get(AppSetting, key)
        return s.value if s else None


def set_setting(key: str, value: str) -> None:
    with get_session() as db:
        db.merge(AppSetting(key=key, value=value))
        db.commit()


def create_conversation(project: str, title: str = "Новый чат") -> str:
    with get_session() as db:
        conv = Conversation(project=project, title=title)
        db.add(conv)
        db.commit()
        return conv.id


def get_conversation(conv_id: str) -> dict[str, Any] | None:
    with get_session() as db:
        conv = db.get(Conversation, conv_id)
        if conv is None:
            return None
        return {
            "id": conv.id,
            "project": conv.project,
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "messages": [_msg_dict(m) for m in conv.messages],
        }


def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    with get_session() as db:
        rows = db.execute(
            select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
        ).scalars().all()
        return [
            {"id": c.id, "project": c.project, "title": c.title,
             "updated_at": c.updated_at.isoformat()}
            for c in rows
        ]


def add_message(
    conv_id: str, role: str, content: str,
    tool_calls: list[dict] | None = None, tool_call_id: str | None = None,
) -> int:
    with get_session() as db:
        msg = Message(
            conversation_id=conv_id, role=role, content=content,
            tool_calls_json=json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
            tool_call_id=tool_call_id,
        )
        db.add(msg)
        conv = db.get(Conversation, conv_id)
        if conv is not None and role == "user" and conv.title == "Новый чат":
            conv.title = content[:60] or conv.title
        db.commit()
        return msg.id


def rename_conversation(conv_id: str, title: str) -> bool:
    with get_session() as db:
        conv = db.get(Conversation, conv_id)
        if conv is None:
            return False
        conv.title = title[:120] or conv.title
        db.commit()
        return True


def log_tool_call(conv_id: str, name: str, args: dict, ok: bool, summary: str) -> None:
    with get_session() as db:
        db.add(ToolCallLog(
            conversation_id=conv_id, name=name,
            args_json=json.dumps(args, ensure_ascii=False), ok=ok, summary=summary,
        ))
        db.commit()


def get_history_for_llm(conv_id: str) -> list[dict[str, Any]]:
    """Собрать историю в формате messages для LLM (без system-промпта)."""
    with get_session() as db:
        conv = db.get(Conversation, conv_id)
        if conv is None:
            return []
        out: list[dict[str, Any]] = []
        for m in conv.messages:
            if m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
                if m.tool_calls_json:
                    calls = json.loads(m.tool_calls_json)
                    msg["tool_calls"] = calls
                out.append(msg)
            elif m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            else:
                out.append({"role": m.role, "content": m.content})
        return ensure_tool_results(out)


def ensure_tool_results(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Гарантировать, что каждый assistant с tool_calls сопровождается tool-ответом
    на КАЖДЫЙ tool_call_id. Иначе DeepSeek API возвращает 400 (например, если агента
    остановили посреди выполнения инструментов).
    """
    out: list[dict[str, Any]] = []
    n = len(msgs)
    for idx, m in enumerate(msgs):
        out.append(m)
        if m.get("role") == "assistant" and m.get("tool_calls"):
            ids = [tc.get("id") for tc in m["tool_calls"] if tc.get("id")]
            provided: set = set()
            j = idx + 1
            while j < n and msgs[j].get("role") == "tool":
                provided.add(msgs[j].get("tool_call_id"))
                j += 1
            for cid in ids:
                if cid not in provided:
                    out.append({"role": "tool", "tool_call_id": cid,
                                "content": "[инструмент прерван: результат отсутствует]"})
    return out


# --- Проекты, созданные через UI -------------------------------------------

def add_project(name: str, path: str) -> None:
    with get_session() as db:
        db.merge(Project(name=name, path=path))
        db.commit()


def list_custom_projects() -> list[dict[str, str]]:
    with get_session() as db:
        rows = db.execute(select(Project).order_by(Project.created_at)).scalars().all()
        return [{"name": p.name, "path": p.path} for p in rows]


def get_custom_project_path(name: str) -> str | None:
    with get_session() as db:
        p = db.get(Project, name)
        return p.path if p else None


def _msg_dict(m: Message) -> dict[str, Any]:
    return {
        "role": m.role,
        "content": m.content,
        "tool_calls": json.loads(m.tool_calls_json) if m.tool_calls_json else None,
        "tool_call_id": m.tool_call_id,
        "created_at": m.created_at.isoformat(),
    }
