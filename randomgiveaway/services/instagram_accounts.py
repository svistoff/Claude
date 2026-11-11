"""Хранилище подключённых Instagram-аккаунтов (разовая авторизация по ссылке
/api/instagram/connect/start) — см. services/instagram_tags.py и README.md,
«Розыгрыш по отметкам в Instagram»."""
from __future__ import annotations

from datetime import datetime, timezone

from randomgiveaway.database.database import get_conn
from randomgiveaway.database.models import InstagramConnectedAccount


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upsert_account(ig_user_id: str, username: str | None, access_token: str) -> InstagramConnectedAccount:
    conn = get_conn()
    now = _now()
    await conn.execute(
        """
        INSERT INTO instagram_connected_accounts (ig_user_id, username, access_token, connected_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ig_user_id) DO UPDATE SET
            username = excluded.username,
            access_token = excluded.access_token,
            updated_at = excluded.updated_at
        """,
        (ig_user_id, username, access_token, now, now),
    )
    await conn.commit()
    cur = await conn.execute(
        "SELECT * FROM instagram_connected_accounts WHERE ig_user_id = ?", (ig_user_id,)
    )
    row = await cur.fetchone()
    return InstagramConnectedAccount.from_row(row)


async def list_accounts() -> list[InstagramConnectedAccount]:
    conn = get_conn()
    cur = await conn.execute("SELECT * FROM instagram_connected_accounts ORDER BY connected_at ASC")
    rows = await cur.fetchall()
    return [InstagramConnectedAccount.from_row(r) for r in rows]


async def get_accounts_by_ids(ids: list[int]) -> list[InstagramConnectedAccount]:
    if not ids:
        return []
    conn = get_conn()
    placeholders = ",".join("?" * len(ids))
    cur = await conn.execute(
        f"SELECT * FROM instagram_connected_accounts WHERE id IN ({placeholders})", ids
    )
    rows = await cur.fetchall()
    return [InstagramConnectedAccount.from_row(r) for r in rows]


async def update_token(ig_user_id: str, access_token: str) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE instagram_connected_accounts SET access_token = ?, updated_at = ? WHERE ig_user_id = ?",
        (access_token, _now(), ig_user_id),
    )
    await conn.commit()
