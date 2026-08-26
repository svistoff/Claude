"""Интерфейс адаптера роутера.

Любая реализация должна возвращать RouterPollResult(success=False, ...) при
любой проблеме связи/авторизации/разбора ответа, а не бросать исключение —
это единственное, что нужно от адаптера, чтобы Attendance Service мог
корректно отличить "устройство не в списке" от "список вообще не получен"
(см. ТЗ, разделы 13 и 32 — это принципиальное требование всей системы).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SeenDevice:
    mac: str
    hostname: str | None = None
    ip: str | None = None


@dataclass(frozen=True)
class RouterPollResult:
    success: bool
    devices: list[SeenDevice]
    error: str | None = None


class RouterAdapter(ABC):
    @abstractmethod
    async def get_connected_devices(self) -> RouterPollResult:
        """Возвращает текущий список подключённых устройств.

        Обязана перехватывать любые сетевые/HTTP/парсинг-ошибки внутри себя
        и возвращать RouterPollResult(success=False, error=...) вместо
        исключения.
        """
        raise NotImplementedError

    async def close(self) -> None:
        """Освободить ресурсы (HTTP-клиент и т.п.). По умолчанию — ничего."""
        return None
