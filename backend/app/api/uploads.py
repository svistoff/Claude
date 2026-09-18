"""Загрузка файлов в чат (раздел 17 ТЗ)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import auth, uploads_store

router = APIRouter(prefix="/api", tags=["uploads"])


@router.post("/upload")
async def upload(file: UploadFile = File(...), user: str = Depends(auth.require_csrf)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "Пустой файл.")
    try:
        info = uploads_store.save_upload(file.filename or "file", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, **info}
