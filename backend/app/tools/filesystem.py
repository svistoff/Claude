"""Файловые инструменты: read / list / search / write / edit.

Все пути проверяются на принадлежность project root; секретные файлы недоступны
для чтения, листинга и поиска.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..security import ensure_not_secret, is_secret_path, resolve_within_root
from .base import ToolContext, ToolResult

# Директории, которые не имеет смысла обходить при листинге/поиске.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
             ".pytest_cache", "dist", "build", ".next", ".idea", ".vscode"}


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def read_file(ctx: ToolContext, path: str) -> ToolResult:
    ensure_not_secret(path, ctx.config.secret_patterns)
    target = resolve_within_root(ctx.project_root, path)
    if not target.exists() or not target.is_file():
        return ToolResult(False, f"Файл не найден: {path}", summary=f"read {path}: not found")

    max_bytes = ctx.config.agent.max_read_bytes
    data = target.read_bytes()
    truncated = False
    if len(data) > max_bytes:
        data = data[:max_bytes]
        truncated = True
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ToolResult(False, f"Файл '{path}' не является текстовым (бинарный).",
                          summary=f"read {path}: binary")

    note = f"\n\n[...обрезано на {max_bytes} байт]" if truncated else ""
    numbered = "\n".join(
        f"{i + 1}\t{line}" for i, line in enumerate(text.splitlines())
    )
    return ToolResult(
        True,
        f"Содержимое {path}:\n{numbered}{note}",
        summary=f"read {path} ({len(text.splitlines())} строк)",
        extra={"path": path, "content": text, "truncated": truncated},
    )


def list_files(ctx: ToolContext, path: str = ".") -> ToolResult:
    target = resolve_within_root(ctx.project_root, path)
    if not target.exists() or not target.is_dir():
        return ToolResult(False, f"Директория не найдена: {path}",
                          summary=f"list {path}: not found")

    entries: list[str] = []
    for child in sorted(target.iterdir(), key=lambda c: (c.is_file(), c.name)):
        rel = _rel(ctx.project_root, child)
        if is_secret_path(rel, ctx.config.secret_patterns):
            continue  # секретные файлы не показываем
        if child.is_dir():
            if child.name in _SKIP_DIRS:
                entries.append(f"{rel}/  (пропущено)")
            else:
                entries.append(f"{rel}/")
        else:
            entries.append(rel)

    listing = "\n".join(entries) if entries else "(пусто)"
    return ToolResult(
        True,
        f"Содержимое директории {path}:\n{listing}",
        summary=f"list {path} ({len(entries)} элементов)",
        extra={"path": path, "entries": entries},
    )


def search_files(ctx: ToolContext, query: str, path: str = ".") -> ToolResult:
    """Поиск текста по проекту. Использует ripgrep, если доступен, иначе fallback."""
    base = resolve_within_root(ctx.project_root, path)
    max_results = ctx.config.agent.max_search_results

    matches = _ripgrep(base, query, ctx) if _has_ripgrep() else _py_grep(base, query, ctx)
    matches = matches[:max_results]

    if not matches:
        return ToolResult(True, f"Совпадений по '{query}' не найдено.",
                          summary=f"search '{query}': 0")
    body = "\n".join(matches)
    return ToolResult(
        True,
        f"Совпадения по '{query}' (до {max_results}):\n{body}",
        summary=f"search '{query}': {len(matches)}",
        extra={"query": query, "matches": matches},
    )


def _has_ripgrep() -> bool:
    from shutil import which
    return which("rg") is not None


def _ripgrep(base: Path, query: str, ctx: ToolContext) -> list[str]:
    globs: list[str] = []
    for d in _SKIP_DIRS:
        globs += ["-g", f"!{d}"]
    for pat in ctx.config.secret_patterns:
        globs += ["-g", f"!{pat}"]
    try:
        proc = subprocess.run(
            ["rg", "--line-number", "--no-heading", "--color", "never",
             "--max-count", "20", *globs, query, "."],
            cwd=str(base), capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    out: list[str] = []
    for line in proc.stdout.splitlines():
        # rg печатает относительно cwd(base); проверим секретность.
        rel_from_root = _rel(ctx.project_root, base / line.split(":", 1)[0]) \
            if ":" in line else line
        if is_secret_path(rel_from_root, ctx.config.secret_patterns):
            continue
        out.append(line)
    return out


def _py_grep(base: Path, query: str, ctx: ToolContext) -> list[str]:
    out: list[str] = []
    q = query.lower()
    for file in base.rglob("*"):
        if not file.is_file():
            continue
        if any(part in _SKIP_DIRS for part in file.parts):
            continue
        rel = _rel(ctx.project_root, file)
        if is_secret_path(rel, ctx.config.secret_patterns):
            continue
        try:
            for i, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                if q in line.lower():
                    out.append(f"{rel}:{i}:{line.strip()[:200]}")
                    if len(out) >= ctx.config.agent.max_search_results:
                        return out
        except (UnicodeDecodeError, OSError):
            continue
    return out


def write_file(ctx: ToolContext, path: str, content: str) -> ToolResult:
    ensure_not_secret(path, ctx.config.secret_patterns)
    target = resolve_within_root(ctx.project_root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    action = "перезаписан" if existed else "создан"
    return ToolResult(
        True,
        f"Файл {path} {action} ({len(content)} символов).",
        summary=f"write {path} ({action})",
        extra={"path": path},
    )


def edit_file(ctx: ToolContext, path: str, old_str: str, new_str: str) -> ToolResult:
    """Точечная замена уникального old_str на new_str (patch-механика)."""
    ensure_not_secret(path, ctx.config.secret_patterns)
    target = resolve_within_root(ctx.project_root, path)
    if not target.exists():
        return ToolResult(False, f"Файл не найден: {path}", summary=f"edit {path}: not found")

    text = target.read_text(encoding="utf-8")
    count = text.count(old_str)
    if count == 0:
        return ToolResult(False,
                          f"Фрагмент old_str не найден в {path}. Проверьте точное совпадение.",
                          summary=f"edit {path}: no match")
    if count > 1:
        return ToolResult(False,
                          f"old_str встречается {count} раз в {path}; сделайте его уникальным.",
                          summary=f"edit {path}: {count} matches")
    new_text = text.replace(old_str, new_str, 1)
    target.write_text(new_text, encoding="utf-8")
    diff = _unified_diff(path, text, new_text)
    return ToolResult(
        True,
        f"Файл {path} изменён.\nDiff:\n{diff}",
        summary=f"edit {path}",
        extra={"path": path, "diff": diff},
    )


def _unified_diff(path: str, before: str, after: str) -> str:
    import difflib
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}",
        )
    )
