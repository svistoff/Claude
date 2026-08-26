"""Настройки приложения: живут в app_settings, при первом запуске
засеваются значениями по умолчанию из .env (см. config.py) — дальше
редактируются через веб-панель без передеплоя, как того требует ТЗ (п.27)."""
from __future__ import annotations

from dataclasses import dataclass

from attendance.config import config
from attendance.database import repository as repo

_KEYS = {
    "poll_interval_seconds": str(config.default_poll_interval_seconds),
    "absence_timeout_minutes": str(config.default_absence_timeout_minutes),
    "long_absence_hint_hours": str(config.default_long_absence_hint_hours),
    "router_adapter": config.default_router_adapter,
    "router_base_url": config.default_router_base_url,
    "router_username": config.default_router_username,
    "router_password": config.default_router_password,
    "timezone": config.default_timezone,
}


async def seed_defaults() -> None:
    for key, value in _KEYS.items():
        await repo.set_setting_if_absent(key, value)


@dataclass(frozen=True)
class RuntimeSettings:
    poll_interval_seconds: int
    absence_timeout_minutes: int
    long_absence_hint_hours: int
    router_adapter: str
    router_base_url: str
    router_username: str
    router_password: str
    timezone: str


async def get_settings() -> RuntimeSettings:
    values = {}
    for key, default in _KEYS.items():
        values[key] = await repo.get_setting(key)
        if values[key] is None:
            values[key] = default
    return RuntimeSettings(
        poll_interval_seconds=int(values["poll_interval_seconds"]),
        absence_timeout_minutes=int(values["absence_timeout_minutes"]),
        long_absence_hint_hours=int(values["long_absence_hint_hours"]),
        router_adapter=values["router_adapter"],
        router_base_url=values["router_base_url"],
        router_username=values["router_username"],
        router_password=values["router_password"],
        timezone=values["timezone"],
    )


async def update_settings(
    *,
    poll_interval_seconds: int,
    absence_timeout_minutes: int,
    long_absence_hint_hours: int,
    router_adapter: str,
    router_base_url: str,
    router_username: str,
    router_password: str | None,
    timezone: str,
) -> None:
    await repo.set_setting("poll_interval_seconds", str(poll_interval_seconds))
    await repo.set_setting("absence_timeout_minutes", str(absence_timeout_minutes))
    await repo.set_setting("long_absence_hint_hours", str(long_absence_hint_hours))
    await repo.set_setting("router_adapter", router_adapter)
    await repo.set_setting("router_base_url", router_base_url)
    await repo.set_setting("router_username", router_username)
    # Пароль обновляем только если реально ввели новый — поле в форме write-only.
    if router_password:
        await repo.set_setting("router_password", router_password)
    await repo.set_setting("timezone", timezone)
