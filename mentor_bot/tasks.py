"""Приоритеты задач и отбор порции на день (без ИИ — детерминированно)."""

from __future__ import annotations

import re

URGENT_RE = re.compile(r"^\s*(!+|срочно\b[:,.\s-]*)", re.IGNORECASE)
LATER_RE = re.compile(r"^\s*(потом\b[:,.\s-]*|на потом\b[:,.\s-]*|когда-нибудь\b[:,.\s-]*|\?\s)",
                      re.IGNORECASE)

MAX_URGENT = 5
MAX_NORMAL = 8
MAX_LATER = 2
STALE_POSTPONES = 3  # столько переносов — пора решать: делаем или удаляем


def parse_priority(text: str) -> tuple[str, str]:
    """Вернуть (приоритет, очищенный текст). «! текст» / «срочно …» / «потом …»."""
    for prio, rx in (("urgent", URGENT_RE), ("later", LATER_RE)):
        m = rx.match(text)
        if m and text[m.end():].strip():
            return prio, text[m.end():].strip()
    return "normal", text.strip()


def select_for_plan(tasks: list[dict], today: str) -> tuple[list[dict], int]:
    """Порция для плана: срочные, обычные и пара «на потом» (давно не показывали).

    Возвращает (отобранные, сколько открытых задач осталось в запасе).
    """
    visible = [t for t in tasks if not t.get("hidden_until") or t["hidden_until"] <= today]
    urgent = [t for t in visible if t["priority"] == "urgent"]
    normal = [t for t in visible if t["priority"] == "normal"]
    later = [t for t in visible if t["priority"] == "later"]
    normal.sort(key=lambda t: (-t["postponed"], t["id"]))
    later.sort(key=lambda t: (t["last_shown"] or "", t["id"]))
    picked = urgent[:MAX_URGENT] + normal[:MAX_NORMAL] + later[:MAX_LATER]
    return picked, len(tasks) - len(picked)


def task_ids_in(text: str, valid: set[int], limit: int = 8) -> list[int]:
    """Номера задач (#N), упомянутые в тексте плана, в порядке появления."""
    seen: list[int] = []
    for m in re.finditer(r"#(\d+)", text):
        n = int(m.group(1))
        if n in valid and n not in seen:
            seen.append(n)
    return seen[:limit]


def plan_buttons(ids: list[int]) -> list[list[dict]]:
    """Inline-клавиатура под планом: на каждую задачу «Сделано» и «Завтра»."""
    return [[{"text": f"✅ #{i} сделано", "callback_data": f"done:{i}"},
             {"text": f"⏸ #{i} завтра", "callback_data": f"snooze:{i}"}] for i in ids]


def new_task_buttons(task_id: int) -> list[list[dict]]:
    return [[{"text": "🔥 Срочно", "callback_data": f"urgent:{task_id}"},
             {"text": "🕓 На потом", "callback_data": f"later:{task_id}"},
             {"text": "🗑", "callback_data": f"drop:{task_id}"}]]


# --- Копилка мыслей ------------------------------------------------------------

NOTE_RE = re.compile(r"^\s*(💡|мысль\b|цитата\b|идея\b|заметка\b)[:,.\s-]*", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+")


def parse_note(text: str) -> tuple[bool, str]:
    """Это мысль для копилки? «💡 …», «мысль: …», «цитата …» или одна ссылка."""
    m = NOTE_RE.match(text)
    if m and text[m.end():].strip():
        return True, text[m.end():].strip()
    if URL_RE.fullmatch(text.strip()):
        return True, text.strip()
    return False, text


def forward_source(message: dict) -> str:
    """Имя источника пересланного сообщения ('' если не пересылка)."""
    fo = message.get("forward_origin")
    if fo:
        chat = fo.get("chat") or {}
        user = fo.get("sender_user") or {}
        return (chat.get("title") or fo.get("sender_user_name") or user.get("first_name")
                or "переслано")
    if message.get("forward_date"):
        chat = message.get("forward_from_chat") or {}
        user = message.get("forward_from") or {}
        return (chat.get("title") or message.get("forward_sender_name")
                or user.get("first_name") or "переслано")
    return ""
