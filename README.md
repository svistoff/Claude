# AI Coding Agent — ai.svistoff.ru

Мобильный веб-агент для управления AI coding-агентом. Пользователь пишет задачу
обычным языком с телефона — агент через **DeepSeek API** (reasoning layer)
самостоятельно читает файлы, ищет, правит код, запускает терминал, работает с git
на выбранном проекте (execution layer).

> Статус: **Фаза 1 (MVP)**. Браузерная автоматизация, полноценный GitHub API и
> планировщик — Фазы 2–3 (заложены архитектурно, ещё не реализованы).

---

## Архитектура

```
Пользователь
   │
   ▼  HTTPS
 nginx (reverse proxy)
   │
   ▼  127.0.0.1:8000
 FastAPI backend ── SQLite
   │
   ▼
 Agent loop ──► LLM Provider (DeepSeek) ──► reasoning
   │
   ├── tools/filesystem   (read/list/search/write/edit)
   ├── tools/terminal     (sandbox + permissions + timeout)
   └── tools/git          (status/diff/commit/...)
   │
   ▼
 Проекты на VPS (только разрешённые директории)
```

Ключевые принципы:

- **Reasoning ≠ execution.** DeepSeek решает *что* делать, агент *исполняет* через tools.
- **LLM-абстракция.** `backend/llm/` — провайдер сменяется через конфиг, agent loop не меняется.
- **Безопасность по умолчанию.** Изоляция по project root, фильтр секретов на всех
  файловых инструментах, подтверждение опасных команд, никаких секретов в логах/UI.

Подробности архитектурных решений — в [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Быстрый старт (локально)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example ../.env
#  отредактируйте .env: DEEPSEEK_API_KEY, ADMIN_USER, ADMIN_PASSWORD_HASH, SECRET_KEY
#  сгенерировать хэш пароля:
python -m app.scripts.hash_password 'ваш-пароль'
#  сгенерировать SECRET_KEY:
python -c "import secrets; print(secrets.token_hex(32))"

#  настройте проекты в config.yaml (пути к вашим проектам на VPS)

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Откройте `http://127.0.0.1:8000`, войдите под `ADMIN_USER`.

## Приложение на телефоне и компьютере

Сайт ставится как приложение: иконка на рабочем столе, открывается без адресной
строки, история чатов на месте.

- **Android / Chrome / Edge:** меню → «Установить приложение». Или кнопка
  «Установить на рабочий стол» в Настройках.
- **iPhone / iPad (Safari):** «Поделиться» → «На экран „Домой“».
- **Компьютер (Chrome/Edge):** иконка установки в адресной строке.

Иконки и манифест лежат в `frontend/` (`manifest.webmanifest`, `icons/`),
пересоздать иконки: `cd backend && .venv/bin/python -m app.scripts.make_icons`.

При запуске открывается **новый чат**, прошлые — в меню слева. В настройках это
меняется на «Продолжить последний чат»; перезагрузка страницы всегда возвращает
в открытый чат.

### Работа локально или на VPS

Одно и то же приложение может работать с агентом на VPS или на вашем компьютере:
Настройки → «Где работает агент» → «На моём компьютере» (`http://localhost:8770`).
Файлы, терминал и git при этом — вашего компьютера, а не сервера.

Чтобы это работало, запустите агент локально (`uvicorn ... --port 8770`) и
разрешите адрес приложения в `CORS_ORIGINS` (см. `.env.example`). Авторизация в
режиме «другой сервер» идёт по токену, потому что cookie между сайтами браузер
не передаёт. Ограничение: с iPhone обращение из https-приложения к
`http://localhost` может блокироваться браузером — для локального режима надёжнее
компьютер или локальная установка по http.

## Конфигурация

- **`.env`** — секреты и переменные окружения (см. `.env.example`). В git **не** попадает.
- **`config.yaml`** — несекретное: список проектов, модель, тарифы DeepSeek, лимиты.

Никогда не храните `DEEPSEEK_API_KEY`, SSH-ключи или пароли в коде, git, README или логах.

## Деплой на VPS

См. [`deploy/README.md`](deploy/README.md): systemd-сервис `ai-agent`, nginx
reverse-proxy для `ai.svistoff.ru`, Let's Encrypt (HTTP→HTTPS), sandbox-пользователь.

## Статус функций (Фаза 1)

| ✓ | Функция |
|---|---------|
| ✅ | Login (админ, bcrypt-хэш, secure cookie, session expiration) |
| ✅ | Mobile-first web UI (Apple-style: стеклянные панели, пружины, light/dark) |
| ✅ | DeepSeek API через LLM-абстракцию + переключатель моделей (flash / v4-pro) |
| ✅ | Chat + streaming (SSE) |
| ✅ | Выбор проекта |
| ✅ | read / list / search / write / edit файлов (в пределах project root) |
| ✅ | terminal (timeout, process-group kill, фильтр опасных команд) |
| ✅ | Подтверждение опасных действий |
| ✅ | git status / diff / commit |
| ✅ | Stop agent |
| ✅ | Скачивание файла / ZIP-архива |
| ✅ | Прикрепление файлов к чату (📎, текст файла виден агенту) |
| ⏳ | HTTPS — настраивается на VPS (см. `deploy/`) |
| ✅ | Markdown в ответах агента |
| ✅ | Реальные тарифы DeepSeek (пер-модельно + пиковые часы) |
| ✅ | **Фаза 2:** GitHub — ветки/PR/CI (fine-grained токен, кнопки в панели Git) |
| ✅ | **Фаза 3:** браузер-агент (Playwright) — open/click/type/get_text/screenshot; скриншоты в чат + OCR |
| ✅ | Интернет: `web_search` + `web_fetch` (DeepSeek Search & Fetch API, $0.75/1000) |
| ✅ | Задачи (`tasks`) и журнал работы (`worklog`) → отчёт шефу за неделю/месяц |
| ✅ | Работа не прерывается при закрытии вкладки (фоновые задачи + переподключение) |
| ✅ | Приложение (PWA): иконка на рабочем столе, standalone-режим, офлайн-оболочка |
| ✅ | Выбор сервера: работать с VPS или с локальным запуском (Bearer-токен + CORS) |
| ✅ | Контекст чатов сохраняется: при входе открывается последний чат (сервер + localStorage) |
| 🔜 | Playwright browser agent (Фаза 3) |
