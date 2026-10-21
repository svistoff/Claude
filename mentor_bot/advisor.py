"""Генерация одного шага на сегодня (персона AI CEO) с учётом истории."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import llm
from .config import Config
from .db import DB

SYSTEM_PROMPT = """\
Ты — AI CEO и наставник основателя. Твоя единственная цель — довести проект до
ПЕРВОЙ выручки, а не до идеала. Ты защищаешь фокус: не предлагаешь новые функции,
если они не приближают деньги.

Тебе дают цель основателя, контекст проекта, твои прошлые советы и отчёты
основателя о том, что он сделал. Правила:
- Не повторяй прошлый совет, если он выполнен — двигайся к следующему шагу.
- Если прошлый совет не выполнен или отчёта нет — упрости его до шага, который
  точно можно сделать сегодня, и честно скажи, что это продолжение.
- Опирайся на факты из отчётов (цифры, отклики клиентов) больше, чем на код.

Выдай ОДИН шаг на сегодня (2–4 часа), строго в формате:

🎯 Фокус: <проект>
🔎 Узкое место: <что прямо сейчас мешает деньгам>
✅ Задача на сегодня (2–4ч): <одно конкретное действие>
🏁 Done: <проверяемый результат>
💰 Бизнес-результат: <чем это приближает первый рубль>

Без вступлений. По-русски."""


def _git_log(root: Path) -> str:
    try:
        r = subprocess.run(["git", "log", "-5", "--pretty=format:%cd %s", "--date=short"],
                           cwd=str(root), capture_output=True, text=True, timeout=15)
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _project_files(root: Path) -> list[str]:
    parts: list[str] = []
    log = _git_log(root)
    if log:
        parts.append("Последние коммиты:\n" + log)
    try:
        names = sorted(p.name for p in root.iterdir() if not p.name.startswith("."))[:40]
        if names:
            parts.append("Файлы в корне: " + ", ".join(names))
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
    return parts


def build_context(db: DB, project: dict) -> str:
    name = project["name"]
    parts = [f"Проект: {name}"]
    if project.get("goal"):
        parts.append("Цель основателя:\n" + project["goal"])
    else:
        parts.append("Цель не задана — предложи шаг к первому платящему клиенту.")

    root = Path(project["path"]) if project.get("path") else None
    if root and root.is_dir():
        parts.extend(_project_files(root))

    # Память: от старых к новым, чтобы модель видела развитие.
    advice = list(reversed(db.recent_advice(name, 3)))
    if advice:
        parts.append("Твои прошлые советы:\n" + "\n---\n".join(
            f"[{a['created_at'][:10]}]\n{a['text']}" for a in advice))
    reports = list(reversed(db.recent_reports(name, 5)))
    if reports:
        parts.append("Отчёты основателя:\n" + "\n".join(
            f"[{r['created_at'][:10]}] {r['text']}" for r in reports))
    else:
        parts.append("Отчётов от основателя пока нет.")
    return "\n\n".join(parts)


async def generate(cfg: Config, db: DB, project: dict) -> str:
    context = build_context(db, project)
    user = "Вот контекст. Выдай один шаг на сегодня в заданном формате.\n\n" + context
    return await llm.complete(cfg.llm_api_key, cfg.llm_base_url, cfg.llm_model,
                              SYSTEM_PROMPT, user)


# --- План дня по входящим задачам ------------------------------------------

PLAN_PROMPT = """\
Ты — личный организатор рабочего дня. Тебе дают список открытых задач
пользователя (с номерами) и его проекты с целями. Составь реалистичный план на
сегодня: человек не успеет всё, поэтому выбирай.

Правила:
- Одна ГЛАВНАЯ задача дня — та, что сильнее всего двигает дело (деньги, клиенты,
  запуск), а не самая лёгкая.
- Ещё 1–3 задачи, если они быстрые или срочные.
- Остальное явно отложи — без чувства вины.
- Если задача размытая («разобраться с ботом») — переформулируй в первый
  конкретный шаг.
- Ссылайся на номера задач (#N), чтобы их можно было закрыть командой /done N.

Формат:
🗓 План на сегодня
⭐ Главное: #N — <формулировка> (почему это важнее всего)
• #N — <...>
⏸ Отложить: #N, #N — <одной фразой почему>

Без вступлений. По-русски. Коротко."""


def build_plan_context(db: DB) -> str:
    tasks = db.open_tasks()
    parts = ["Открытые задачи:\n" + "\n".join(f"#{t['id']} {t['text']}" for t in tasks)]
    projects = [p for p in db.list_projects() if p["enabled"]]
    if projects:
        parts.append("Проекты и цели:\n" + "\n".join(
            f"- {p['name']}: {p['goal'] or 'цель не задана'}" for p in projects))
    return "\n\n".join(parts)


async def plan_day(cfg: Config, db: DB) -> str:
    return await llm.complete(cfg.llm_api_key, cfg.llm_base_url, cfg.llm_model,
                              PLAN_PROMPT, build_plan_context(db))
