"""Роуты проектов: список и создание нового (внутри workspace)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, projects_store

router = APIRouter(prefix="/api", tags=["projects"])


class NewProjectBody(BaseModel):
    name: str


class AddProjectBody(BaseModel):
    path: str
    name: str | None = None


@router.get("/projects")
def list_projects(user: str = Depends(auth.require_user)) -> dict:
    return {
        "projects": projects_store.all_projects(),
        "can_create": projects_store.workspace_root() is not None,
        "can_browse": bool(projects_store.browse_roots()),
    }


@router.get("/projects/browse")
def browse(path: str | None = None, user: str = Depends(auth.require_user)) -> dict:
    try:
        return projects_store.browse_dirs(path)
    except projects_store.ProjectError as exc:
        raise HTTPException(400, str(exc))


@router.post("/projects/new")
def new_project(body: NewProjectBody, user: str = Depends(auth.require_csrf)) -> dict:
    try:
        project = projects_store.create_project(body.name)
    except projects_store.ProjectError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "project": project}


@router.post("/projects/add")
def add_project(body: AddProjectBody, user: str = Depends(auth.require_csrf)) -> dict:
    try:
        project = projects_store.add_existing_project(body.path, body.name)
    except projects_store.ProjectError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "project": project}


@router.delete("/projects/{name}")
def delete_project(name: str, user: str = Depends(auth.require_csrf)) -> dict:
    try:
        projects_store.remove_project(name)
    except projects_store.ProjectError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}
