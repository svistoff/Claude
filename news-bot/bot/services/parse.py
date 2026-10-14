"""Разбор поста по разметке Telegram (см. 4.2 ТЗ).

repost-bot публикует в «На выкладку» посты вида
    <b>Заголовок</b>
    <i>Подзаголовок-описание</i>

    Основной текст…
При пересылке разметка приходит как entities, их offset/length считаются
в UTF-16 code units (эмодзи = 2 единицы), поэтому все срезы — через UTF-16.

Модуль чистый (без aiogram/config), entities — список dict с ключами
type/offset/length/url, чтобы его можно было проверять без Telegram.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TITLE_MAX_LEN = 140  # длиннее — скорее всего жирным выделен не заголовок → AI


@dataclass
class Parsed:
    title: str | None = None
    summary: str | None = None
    body: str = ""
    warnings: list[str] = field(default_factory=list)


class _U16:
    """Текст с доступом по UTF-16 смещениям."""

    def __init__(self, text: str) -> None:
        self.raw = text.encode("utf-16-le")
        self.len = len(self.raw) // 2

    def slice(self, start: int, end: int) -> str:
        return self.raw[start * 2 : end * 2].decode("utf-16-le", errors="ignore")


def _merged_spans(entities: list[dict], types: set[str], u: _U16) -> list[tuple[int, int]]:
    """Склеивает соседние/пересекающиеся entities нужного типа: при ручной правке
    поста жирный часто рвётся на куски («<b>Заголовок</b> <b>🔥</b>»)."""
    spans = sorted((e["offset"], e["offset"] + e["length"]) for e in entities if e.get("type") in types)
    merged: list[list[int]] = []
    for s, e in spans:
        if merged:
            gap = u.slice(merged[-1][1], s) if s > merged[-1][1] else ""
            if s <= merged[-1][1] or (gap.strip() == "" and "\n" not in gap):
                merged[-1][1] = max(merged[-1][1], e)
                continue
        merged.append([s, e])
    return [(s, e) for s, e in merged]


def _is_noise(s: str) -> bool:
    """Нет ни букв, ни цифр — пробелы, эмодзи, тире, точки и т.п."""
    return not any(ch.isalnum() for ch in s)


def _clean(s: str) -> str:
    return " ".join(s.split()).strip(" -–—:|")


def render_plain(text: str, entities: list[dict], start: int = 0, end: int | None = None) -> str:
    """Текст фрагмента [start, end) (UTF-16), где у скрытых ссылок (text_link)
    URL дописан в скобках — иначе ссылка «подробнее» потеряется на сайте."""
    u = _U16(text)
    end = u.len if end is None else end
    links = sorted(
        (e["offset"], e["offset"] + e["length"], e["url"])
        for e in entities
        if e.get("type") == "text_link" and e.get("url") and start <= e["offset"] < end
    )
    out, pos = [], start
    for s, e, url in links:
        e = min(e, end)
        if s < pos:
            continue
        label = u.slice(s, e)
        out.append(u.slice(pos, s))
        out.append(label)
        if url not in label:
            out.append(f" ({url})")
        pos = e
    out.append(u.slice(pos, end))
    return "".join(out)


def parse_by_entities(text: str, entities: list[dict]) -> Parsed | None:
    """Основной путь: жирное в начале → title, курсив сразу после → summary,
    остальное → body. None — разметки нет, нужен AI."""
    u = _U16(text)
    bold = _merged_spans(entities, {"bold"}, u)
    if not bold:
        return None
    b_start, b_end = bold[0]
    if not _is_noise(u.slice(0, b_start)):
        return None  # жирное не в начале поста
    title = _clean(u.slice(b_start, b_end))
    if not title or len(title) > TITLE_MAX_LEN:
        return None

    pos = b_end
    summary = None
    italic = [sp for sp in _merged_spans(entities, {"italic"}, u) if sp[0] >= b_end]
    if italic:
        i_start, i_end = italic[0]
        if _is_noise(u.slice(b_end, i_start)):
            summary = _clean(u.slice(i_start, i_end)) or None
            pos = i_end if summary else pos

    body = render_plain(text, entities, pos, u.len).strip()
    return Parsed(title=title, summary=summary, body=body)


def parse_by_lines(text: str) -> Parsed:
    """Последний запасной путь (AI недоступен): первая строка — заголовок,
    вторая — описание, остальное — текст."""
    lines = [ln.strip() for ln in text.strip().splitlines()]
    non_empty = [i for i, ln in enumerate(lines) if ln]
    if not non_empty:
        return Parsed(title="Без заголовка")
    t_i = non_empty[0]
    title = _clean(lines[t_i])[:TITLE_MAX_LEN] or "Без заголовка"
    rest = lines[t_i + 1 :]
    summary = None
    if rest and rest[0]:
        summary = _clean(rest[0]) or None
        rest = rest[1:]
    return Parsed(title=title, summary=summary, body="\n".join(rest).strip())
