# afisha-bot — Telegram-бот-публикатор афиши + видео-хранилище

Принимает пересланные анонсы (текст/фото/альбом/видео), через OpenAI извлекает
структурированные поля (заголовок, дата/время, площадка, цена и т.д.),
заливает медиа и кладёт заявку в `event_submissions` (`status='pending'`)
афиши `afisha.ekb-guide.ru`. Дальше пользователь вручную проверяет/правит
заявку и публикует её через кнопку «Опубликовать» в существующей админке
афиши (`afisha-site/admin.html`).

Полное техническое задание, из которого собран проект (три компонента —
A: бот, B: видео-хранилище, C: правки в самой афише) хранится в истории
задачи/PR; ключевые решения продублированы ниже.

## Компоненты

- **Бот** (`bot/`) — приём форвардов, буферизация альбомов по `media_group_id`
  (как в `../bot/services/albums.py`, но без персистентной очереди — заявка
  обрабатывается сразу и не переживает падение процесса между приёмом и
  ответом), AI-разбор (`bot/services/ai.py`), заливка медиа и запись заявки
  (`bot/services/pipeline.py`). При массовой пересылке анонсов пачкой число
  одновременно обрабатываемых заявок ограничено `MAX_CONCURRENT_SUBMISSIONS`
  (по умолчанию 3, семафор в `bot/services/albums.py`) — лишние просто ждут
  своей очереди в памяти процесса, это защита от антифлуда Telegram на канале-
  хранилище и всплеска запросов к OpenAI, а не персистентная очередь.
- **Видео-хранилище** — видео ≤20 МБ пересылается (без скачивания и
  перезаливки, по `file_id`) в приватный Telegram-канал-хранилище
  (`bot/services/video_storage.py`), доступ наружу — через HTTP-прокси с
  поддержкой Range (`bot/proxy/server.py`, слушает `127.0.0.1:8092`, наружу
  через nginx `video.ekb-guide.ru`). Видео крупнее 20 МБ **не публикуется
  вообще** — жёсткий лимит, заявка создаётся без видео с пометкой в ответе бота.
- **Крон-очистка** (`bot/cron_cleanup.py`) — раз в сутки удаляет видео из
  канала-хранилища после прошедшего события (`event_date < today - 3 дня`)
  либо по запасному TTL (30 дней), если дата не распозналась. Запись в
  `event_videos` не удаляется физически — только `deleted=true`.

## `.env`

```bash
cp .env.example .env
nano .env
```

Обязательно заполнить: `TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_ID`,
`TELEGRAM_STORAGE_CHANNEL_ID` (id приватного канала-хранилища, бот должен
быть там админом), `OPENAI_API_KEY`, `SUPABASE_SERVICE_KEY` (service_role —
**никогда** не попадает в git/клиентские файлы/логи).

`.env` читается напрямую по абсолютному пути рядом с `bot/config.py` — как в
`repost-bot`, прокидывать переменные через `environment=` в Supervisor не нужно.

## SQL (выполнить в Supabase перед первым запуском)

```bash
psql ... < sql/event_videos.sql
psql ... < sql/venues_logo.sql
```

(или вставить содержимое в SQL Editor Supabase вручную). `event_videos` — RLS
включён, политик для `anon` нет — доступ только через `service_role` (бот/
прокси/крон).

## Первый запуск (интерактивно)

```bash
cd /root/afisha-bot   # или любой другой путь
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env

python -m bot.bot                 # сам бот (long polling)
python -m bot.proxy.server        # видео-прокси, отдельным процессом
```

Перешлите боту тестовый анонс с датой/временем и фото — заявка должна
появиться в «Предложенное» афиши.

## Деплой на VPS через Supervisor

```bash
sudo cp deploy/supervisor/afisha-bot.conf /etc/supervisor/conf.d/
sudo cp deploy/supervisor/afisha-video-proxy.conf /etc/supervisor/conf.d/
sudo supervisorctl reread && sudo supervisorctl update
sudo supervisorctl start afisha-bot afisha-video-proxy
sudo supervisorctl status afisha-bot afisha-video-proxy

tail -f /var/log/afisha-bot.out.log /var/log/afisha-bot.err.log
tail -f /var/log/afisha-video-proxy.out.log /var/log/afisha-video-proxy.err.log
```

Оба конфига предполагают, что код лежит в `/root/afisha-bot` (директория —
содержимое этой папки репозитория, `venv/` создаётся прямо внутри неё), как и
остальные боты на этом VPS (см. `../CLAUDE.md`).

### nginx + видео-прокси

```bash
sudo cp deploy/nginx/video.ekb-guide.ru.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/video.ekb-guide.ru.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Перед этим — вручную: DNS `A video.ekb-guide.ru → 77.110.125.73`, сертификат
`certbot --nginx -d video.ekb-guide.ru`.

### Крон-очистка видео

```cron
0 5 * * *  /root/afisha-bot/venv/bin/python -m bot.cron_cleanup >> /var/log/afisha-cleanup.log 2>&1
```

## Известные ограничения (заложены сознательно, см. ТЗ)

- Видео >20 МБ не публикуется вообще — локальный Bot API сервер ради обхода
  этого лимита не поднимаем.
- Если дата события в `event_submissions`/`events` сдвигается пользователем
  вручную сильно вперёд при публикации, `event_date` в `event_videos`
  остаётся от AI-разбора — видео может удалиться раньше «нового» события.
  Редкий кейс, синхронизация с таблицей `events` в этой фазе не делается —
  при необходимости видео перезаливается вручную.
- `venue_id`/`category_id` заявка не проставляет — назначаются вручную при
  публикации в админке.
- Автоматический матчинг заведений и автопубликация в обход модерации — не
  делаются намеренно, всё идёт в «Предложенное» на ручную проверку.
