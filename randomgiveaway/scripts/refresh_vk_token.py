"""Периодическое продление пользовательского токена VK через refresh_token
(VK ID, id.vk.ru — токен короткоживущий, в отличие от старого scope=offline).

Запускать через cron (НЕ через Supervisor — это разовая периодическая
задача, а не долгоживущий процесс, поэтому Supervisor тут не подходит по
смыслу, в отличие от самого API-сервиса).

Пример crontab (раз в час — токен VK ID живёт заметно меньше суток):

    0 * * * * cd /root/random-giveaway && venv/bin/python -m randomgiveaway.scripts.refresh_vk_token >> /var/log/random-giveaway-vk-token-refresh.log 2>&1

Добавить: crontab -e (под пользователем root, как и весь остальной деплой).
"""
from __future__ import annotations

import asyncio
import subprocess
import sys

from randomgiveaway.config import ENV_PATH, config
from randomgiveaway.env_file import set_env_var
from randomgiveaway.services import vk_oauth


async def main() -> int:
    if not (config.vk_refresh_token and config.vk_app_id and config.vk_device_id):
        print(
            "VK_REFRESH_TOKEN / VK_APP_ID / VK_DEVICE_ID не заданы — нечего обновлять. "
            "Сначала пройдите /api/vk/oauth/start."
        )
        return 1

    try:
        token, expires_in, refresh_token = await vk_oauth.refresh_access_token(
            config.vk_refresh_token, config.vk_app_id, config.vk_device_id
        )
    except vk_oauth.VKOAuthError as exc:
        print(f"Не удалось обновить токен: {exc}", file=sys.stderr)
        return 1

    set_env_var(ENV_PATH, "VK_ACCESS_TOKEN", token)
    if refresh_token:
        set_env_var(ENV_PATH, "VK_REFRESH_TOKEN", refresh_token)
    lifetime_note = f"~{expires_in // 60} минут" if expires_in else "не указан VK"
    print(f"Токен обновлён, действителен ещё {lifetime_note}")

    restart = subprocess.run(
        ["supervisorctl", "restart", "random-giveaway-api"], capture_output=True, text=True
    )
    if restart.returncode != 0:
        print(f"Токен сохранён, но не удалось перезапустить сервис: {restart.stderr}", file=sys.stderr)
        return 1
    print("Сервис перезапущен с новым токеном")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
