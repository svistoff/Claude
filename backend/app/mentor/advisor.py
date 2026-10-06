"""Генерация одного конкретного шага к первой выручке (персона AI CEO)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import projects_store
from ..llm import get_provider

SYSTEM_PROMPT = """\
Ты — AI CEO и наставник основателя. Твоя единственная цель — довести проект до
ПЕРВОЙ выручки, а не до идеала. Ты защищаешь фокус: не предлагаешь новые функции,
если они не приближают деньги; лишние идеи отправляешь в «паркинг».

Тебе дают проект, цель основателя и краткий контекст (git-лог, файлы). Выдай ОДИН
шаг на сегодня (2–4 часа), который максимально приближает первый рубль.

Отвечай коротко, по-русски, строго в формате:

🎯 Фокус: <актив/проект>
🔎 Узкое место: <что прямо сейчас мешает деньгам>
✅ Задача на сегодня (2–4ч): <одно конкретное действие>
🏁 Done: <как понять, что сделано — проверяемо>
💰 Бизнес-результат: <чем это приближает первый рубль>

Без вступлений и воды. Если данных мало — всё равно предложи лучший следующий шаг
к продаже/клиенту, а не к улучшению кода."""


def _run(cmd: list[str], cwd: str) -> str:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=15)
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def build_context(project: str | None, goal: str) -> str:
    parts: list[str] = []
    if goal.strip():
        parts.append(f"Цель основателя:\n{goal.strip()}")

    root: Path | None = projects_store.project_root(project) if project else None
    if project:
        parts.append(f"Проект: {project}")
    if root and root.is_dir():
        log = _run(["git", "log", "-5", "--pretty=format:%cd %s", "--date=short"], str(root))
        if log:
            parts.append("Последние коммиты:\n" + log)
        try:
            top = sorted(p.name for p in root.iterdir()
                         if not p.name.startswith("."))[:40]
            if top:
                parts.append("Файлы в корне: " + ", ".join(top))
        except OSError:
            pass
        for readme in ("README.md", "readme.md", "README.txt"):
            rp = root / readme
            if rp.is_file():
                try:
                    parts.append("README (фрагмент):\n" + rp.read_text("utf-8", "ignore")[:1500])
                except OSError:
                    pass
                break
    return "\n\n".join(parts) if parts else "Контекста нет — дай лучший следующий шаг к продаже."


async def _complete(system: str, user: str) -> str:
    provider = get_provider()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    chunks: list[str] = []
    async for ev in provider.stream(messages, tools=None):
        t = ev.get("type")
        if t == "text":
            chunks.append(ev.get("delta", ""))
        elif t == "error":
            raise RuntimeError(ev.get("message", "LLM error"))
    return "".join(chunks).strip()


async def generate_advice(project: str | None, goal: str) -> str:
    context = build_context(project, goal)
    user = ("Вот контекст. Выдай один шаг на сегодня к первой выручке "
            "в заданном формате.\n\n" + context)
    text = await _complete(SYSTEM_PROMPT, user)
    return text or "Не удалось сформировать совет — проверь настройки модели."
