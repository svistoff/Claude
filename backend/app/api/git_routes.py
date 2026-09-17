"""Git API: status / diff / commit (раздел 32 ТЗ)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth
from ..config import get_project_map
from ..tools import git

router = APIRouter(prefix="/api/git", tags=["git"])


def _root(project: str):
    pm = get_project_map()
    if project not in pm:
        raise HTTPException(400, f"Неизвестный проект: {project}")
    root = pm[project]
    if not root.is_dir():
        raise HTTPException(400, "Директория проекта не найдена.")
    return root


class CommitBody(BaseModel):
    project: str
    message: str
    add_all: bool = True


@router.get("/status")
def git_status(project: str, user: str = Depends(auth.require_user)) -> dict:
    return git.status(_root(project))


@router.get("/diff")
def git_diff(project: str, staged: bool = False, user: str = Depends(auth.require_user)) -> dict:
    return git.diff(_root(project), staged=staged)


@router.post("/commit")
def git_commit(body: CommitBody, user: str = Depends(auth.require_csrf)) -> dict:
    if not body.message.strip():
        raise HTTPException(400, "Сообщение commit не должно быть пустым.")
    return git.commit(_root(body.project), body.message, add_all=body.add_all)
