"""Безопасность файловых инструментов: sandbox путей и фильтр секретов.

Применяется на уровне ВСЕХ файловых инструментов (read/list/search/write/edit),
а не только листинга — чтобы через read/grep нельзя было вытащить содержимое
секретного файла в контекст модели (разделы 9.2, 44 ТЗ).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path


class SecurityError(Exception):
    """Нарушение границ песочницы или попытка доступа к секрету."""


def resolve_within_root(root: Path, rel_path: str) -> Path:
    """Разрешить rel_path относительно root, гарантируя, что результат внутри root.

    Блокирует выход за пределы project root через `..`, симлинки и абсолютные пути.
    Бросает SecurityError при попытке выхода.
    """
    root = root.resolve()
    # Абсолютные пути внутри проекта разрешаем, но всё равно проверяем границы.
    candidate = Path(rel_path)
    if candidate.is_absolute():
        target = candidate
    else:
        target = root / candidate

    # Резолвим симлинки и `..`. strict=False — файла может ещё не быть (write).
    resolved = _resolve_no_strict(target)

    if resolved != root and root not in resolved.parents:
        raise SecurityError(
            f"Путь '{rel_path}' выходит за пределы разрешённого project root."
        )
    return resolved


def _resolve_no_strict(path: Path) -> Path:
    """resolve() без требования существования, но с раскрытием симлинков предков."""
    path = path.expanduser()
    resolved_parts: Path
    try:
        # Резолвим ближайшего существующего предка (раскрывая симлинки),
        # затем дописываем оставшийся хвост.
        existing = path
        tail: list[str] = []
        while not existing.exists():
            tail.append(existing.name)
            parent = existing.parent
            if parent == existing:
                break
            existing = parent
        resolved_parts = existing.resolve()
        for part in reversed(tail):
            resolved_parts = resolved_parts / part
        return resolved_parts
    except (OSError, RuntimeError):
        return path.absolute()


def is_secret_path(rel_path: str, patterns: list[str]) -> bool:
    """True, если ЛЮБОЙ сегмент пути совпадает с секретным паттерном.

    Проверяем каждый компонент пути (не только basename), чтобы поймать,
    например, `config/id_rsa` или `.git/config`.
    """
    p = Path(rel_path)
    parts = list(p.parts)
    basename = p.name
    for pattern in patterns:
        # Полное совпадение относительного пути (например ".git/config").
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(
            rel_path.lstrip("./"), pattern
        ):
            return True
        # Совпадение basename.
        if fnmatch.fnmatch(basename, pattern):
            return True
        # Совпадение любого сегмента.
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def ensure_not_secret(rel_path: str, patterns: list[str]) -> None:
    if is_secret_path(rel_path, patterns):
        raise SecurityError(
            f"Доступ к '{rel_path}' запрещён: файл в списке секретных."
        )
