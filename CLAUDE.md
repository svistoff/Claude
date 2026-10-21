# Инструкции для Claude Code в этом репозитории (ветка claude/mentor-bot)

Это отдельный проект — «Мой наставник», личный организатор рабочего дня в Telegram.
Описание и команды — в `README.md`, планы развития — в `HANDOFF.md`.
Не путать с ботом «Лиза» (`companion_bot`, ветка `claude/ecstatic-bell-l0zxs5`) — это другой проект.

## Деплой

На VPS (`root@45.146.90.128`, хост `magic-copper`) боты запускаются через
**Supervisor**, не через systemd:

- конфиг — `deploy/supervisor/mentor-bot.conf`, копируется в `/etc/supervisor/conf.d/`;
- код живёт в `/root/mentor-bot`;
- логи — `/var/log/mentor-bot.out.log` / `.err.log`;
- после изменений: `git pull && supervisorctl restart mentor-bot`.

## Правила

- Секреты только в `.env` (в git не коммитится).
- Бот только советует: не меняет файлы проектов, папки читает для контекста.
- Перед коммитом: `venv/bin/python -m pytest -q`.
