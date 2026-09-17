"""Роуты проектов: список и создание нового (внутри workspace)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, projects_store

router = APIRouter(prefix="/api", tags=["projects"])


class NewProjectBody(BaseModel):
    name: str


@router.get("/projects")
def list_projects(user: str = Depends(auth.require_user)) -> dict:
    return {
        "projects": projects_store.all_projects(),
        "can_create": projects_store.workspace_root() is not None,
    }


@router.post("/projects/new")
def new_project(body: NewProjectBody, user: str = Depends(auth.require_csrf)) -> dict:
    try:
        project = projects_store.create_project(body.name)
    except projects_store.ProjectError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "project": project}
