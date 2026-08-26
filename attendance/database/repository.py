"""CRUD-функции поверх SQLite. Все функции работают с общим соединением из database.py."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from attendance.database.database import get_conn
from attendance.database.models import AttendanceSession, Device, Employee, SystemEvent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- employees

async def create_employee(name: str) -> int:
    conn = get_conn()
    cur = await conn.execute(
        "INSERT INTO employees (name, created_at, updated_at) VALUES (?, ?, ?)",
        (name, _now_iso(), _now_iso()),
    )
    await conn.commit()
    return cur.lastrowid


async def get_employee(employee_id: int) -> Employee | None:
    conn = get_conn()
    cur = await conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    row = await cur.fetchone()
    return Employee.from_row(row) if row else None


async def list_employees(include_inactive: bool = True) -> list[Employee]:
    conn = get_conn()
    query = "SELECT * FROM employees"
    if not include_inactive:
        query += " WHERE is_active = 1"
    query += " ORDER BY name"
    cur = await conn.execute(query)
    rows = await cur.fetchall()
    return [Employee.from_row(r) for r in rows]


async def rename_employee(employee_id: int, name: str) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE employees SET name = ?, updated_at = ? WHERE id = ?",
        (name, _now_iso(), employee_id),
    )
    await conn.commit()


async def set_employee_active(employee_id: int, is_active: bool) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE employees SET is_active = ?, updated_at = ? WHERE id = ?",
        (int(is_active), _now_iso(), employee_id),
    )
    await conn.commit()


# ------------------------------------------------------------------ devices

async def get_device_by_employee(employee_id: int) -> Device | None:
    conn = get_conn()
    cur = await conn.execute("SELECT * FROM devices WHERE employee_id = ?", (employee_id,))
    row = await cur.fetchone()
    return Device.from_row(row) if row else None


async def get_device_by_identifier(identifier: str) -> Device | None:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT * FROM devices WHERE device_identifier = ?", (identifier.upper(),)
    )
    row = await cur.fetchone()
    return Device.from_row(row) if row else None


async def upsert_device(employee_id: int, identifier: str, name: str) -> None:
    """Создаёт устройство сотрудника или заменяет существующее (one-to-one)."""
    conn = get_conn()
    identifier = identifier.upper()
    existing = await get_device_by_employee(employee_id)
    if existing is None:
        await conn.execute(
            "INSERT INTO devices (employee_id, device_identifier, name, created_at) "
            "VALUES (?, ?, ?, ?)",
            (employee_id, identifier, name, _now_iso()),
        )
    else:
        await conn.execute(
            "UPDATE devices SET device_identifier = ?, name = ?, is_active = 1, "
            "last_seen_at = NULL, last_seen_hostname = NULL WHERE employee_id = ?",
            (identifier, name, employee_id),
        )
    await conn.commit()


async def touch_device_seen(device_id: int, seen_at: datetime, hostname: str | None) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE devices SET last_seen_at = ?, last_seen_hostname = ? WHERE id = ?",
        (seen_at.isoformat(), hostname, device_id),
    )
    await conn.commit()


@dataclass
class RegisteredDevice:
    """Устройство активного сотрудника — то, что реально участвует в опросе."""

    id: int
    employee_id: int
    device_identifier: str
    last_seen_at: str | None
    last_seen_hostname: str | None


async def get_active_devices_with_employees() -> list[RegisteredDevice]:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT d.id, d.employee_id, d.device_identifier, d.last_seen_at, d.last_seen_hostname "
        "FROM devices d JOIN employees e ON e.id = d.employee_id "
        "WHERE d.is_active = 1 AND e.is_active = 1"
    )
    rows = await cur.fetchall()
    return [
        RegisteredDevice(
            id=r["id"],
            employee_id=r["employee_id"],
            device_identifier=r["device_identifier"],
            last_seen_at=r["last_seen_at"],
            last_seen_hostname=r["last_seen_hostname"],
        )
        for r in rows
    ]


# ---------------------------------------------------------- attendance_sessions

async def get_active_session(employee_id: int) -> AttendanceSession | None:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT * FROM attendance_sessions WHERE employee_id = ? AND status = 'active' "
        "ORDER BY started_at DESC LIMIT 1",
        (employee_id,),
    )
    row = await cur.fetchone()
    return AttendanceSession.from_row(row) if row else None


async def get_latest_session(employee_id: int) -> AttendanceSession | None:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT * FROM attendance_sessions WHERE employee_id = ? "
        "ORDER BY started_at DESC LIMIT 1",
        (employee_id,),
    )
    row = await cur.fetchone()
    return AttendanceSession.from_row(row) if row else None


async def create_session(employee_id: int, started_at: datetime) -> int:
    conn = get_conn()
    cur = await conn.execute(
        "INSERT INTO attendance_sessions (employee_id, started_at, last_seen_at, status) "
        "VALUES (?, ?, ?, 'active')",
        (employee_id, started_at.isoformat(), started_at.isoformat()),
    )
    await conn.commit()
    return cur.lastrowid


async def update_session_last_seen(session_id: int, seen_at: datetime) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE attendance_sessions SET last_seen_at = ? WHERE id = ?",
        (seen_at.isoformat(), session_id),
    )
    await conn.commit()


async def close_session(session_id: int, ended_at: datetime) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE attendance_sessions SET status = 'completed', ended_at = ? WHERE id = ?",
        (ended_at.isoformat(), session_id),
    )
    await conn.commit()


async def list_all_active_sessions() -> list[AttendanceSession]:
    conn = get_conn()
    cur = await conn.execute("SELECT * FROM attendance_sessions WHERE status = 'active'")
    rows = await cur.fetchall()
    return [AttendanceSession.from_row(r) for r in rows]


async def list_sessions_for_employee(employee_id: int, limit: int = 60) -> list[AttendanceSession]:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT * FROM attendance_sessions WHERE employee_id = ? "
        "ORDER BY started_at DESC LIMIT ?",
        (employee_id, limit),
    )
    rows = await cur.fetchall()
    return [AttendanceSession.from_row(r) for r in rows]


async def list_sessions_in_period(
    start: datetime, end: datetime, employee_id: int | None = None
) -> list[AttendanceSession]:
    conn = get_conn()
    query = "SELECT * FROM attendance_sessions WHERE started_at >= ? AND started_at < ?"
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if employee_id is not None:
        query += " AND employee_id = ?"
        params.append(employee_id)
    query += " ORDER BY started_at DESC"
    cur = await conn.execute(query, params)
    rows = await cur.fetchall()
    return [AttendanceSession.from_row(r) for r in rows]


# -------------------------------------------------------------- system_events

async def log_event(
    event_type: str, message: str, success: bool = True, details: dict[str, Any] | None = None
) -> None:
    conn = get_conn()
    await conn.execute(
        "INSERT INTO system_events (created_at, event_type, message, success, details) "
        "VALUES (?, ?, ?, ?, ?)",
        (_now_iso(), event_type, message, int(success), json.dumps(details) if details else None),
    )
    await conn.commit()


async def recent_similar_event_exists(event_type: str, employee_id: int, hours: int) -> bool:
    conn = get_conn()
    cutoff = (datetime.now(timezone.utc)).isoformat()
    cur = await conn.execute(
        "SELECT id, details FROM system_events WHERE event_type = ? "
        "AND created_at >= datetime('now', ?) ORDER BY created_at DESC",
        (event_type, f"-{hours} hours"),
    )
    rows = await cur.fetchall()
    for row in rows:
        if row["details"]:
            details = json.loads(row["details"])
            if details.get("employee_id") == employee_id:
                return True
    return False


async def list_recent_events(limit: int = 200, event_type: str | None = None) -> list[SystemEvent]:
    conn = get_conn()
    query = "SELECT * FROM system_events"
    params: list[Any] = []
    if event_type is not None:
        query += " WHERE event_type = ?"
        params.append(event_type)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await conn.execute(query, params)
    rows = await cur.fetchall()
    return [SystemEvent.from_row(r) for r in rows]


async def last_successful_poll_at() -> str | None:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT created_at FROM system_events WHERE event_type = 'router_poll_ok' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    row = await cur.fetchone()
    return row["created_at"] if row else None


async def is_router_currently_unreachable() -> bool:
    """True, если самое последнее событие опроса — неудача (роутер недоступен прямо сейчас)."""
    conn = get_conn()
    cur = await conn.execute(
        "SELECT event_type FROM system_events "
        "WHERE event_type IN ('router_poll_ok', 'router_poll_failed') "
        "ORDER BY created_at DESC LIMIT 1"
    )
    row = await cur.fetchone()
    return bool(row) and row["event_type"] == "router_poll_failed"


# ---------------------------------------------------------------- app_settings

async def get_setting(key: str) -> str | None:
    conn = get_conn()
    cur = await conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    conn = get_conn()
    await conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await conn.commit()


async def set_setting_if_absent(key: str, value: str) -> None:
    if await get_setting(key) is None:
        await set_setting(key, value)


# ----------------------------------------------------------------- admin_users

async def get_admin_by_username(username: str):
    conn = get_conn()
    cur = await conn.execute("SELECT * FROM admin_users WHERE username = ?", (username,))
    return await cur.fetchone()


async def create_admin(username: str, password_hash: str) -> None:
    conn = get_conn()
    await conn.execute(
        "INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, _now_iso()),
    )
    await conn.commit()


async def update_admin_password(username: str, password_hash: str) -> None:
    conn = get_conn()
    await conn.execute(
        "UPDATE admin_users SET password_hash = ? WHERE username = ?",
        (password_hash, username),
    )
    await conn.commit()


async def any_admin_exists() -> bool:
    conn = get_conn()
    cur = await conn.execute("SELECT 1 FROM admin_users LIMIT 1")
    return (await cur.fetchone()) is not None
