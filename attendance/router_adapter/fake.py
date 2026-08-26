"""Фейковый адаптер для разработки, тестов и демо без реального роутера."""
from __future__ import annotations

from attendance.router_adapter.base import RouterAdapter, RouterPollResult, SeenDevice


class FakeRouterAdapter(RouterAdapter):
    def __init__(self, devices: list[SeenDevice] | None = None, fail: bool = False) -> None:
        self._devices = devices or []
        self._fail = fail

    def set_devices(self, devices: list[SeenDevice]) -> None:
        self._devices = devices

    def set_fail(self, fail: bool) -> None:
        self._fail = fail

    async def get_connected_devices(self) -> RouterPollResult:
        if self._fail:
            return RouterPollResult(success=False, devices=[], error="fake: имитация сбоя связи")
        return RouterPollResult(success=True, devices=list(self._devices))
