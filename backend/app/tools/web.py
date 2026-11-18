"""Поиск в интернете и чтение страниц — DeepSeek Search & Fetch API.

Два инструмента:
- ``web_search`` — найти страницы по запросу (title / url / summary / дата),
  поддерживает операторы поиска: ``site:``, ``-site:``, ``"точная фраза"``,
  ``lang:ru,en``, ``after:2026-01-01``, ``before:2026``;
- ``web_fetch`` — прочитать страницу и получить её содержимое в Markdown.

Зачем отдельно, если есть браузер: браузер (Playwright) нужен для сайтов с
логином, JS и кликами; для «найди и прочитай» он в десятки раз медленнее и
ломается на капче. Поиск и чтение — здесь, на API DeepSeek.

Тариф: $0.75 за 1000 успешных запросов Search и столько же за Fetch;
неуспешные запросы (4xx/5xx, пустые результаты) не тарифицируются. Ключ —
``DEEPSEEK_API_KEY`` (тот же, что у модели).
"""

from __future__ import annotations

import httpx

from ..config import get_app_config, get_settings
from .base import ToolContext, ToolResult

# Сколько символов summary страницы отдавать модели на один результат.
MAX_SUMMARY_CHARS = 1200
# API не принимает query/ori_question длиннее 128 символов.
QUERY_LIMIT = 128


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _base_url() -> str:
    return get_app_config().web.base_url.rstrip("/")


def _error_text(r: httpx.Response) -> str:
    """Человекочитаемая ошибка API (или пустая строка, если всё хорошо)."""
    if r.status_code == 200:
        return ""
    hints = {
        401: "неверный или отсутствующий DEEPSEEK_API_KEY",
        402: "на балансе DeepSeek недостаточно средств",
        403: "запрос отклонён политикой безопасности",
        404: "страница недоступна или из неё не извлекается текст",
        408: "таймаут чтения запроса",
        413: "слишком большой ответ",
        429: "превышен лимит запросов в секунду (Search 100 QPS, Fetch 25 QPS)",
        500: "внутренняя ошибка DeepSeek",
        504: "таймаут на стороне DeepSeek",
    }
    hint = hints.get(r.status_code, "")
    detail = ""
    try:
        err = (r.json() or {}).get("error") or {}
        detail = err.get("message") or ""
    except Exception:  # noqa: BLE001 — тело может быть не JSON
        detail = (r.text or "")[:200]
    msg = f"Search/Fetch API {r.status_code}"
    if hint:
        msg += f": {hint}"
    if detail:
        msg += f" ({detail[:200]})"
    return msg


def _need_key() -> tuple[str, ToolResult | None]:
    key = get_settings().deepseek_api_key
    if not key:
        return "", ToolResult(
            False,
            "DEEPSEEK_API_KEY не задан — поиск в интернете и чтение страниц недоступны.",
            summary="web: no key",
        )
    return key, None


# --- web_search --------------------------------------------------------------

