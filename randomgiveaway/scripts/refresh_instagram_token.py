"""Периодическое продление long-lived Instagram-токена.

Запускать через cron (НЕ через Supervisor — это разовая периодическая
задача, а не долгоживущий процесс, поэтому Supervisor тут не подходит по
смыслу, в отличие от самого API-сервиса).

Пример crontab (раз в сутки в 4:00 — токен живёт ~60 дней, суточный запас
более чем достаточен):

    0 4 * * * cd /root/random-giveaway && venv/bin/python -m randomgiveaway.scripts.refresh_instagram_token >> /var/log/random-giveaway-token-refresh.log 2>&1

Добавить: crontab -e (под пользователем root, как и весь остальной деплой).
"""
from __future__ import annotations

import asyncio
import subprocess
import sys

from randomgiveaway.config import ENV_PATH, config
from randomgiveaway.env_file import set_env_var
from randomgiveaway.services import instagram_oauth


async def main() -> int:
    if not config.instagram_access_token:
        print(
            "INSTAGRAM_ACCESS_TOKEN не задан — нечего обновлять. "
            "Сначала пройдите /api/instagram/oauth/start."
        )
        return 1

    try:
        token, expires_in = await instagram_oauth.refresh_long_lived_token(config.instagram_access_token)
    except instagram_oauth.InstagramOAuthError as exc:
        print(f"Не удалось обновить токен: {exc}", file=sys.stderr)
        return 1

    set_env_var(ENV_PATH, "INSTAGRAM_ACCESS_TOKEN", token)
    print(f"Токен обновлён, действителен ещё ~{expires_in // 86400} дней")

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
