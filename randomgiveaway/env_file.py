"""Точечное обновление одной переменной в .env-файле — без внешних зависимостей.

Нужен, чтобы сохранять/продлевать INSTAGRAM_ACCESS_TOKEN без ручного
редактирования файла (см. api/routes.py: /instagram/oauth/callback и
scripts/refresh_instagram_token.py).
"""
from __future__ import annotations

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
    env_path.write_text("".join(lines), encoding="utf-8")
