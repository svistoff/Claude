# Бот-наставник (mentor-bot)

Личный Telegram-бот: каждое утро присылает **один конкретный шаг к первой
выручке** по каждому твоему проекту, вечером спрашивает «как прошло?» и
учитывает твои ответы в следующих советах. Управление целиком из Telegram.

Вырос из модуля «Наставник» в ai.svistoff.ru (ветка
`claude/ai-coding-agent-mvp-3kfoqe`) и теперь живёт отдельно: своя база,
своё подключение к ИИ, свой процесс.

## Как работает

- **Утром** (время задаётся на проект) ИИ в роли CEO смотрит цель проекта,
  папку на сервере (git-лог, README), свои прошлые советы и твои отчёты — и
  присылает одну задачу на 2–4 часа: узкое место → задача → Done → бизнес-результат.
- **Ты отвечаешь (reply) на совет** — «сделал, 2 отклика» или «не успел» —
  это сохраняется как отчёт по проекту.
- **Вечером** (`EVENING_TIME`) бот спрашивает про задачи, по которым отчёта нет.
- **Следующий совет** учитывает отчёты: не повторяет выполненное, упрощает невыполненное.

Только советы — бот ничего не меняет в коде проектов, папки читает только для контекста.

## Команды

```
/add имя [путь]        добавить проект (путь к папке — по желанию)
/goal имя текст        цель: кто клиент, за что платит, что мешает первому рублю
/path имя путь         привязать папку проекта
/time имя ЧЧ:ММ [будни] время совета
/on имя · /off имя     включить/выключить
/del имя               удалить проект из наставника
/projects              список
/now [имя]             совет прямо сейчас
/report имя текст      отчёт о сделанном (или просто reply на совет)
/id                    показать chat_id
```

## Установка на VPS (Supervisor, `/root/mentor-bot`)

```bash
git clone -b claude/mentor-bot https://github.com/svistoff/Claude /root/mentor-bot
cd /root/mentor-bot
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env        # TELEGRAM_BOT_TOKEN и LLM_API_KEY; OWNER_CHAT_ID пока пустой
```

Первый запуск — узнать chat_id:

```bash
venv/bin/python -m mentor_bot
```

Напиши боту `/start` — он ответит твоим chat_id. Останови (`Ctrl+C`), впиши
`OWNER_CHAT_ID=...` в `.env`, затем поставь в Supervisor:

```bash
cp deploy/supervisor/mentor-bot.conf /etc/supervisor/conf.d/
supervisorctl reread && supervisorctl update
supervisorctl status mentor-bot
```

Логи: `/var/log/mentor-bot.out.log` и `/var/log/mentor-bot.err.log`.

Обновление: `cd /root/mentor-bot && git pull && supervisorctl restart mentor-bot`.

## Разработка

```bash
python3 -m venv venv && venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest -q
```

Структура: `config.py` (.env) · `db.py` (SQLite) · `llm.py` (OpenAI-совместимый API) ·
`telegram.py` (Bot API, long polling) · `advisor.py` (промпт + контекст + память) ·
`scheduler.py` (утро/вечер) · `handlers.py` (команды) · `bot.py` (точка входа).
