"""Роуты браузер-агента: статус и отдача скриншотов (Фаза 3)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import auth
from ..browser import manager, screenshots_dir

router = APIRouter(prefix="/api/browser", tags=["browser"])

_ID_RE = re.compile(r"^[a-f0-9]{1,32}$")


@router.get("/status")
def status(user: str = Depends(auth.require_user)) -> dict:
    ok, reason = manager.available()
    return {"available": ok, "reason": reason}


@router.get("/screenshot/{shot_id}")
def screenshot(shot_id: str, user: str = Depends(auth.require_user)):
    if not _ID_RE.match(shot_id):
        raise HTTPException(400, "Неверный id.")
    path = screenshots_dir() / f"{shot_id}.png"
    if not path.is_file():
        raise HTTPException(404, "Скриншот не найден.")
    return FileResponse(str(path), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})
