"""slug новости: транслит заголовка + 4 случайных символа (см. 4.4 ТЗ)."""
from __future__ import annotations

import re
import secrets
import string

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}
_ALPHABET = string.ascii_lowercase + string.digits
_MAX_BASE = 60


def make_slug(title: str) -> str:
    latin = "".join(_TRANSLIT.get(ch, ch) for ch in title.lower())
    base = re.sub(r"[^a-z0-9]+", "-", latin).strip("-")
    if len(base) > _MAX_BASE:
        base = base[:_MAX_BASE].rsplit("-", 1)[0] or base[:_MAX_BASE]
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(4))
    return f"{base or 'news'}-{suffix}"
