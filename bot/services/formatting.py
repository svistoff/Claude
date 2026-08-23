"""Форматирование ответа AI в Telegram HTML: заголовок жирным, подзаголовок курсивом.

Заголовок и подзаголовок определяются по позиции абзаца (первый и второй,
разделённые пустой строкой), а не по меткам "Заголовок:"/"Подзаголовок:" —
это не зависит от того, добавит их модель или нет. Вся markdown-разметка
(**bold**, *italic*, _italic_, `code`), которую модель может добавить сама
(в том числе внутри обычного текста, не только в заголовке), снимается
заранее — жирный/курсив в Telegram проставляет только сам бот через HTML.
"""
from __future__ import annotations

import html
import re

_LABEL_RE = re.compile(r"^\s*(заголовок|подзаголовок|title|subtitle)\s*:?\s*", re.IGNORECASE)

# Markdown-обёртки, которые AI иногда добавляет по привычке: убираем разметку,
# оставляя только содержимое. Подчёркивание НЕ трогаем — оно почти всегда часть
# @username/хэштега в исходном тексте, а не markdown-курсив, и его вырезание
# ломало бы упоминания вроде @zdorovie_ekb.
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_MD_CODE_RE = re.compile(r"`([^`\n]+?)`")
_LEFTOVER_MD_RE = re.compile(r"[*`]+")


def _strip_markdown(text: str) -> str:
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_ITALIC_STAR_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    # На случай непарных/вложенных звёздочек, которые не подошли под шаблоны выше
    return _LEFTOVER_MD_RE.sub("", text)


def _clean(line: str) -> str:
    return _LABEL_RE.sub("", line.strip()).strip()


def format_ai_text(raw: str) -> str:
    """Возвращает готовый к отправке HTML-текст для Telegram (parse_mode=HTML)."""
    raw = _strip_markdown(raw)
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
