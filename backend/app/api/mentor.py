"""Роуты наставника: напоминания + отправка совета в Telegram (раздел 30 ТЗ)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth
from ..database import repo
from ..mentor import advisor, telegram

router = APIRouter(prefix="/api/mentor", tags=["mentor"])

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ReminderBody(BaseModel):
    project: str | None = None
    goal: str = ""
    time_local: str = "09:00"
    weekdays_only: bool = False


class ReminderPatch(BaseModel):
    project: str | None = None
    goal: str | None = None
    time_local: str | None = None
    weekdays_only: bool | None = None
    enabled: bool | None = None


class TestBody(BaseModel):
    id: str | None = None
    project: str | None = None
    goal: str = ""


@router.get("")
def get_mentor(user: str = Depends(auth.require_user)) -> dict:
    return {
        "telegram_configured": telegram.configured(),
        "reminders": repo.list_reminders(),
        "recent": repo.recent_reminder_logs(),
    }


@router.post("/reminders")
def create_reminder(body: ReminderBody, user: str = Depends(auth.require_csrf)) -> dict:
    if not _TIME_RE.match(body.time_local):
        raise HTTPException(400, "Время должно быть в формате ЧЧ:ММ (например 09:00).")
    r = repo.create_reminder(body.project or None, body.goal, body.time_local,
                             body.weekdays_only)
    return {"ok": True, "reminder": r}


@router.patch("/reminders/{reminder_id}")
def patch_reminder(reminder_id: str, body: ReminderPatch,
                   user: str = Depends(auth.require_csrf)) -> dict:
    if body.time_local is not None and not _TIME_RE.match(body.time_local):
        raise HTTPException(400, "Время должно быть в формате ЧЧ:ММ.")
    r = repo.update_reminder(reminder_id, **body.model_dump(exclude_unset=True))
    if r is None:
        raise HTTPException(404, "Напоминание не найдено.")
    return {"ok": True, "reminder": r}


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: str, user: str = Depends(auth.require_csrf)) -> dict:
    if not repo.delete_reminder(reminder_id):
        raise HTTPException(404, "Напоминание не найдено.")
    return {"ok": True}


@router.post("/test")
async def test_send(body: TestBody, user: str = Depends(auth.require_csrf)) -> dict:
    """Сгенерировать совет сейчас и отправить в Telegram (проверка связки)."""
    project, goal = body.project, body.goal
    if body.id:
        r = repo.get_reminder(body.id)
        if r is None:
            raise HTTPException(404, "Напоминание не найдено.")
        project, goal = r["project"], r["goal"]
    try:
        advice = await advisor.generate_advice(project, goal)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Не удалось сгенерировать совет: {exc}")
    ok, err = telegram.send_message(advice)
    repo.add_reminder_log(body.id, project, advice if ok else f"{advice}\n\n[{err}]", ok)
    return {"ok": ok, "advice": advice, "error": err}
