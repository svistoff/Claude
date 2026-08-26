"""Проверка эвристики "возможно, у телефона сменился MAC" (см. обсуждение
рандомизации MAC-адресов) — реализована в attendance._check_possible_device_changes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from attendance.database import repository as repo
from attendance.router_adapter.base import RouterPollResult, SeenDevice
from attendance.services import attendance

ABSENCE_TIMEOUT = timedelta(minutes=20)
HINT = timedelta(hours=3)


async def test_hint_logged_when_hostname_reappears_on_new_mac(db, monkeypatch):
    employee_id = await repo.create_employee("Дмитрий")
    await repo.upsert_device(employee_id, "AA:AA:AA:AA:AA:09", "Старый телефон")

    t0 = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t0)
    await attendance.process_poll_result(
        RouterPollResult(
            success=True,
            devices=[SeenDevice(mac="AA:AA:AA:AA:AA:09", hostname="Dmitrys-iPhone")],
        ),
        ABSENCE_TIMEOUT, HINT,
    )

    # Старый MAC пропал на 4 часа (> HINT=3ч), а в сети появился новый MAC с тем же hostname.
    t1 = t0 + timedelta(hours=4)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t1)
    await attendance.process_poll_result(
        RouterPollResult(
            success=True,
            devices=[SeenDevice(mac="BB:BB:BB:BB:BB:10", hostname="Dmitrys-iPhone")],
        ),
        ABSENCE_TIMEOUT, HINT,
    )

    events = await repo.list_recent_events(event_type="possible_device_mac_changed")
    assert len(events) == 1
    assert events[0].details["employee_id"] == employee_id
    assert events[0].details["new_mac"] == "BB:BB:BB:BB:BB:10"


async def test_no_hint_when_hostname_differs(db, monkeypatch):
    employee_id = await repo.create_employee("Елена")
    await repo.upsert_device(employee_id, "AA:AA:AA:AA:AA:11", "Телефон")

    t0 = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t0)
    await attendance.process_poll_result(
        RouterPollResult(
            success=True, devices=[SeenDevice(mac="AA:AA:AA:AA:AA:11", hostname="Elenas-Phone")]
        ),
        ABSENCE_TIMEOUT, HINT,
    )

    t1 = t0 + timedelta(hours=4)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t1)
    await attendance.process_poll_result(
        RouterPollResult(
            success=True, devices=[SeenDevice(mac="CC:CC:CC:CC:CC:12", hostname="Some-Other-Device")]
        ),
        ABSENCE_TIMEOUT, HINT,
    )

    events = await repo.list_recent_events(event_type="possible_device_mac_changed")
    assert len(events) == 0
