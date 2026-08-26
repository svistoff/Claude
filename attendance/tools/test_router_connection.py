"""Автономная CLI-проверка подключения к роутеру — без веб-панели и без БД.

Именно этот скрипт нужно запустить первым делом, когда появится физический
доступ к роутеру Xiaomi AX3000T/RD23:

    cd attendance
    source venv/bin/activate   # или как у вас называется окружение
    python -m attendance.tools.test_router_connection --url http://192.168.31.1 \\
        --username admin --password '<реальный пароль роутера>'

Скрипт печатает необработанный список устройств от роутера. Если что-то
не совпадает с ожиданиями (нет поля 'list', другой формат stok, 403 на
логине и т.п.) — правьте только attendance/router_adapter/xiaomi.py,
остальной сервис не завязан на детали конкретного API роутера.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from attendance.router_adapter.xiaomi import XiaomiRouterAdapter


async def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка подключения к Xiaomi-роутеру")
    parser.add_argument("--url", default="http://192.168.31.1", help="Адрес роутера")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    adapter = XiaomiRouterAdapter(base_url=args.url, username=args.username, password=args.password)
    try:
        result = await adapter.get_connected_devices()
    finally:
        await adapter.close()

    if not result.success:
        print(f"ОШИБКА: {result.error}")
        raise SystemExit(1)

    print(f"Успешно. Устройств в сети: {len(result.devices)}\n")
    for d in result.devices:
        print(json.dumps({"mac": d.mac, "hostname": d.hostname, "ip": d.ip}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
