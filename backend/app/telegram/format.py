"""Markdown ответа агента → HTML-разметка Telegram + нарезка длинных сообщений."""

from __future__ import annotations

import html
import re

CHUNK = 3500  # запас до лимита Telegram в 4096 символов (с учётом тегов)

_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)\*(?![\w*])")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_HEADER = re.compile(r"^#{1,6}\s+(.*)$")


def _inline(line: str) -> str:
    """Экранировать строку и применить инлайн-разметку (код не трогаем внутри)."""
    parts = _INLINE_CODE.split(line)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # содержимое `кода`
            out.append(f"<code>{html.escape(part)}</code>")
            continue
        t = html.escape(part)
        t = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', t)
        t = _BOLD.sub(r"<b>\1</b>", t)
        t = _ITALIC.sub(r"<i>\1</i>", t)
        out.append(t)
    return "".join(out)


def md_to_html(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1  # закрывающий ```
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
            continue
        if line.lstrip().startswith("|"):  # таблица — моноширинным блоком
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                if not re.fullmatch(r"\s*\|[\s:|-]+\|\s*", lines[i]):  # без строки-разделителя
                    block.append(lines[i].strip())
                i += 1
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
            continue
        h = _HEADER.match(line)
        if h:
            out.append(f"<b>{_inline(h.group(1))}</b>")
        elif re.match(r"^\s*[-*]\s+", line):
            out.append("• " + _inline(re.sub(r"^\s*[-*]\s+", "", line)))
        else:
            out.append(_inline(line))
        i += 1
    return "\n".join(out)


def split_markdown(text: str, limit: int = CHUNK) -> list[str]:
    """Нарезать по строкам, не разрывая блоки кода."""
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    in_code = False
    for line in text.split("\n"):
        if size + len(line) + 1 > limit and cur:
            if in_code:
                cur.append("```")
            chunks.append("\n".join(cur))
            cur = ["```"] if in_code else []
            size = sum(len(x) + 1 for x in cur)
        # Очень длинная строка — режем жёстко.
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        cur.append(line)
        size += len(line) + 1
        if line.strip().startswith("```"):
            in_code = not in_code
    if cur and "\n".join(cur).strip():
        chunks.append("\n".join(cur))
    return chunks or [""]
