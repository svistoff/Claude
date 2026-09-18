"""Настройки: выбор LLM-модели (переключатель flash / v4-pro)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, settings_store

router = APIRouter(prefix="/api", tags=["settings"])


class ModelBody(BaseModel):
    model: str


@router.get("/settings")
def get_settings_route(user: str = Depends(auth.require_user)) -> dict:
    return {
        "model": settings_store.current_model(),
        "available_models": settings_store.available_models(),
    }


@router.post("/settings/model")
def set_model_route(body: ModelBody, user: str = Depends(auth.require_csrf)) -> dict:
    try:
        model = settings_store.set_model(body.model)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "model": model}
