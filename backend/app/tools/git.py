"""Git-инструменты. Все операции — в пределах project root.

git push и деструктивные действия классифицируются как требующие подтверждения
в agent/permissions.py; сюда приходят уже разрешёнными.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .base import ToolContext, ToolResult

# Разрешённые git-подкоманды (белый список).
_ALLOWED = {
    "status", "diff", "log", "branch", "checkout", "add",
    "commit", "push", "remote", "show", "rev-parse", "stash",
}


def _run_git(root: Path, args: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return -1, "git: timeout"
    except OSError as exc:
        return -1, f"git недоступен: {exc}"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def git_tool(ctx: ToolContext, args: list[str] | str) -> ToolResult:
    """Универсальный git-инструмент. args — список аргументов или строка."""
    if isinstance(args, str):
        parts = args.split()
    else:
        parts = list(args)
    if not parts:
        return ToolResult(False, "Не указана git-команда.", summary="git: empty")

    sub = parts[0]
    if sub not in _ALLOWED:
        return ToolResult(False, f"git-подкоманда '{sub}' не разрешена.",
                          summary=f"git {sub}: denied")

    code, out = _run_git(ctx.project_root, parts)
    ok = code == 0
    out = out.strip() or "(нет вывода)"
    return ToolResult(
        ok, f"$ git {' '.join(parts)}\n{out}",
        summary=f"git {' '.join(parts)[:50]} → {'ok' if ok else 'error'}",
        extra={"args": parts, "exit_code": code, "output": out},
    )


# --- Функции для API-роутера /api/git/* -------------------------------------

def status(root: Path) -> dict:
    code, porcelain = _run_git(root, ["status", "--porcelain=v1", "--branch"])
    _, human = _run_git(root, ["status"])
    modified, added, deleted, untracked = [], [], [], []
    branch = ""
    for line in porcelain.splitlines():
        if line.startswith("##"):
            branch = line[3:].split("...")[0].strip()
            continue
        if len(line) < 3:
            continue
        x, path = line[:2], line[3:]
        if "?" in x:
            untracked.append(path)
        elif "D" in x:
            deleted.append(path)
        elif "A" in x:
            added.append(path)
        else:
            modified.append(path)
    return {
        "ok": code == 0, "branch": branch,
        "modified": modified, "added": added,
        "deleted": deleted, "untracked": untracked,
        "raw": human.strip(),
    }


def diff(root: Path, staged: bool = False) -> dict:
    args = ["diff", "--cached"] if staged else ["diff"]
    code, out = _run_git(root, args)
    return {"ok": code == 0, "diff": out}


def commit(root: Path, message: str, add_all: bool = True) -> dict:
    if add_all:
        _run_git(root, ["add", "-A"])
    code, out = _run_git(root, ["commit", "-m", message])
    _, last = _run_git(root, ["log", "-1", "--oneline"])
    return {"ok": code == 0, "output": out.strip(), "last_commit": last.strip()}
