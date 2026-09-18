"""GitHub-инструменты (Фаза 2): remote, ветки, Pull Request, статус CI.

Доступ через fine-grained токен (GITHUB_TOKEN в .env) с минимальными правами.
Токен нигде не логируется и не возвращается пользователю.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import httpx

from ..config import get_settings
from .base import ToolContext, ToolResult

API = "https://api.github.com"


def _token() -> str:
    return get_settings().github_token


def parse_remote(root: Path) -> tuple[str, str] | None:
    """(owner, repo) из origin, либо None если remote не на GitHub."""
    try:
        proc = subprocess.run(["git", "remote", "get-url", "origin"],
                              cwd=str(root), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    url = (proc.stdout or "").strip()
    if not url:
        return None
    # https://github.com/owner/repo(.git)  |  git@github.com:owner/repo(.git)
    m = re.match(r"(?:https?://github\.com/|git@github\.com:)([^/]+)/(.+?)(?:\.git)?/?$", url)
    if not m:
        return None
    return m.group(1), m.group(2)


def _api(method: str, path: str, json: dict | None = None) -> tuple[int, dict]:
    token = _token()
    if not token:
        return 0, {"error": "GITHUB_TOKEN не задан."}
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with httpx.Client(timeout=30) as c:
            r = c.request(method, f"{API}{path}", headers=headers, json=json)
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, data
    except httpx.HTTPError as exc:
        return 0, {"error": f"Сетевая ошибка GitHub: {exc}"}


def _current_branch(root: Path) -> str:
    try:
        p = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                           cwd=str(root), capture_output=True, text=True, timeout=15)
        return (p.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _head_sha(root: Path) -> str:
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"],
                           cwd=str(root), capture_output=True, text=True, timeout=15)
        return (p.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


# --- Функции для API-роутера /api/github/* ----------------------------------

def repo_info(root: Path) -> dict:
    remote = parse_remote(root)
    if remote is None:
        return {"github": False, "reason": "У проекта нет remote на GitHub."}
    owner, repo = remote
    info = {"github": True, "owner": owner, "repo": repo,
            "current_branch": _current_branch(root), "has_token": bool(_token())}
    if _token():
        code, data = _api("GET", f"/repos/{owner}/{repo}")
        if code == 200:
            info["default_branch"] = data.get("default_branch", "main")
            info["private"] = data.get("private")
        elif code == 401 or code == 403:
            info["token_error"] = "Токен недействителен или нет прав на репозиторий."
    return info


def list_branches(root: Path) -> dict:
    remote = parse_remote(root)
    if remote is None:
        return {"ok": False, "error": "Нет GitHub-remote."}
    owner, repo = remote
    code, data = _api("GET", f"/repos/{owner}/{repo}/branches?per_page=100")
    if code != 200:
        return {"ok": False, "error": _err(code, data)}
    return {"ok": True, "branches": [b["name"] for b in data]}


def create_pr(root: Path, title: str, head: str | None = None,
              base: str | None = None, body: str = "") -> dict:
    remote = parse_remote(root)
    if remote is None:
        return {"ok": False, "error": "Нет GitHub-remote."}
    owner, repo = remote
    head = head or _current_branch(root)
    if not base:
        code, data = _api("GET", f"/repos/{owner}/{repo}")
        base = data.get("default_branch", "main") if code == 200 else "main"
    if head == base:
        return {"ok": False, "error": f"Ветка '{head}' совпадает с базовой '{base}'."}
    code, data = _api("POST", f"/repos/{owner}/{repo}/pulls",
                     {"title": title, "head": head, "base": base, "body": body})
    if code == 201:
        return {"ok": True, "number": data["number"], "url": data["html_url"],
                "head": head, "base": base}
    return {"ok": False, "error": _err(code, data)}


def ci_status(root: Path, ref: str | None = None) -> dict:
    remote = parse_remote(root)
    if remote is None:
        return {"ok": False, "error": "Нет GitHub-remote."}
    owner, repo = remote
    ref = ref or _head_sha(root) or _current_branch(root)
    code, data = _api("GET", f"/repos/{owner}/{repo}/commits/{ref}/check-runs")
    if code != 200:
        return {"ok": False, "error": _err(code, data)}
    runs = data.get("check_runs", [])
    summary = {"total": len(runs), "success": 0, "failure": 0, "pending": 0, "runs": []}
    for r in runs:
        concl = r.get("conclusion")
        status = r.get("status")
        if status != "completed":
            summary["pending"] += 1
        elif concl == "success":
            summary["success"] += 1
        elif concl in ("failure", "timed_out", "cancelled"):
            summary["failure"] += 1
        summary["runs"].append({"name": r.get("name"), "status": status, "conclusion": concl})
    summary["ok"] = True
    summary["ref"] = ref
    return summary


def _err(code: int, data: dict) -> str:
    if code == 0:
        return data.get("error", "Ошибка сети GitHub.")
    msg = data.get("message", "")
    return f"GitHub {code}: {msg}" if msg else f"GitHub {code}"


# --- Инструмент агента -------------------------------------------------------

def github_tool(ctx: ToolContext, action: str, **kwargs) -> ToolResult:
    root = ctx.project_root
    if not _token():
        return ToolResult(False, "GITHUB_TOKEN не настроен — GitHub-операции недоступны.",
                          summary="github: no token")
    if action == "info":
        info = repo_info(root)
        return ToolResult(info.get("github", False), str(info), summary="github: info", extra=info)
    if action == "branches":
        r = list_branches(root)
        return ToolResult(r.get("ok", False), str(r), summary="github: branches", extra=r)
    if action == "ci_status":
        r = ci_status(root, kwargs.get("ref"))
        return ToolResult(r.get("ok", False),
                          f"CI: {r.get('success',0)} ок, {r.get('failure',0)} ошибок, "
                          f"{r.get('pending',0)} в процессе" if r.get("ok") else str(r),
                          summary="github: ci", extra=r)
    if action == "create_pr":
        title = kwargs.get("title")
        if not title:
            return ToolResult(False, "Нужен title для PR.", summary="github: pr no title")
        r = create_pr(root, title, kwargs.get("head"), kwargs.get("base"), kwargs.get("body", ""))
        if r.get("ok"):
            return ToolResult(True, f"PR #{r['number']} создан: {r['url']}",
                              summary=f"github: PR #{r['number']}", extra=r)
        return ToolResult(False, r.get("error", "Не удалось создать PR."),
                          summary="github: pr error", extra=r)
    return ToolResult(False, f"Неизвестное github-действие: {action}", summary="github: unknown")
