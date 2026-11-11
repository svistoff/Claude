"""Периодическое продление long-lived токенов всех подключённых по ссылке
/api/instagram/connect/start Instagram-аккаунтов (механика "отметил нас на
фото" — см. services/instagram_tags.py). Отдельно от
refresh_instagram_token.py, который продлевает только собственный токен
ekb_guide в .env — здесь токены хранятся в БД (instagram_connected_accounts),
их может быть несколько.

Запускать через cron (НЕ через Supervisor — разовая периодическая задача).
В отличие от refresh_instagram_token.py, перезапуск сервиса не нужен:
токены читаются из БД при каждом обращении, а не кешируются в памяти при
старте процесса.

Пример crontab (раз в сутки):

    30 4 * * * cd /root/random-giveaway && venv/bin/python -m randomgiveaway.scripts.refresh_instagram_connected_accounts >> /var/log/random-giveaway-connected-accounts-refresh.log 2>&1
"""
from __future__ import annotations

import asyncio
import sys

from randomgiveaway.database.database import close_db, init_db
from randomgiveaway.services import instagram_accounts
from randomgiveaway.services import instagram_oauth


async def main() -> int:
    await init_db()
    try:
        accounts = await instagram_accounts.list_accounts()
        if not accounts:
            print("Нет подключённых аккаунтов — нечего обновлять.")
            return 0

        had_errors = False
        for account in accounts:
            try:
                token, expires_in = await instagram_oauth.refresh_long_lived_token(account.access_token)
            except instagram_oauth.InstagramOAuthError as exc:
                print(f"@{account.username}: не удалось обновить токен: {exc}", file=sys.stderr)
                had_errors = True
                continue
            await instagram_accounts.update_token(account.ig_user_id, token)
            print(f"@{account.username}: токен обновлён, действителен ещё ~{expires_in // 86400} дней")
        return 1 if had_errors else 0
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
