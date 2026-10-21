"""Чтение GitHub-репозитория проекта для контекста совета (только чтение)."""

from __future__ import annotations

import re

import httpx

REPO_RE = re.compile(r"^(?:https?://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
API = "https://api.github.com"


class GitHubError(Exception):
    pass


def parse_repo(value: str) -> str | None:
    """'owner/name' из 'owner/name' или ссылки на GitHub; иначе None."""
    m = REPO_RE.match(value.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


async def fetch_context(repo: str, token: str = "") -> list[str]:
    """Описание, README, свежие коммиты и открытые issue/PR. Не удалось достучаться — GitHubError."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "mentor-bot"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=20, headers=headers) as c:
            info = await c.get(f"{API}/repos/{repo}")
            if info.status_code == 404:
                raise GitHubError(f"{repo}: репозиторий не найден или закрыт (нужен GITHUB_TOKEN)")
            if info.status_code != 200:
                raise GitHubError(f"{repo}: ошибка API {info.status_code}")
            meta = info.json()
            commits = await c.get(f"{API}/repos/{repo}/commits", params={"per_page": 8})
            issues = await c.get(f"{API}/repos/{repo}/issues",
                                 params={"state": "open", "per_page": 10})
            readme = await c.get(f"{API}/repos/{repo}/readme",
                                 headers={**headers, "Accept": "application/vnd.github.raw+json"})
    except httpx.HTTPError as exc:
        raise GitHubError(f"{repo}: сетевая ошибка ({exc})") from exc

    parts = [f"GitHub {repo}: {meta.get('description') or 'без описания'} "
             f"(язык: {meta.get('language') or '?'}, ★{meta.get('stargazers_count', 0)}, "
             f"последний пуш: {(meta.get('pushed_at') or '')[:10]})"]
    if commits.status_code == 200:
        lines = [f"{(x['commit']['author'] or {}).get('date', '')[:10]} "
                 f"{x['commit']['message'].splitlines()[0][:100]}" for x in commits.json()]
        if lines:
            parts.append("Свежие коммиты на GitHub:\n" + "\n".join(lines))
    if issues.status_code == 200:
        lines = [f"{'PR' if 'pull_request' in i else 'issue'} #{i['number']}: {i['title'][:100]}"
                 for i in issues.json()]
        parts.append("Открытые issue/PR:\n" + "\n".join(lines) if lines
                     else "Открытых issue/PR нет.")
    if readme.status_code == 200:
        parts.append("README (фрагмент):\n" + readme.text[:1500])
    return parts
