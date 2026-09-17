"""Роут списка проектов."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from .. import auth
from ..config import get_app_config

router = APIRouter(prefix="/api", tags=["projects"])


@router.get("/projects")
def list_projects(user: str = Depends(auth.require_user)) -> dict:
    projects = []
    for proj in get_app_config().projects:
        exists = Path(proj.path).is_dir()
        projects.append({"name": proj.name, "path": proj.path, "available": exists})
    return {"projects": projects}
