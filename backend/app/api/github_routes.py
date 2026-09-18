"""GitHub API для UI (Фаза 2): info / branches / ci / создание PR."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, projects_store
from ..tools import github

router = APIRouter(prefix="/api/github", tags=["github"])


def _root(project: str):
    root = projects_store.project_root(project)
    if root is None or not root.is_dir():
        raise HTTPException(400, "Проект не найден.")
    return root


class PRBody(BaseModel):
    project: str
    title: str
    head: str | None = None
    base: str | None = None
    body: str = ""


@router.get("/info")
def info(project: str, user: str = Depends(auth.require_user)) -> dict:
    return github.repo_info(_root(project))


@router.get("/branches")
def branches(project: str, user: str = Depends(auth.require_user)) -> dict:
    return github.list_branches(_root(project))


@router.get("/ci")
def ci(project: str, ref: str | None = None, user: str = Depends(auth.require_user)) -> dict:
    return github.ci_status(_root(project), ref)


@router.post("/pr")
def create_pr(body: PRBody, user: str = Depends(auth.require_csrf)) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "Заголовок PR обязателен.")
    return github.create_pr(_root(body.project), body.title, body.head, body.base, body.body)
