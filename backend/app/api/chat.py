"""Чат и управление агентом: SSE-стриминг, stop, confirm, история."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import auth, projects_store, uploads_store
from ..agent.loop import run_agent
from ..agent.prompts import SYSTEM_PROMPT
from ..agent.runtime import registry
from ..config import get_app_config
from ..database import repo
from ..llm import get_provider
from ..tools.base import ToolContext

router = APIRouter(prefix="/api", tags=["chat"])


class ChatBody(BaseModel):
    project: str
    message: str
    conversation_id: str | None = None
    # Приложенные файлы: [{token, name}] из /api/upload.
    attachments: list[dict] | None = None


class ConfirmBody(BaseModel):
    conversation_id: str
    call_id: str
    approved: bool


class StopBody(BaseModel):
    conversation_id: str


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat")
def chat(body: ChatBody, user: str = Depends(auth.require_csrf)) -> StreamingResponse:
    project_root = projects_store.project_root(body.project)
    if project_root is None:
        raise HTTPException(400, f"Неизвестный проект: {body.project}")
    if not project_root.is_dir():
        raise HTTPException(400, f"Директория проекта не найдена: {project_root}")

    config = get_app_config()

    # Conversation (= сессия задачи).
    conv_id = body.conversation_id or repo.create_conversation(body.project, body.message[:60])
    # Содержимое приложенных файлов добавляем к сообщению, чтобы агент их «видел».
    attach_ctx = uploads_store.build_attachments_context(body.attachments or [])
    repo.add_message(conv_id, "user", body.message + attach_ctx)

    # История для LLM (уже включает только что добавленное сообщение пользователя).
    prior = repo.get_history_for_llm(conv_id)
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *prior]
    preloaded = len(messages)

    run = registry.create(conv_id)
    ctx = ToolContext(project_name=body.project, project_root=project_root,
                      config=config, run=run)
    provider = get_provider()

    async def generator():
        tool_meta: dict[str, dict] = {}
        # conversation_id сразу — фронт запомнит сессию.
        yield _sse({"type": "session", "conversation_id": conv_id, "project": body.project})
        try:
            async for ev in run_agent(run=run, provider=provider, ctx=ctx,
                                      history=messages, config=config):
                if ev.get("type") == "tool_result":
                    tool_meta[ev["id"]] = {"ok": ev["ok"], "summary": ev["summary"],
                                           "name": ev["name"]}
                yield _sse(ev)
        finally:
            _persist_delta(conv_id, messages, preloaded, tool_meta)
            registry.finish(conv_id, run)
            yield _sse({"type": "end"})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


def _persist_delta(conv_id: str, messages: list[dict], preloaded: int,
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


@router.post("/agent/stop")
def stop_agent(body: StopBody, user: str = Depends(auth.require_csrf)) -> dict:
    stopped = registry.stop(body.conversation_id)
    return {"ok": stopped}


@router.post("/chat/confirm")
def confirm_action(body: ConfirmBody, user: str = Depends(auth.require_csrf)) -> dict:
    ok = registry.confirm(body.conversation_id, body.call_id, body.approved)
    return {"ok": ok}


class RenameBody(BaseModel):
    title: str


@router.get("/chats")
def list_chats(user: str = Depends(auth.require_user)) -> dict:
    return {"chats": repo.list_conversations()}


@router.post("/chat/{conv_id}/rename")
def rename_chat(conv_id: str, body: RenameBody, user: str = Depends(auth.require_csrf)) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "Название не должно быть пустым.")
    ok = repo.rename_conversation(conv_id, body.title.strip())
    if not ok:
        raise HTTPException(404, "Чат не найден.")
    return {"ok": True}


@router.get("/chat/{conv_id}")
def get_chat(conv_id: str, user: str = Depends(auth.require_user)) -> dict:
    conv = repo.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(404, "Чат не найден.")
    return conv
