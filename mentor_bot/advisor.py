"""Генерация одного шага на сегодня (персона AI CEO) с учётом истории."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import github, llm
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
💡 Идея развития: <одна идея, как улучшить или развить проект дальше — по состоянию кода, коммитов и issue>

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


def build_context(db: DB, project: dict, remote: list[str] | None = None) -> str:
    name = project["name"]
    parts = [f"Проект: {name}"]
    if project.get("goal"):
        parts.append("Цель основателя:\n" + project["goal"])
    else:
        parts.append("Цель не задана — предложи шаг к первому платящему клиенту.")

    root = Path(project["path"]) if project.get("path") else None
    if root and root.is_dir():
        parts.extend(_project_files(root))
    parts.extend(remote or [])

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
    remote: list[str] = []
    if project.get("repo"):
        try:
            remote = await github.fetch_context(project["repo"], cfg.github_token)
        except github.GitHubError as exc:
            remote = [f"GitHub недоступен: {exc}. Опирайся на остальной контекст."]
    context = build_context(db, project, remote)
    user = "Вот контекст. Выдай один шаг на сегодня в заданном формате.\n\n" + context
    return await llm.complete(cfg.llm_api_key, cfg.llm_base_url, cfg.llm_model,
                              SYSTEM_PROMPT, user)


# --- План дня по входящим задачам ------------------------------------------

PLAN_PROMPT = """\
Ты — личный секретарь и организатор рабочего дня. Тебе дают порцию открытых
задач (с номерами, срочностью и сколько раз их откладывали) и проекты с целями.
Составь реалистичный план на сегодня: человек не успеет всё, поэтому выбирай.

Правила:
- Одна ГЛАВНАЯ задача дня — та, что сильнее всего двигает дело (деньги, клиенты,
  запуск), а не самая лёгкая. Срочные (🔥) в приоритете, но не обязательно все сразу.
- Ещё 1–3 задачи, если они быстрые или срочные.
- Задачи «на потом» (🕓) — не больше одной, мягко напомни о ней, если есть силы.
- Остальное явно отложи — без чувства вины.
- Размытую задачу переформулируй в первый конкретный шаг.
- Если задачу откладывали 3+ раза — прямо спроси: делаем сегодня или удаляем?
- Если видишь, как улучшить: разбить, объединить, делегировать — скажи одной строкой.
- Ссылайся на номера задач (#N), чтобы их можно было закрыть кнопкой или /done N.

Формат:
🗓 План на сегодня
⭐ Главное: #N — <формулировка> (почему это важнее всего)
• #N — <...>
🕓 Напоминание: #N — <...>
⏸ Отложить: #N, #N — <одной фразой почему>
💡 Улучшение: <одна строка, если есть>

Без вступлений. По-русски. Коротко."""

PRIO_MARK = {"urgent": "🔥 срочно", "normal": "обычная", "later": "🕓 на потом"}


def build_plan_context(db: DB, tasks: list[dict], reserve: int) -> str:
    lines = []
    for t in tasks:
        extra = f", откладывали {t['postponed']} р." if t["postponed"] else ""
        lines.append(f"#{t['id']} [{PRIO_MARK[t['priority']]}{extra}] {t['text']}")
    parts = ["Порция задач на сегодня:\n" + "\n".join(lines)]
    if reserve > 0:
        parts.append(f"Ещё {reserve} задач в запасе — сегодня их не показываем.")
    projects = [p for p in db.list_projects() if p["enabled"]]
    if projects:
        parts.append("Проекты и цели:\n" + "\n".join(
            f"- {p['name']}: {p['goal'] or 'цель не задана'}" for p in projects))
    return "\n\n".join(parts)


async def plan_day(cfg: Config, db: DB, tasks: list[dict], reserve: int) -> str:
    return await llm.complete(cfg.llm_api_key, cfg.llm_base_url, cfg.llm_model,
                              PLAN_PROMPT, build_plan_context(db, tasks, reserve))


# --- Голосовая заметка → несколько задач ------------------------------------

SPLIT_PROMPT = """\
Тебе дают расшифровку голосового сообщения, в котором человек диктует задачи.
Выдели отдельные задачи. Для каждой: короткая формулировка с глагола (без слов
«надо», «мне нужно») и срочность: "urgent" — если сказано срочно/сегодня/горит,
"later" — если сказано потом/когда-нибудь/не горит, иначе "normal".
Ничего не выдумывай и не добавляй. Если это не задачи, а просто мысль — одна
задача с этой мыслью.

Ответ — ТОЛЬКО JSON-массив без пояснений:
[{"text": "...", "priority": "urgent|normal|later"}]"""


def parse_split(raw: str) -> list[tuple[str, str]]:
    """Разобрать ответ модели; при мусоре вернуть пустой список."""
    import json
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        items = json.loads(raw)
    except ValueError:
        return []
    out: list[tuple[str, str]] = []
    if isinstance(items, list):
        for it in items[:15]:
            if isinstance(it, dict) and str(it.get("text", "")).strip():
                prio = it.get("priority") if it.get("priority") in ("urgent", "normal", "later") else "normal"
                out.append((str(it["text"]).strip(), prio))
    return out


async def split_tasks(cfg: Config, transcript: str) -> list[tuple[str, str]]:
    raw = await llm.complete(cfg.llm_api_key, cfg.llm_base_url, cfg.llm_model,
                             SPLIT_PROMPT, transcript, max_tokens=600)
    return parse_split(raw)
