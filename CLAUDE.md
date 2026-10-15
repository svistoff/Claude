# Инструкции для Claude Code в этом репозитории

## Деплой ботов на VPS

Все боты на этом VPS (`root@45.146.90.128`, хост `magic-copper`) запускаются
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

## Автодеплой (GitHub → VPS)

На VPS под Supervisor крутится `autodeploy` (`deploy/autodeploy/autodeploy.sh`,
конфиг `deploy/supervisor/autodeploy.conf`): раз в минуту делает fast-forward
`git pull` в `/root/afisha-news-bot` (ветка `claude/news-bot`) и
`/root/claude-repo`; если в news-bot менялся код бота (не `site/`) — rsync в
`/root/news-bot`, `pip install`, `supervisorctl restart news-bot news-media-proxy`.
Лог — `/var/log/autodeploy.out.log`. Изменения попадают на сайт/бот в течение
минуты после того, как оказались в `claude/news-bot`. Для виджета Tilda
(`news-embed.js`) по-прежнему нужно поднять `?v=` в коде на Tilda.

Установка на VPS (один раз):
```bash
cd /root/afisha-news-bot && git pull --ff-only
mkdir -p /root/autodeploy && cp deploy/autodeploy/autodeploy.sh /root/autodeploy/ && chmod +x /root/autodeploy/autodeploy.sh
cp deploy/supervisor/autodeploy.conf /etc/supervisor/conf.d/ && supervisorctl reread && supervisorctl update
```

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
  (`afisha.ekb-guide.ru`): `admin.html`, `index.html`, `embed.js`,
  `submit.html`, `event.php`, `sb-config.php`. Отдаёт их nginx на VPS прямо из
  клона репозитория (`root /root/claude-repo/afisha-site`), обновление —
  `cd /root/claude-repo && git pull`. Файловый архив Timeweb для сайта не
  используется. Подробности — в `afisha-site/README.md`.
- `news-bot/` — news-bot (@EG_newsbot): Telegram-бот на aiogram 3, принимает
  пересланные новости из «На выкладку», делит на заголовок (жирный) /
  описание (курсив) / текст (AI — запасной путь), копирует фото/видео в тот же
  канал-хранилище, что и афиша, и сразу публикует в Supabase (`news`,
  `news_media`). Медиа браузеру отдаёт прокси `video.ekb-guide.ru/m/<token>`
  (порт 8093). Сайт `news.ekb-guide.ru` и виджет для Tilda (`news-embed.js`)
  лежат в `news-bot/site/`; nginx отдаёт их из **отдельного клона**
  `/root/afisha-news-bot` (ветка `claude/news-bot`), не из `/root/claude-repo`.
  Подробности — в `news-bot/README.md`.
