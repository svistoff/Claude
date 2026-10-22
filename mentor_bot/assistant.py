"""Диалог-секретарь: понимает, что написал владелец, отвечает и сам ведёт базу.

Модель получает память (факты о человеке, открытые задачи, последние реплики) и
возвращает JSON: ответ + действия над базой (задачи, мысли, факты). Действия
проверяются здесь же — модель не может тронуть то, чего нет.
"""

from __future__ import annotations

import json
from datetime import datetime

from . import llm
from .config import Config
from .db import DB

SYSTEM_PROMPT = """\
Ты — личный ИИ-секретарь владельца: ведёшь его задачи, мысли и память, помогаешь
управлять временем. Общайся на «ты», живо и коротко, как толковый помощник, а не
как форма ввода. Тебе дают: что ты о нём помнишь, открытые задачи, последние
реплики диалога и новое сообщение.

Что ты умеешь (можешь рассказать, если спросят): записывать задачи со срочностью,
утром присылать план дня порцией, вечером подводить итог, копить мысли и цитаты,
понимать голосовые, вести проекты и по GitHub-репозиторию давать ежедневный шаг
и идеи развития, помнить факты о человеке.

Сначала пойми, чего человек хочет, и только потом действуй:
- Вопрос, приветствие, разговор, «ты готов?» — просто ответь по делу. Задачу НЕ создавай.
- Человек ставит дело (одно или несколько) — add_task на каждое: формулировка
  с глагола, priority: "urgent" (срочно/сегодня/горит), "later" (потом/не горит),
  иначе "normal". Если человек не назвал срочность, оцени сам по смыслу и срокам
  («завтра встреча», «клиент ждёт», «просрочено» — urgent; «когда-нибудь», «было бы
  неплохо» — later). Не выдумывай задач, о которых не просили.
- «Сделал X», «закончил X» — done_task с id подходящей открытой задачи.
  Если сообщение — продолжение, уточнение или деталь к уже открытой задаче («по
  отчёту: цифры за сентябрь», «звонить надо до обеда») — append_task с id этой
  задачи, а не новая задача. Новую заводи, только если это правда другое дело.
  «Убери/не надо X» — drop_task. «X на самом деле срочно/потом» — set_priority.
- Мысль, цитата, наблюдение «на будущее» — save_note.
- Важное о человеке, его проектах, предпочтениях, правилах, привычках («я
  работаю по утрам», «клиент — салоны красоты») — remember: короткий
  самостоятельный факт. Не запоминай разовые дела и мелочи, и не дублируй то, что уже помнишь.
- «Забудь про X» — forget с id факта.
- Если непонятно, что имелось в виду, — задай ОДИН уточняющий вопрос и не делай действий.
Если сообщение — «сделал» без указания чего и открытых задач несколько, уточни.

Ответ — ТОЛЬКО JSON, без пояснений и markdown:
{"reply": "<что сказать человеку, 1–4 предложения>",
 "actions": [
   {"type": "add_task", "text": "...", "priority": "urgent|normal|later"},
   {"type": "done_task", "id": 3}, {"type": "drop_task", "id": 3},
   {"type": "set_priority", "id": 3, "priority": "urgent|normal|later"},
   {"type": "append_task", "id": 3, "text": "деталь к задаче"},
   {"type": "save_note", "text": "..."},
   {"type": "remember", "text": "..."}, {"type": "forget", "id": 5}
 ]}
actions может быть пустым. В reply кратко подтверждай сделанное (например, «Записал:
позвонить бухгалтеру, срочно»), номера задач указывай как #N."""

PRIORITIES = ("urgent", "normal", "later")
MARK = {"urgent": "🔥", "normal": "•", "later": "🕓"}


def build_context(db: DB, now_local: datetime, text: str) -> str:
    parts = [f"Сейчас: {now_local.strftime('%Y-%m-%d %H:%M')}, "
             f"{['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'][now_local.weekday()]}"]
    facts = db.list_facts()
    parts.append("Что ты помнишь о человеке:\n" + "\n".join(f"[{f['id']}] {f['text']}" for f in facts)
                 if facts else "О человеке пока ничего не запомнено.")
    tasks = db.open_tasks()
    parts.append("Открытые задачи:\n" + "\n".join(
        f"#{t['id']} {MARK[t['priority']]} {t['text']}" for t in tasks[:40])
        if tasks else "Открытых задач нет.")
    chat = db.recent_chat(12)
    if chat:
        parts.append("Последние реплики:\n" + "\n".join(
            f"{'Человек' if m['role'] == 'user' else 'Ты'}: {m['text'][:400]}" for m in chat))
    parts.append("Новое сообщение человека:\n" + text)
    return "\n\n".join(parts)


def parse_response(raw: str) -> tuple[str, list[dict]] | None:
    """(reply, actions) или None, если модель вернула не JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    actions = [a for a in (data.get("actions") or []) if isinstance(a, dict)]
    return str(data.get("reply") or "").strip(), actions[:20]


def apply_actions(db: DB, actions: list[dict]) -> dict:
    """Выполнить проверенные действия. Вернуть сводку: id новых задач и т. п."""
    out = {"added": [], "done": [], "dropped": [], "appended": [], "notes": 0, "facts": 0}
    for a in actions:
        kind, text = a.get("type"), str(a.get("text") or "").strip()
        prio = a.get("priority") if a.get("priority") in PRIORITIES else "normal"
        try:
            tid = int(a.get("id")) if a.get("id") is not None else None
        except (TypeError, ValueError):
            tid = None
        if kind == "add_task" and text:
            out["added"].append(db.add_task(text, prio))
        elif kind == "done_task" and tid and db.complete_task(tid):
            out["done"].append(tid)
        elif kind == "drop_task" and tid and db.delete_task(tid):
            out["dropped"].append(tid)
        elif kind == "set_priority" and tid and a.get("priority") in PRIORITIES:
            db.set_priority(tid, a["priority"])
        elif kind == "append_task" and tid and text and db.append_task(tid, text):
            out["appended"].append(tid)
        elif kind == "save_note" and text:
            db.add_note(text)
            out["notes"] += 1
        elif kind == "remember" and text:
            if db.add_fact(text) is not None:
                out["facts"] += 1
        elif kind == "forget" and tid:
            db.delete_fact(tid)
    return out


async def respond(cfg: Config, db: DB, now_local: datetime, text: str) -> tuple[str, dict] | None:
    """Обработать сообщение. None — модель ответила не по формату (решает вызывающий)."""
    raw = await llm.complete(cfg.llm_api_key, cfg.llm_base_url, cfg.llm_model, SYSTEM_PROMPT,
                             build_context(db, now_local, text), max_tokens=900)
    parsed = parse_response(raw)
    if parsed is None:
        return None
    reply, actions = parsed
    db.add_chat("user", text)
    summary = apply_actions(db, actions)
    if not reply:
        reply = "Принял."
    db.add_chat("assistant", reply)
    return reply, summary
