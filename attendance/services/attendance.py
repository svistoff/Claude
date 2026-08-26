"""Ядро определения присутствия — ТЗ разделы 10-13, 32.

Два принципиально разных исхода опроса роутера:
  - success=True  -> список получен корректно, отсутствие в нём означает
                      реальное отсутствие устройства, таймаут применим.
  - success=False -> список НЕ получен вообще, отсутствие устройства в
                      (несуществующем) списке НИЧЕГО не доказывает — никого
                      нельзя автоматически отмечать ушедшим.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from attendance.database import repository as repo
from attendance.router_adapter.base import RouterPollResult

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def process_poll_result(
    result: RouterPollResult, absence_timeout: timedelta, long_absence_hint: timedelta
) -> None:
    if not result.success:
        await repo.log_event(
            "router_poll_failed",
            f"Не удалось получить список устройств от роутера: {result.error}",
            success=False,
        )
        logger.warning("Опрос роутера не удался: %s", result.error)
        return

    now = _utcnow()
    seen_by_mac = {d.mac.upper(): d for d in result.devices}
    await repo.log_event(
        "router_poll_ok",
        f"Опрос роутера успешен, устройств в сети: {len(seen_by_mac)}",
        success=True,
    )

    registered = await repo.get_active_devices_with_employees()

    for device in registered:
        seen = seen_by_mac.get(device.device_identifier.upper())
        if seen is not None:
            await repo.touch_device_seen(device.id, now, seen.hostname)
            active_session = await repo.get_active_session(device.employee_id)
            if active_session is None:
                await repo.create_session(device.employee_id, now)
                await repo.log_event(
                    "employee_arrived",
                    f"Обнаружен телефон сотрудника (employee_id={device.employee_id}) — отмечен приход",
                    success=True,
                    details={"employee_id": device.employee_id},
                )
                logger.info("Employee %s marked as present", device.employee_id)
            else:
                await repo.update_session_last_seen(active_session.id, now)
            continue

        # Устройство не найдено в корректно полученном списке.
        active_session = await repo.get_active_session(device.employee_id)
        if active_session is None:
            continue  # сотрудник и так не считается присутствующим

        last_seen = _parse(active_session.last_seen_at)
        elapsed = now - last_seen
        if elapsed < absence_timeout:
            continue  # кратковременное отключение — сессию не закрываем (ТЗ п.11)

        ended_at = last_seen + absence_timeout
        await repo.close_session(active_session.id, ended_at)
        await repo.log_event(
            "employee_departed",
            f"Телефон сотрудника (employee_id={device.employee_id}) отсутствует "
            f">= {int(absence_timeout.total_seconds() // 60)} мин — отмечен уход",
            success=True,
            details={"employee_id": device.employee_id, "ended_at": ended_at.isoformat()},
        )
        logger.info("Employee %s marked as absent (ended_at=%s)", device.employee_id, ended_at)

    await _check_possible_device_changes(seen_by_mac, registered, now, long_absence_hint)


async def _check_possible_device_changes(seen_by_mac, registered, now, hint_after: timedelta) -> None:
    """Секундарная эвристика: если долго не видно зарегистрированного телефона,
    а в сети появилось незарегистрированное устройство с тем же hostname,
    что и раньше отдавал этот телефон — вероятно, у него сменился MAC
    (рандомизация адреса). Подсказка для администратора, не автодействие."""
    registered_macs = {d.device_identifier.upper() for d in registered}
    unregistered_seen = {mac: dev for mac, dev in seen_by_mac.items() if mac not in registered_macs}
    if not unregistered_seen:
        return

    for device in registered:
        if device.device_identifier.upper() in seen_by_mac:
            continue
        if not device.last_seen_hostname or not device.last_seen_at:
            continue
        last_seen = _parse(device.last_seen_at)
        if now - last_seen < hint_after:
            continue
        for mac, seen in unregistered_seen.items():
            if seen.hostname and seen.hostname == device.last_seen_hostname:
                if await repo.recent_similar_event_exists(
                    "possible_device_mac_changed", device.employee_id, hours=6
                ):
                    continue
                await repo.log_event(
                    "possible_device_mac_changed",
                    f"Устройство сотрудника (employee_id={device.employee_id}) не отвечает уже "
                    f"{int(hint_after.total_seconds() // 3600)}+ ч, но в сети появилось новое "
                    f"устройство с тем же именем '{seen.hostname}' (MAC {mac}). Возможно, у телефона "
                    f"сменился MAC-адрес — проверьте и при необходимости перепривяжите устройство.",
                    success=False,
                    details={
                        "employee_id": device.employee_id,
                        "old_mac": device.device_identifier,
                        "new_mac": mac,
                        "hostname": seen.hostname,
                    },
                )
                logger.info(
                    "Possible MAC change hint for employee %s: %s -> %s",
                    device.employee_id, device.device_identifier, mac,
                )


async def recover_on_startup(absence_timeout: timedelta) -> None:
    """При старте сервиса закрывает 'зависшие' активные сессии, которые уже
    должны были закрыться по таймауту, пока сервис был выключен (ТЗ п.30)."""
    now = _utcnow()
    active_sessions = await repo.list_all_active_sessions()
    closed = 0
    for session in active_sessions:
        last_seen = _parse(session.last_seen_at)
        if now - last_seen >= absence_timeout:
            ended_at = last_seen + absence_timeout
            await repo.close_session(session.id, ended_at)
            await repo.log_event(
                "employee_departed",
                f"Сессия сотрудника (employee_id={session.employee_id}) закрыта при "
                f"восстановлении после перезапуска (последний раз виден {session.last_seen_at})",
                success=True,
                details={"employee_id": session.employee_id, "ended_at": ended_at.isoformat()},
            )
            closed += 1
    if closed:
        logger.info("При старте закрыто зависших активных сессий: %s", closed)
    await repo.log_event("service_started", "Сервис учёта посещаемости запущен", success=True)
