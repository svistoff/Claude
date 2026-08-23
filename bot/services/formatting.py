"""Форматирование ответа AI в Telegram HTML: заголовок жирным, подзаголовок курсивом.

Заголовок и подзаголовок определяются по позиции абзаца (первый и второй,
разделённые пустой строкой), а не по меткам "Заголовок:"/"Подзаголовок:" —
это не зависит от того, добавит их модель или нет. Если модель всё же
приписала метку или markdown-звёздочки, они срезаются защитным regex'ом.
"""
from __future__ import annotations

import html
import re

_LABEL_RE = re.compile(r"^\s*\*{0,2}(заголовок|подзаголовок|title|subtitle)\s*:?\*{0,2}\s*", re.IGNORECASE)


def _clean(line: str) -> str:
    line = _LABEL_RE.sub("", line.strip())
    return line.strip("* ").strip()


def format_ai_text(raw: str) -> str:
    """Возвращает готовый к отправке HTML-текст для Telegram (parse_mode=HTML)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw.strip()) if p.strip()]

    if not paragraphs:
        return ""

    if len(paragraphs) == 1:
        return html.escape(_clean(paragraphs[0]))

    title = _clean(paragraphs[0])
    subtitle = _clean(paragraphs[1])
    body_paragraphs = paragraphs[2:]

    parts = [f"<b>{html.escape(title)}</b>", f"<i>{html.escape(subtitle)}</i>"]
    if body_paragraphs:
        parts.append("")
        parts.append("\n\n".join(html.escape(p) for p in body_paragraphs))

    return "\n".join(parts)
