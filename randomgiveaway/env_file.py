"""Точечное обновление одной переменной в .env-файле — без внешних зависимостей.

Нужен, чтобы сохранять/продлевать токены (Instagram/VK/Telegram) без ручного
редактирования файла (см. api/routes.py и scripts/refresh_*.py).
"""
from __future__ import annotations

import os
from pathlib import Path


def set_env_var(env_path: Path, key: str, value: str) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True) if env_path.exists() else []
    prefix = f"{key}="
    new_line = f"{key}={value}\n"
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = new_line
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line)

    # Запись атомарная (временный файл в той же папке + os.replace) — если
    # процесс упадёт или кончится место на диске посреди записи, исходный
    # .env останется нетронутым вместо того, чтобы обнулиться наполовину
    # записанным. os.replace — атомарная операция на уровне ФС (в отличие
    # от write_text, который открывает файл с truncate ещё до записи).
    tmp_path = env_path.with_name(f"{env_path.name}.tmp-{os.getpid()}")
    tmp_path.write_text("".join(lines), encoding="utf-8")
    os.replace(tmp_path, env_path)
