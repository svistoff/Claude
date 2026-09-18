"""Загрузка файлов в чат: сохранение в сессионную tmp-папку и подготовка контекста.

Безопасность (раздел 17 ТЗ):
- имя файла санируется (только basename, безопасный набор символов);
- файлы кладутся ТОЛЬКО внутрь WORKSPACE_TMP/uploads/<token>/ — перезаписать
  произвольные системные файлы нельзя;
- секретные имена (.env, *.key, id_rsa …) отклоняются;
- размер файла ограничен; в модель отдаётся ограниченный объём текста.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from .config import BACKEND_DIR, get_app_config, get_settings
from .security import is_secret_path, resolve_within_root

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def uploads_root() -> Path:
    tmp = get_settings().workspace_tmp
    path = Path(tmp)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    root = (path / "uploads").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_name(name: str) -> str:
    base = Path(name).name                       # только basename, без путей
    base = _SAFE.sub("_", base).rstrip(". ")     # убрать хвостовые точки/пробелы
    if not base or set(base) <= {".", "_"}:
        base = "file"
    return base[:120]


def save_upload(filename: str, data: bytes) -> dict:
    cfg = get_app_config().uploads
    if len(data) > cfg.max_file_bytes:
        raise ValueError(f"Файл больше {cfg.max_file_bytes // 1_000_000} МБ.")

    safe = sanitize_name(filename)
    if is_secret_path(safe, get_app_config().secret_patterns):
        raise ValueError("Загрузка файлов такого типа запрещена (секрет).")

    token = uuid.uuid4().hex[:16]
    folder = uploads_root() / token
    folder.mkdir(parents=True, exist_ok=True)
    target = resolve_within_root(folder, safe)   # защита от traversal
    target.write_bytes(data)

    is_text = _is_text(data)
    return {"token": token, "name": safe, "size": len(data), "is_text": is_text}


def _is_text(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def read_upload(token: str, name: str) -> Path | None:
    safe = sanitize_name(name)
    folder = (uploads_root() / sanitize_name(token))
    try:
        target = resolve_within_root(folder, safe)
    except Exception:
        return None
    return target if target.is_file() else None


def build_attachments_context(attachments: list[dict]) -> str:
    """Собрать текст приложенных файлов для добавления в сообщение пользователя."""
    if not attachments:
        return ""
    cfg = get_app_config().uploads
    parts: list[str] = []
    total = 0
    for att in attachments[: cfg.max_files]:
        token, name = att.get("token", ""), att.get("name", "")
        path = read_upload(token, name)
        if path is None:
            continue
        data = path.read_bytes()
        if not _is_text(data):
            parts.append(f"[файл: {name} — бинарный, сохранён, текст не извлекается]")
            continue
        text = data.decode("utf-8", "replace")
        budget = min(cfg.max_inline_per_file, cfg.max_inline_total - total)
        if budget <= 0:
            parts.append(f"[файл: {name} — не приложен: превышен лимит контекста]")
            continue
        clipped = text[:budget]
        total += len(clipped)
        note = "" if len(clipped) == len(text) else "\n[...файл обрезан]"
        parts.append(f"[файл: {name}]\n{clipped}{note}")
    if not parts:
        return ""
    return "\n\n--- Прикреплённые файлы ---\n" + "\n\n".join(parts)