def web_search(
    ctx: ToolContext,
    query: str,
    count: int | None = None,
    need_content: bool = False,
    ori_question: str | None = None,
) -> ToolResult:
    cfg = get_app_config().web
    if not cfg.enabled:
        return ToolResult(False, "Веб-поиск выключен в конфигурации (web.enabled: false).",
                          summary="web_search: disabled")
    key, err = _need_key()
    if err:
        return err

    q = (query or "").strip()
    if not q:
        return ToolResult(False, "Пустой поисковый запрос.", summary="web_search: empty query")
    q = q[:QUERY_LIMIT]

    n = int(count or cfg.default_count)
    n = max(1, min(n, cfg.max_count))

    payload: dict = {"query": q, "count": n}
    if need_content:
        payload["need_content"] = True
    if ori_question:
        payload["ori_question"] = ori_question.strip()[:QUERY_LIMIT]

    try:
        with httpx.Client(timeout=cfg.timeout) as c:
            r = c.post(f"{_base_url()}/v1/tools/search", headers=_headers(key), json=payload)
    except httpx.HTTPError as exc:
        return ToolResult(False, f"Сетевая ошибка поиска: {exc}", summary="web_search: neterr")

    bad = _error_text(r)
    if bad:
        return ToolResult(False, bad, summary="web_search: error")

    try:
        results = (r.json() or {}).get("results") or []
    except ValueError:
        return ToolResult(False, "Search API вернул не-JSON ответ.", summary="web_search: bad json")

    if not results:
        return ToolResult(True, f"По запросу «{q}» ничего не найдено. Попробуй переформулировать "
                               f"или убрать операторы.", summary="web_search: пусто")

    lines = [f"Результаты поиска «{q}» ({len(results)}):"]
    structured: list[dict] = []
    for i, item in enumerate(results, 1):
        title = (item.get("title") or "").strip() or "(без заголовка)"
        url = (item.get("url") or "").strip()
        site = item.get("site_name") or ""
        date = (item.get("date") or "")[:10]
        summary = (item.get("summary") or item.get("snippet") or "").strip()
        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[:MAX_SUMMARY_CHARS] + "…"
        head = f"{i}. {title}"
        meta = " · ".join(x for x in (site, date) if x)
        if meta:
            head += f" — {meta}"
        lines.append(head)
        if url:
            lines.append(f"   {url}")
        if summary:
            lines.append(f"   {summary}")
        content = (item.get("content") or "").strip()
        if content:
            snippet = content[:MAX_SUMMARY_CHARS]
            lines.append(f"   [фрагмент] {snippet}" + ("…" if len(content) > len(snippet) else ""))
        structured.append({"title": title, "url": url, "site": site, "date": date,
                           "summary": summary})

    lines.append("\nЧтобы прочитать страницу целиком — вызови web_fetch(url).")
    return ToolResult(
        True, "\n".join(lines),
        summary=f"web_search: {len(results)} рез. по «{q[:40]}»",
        extra={"query": q, "results": structured},
    )


# --- web_fetch ---------------------------------------------------------------

def web_fetch(ctx: ToolContext, url: str, max_chars: int | None = None) -> ToolResult:
    cfg = get_app_config().web
    if not cfg.enabled:
        return ToolResult(False, "Чтение страниц выключено в конфигурации (web.enabled: false).",
                          summary="web_fetch: disabled")
    key, err = _need_key()
    if err:
        return err

    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return ToolResult(False, "Нужен полный URL, начинающийся с http:// или https:// "
                                 f"(получено: «{u[:80]}»).", summary="web_fetch: bad url")

    try:
        with httpx.Client(timeout=cfg.timeout) as c:
            r = c.post(f"{_base_url()}/v1/tools/fetch", headers=_headers(key), json={"url": u})
    except httpx.HTTPError as exc:
        return ToolResult(False, f"Сетевая ошибка чтения страницы: {exc}", summary="web_fetch: neterr")

    bad = _error_text(r)
    if bad:
        return ToolResult(False, bad, summary="web_fetch: error")

    try:
        data = r.json() or {}
    except ValueError:
        return ToolResult(False, "Fetch API вернул не-JSON ответ.", summary="web_fetch: bad json")

    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    if not content:
        return ToolResult(False, f"Страница {u} не содержит извлекаемого текста.",
                          summary="web_fetch: пусто")

    limit = int(max_chars or cfg.max_content_chars)
    limit = max(1000, min(limit, cfg.max_content_chars))
    truncated = len(content) > limit
    body = content[:limit]
    head = f"# {title}\n" if title else ""
    out = f"{head}Источник: {u}\n\n{body}"
    if truncated:
        out += f"\n\n[…обрезано: показано {limit} из {len(content)} символов]"
    return ToolResult(
        True, out,
        summary=f"web_fetch: {u[:60]}" + (" (обрезано)" if truncated else ""),
        extra={"url": u, "title": title, "chars": len(content), "truncated": truncated},
    )
