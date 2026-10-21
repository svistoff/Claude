# «Мой наставник» (mentor-bot)

Личный Telegram-бот, который **организует рабочий день**. Скидываешь ему задачи
обычными сообщениями, утром он присылает план (главное дело дня и что можно
отложить), вечером подводит итог. Для долгих целей можно завести проекты, и
по ним бот раз в день даёт конкретный следующий шаг.

Вырос из модуля «Наставник» в ai.svistoff.ru (ветка
`claude/ai-coding-agent-mvp-3kfoqe`) и живёт отдельно: своя база, своё
подключение к ИИ, свой процесс. Не связан с ботом «Лиза» (`companion_bot`).

## Как работает

- **Входящие:** любое сообщение боту (не команда и не ответ на совет) — новая
  задача с номером.
- **Утро (`PLAN_TIME`, 08:30):** бот берёт порцию задач (все срочные, обычные и
  не больше двух «на потом», которые давно не показывал), ИИ присылает план:
  ⭐ одна главная, 1–3 быстрых, остальное «отложить». Под планом кнопки
  «✅ сделано» / «⏸ завтра» (отложенная задача возвращается на следующий день).
- **В течение дня:** `/done N` — сделано, `/drop N` — убрать, `/plan` — пересобрать план.
- **Проекты (по желанию):** в заданное время — совет-шаг по проекту с учётом
  цели, папки на сервере (git-лог, README), прошлых советов и твоих отчётов.
  Отчёт = reply на совет.
- **Вечер (`EVENING_TIME`, 20:00):** итог дня (сделано / открыто) и вопрос
  «как прошло?» по проектам без отчёта.

Бот только советует: ничего не меняет в файлах проектов.

## Команды

```
Задачи
  <любой текст>          новая задача во входящие
  ! текст · срочно …     срочная · потом …  «на потом»
  /urgent N · /later N   сменить срочность
  /tasks                 открытые задачи
  /done N · /drop N      сделано · убрать
  /plan                  план дня сейчас

Проекты
  /add имя [путь]        добавить проект (путь к папке — по желанию)
  /goal имя текст        долгая цель проекта
  /path имя путь         привязать папку
  /time имя ЧЧ:ММ [будни] время совета
  /on имя · /off имя     включить/выключить
  /del имя               удалить
  /projects              список
  /now [имя]             совет сейчас
  /report имя текст      отчёт (или reply на совет)

/id — показать chat_id
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
