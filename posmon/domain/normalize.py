"""Нормализация доменов и сопоставление сайта с результатом выдачи.

Разделы 31-32 ТЗ:
- один домен должен сопоставляться независимо от схемы, www и слэша;
- режим сопоставления сайта задаётся в его настройках (`match_mode`):
  * ``domain``     — сайту принадлежат сам домен и все его поддомены;
  * ``exact_host`` — только точный host.
"""
from __future__ import annotations

from urllib.parse import urlsplit

MatchMode = str  # "domain" | "exact_host"

MATCH_DOMAIN: MatchMode = "domain"
MATCH_EXACT_HOST: MatchMode = "exact_host"


def normalize_host(value: str) -> str:
    """Привести URL или host к нормализованному хосту.

    ``https://www.Example.RU/page?x=1`` -> ``www.example.ru``
    ``example.ru/`` -> ``example.ru``

    Отбрасываются: схема, userinfo, порт, путь, query, регистр и завершающая
    точка. Ведущее ``www.`` НЕ убирается (нужно для режима exact_host); за это
    отвечает :func:`registrable_base`.
    """
    v = (value or "").strip().lower()
    if not v:
        return ""
    # Гарантируем, что host окажется в netloc: если схемы нет, добавляем "//".
    if "://" not in v and not v.startswith("//"):
        v = "//" + v
    parts = urlsplit(v)
    host = parts.netloc or parts.path
    if "@" in host:            # отбрасываем userinfo
        host = host.rsplit("@", 1)[-1]
    if host.startswith("["):   # IPv6-литерал в скобках
        host = host[1:].split("]", 1)[0]
    elif ":" in host:          # отбрасываем порт
        host = host.split(":", 1)[0]
    return host.strip(".")


def registrable_base(value: str) -> str:
    """База для режима ``domain``: нормализованный host без ведущего ``www.``.

    Это тот домен, поддомены которого также считаются принадлежащими сайту.
    Пользователь вводит, например, ``example.ru`` или ``https://www.example.ru`` —
    в обоих случаях базой будет ``example.ru``.
    """
    host = normalize_host(value)
    return host[4:] if host.startswith("www.") else host


def host_matches(candidate: str, site_value: str, match_mode: MatchMode = MATCH_DOMAIN) -> bool:
    """Принадлежит ли результат выдачи ``candidate`` сайту ``site_value``.

    ``candidate`` — URL или host результата выдачи.
    ``site_value`` — домен/URL, заданный в настройках сайта.
    """
    cand = normalize_host(candidate)
    if not cand:
        return False
    if match_mode == MATCH_EXACT_HOST:
        return cand == normalize_host(site_value)
    base = registrable_base(site_value)
    if not base:
        return False
    return cand == base or cand.endswith("." + base)
