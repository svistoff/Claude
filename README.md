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
| 🔜 | GitHub API, PR, CI (Фаза 2) |
| 🔜 | Playwright browser agent (Фаза 3) |
