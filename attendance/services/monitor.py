"""Device Monitor — фоновый цикл опроса роутера (ТЗ раздел 9-10)."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from attendance.router_adapter import build_router_adapter
from attendance.services import attendance, settings_service

logger = logging.getLogger(__name__)


async def run_monitor(stop_event: asyncio.Event) -> None:
    logger.info("Device Monitor запущен")
    while not stop_event.is_set():
        settings = await settings_service.get_settings()
        adapter = build_router_adapter(
            settings.router_adapter,
            settings.router_base_url,
            settings.router_username,
            settings.router_password,
        )
        try:
            logger.debug("Router check started")
            result = await adapter.get_connected_devices()
            await attendance.process_poll_result(
                result,
                absence_timeout=timedelta(minutes=settings.absence_timeout_minutes),
                long_absence_hint=timedelta(hours=settings.long_absence_hint_hours),
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — цикл не должен падать целиком
            logger.exception("Непредвиденная ошибка в цикле Device Monitor")
        finally:
            await adapter.close()

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.poll_interval_seconds)
        except asyncio.TimeoutError:
            pass
    logger.info("Device Monitor остановлен")
