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

## Боты и проекты в этом репозитории

Монорепо: каждый бот/проект — отдельная папка в корне со своим `requirements.txt`
и своим venv на сервере (в `/root/<имя-папки>`), деплоятся независимо друг от
друга через Supervisor (см. выше).

- `bot/` — repost-bot: Telegram-бот на aiogram 3, принимает пересланные посты,
  переписывает текст через OpenAI по промту из `/prompt`, публикует с
  оригинальными вложениями в канал "На выкладку". Подробности — в `README.md`.
- `afisha-bot/` — afisha-bot: Telegram-бот на aiogram 3, принимает пересланные
  анонсы, AI извлекает структуру (дата/время/площадка/цена и т.д.), заливает
  медиа в Supabase Storage (видео — через собственное хранилище на приватном
  Telegram-канале с HTTP-прокси `video.ekb-guide.ru`), кладёт заявку в
  `event_submissions` афиши. Подробности — в `afisha-bot/README.md`.
- `afisha-site/` — не бот, а статические файлы фронтенда афиши
  (`afisha.ekb-guide.ru`, хостится на Timeweb, вне VPS): `admin.html`,
  `index.html`, `embed.js`, `event.php`, `sb-config.php`. Правки заливаются на
  Timeweb вручную, Supervisor их не касается. Подробности — в
  `afisha-site/README.md`.
