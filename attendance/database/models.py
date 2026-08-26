"""Датаклассы для строк БД."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import aiosqlite


@dataclass
class Employee:
    id: int
    name: str
    is_active: bool
    created_at: str
    updated_at: str

    @staticmethod
    def from_row(row: aiosqlite.Row) -> "Employee":
        return Employee(
            id=row["id"],
            name=row["name"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class Device:
    id: int
    employee_id: int
    device_identifier: str
    name: str
    is_active: bool
    created_at: str
    last_seen_at: str | None
    last_seen_hostname: str | None

    @staticmethod
    def from_row(row: aiosqlite.Row) -> "Device":
        return Device(
            id=row["id"],
            employee_id=row["employee_id"],
            device_identifier=row["device_identifier"],
            name=row["name"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
            last_seen_hostname=row["last_seen_hostname"],
        )


@dataclass
class AttendanceSession:
    id: int
    employee_id: int
    started_at: str
    ended_at: str | None
    last_seen_at: str
    status: str  # "active" | "completed"

    @staticmethod
    def from_row(row: aiosqlite.Row) -> "AttendanceSession":
        return AttendanceSession(
            id=row["id"],
            employee_id=row["employee_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            last_seen_at=row["last_seen_at"],
            status=row["status"],
        )


@dataclass
class SystemEvent:
    id: int
    created_at: str
    event_type: str
    message: str
    success: bool
    details: dict[str, Any] | None

    @staticmethod
    def from_row(row: aiosqlite.Row) -> "SystemEvent":
        return SystemEvent(
            id=row["id"],
            created_at=row["created_at"],
            event_type=row["event_type"],
            message=row["message"],
            success=bool(row["success"]),
            details=json.loads(row["details"]) if row["details"] else None,
        )
