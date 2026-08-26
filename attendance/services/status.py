"""Вычисление статуса сотрудника для дашборда/карточки (ТЗ раздел 15).

Статус ⚠️ "Нет данных" — это глобальный баннер про связь с роутером
(ТЗ п.13: "17:00 — последний успешный запрос ... Нет связи с роутером"), а
не персональный статус сотрудника: пока связи нет, каждый сотрудник
продолжает показывать своё последнее достоверно известное состояние
(🟢/🔴/⚪), и это принципиально — иначе выключение роутера на минуту красило
бы всю панель в "нет данных" и создавало ложное впечатление, будто данные
потеряны, хотя они просто не обновлялись последние секунды.
"""
from __future__ import annotations

from dataclasses import dataclass

from attendance.database.models import AttendanceSession, Device, Employee

STATUS_ON_WORK = "on_work"
STATUS_LEFT = "left"
STATUS_NOT_ARRIVED = "not_arrived"

STATUS_LABELS = {
    STATUS_ON_WORK: "🟢 На работе",
    STATUS_LEFT: "🔴 Ушёл",
    STATUS_NOT_ARRIVED: "⚪ Не приходил",
}


@dataclass(frozen=True)
class EmployeeStatus:
    employee: Employee
    device: Device | None
    status: str
    arrived_at: str | None
    left_at: str | None
    last_seen_at: str | None

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]


def compute_status(
    employee: Employee, device: Device | None, latest_session: AttendanceSession | None
) -> EmployeeStatus:
    if latest_session is None:
        return EmployeeStatus(employee, device, STATUS_NOT_ARRIVED, None, None, None)
    if latest_session.status == "active":
        return EmployeeStatus(
            employee, device, STATUS_ON_WORK,
            arrived_at=latest_session.started_at,
            left_at=None,
            last_seen_at=latest_session.last_seen_at,
        )
    return EmployeeStatus(
        employee, device, STATUS_LEFT,
        arrived_at=latest_session.started_at,
        left_at=latest_session.ended_at,
        last_seen_at=latest_session.last_seen_at,
    )
