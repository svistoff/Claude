# Инструкции для Claude Code в этом репозитории

## Деплой ботов на VPS

Все боты на этом VPS (`root@77.110.125.73`, хост `magic-copper`) запускаются
через **Supervisor**, не через systemd. При добавлении нового бота или
изменении деплоя:

- Конфиг Supervisor кладётся в `deploy/supervisor/<имя-бота>.conf` в
  репозитории и копируется на сервер в `/etc/supervisor/conf.d/`.
- Все боты живут в `/root/<имя-папки-бота>` (не в `/opt/...`), т.к. всё
  администрируется под пользователем root.
- Логи — через `stdout_logfile`/`stderr_logfile` в `/var/log/<имя-бота>.out.log`
  и `.err.log`, не через journald.
- После изменения конфига: `supervisorctl reread && supervisorctl update`,
  дальше `supervisorctl start/restart/status <имя программы>`.
- Не предлагать systemd как основной вариант — только Supervisor. Unit-файл
  для systemd можно оставить в репозитории как fallback-документацию, но не
  как рекомендуемый путь.

## Текущий бот в этом репозитории

`bot/` — Telegram-бот на aiogram 3: принимает пересланные посты, переписывает
текст через OpenAI по промту из `/prompt`, публикует с оригинальными
вложениями в целевой канал. Подробности — в `README.md`.
