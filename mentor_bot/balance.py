"""Остаток на балансе ИИ-провайдеров и предупреждение о пополнении.

DeepSeek отдаёт баланс напрямую (GET /user/balance, ключ тот же, что у бота).
OpenAI остаток по API не отдаёт: считаем «сумма пополнения − расходы с тех пор»
по Costs API (нужен Admin-ключ), сумму пополнения владелец сообщает командой /topup.
"""

from __future__ import annotations

import time

import httpx

from .db import DB

OPENAI_COSTS = "https://api.openai.com/v1/organization/costs"
CNY_PER_USD = 7.2  # грубо, только чтобы порог в долларах имел смысл для баланса в юанях


class BalanceError(Exception):
    pass


async def deepseek_balance(api_key: str, base_url: str) -> tuple[float, str]:
    """(сумма, валюта). Бросает BalanceError."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{base_url.rstrip('/')}/user/balance",
                            headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        raise BalanceError(f"сетевая ошибка: {exc}") from exc
    if r.status_code != 200:
        raise BalanceError(f"API {r.status_code}")
    try:
        info = r.json()["balance_infos"][0]
        return float(info["total_balance"]), info["currency"]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise BalanceError("неожиданный ответ API баланса") from exc


async def openai_spent_since(admin_key: str, since_ts: int) -> float:
    """Сумма расходов (USD) организации с момента since_ts. Бросает BalanceError."""
    total, page = 0.0, None
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            for _ in range(20):  # страховка от бесконечной пагинации
                params = {"start_time": since_ts, "bucket_width": "1d", "limit": 180}
                if page:
                    params["page"] = page
                r = await c.get(OPENAI_COSTS, params=params,
                                headers={"Authorization": f"Bearer {admin_key}"})
                if r.status_code != 200:
                    raise BalanceError(f"OpenAI Costs API {r.status_code} "
                                       "(нужен Admin-ключ с доступом к usage)")
                data = r.json()
                for bucket in data.get("data", []):
                    for res in bucket.get("results", []):
                        total += float((res.get("amount") or {}).get("value") or 0)
                page = data.get("next_page")
                if not data.get("has_more") or not page:
                    break
    except httpx.HTTPError as exc:
        raise BalanceError(f"сетевая ошибка: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise BalanceError("неожиданный ответ OpenAI") from exc
    return total


async def openai_remaining(admin_key: str, db: DB) -> float | None:
    """Остаток по расчёту или None, если /topup ещё не вводили."""
    topup = db.get_state("openai_topup")
    since = db.get_state("openai_since")
    if topup is None or since is None:
        return None
    return float(topup) - await openai_spent_since(admin_key, int(since))


def set_openai_topup(db: DB, amount: float) -> None:
    db.set_state("openai_topup", str(amount))
    db.set_state("openai_since", str(int(time.time())))


async def collect(cfg, db: DB) -> list[tuple[str, float, str, float]]:
    """[(провайдер, остаток, валюта, порог в этой валюте)] для настроенных провайдеров.

    Ошибка одного провайдера не мешает остальным — такие пропускаются.
    """
    out = []
    thr = cfg.balance_alert_usd
    if cfg.llm_api_key and "deepseek" in cfg.llm_base_url:
        try:
            amount, cur = await deepseek_balance(cfg.llm_api_key, cfg.llm_base_url)
            out.append(("DeepSeek", amount, cur, thr * (CNY_PER_USD if cur == "CNY" else 1)))
        except BalanceError:
            pass
    if cfg.openai_admin_key:
        try:
            rem = await openai_remaining(cfg.openai_admin_key, db)
            if rem is not None:
                out.append(("OpenAI", rem, "USD", thr))
        except BalanceError:
            pass
    return out
