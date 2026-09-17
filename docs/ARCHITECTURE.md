# Архитектура AI Coding Agent

Документ фиксирует ключевые решения MVP (Фаза 1) и точки расширения для Фаз 2–3.

## Слои

```
frontend/ (vanilla SPA, mobile-first, SSE)
        │  HTTP + Server-Sent Events
backend/app/
  ├── main.py            сборка FastAPI, статика, заголовки безопасности
  ├── config.py          .env (секреты) + config.yaml (несекретное)
  ├── auth.py            bcrypt, подписанные cookie, CSRF, rate limit
  ├── security.py        sandbox путей + фильтр секретов (общий для всех fs-tools)
  ├── api/               роутеры: auth, projects, chat(SSE), git, files
  ├── agent/
  │   ├── loop.py        цикл DeepSeek ↔ инструменты
  │   ├── permissions.py классификация allow/confirm/block
  │   ├── prompts.py     системный промпт
  │   ├── runtime.py     активные запуски: stop, подтверждения, usage
  │   └── pricing.py     оценка стоимости по тарифам из config
  ├── llm/               абстракция провайдера (base) + deepseek
  ├── tools/             filesystem, terminal, git + registry (схемы)
  └── database/          SQLite: conversations, messages, tool_calls
```

## Ключевые решения (согласовано с заказчиком)

### 1. Reasoning ≠ execution
DeepSeek решает *что* делать (reasoning), агент исполняет через tools (execution).
Модель получает схемы инструментов (function calling) и вызывает их в цикле, пока
задача не решена или не достигнут `MAX_AGENT_ITERATIONS` (по умолчанию 30).

### 2. Абстракция LLM (раздел 43 ТЗ)
`llm/base.py` задаёт единый контракт потока событий (text / tool_calls / usage /
finish). `agent/loop.py` работает только с этим контрактом. Смена провайдера или
модели — через `config.yaml` (`llm.provider`, `llm.model`) без правки цикла.
Сейчас реализован DeepSeek (официальный API, OpenAI-совместимый).

### 3. Модель
Используется официальный DeepSeek API (`DEEPSEEK_BASE_URL=https://api.deepseek.com`),
ключ — только в `.env`. Id модели вынесен в конфиг; при появлении V4.1-Flash в
официальном API достаточно поменять `llm.model` / `DEEPSEEK_MODEL`.

### 4. Пауза на подтверждение (разделы 10, 44 ТЗ)
Опасные действия (`git push`, `rm -rf`, перезапуск сервисов, nginx, firewall,
установка пакетов) классифицируются в `permissions.py`. При действии класса
`confirm` цикл **приостанавливается**: `runtime.RunState.create_confirmation()`
создаёт `asyncio.Future`, событие `confirm_required` уходит в UI, цикл ждёт ответа
(`/api/chat/confirm`) и продолжается с той же точки. Класс `block` (mkfs, dd,
fork bomb) не выполняется никогда.

### 5. Stop Agent (раздел 20 ТЗ)
Каждая terminal-команда стартует в отдельной process group (`start_new_session`).
`RunState` хранит зарегистрированные pgid; Stop шлёт SIGTERM/SIGKILL всей группе —
дочерние процессы (`pytest` и т.п.) убиваются немедленно.

### 6. Фильтр секретов на всех fs-инструментах (разделы 9.2, 44 ТЗ)
`security.py` применяется в read/list/search/write/edit и в `/api/files/*`.
Секретные файлы (`.env`, `*.key`, `id_rsa`, `credentials*` и т.д.) не листятся, не
читаются и не попадают в архивы. Совпадение проверяется по каждому сегменту пути.

### 7. Восстановление сессии (безопасный вариант, раздел 29 ТЗ)
Персистятся история диалога, вызовы инструментов и их результаты (SQLite). После
перезагрузки страницы чат восстанавливается из БД. Живой subprocess **не**
восстанавливается — незавершённое действие помечается как прерванное, чтобы не
оставлять «висящих» процессов и не выдавать неполный результат за готовый.

### Sandbox путей
Все пути резолвятся относительно root выбранного проекта с раскрытием симлинков;
выход за границы (`..`, абсолютные пути, симлинк наружу) → `SecurityError`.

## Поток одного запроса

```
POST /api/chat {project, message, conversation_id?}
  → сохранить user-сообщение
  → history = [system] + прошлые сообщения из БД
  → run_agent(): DeepSeek(stream) → tool_calls?
        confirm? → пауза → /api/chat/confirm → продолжить
        allow?   → dispatch(tool) → результат в history
     повтор до финального ответа / stop / лимита
  → SSE-события в UI, дельта истории сохраняется в БД
```

## Точки расширения (Фазы 2–3)
- **GitHub** (`tools/github.py`): fine-grained PAT / GitHub App, PR, CI.
- **Browser** (`tools/browser.py`): Playwright, отдельный профиль, скриншоты модели.
- **Archive/upload**: расширить `api/files.py`, добавить `uploaded_files`.
- **Scheduler**: recurring tasks поверх существующих conversations/sessions.
- **Docker-изоляция терминала**: сменить runner в `tools/terminal.py`.
- **Другие LLM**: добавить провайдер в `llm/`, выбрать через `config.yaml`.
