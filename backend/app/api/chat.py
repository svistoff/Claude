"""Чат и управление агентом: SSE-стриминг, stop, confirm, история."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import auth, chat_state, projects_store, uploads_store
from ..agent.jobs import Job, jobs
from ..agent.loop import run_agent
from ..agent.prompts import NO_PROJECT_NOTE, SYSTEM_PROMPT
from ..agent.runtime import registry
from ..agent.session import persist_delta
from ..config import get_app_config
from ..database import repo
from ..llm import get_provider
from ..tools.base import ToolContext

router = APIRouter(prefix="/api", tags=["chat"])

log = logging.getLogger(__name__)


class ChatBody(BaseModel):
    # Проект необязателен: можно вести чат «с чистого листа», без привязки.
    project: str | None = None
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


def _sse_response(job: Job, from_seq: int = 0) -> StreamingResponse:
    """SSE-поток по задаче: сначала пропущенные события, затем живые.

    Обрыв этого потока (закрыли вкладку) НЕ останавливает задачу: клиент лишь
    отписывается. Вернувшись, браузер запросит поток с `from=<последний seq>`.
    """
    async def generator():
        try:
            async for ev in job.stream(from_seq=from_seq):
                if ev.get("type") == "ping":
                    yield ": ping\n\n"          # комментарий SSE — клиенту не событие
                else:
                    yield _sse(ev)
        except asyncio.CancelledError:
            # Клиент отключился — это нормально, работа продолжается.
            raise

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


def _notify_if_unwatched(job: Job) -> None:
    """Если задачу никто не смотрел (вкладка закрыта) — пришлём итог в Telegram."""
    if job.watching:
        return
    text = (job.final_text or "").strip()
    if not text:
        if job.error:
            text = "Задача завершилась с ошибкой: " + job.error[:400]
        else:
            return
    from ..mentor import telegram as tg
    if not tg.configured():
        return
    ok, err = tg.send_message("✅ Готово, пока ты был не у экрана:\n\n" + text, markdown=True)
    if not ok:
        log.warning("не удалось переслать итог в Telegram: %s", err)


@router.post("/chat")
async def chat(body: ChatBody, user: str = Depends(auth.require_csrf)) -> StreamingResponse:
    # Проект не выбран — это не ошибка: агент поговорит, а к файлам/терминалу
    # получит доступ только после выбора проекта.
    project = (body.project or "").strip() or None
    project_root = projects_store.project_root(project) if project else None
    if project is not None:
        if project_root is None:
            raise HTTPException(400, f"Неизвестный проект: {project}")
        if not project_root.is_dir():
            raise HTTPException(400, f"Директория проекта не найдена: {project_root}")

    config = get_app_config()

    # Подготовка (SQLite, чтение вложений) — в отдельном потоке, чтобы не
    # блокировать event loop: эндпоинт асинхронный ради создания фоновой задачи.
    def _prepare() -> tuple[str, list[dict[str, Any]], int]:
        if body.conversation_id:
            conv_id = body.conversation_id
            meta = repo.get_conversation_meta(conv_id)
            if meta is None:
                conv_id = repo.create_conversation(project, body.message[:60])
            elif project is not None and meta["project"] != project:
                # Проект выбрали уже после начала разговора — привязываем чат.
                repo.set_conversation_project(conv_id, project)
        else:
            conv_id = repo.create_conversation(project, body.message[:60])
        # Содержимое приложенных файлов добавляем к сообщению, чтобы агент их «видел».
        attach_ctx = uploads_store.build_attachments_context(body.attachments or [])
        repo.add_message(conv_id, "user", body.message + attach_ctx)
        # История для LLM (уже включает только что добавленное сообщение пользователя).
        prior = repo.get_history_for_llm(conv_id)
        system = SYSTEM_PROMPT if project else SYSTEM_PROMPT + NO_PROJECT_NOTE
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}, *prior]
        return conv_id, msgs, len(msgs)

    conv_id, messages, preloaded = await asyncio.to_thread(_prepare)

    run = registry.create(conv_id)
    ctx = ToolContext(project_name=project, project_root=project_root,
                      config=config, run=run)
    provider = get_provider()
    tool_meta: dict[str, dict] = {}

    async def runner(job: Job):
        """Тело задачи: живёт в отдельной asyncio-задаче, не в HTTP-запросе."""
        job.emit({"type": "session", "conversation_id": conv_id, "project": body.project})
        try:
            async for ev in run_agent(run=run, provider=provider, ctx=ctx,
                                      history=messages, config=config):
                if ev.get("type") == "tool_result":
                    tool_meta[ev["id"]] = {"ok": ev["ok"], "summary": ev["summary"],
                                           "name": ev["name"]}
                yield ev
        finally:
            # История сохраняется даже при обрыве связи и при отмене.
            await asyncio.to_thread(persist_delta, conv_id, messages, preloaded, tool_meta)
            registry.finish(conv_id, run)

    job = jobs.start(conv_id, body.project, runner, on_finish=_notify_if_unwatched)
    return _sse_response(job, from_seq=0)


@router.post("/agent/stop")
def stop_agent(body: StopBody, user: str = Depends(auth.require_csrf)) -> dict:
    """Остановить работу. Останавливает и фоновую задачу, и её процессы."""
    stopped = registry.stop(body.conversation_id)
    stopped = jobs.cancel(body.conversation_id) or stopped
    return {"ok": stopped}


@router.get("/chat/{conv_id}/job")
def job_status(conv_id: str, user: str = Depends(auth.require_user)) -> dict:
    """Идёт ли сейчас работа по этому чату (для переподключения после закрытия вкладки)."""
    job = jobs.get(conv_id)
    if job is None:
        return {"running": False, "done": True, "seq": 0, "exists": False}
    return {**job.status(), "exists": True}


@router.get("/chat/{conv_id}/stream")
def attach_stream(
    conv_id: str,
    from_seq: int = Query(0, alias="from", ge=0),
    user: str = Depends(auth.require_user),
) -> StreamingResponse:
    """Подключиться к уже идущей задаче и получить пропущенные события.

    Так работа продолжается, даже если вкладку закрыли: вернувшись, клиент
    вызывает этот адрес с номером последнего полученного события.
    """
    job = jobs.get(conv_id)
    if job is None:
        raise HTTPException(404, "По этому чату нет активной задачи.")
    return _sse_response(job, from_seq=from_seq)


@router.post("/chat/confirm")
def confirm_action(body: ConfirmBody, user: str = Depends(auth.require_csrf)) -> dict:
    ok = registry.confirm(body.conversation_id, body.call_id, body.approved)
    return {"ok": ok}


class RenameBody(BaseModel):
    title: str


class FolderBody(BaseModel):
    name: str


class MoveBody(BaseModel):
    folder_id: str | None = None


@router.get("/chats")
def list_chats(user: str = Depends(auth.require_user)) -> dict:
    return {"chats": repo.list_conversations(), "folders": repo.list_folders()}


class ActiveChatBody(BaseModel):
    # Какой чат считать активным (см. chat_state.set_active).
    conversation_id: str | None = None
    project: str | None = None


@router.get("/chats/active")
def get_active_chat(user: str = Depends(auth.require_user)) -> dict:
    """Какой чат открывать при входе — чтобы контекст не терялся между сессиями."""
    return chat_state.current()


@router.post("/chats/active")
def set_active_chat(body: ActiveChatBody, user: str = Depends(auth.require_csrf)) -> dict:
    return chat_state.set_active(body.conversation_id, body.project)


@router.get("/folders")
def list_folders(user: str = Depends(auth.require_user)) -> dict:
    return {"folders": repo.list_folders()}


@router.post("/folders")
def create_folder(body: FolderBody, user: str = Depends(auth.require_csrf)) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "Название папки не должно быть пустым.")
    return {"ok": True, "id": repo.create_folder(body.name.strip())}


@router.post("/folders/{folder_id}/rename")
def rename_folder(folder_id: str, body: FolderBody, user: str = Depends(auth.require_csrf)) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "Название не должно быть пустым.")
    if not repo.rename_folder(folder_id, body.name.strip()):
        raise HTTPException(404, "Папка не найдена.")
    return {"ok": True}


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str, user: str = Depends(auth.require_csrf)) -> dict:
    if not repo.delete_folder(folder_id):
        raise HTTPException(404, "Папка не найдена.")
    return {"ok": True}


@router.post("/chat/{conv_id}/move")
def move_chat(conv_id: str, body: MoveBody, user: str = Depends(auth.require_csrf)) -> dict:
    if not repo.move_conversation(conv_id, body.folder_id):
        raise HTTPException(404, "Чат или папка не найдены.")
    return {"ok": True}


@router.post("/chat/{conv_id}/rename")
def rename_chat(conv_id: str, body: RenameBody, user: str = Depends(auth.require_csrf)) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "Название не должно быть пустым.")
    ok = repo.rename_conversation(conv_id, body.title.strip())
    if not ok:
        raise HTTPException(404, "Чат не найден.")
    return {"ok": True}


@router.delete("/chat/{conv_id}")
def delete_chat(conv_id: str, user: str = Depends(auth.require_csrf)) -> dict:
    ok = repo.delete_conversation(conv_id)
    if not ok:
        raise HTTPException(404, "Чат не найден.")
    return {"ok": True}


@router.get("/chat/{conv_id}")
def get_chat(conv_id: str, user: str = Depends(auth.require_user)) -> dict:
    conv = repo.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(404, "Чат не найден.")
    return conv
