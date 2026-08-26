from __future__ import annotations

from attendance.router_adapter.base import RouterAdapter
from attendance.router_adapter.fake import FakeRouterAdapter
from attendance.router_adapter.xiaomi import XiaomiRouterAdapter


def build_router_adapter(
    adapter_name: str, base_url: str, username: str, password: str
) -> RouterAdapter:
    """Фабрика: собирает адаптер по имени из настроек.

    Разделено намеренно — чтобы в будущем добавить другой роутер, не трогая
    ни Device Monitor, ни бизнес-логику посещаемости (см. README, раздел
    "Архитектура").
    """
    if adapter_name == "xiaomi":
        return XiaomiRouterAdapter(base_url=base_url, username=username, password=password)
    if adapter_name == "fake":
        return FakeRouterAdapter()
    raise ValueError(f"Неизвестный тип адаптера роутера: {adapter_name!r}")


__all__ = ["RouterAdapter", "FakeRouterAdapter", "XiaomiRouterAdapter", "build_router_adapter"]
