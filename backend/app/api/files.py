"""Файлы: скачивание одного файла и создание/скачивание ZIP (разделы 16, 32 ТЗ)."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .. import auth
from ..config import get_app_config, get_project_map
from ..security import SecurityError, is_secret_path, resolve_within_root

router = APIRouter(prefix="/api/files", tags=["files"])


def _root(project: str) -> Path:
    pm = get_project_map()
    if project not in pm:
        raise HTTPException(400, f"Неизвестный проект: {project}")
    root = pm[project]
    if not root.is_dir():
        raise HTTPException(400, "Директория проекта не найдена.")
    return root


@router.get("/download")
def download(project: str, path: str, user: str = Depends(auth.require_user)):
    root = _root(project)
    config = get_app_config()
    if is_secret_path(path, config.secret_patterns):
        raise HTTPException(403, "Файл в списке секретных.")
    try:
        target = resolve_within_root(root, path)
    except SecurityError as exc:
        raise HTTPException(403, str(exc))
    if not target.is_file():
        raise HTTPException(404, "Файл не найден.")
    return FileResponse(str(target), filename=target.name)


class ZipBody(BaseModel):
    project: str
    paths: list[str] | None = None  # если None — весь проект (кроме секретов/мусора)


_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv"}


@router.post("/zip")
def create_zip(body: ZipBody, user: str = Depends(auth.require_user)):
    root = _root(body.project)
    config = get_app_config()
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if body.paths:
            files = []
            for p in body.paths:
                try:
                    t = resolve_within_root(root, p)
                except SecurityError:
                    continue
                if t.is_file():
                    files.append(t)
        else:
            files = [f for f in root.rglob("*") if f.is_file()]

        for f in files:
            rel = str(f.relative_to(root))
            if is_secret_path(rel, config.secret_patterns):
                continue
            if any(part in _SKIP for part in f.parts):
                continue
            zf.write(f, arcname=rel)

    buf.seek(0)
    fname = f"{body.project}-{date.today().isoformat()}.zip"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
