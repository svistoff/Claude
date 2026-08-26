"""Тесты ядра посещаемости — сценарии из ТЗ, раздел 33 (тесты 1-7).

Роутер не нужен: всё крутится вокруг FakeRouterAdapter и прямых вызовов
attendance.process_poll_result с управляемым временем.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from attendance.database import repository as repo
from attendance.router_adapter.base import RouterPollResult, SeenDevice
from attendance.services import attendance

ABSENCE_TIMEOUT = timedelta(minutes=20)
HINT = timedelta(hours=3)


async def _make_employee_with_device(name: str, mac: str) -> int:
    employee_id = await repo.create_employee(name)
    await repo.upsert_device(employee_id, mac, f"{name}'s phone")
    return employee_id


async def test_arrival_creates_active_session(db):
    employee_id = await _make_employee_with_device("Иван", "AA:AA:AA:AA:AA:01")

    result = RouterPollResult(success=True, devices=[SeenDevice(mac="AA:AA:AA:AA:AA:01")])
    await attendance.process_poll_result(result, ABSENCE_TIMEOUT, HINT)

    session = await repo.get_active_session(employee_id)
    assert session is not None
    assert session.status == "active"


async def test_short_disconnect_does_not_close_session(db):
    employee_id = await _make_employee_with_device("Анна", "AA:AA:AA:AA:AA:02")
    seen = RouterPollResult(success=True, devices=[SeenDevice(mac="AA:AA:AA:AA:AA:02")])
    await attendance.process_poll_result(seen, ABSENCE_TIMEOUT, HINT)

    # Телефон пропал из списка, но 5 минут ещё не прошло — сессия должна остаться активной.
    missing = RouterPollResult(success=True, devices=[])
    await attendance.process_poll_result(missing, ABSENCE_TIMEOUT, HINT)

    session = await repo.get_active_session(employee_id)
    assert session is not None
    assert session.status == "active"


async def test_absence_over_20_minutes_closes_session(db, monkeypatch):
    employee_id = await _make_employee_with_device("Сергей", "AA:AA:AA:AA:AA:03")

    t0 = datetime(2026, 8, 26, 18, 3, tzinfo=timezone.utc)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t0)
    seen = RouterPollResult(success=True, devices=[SeenDevice(mac="AA:AA:AA:AA:AA:03")])
    await attendance.process_poll_result(seen, ABSENCE_TIMEOUT, HINT)

    t1 = t0 + timedelta(minutes=25)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t1)
    missing = RouterPollResult(success=True, devices=[])
    await attendance.process_poll_result(missing, ABSENCE_TIMEOUT, HINT)

    session = await repo.get_latest_session(employee_id)
    assert session.status == "completed"
    assert session.ended_at == (t0 + ABSENCE_TIMEOUT).isoformat()


async def test_return_after_departure_creates_new_session(db, monkeypatch):
    employee_id = await _make_employee_with_device("Ольга", "AA:AA:AA:AA:AA:04")

    t0 = datetime(2026, 8, 26, 9, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t0)
    await attendance.process_poll_result(
        RouterPollResult(success=True, devices=[SeenDevice(mac="AA:AA:AA:AA:AA:04")]),
        ABSENCE_TIMEOUT, HINT,
    )

    t1 = t0 + timedelta(hours=4)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t1)
    await attendance.process_poll_result(
        RouterPollResult(success=True, devices=[]), ABSENCE_TIMEOUT, HINT
    )

    first_session = await repo.get_latest_session(employee_id)
    assert first_session.status == "completed"

    t2 = t1 + timedelta(hours=1)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t2)
    await attendance.process_poll_result(
        RouterPollResult(success=True, devices=[SeenDevice(mac="AA:AA:AA:AA:AA:04")]),
        ABSENCE_TIMEOUT, HINT,
    )

    sessions = await repo.list_sessions_for_employee(employee_id)
    assert len(sessions) == 2
    assert sessions[0].status == "active"


async def test_employee_never_seen_has_no_session(db):
    employee_id = await _make_employee_with_device("Пётр", "AA:AA:AA:AA:AA:05")
    await attendance.process_poll_result(
        RouterPollResult(success=True, devices=[]), ABSENCE_TIMEOUT, HINT
    )
    assert await repo.get_latest_session(employee_id) is None


async def test_router_failure_does_not_close_active_session(db, monkeypatch):
    employee_id = await _make_employee_with_device("Мария", "AA:AA:AA:AA:AA:06")

    t0 = datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t0)
    await attendance.process_poll_result(
        RouterPollResult(success=True, devices=[SeenDevice(mac="AA:AA:AA:AA:AA:06")]),
        ABSENCE_TIMEOUT, HINT,
    )

    # Роутер недоступен 30 минут подряд — несколько неудачных опросов.
    for minutes in (5, 10, 15, 20, 25, 30):
        t = t0 + timedelta(minutes=minutes)
        monkeypatch.setattr(attendance, "_utcnow", lambda t=t: t)
        await attendance.process_poll_result(
            RouterPollResult(success=False, devices=[], error="таймаут"), ABSENCE_TIMEOUT, HINT
        )

    session = await repo.get_active_session(employee_id)
    assert session is not None, "сотрудник не должен автоматически получить статус «ушёл»"
    assert session.status == "active"
    assert await repo.is_router_currently_unreachable() is True


async def test_laptop_left_behind_is_ignored(db, monkeypatch):
    """Тест 8 из ТЗ: незарегистрированное устройство (ноутбук) не влияет на учёт."""
    employee_id = await _make_employee_with_device("Игорь", "AA:AA:AA:AA:AA:07")

    t0 = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t0)
    await attendance.process_poll_result(
        RouterPollResult(
            success=True,
            devices=[SeenDevice(mac="AA:AA:AA:AA:AA:07"), SeenDevice(mac="BB:BB:BB:BB:BB:BB")],
        ),
        ABSENCE_TIMEOUT, HINT,
    )

    # Телефон ушёл, ноутбук (незарегистрированный) остался в сети.
    t1 = t0 + timedelta(minutes=25)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t1)
    await attendance.process_poll_result(
        RouterPollResult(success=True, devices=[SeenDevice(mac="BB:BB:BB:BB:BB:BB")]),
        ABSENCE_TIMEOUT, HINT,
    )

    session = await repo.get_latest_session(employee_id)
    assert session.status == "completed"


async def test_recover_on_startup_closes_stale_active_session(db, monkeypatch):
    employee_id = await _make_employee_with_device("Наталья", "AA:AA:AA:AA:AA:08")

    t0 = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t0)
    await attendance.process_poll_result(
        RouterPollResult(success=True, devices=[SeenDevice(mac="AA:AA:AA:AA:AA:08")]),
        ABSENCE_TIMEOUT, HINT,
    )

    # Сервис "лежал" 2 часа — при старте зависшая активная сессия должна закрыться.
    t1 = t0 + timedelta(hours=2)
    monkeypatch.setattr(attendance, "_utcnow", lambda: t1)
    await attendance.recover_on_startup(ABSENCE_TIMEOUT)

    session = await repo.get_latest_session(employee_id)
    assert session.status == "completed"
    assert session.ended_at == (t0 + ABSENCE_TIMEOUT).isoformat()
