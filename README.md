# Telegram repost-бот (aiogram 3 + OpenAI)

Принимает пересланные посты, переписывает текст через AI по заданному промту
и публикует результат в канал "На выкладку", сохраняя вложения без изменений.

## Как это устроено

- **Очередь** — таблица `jobs` в SQLite, строго FIFO, переживает рестарт бота.
  Статусы: `RECEIVED → QUEUED → PROCESSING → AI_DONE → PUBLISHED`, либо
  `ERROR` / `WAITING_RETRY` при ошибках.
- **Альбомы** — части одного `media_group_id` буферизуются в памяти
  (`bot/services/albums.py`) в течение `ALBUM_WINDOW_SECONDS` (таймер
  сбрасывается на каждый новый элемент), затем всё задание разом уходит в
  очередь и публикуется одним постом.
- **Промт** — хранится в таблице `settings`, редактируется командой `/prompt`.
- **Воркер** (`bot/worker/processor.py`) — отдельная asyncio-задача, берёт из
  очереди строго по одному заданию, зовёт AI (только если был исходный
  текст/подпись), публикует вложения как есть + новый текст.
- **Retry** — 30с → 2мин → 10мин, после этого — `ERROR` (запись остаётся в БД,
  видна в `/errors`, повторно поставить в очередь можно через `/retry`).
- **Восстановление после рестарта** — при старте `recover_on_startup()`
  переводит зависшие `PROCESSING`/`RECEIVED` задания обратно в очередь.

### Особенности реализации, которые стоит знать

- Если у сообщения нет текста/caption — AI не вызывается, публикуется как есть.
- Стикеры и video-note не поддерживают caption в Telegram API — бот публикует
  вложение и (если есть новый текст) отдельным сообщением сразу следом.
- Альбом, где перемешаны типы, не укладывающиеся в один `media_group`
  (например стикер + фото), публикуется как несколько сообщений, текст —
  последним.
- По умолчанию бот отправляет сообщения без `parse_mode`, чтобы текст от AI
  с символами `< > &` не ломал разбор HTML/Markdown.

## Структура проекта

```
bot/
├── bot.py                  # точка входа
├── config.py                # чтение .env
├── handlers/
│   ├── messages.py           # приём постов, сборка альбомов
│   └── commands.py           # /status /prompt /retry /errors
├── services/
│   ├── ai.py                  # вызов OpenAI
│   ├── telegram.py            # публикация в канал
│   ├── queue.py                # логика очереди
│   ├── albums.py               # буферизация media_group
│   └── settings.py             # key/value настройки (промт)
├── database/
│   ├── models.py
│   └── database.py             # SQLite, миграции при старте
├── worker/
│   └── processor.py            # воркер, retry-логика
├── .env.example
└── requirements.txt
deploy/
└── telegram-repost-bot.service
```

## Установка и первый запуск

```bash
# 1. Клонировать репозиторий и перейти в его корень (тот, что содержит папку bot/)
cd /opt/repost-bot   # или любой другой путь

# 2. Создать виртуальное окружение
python3.12 -m venv venv
source venv/bin/activate

# 3. Установить зависимости
pip install -r bot/requirements.txt

# 4. Настроить .env
cp bot/.env.example bot/.env
nano bot/.env
```

Заполните в `bot/.env`:
- `BOT_TOKEN` — токен от @BotFather
- `ALLOWED_USER_ID` — ваш Telegram ID (узнать у @userinfobot)
- `TARGET_CHANNEL_ID` — id канала "На выкладку" (бот должен быть в нём
  администратором с правом публикации), например `-1001234567890`
- `OPENAI_API_KEY` — ключ OpenAI

```bash
# 5. Первый запуск (в интерактивном режиме, чтобы сразу увидеть логи/ошибки)
python -m bot.bot
```

Дальше:
1. Напишите боту `/prompt <ваш системный промт>` — задать промт переписывания.
2. Перешлите боту тестовый пост (текст, альбом, видео и т.д.) и проверьте,
   что он появился в канале "На выкладку" с новым текстом.
3. `Ctrl+C` для остановки интерактивного запуска перед переходом на systemd.

## Деплой на VPS через systemd

```bash
sudo cp deploy/telegram-repost-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/telegram-repost-bot.service
```

Проверьте и поправьте под свой сервер:
- `User=` / `Group=` — системный пользователь, под которым будет работать бот
  (создайте отдельного: `sudo useradd -r -s /usr/sbin/nologin botuser`, затем
  `sudo chown -R botuser:botuser /opt/repost-bot`)
- `WorkingDirectory=` и путь в `ExecStart=` — если репозиторий лежит не в
  `/opt/repost-bot`, поправьте оба пути

```bash
# Включить и запустить
sudo systemctl daemon-reload
sudo systemctl enable telegram-repost-bot
sudo systemctl start telegram-repost-bot

# Проверить статус
sudo systemctl status telegram-repost-bot

# Смотреть логи в реальном времени
sudo journalctl -u telegram-repost-bot -f

# Перезапуск после обновления кода / .env
sudo systemctl restart telegram-repost-bot
```

Бот сам создаёт файл SQLite (`bot/data/bot.db` по умолчанию, путь можно
переопределить через `DB_PATH` в `.env`) и таблицы при первом старте —
никакой отдельной миграции запускать не нужно.

## Команды бота

- `/status` — сводка по очереди (всего / в очереди / обрабатывается /
  опубликовано / ошибок)
- `/prompt` — показать текущий системный промт
- `/prompt <текст>` — установить/обновить промт
- `/retry` — повторно поставить в очередь все задания со статусом `ERROR`
- `/errors` — последние 10 ошибочных заданий с причиной

Все команды и пересылаемые посты обрабатываются только от пользователя с id
`ALLOWED_USER_ID`; сообщения от любых других пользователей молча игнорируются.
