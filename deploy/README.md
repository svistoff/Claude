# Деплой на VPS (ai.svistoff.ru)

Инструкция для VPS `77.110.125.73`. Все шаги выполняются по SSH с **ключевой
авторизацией** (не паролем). SSH-пароль/ключ нигде в коде не хранятся.

> Предварительно (раздел 45 ТЗ) проверьте сервер: ОС, `python3 --version`,
> наличие `nginx`, `git`, свободные RAM/диск, текущие systemd/supervisor сервисы —
> чтобы **не сломать** существующие проекты.

## 1. Отдельный пользователь агента (минимум прав)

Агент НЕ работает под root. Создаём непривилегированного пользователя:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin aiagent
sudo mkdir -p /var/log/ai-agent && sudo chown aiagent:aiagent /var/log/ai-agent
```

Дайте `aiagent` доступ только к директориям проектов, которыми он должен управлять
(например, через группу-владельца каталогов в `/var/www/*`). Не давайте доступ ко
всей файловой системе.

## 2. Код и зависимости

```bash
sudo mkdir -p /opt/ai-agent && sudo chown aiagent:aiagent /opt/ai-agent
sudo -u aiagent git clone <repo-url> /opt/ai-agent
cd /opt/ai-agent/backend
sudo -u aiagent python3 -m venv .venv
sudo -u aiagent .venv/bin/pip install -r requirements.txt
```

## 3. Конфигурация

```bash
sudo -u aiagent cp /opt/ai-agent/.env.example /opt/ai-agent/.env
sudo -u aiagent nano /opt/ai-agent/.env
```

Заполните в `.env`:
- `DEEPSEEK_API_KEY` — ключ официального DeepSeek API;
- `GITHUB_TOKEN` — (опц., Фаза 2) fine-grained PAT: Contents R/W, Pull requests R/W,
  Checks/Commit statuses R — только на нужные репозитории;
- `ADMIN_USER`, `ADMIN_PASSWORD_HASH` — хэш от `python -m app.scripts.hash_password '...'`;
- `SECRET_KEY` — `python -c "import secrets; print(secrets.token_hex(32))"`;
- `COOKIE_SECURE=true` (за HTTPS обязательно).

Создайте рабочий конфиг из шаблона и впишите **фактические пути** к проектам на VPS
(и при необходимости id модели DeepSeek). Рабочий `config.yaml` в git не хранится —
обновления кода его не затрут:

```bash
sudo -u aiagent cp /opt/ai-agent/backend/config.example.yaml /opt/ai-agent/backend/config.yaml
sudo -u aiagent nano /opt/ai-agent/backend/config.yaml
```

### Workspace для новых проектов

Чтобы из UI работала кнопка **«+ Новый проект»** (создание проектов прямо с телефона),
создайте папку из поля `workspace` в `config.yaml` (по умолчанию `/var/www/ai-workspace`)
и дайте к ней доступ пользователю `aiagent`:

```bash
sudo apt install -y acl
sudo mkdir -p /var/www/ai-workspace
sudo setfacl -R  -m u:aiagent:rwx /var/www/ai-workspace
sudo setfacl -R -d -m u:aiagent:rwx /var/www/ai-workspace   # и для будущих файлов
```

Так же дайте `aiagent` доступ к папкам уже существующих проектов, которыми он должен
управлять (по одной команде `setfacl` на проект). Новые проекты, созданные кнопкой,
живут внутри `workspace` — песочница сохраняется.

### (Опционально) OCR для скриншотов

Чтобы агент **читал текст со вставленных скриншотов** (Ctrl+V в чат), поставьте
tesseract и Python-обёртки. Без этого скриншоты просто прикрепляются, но текст с
них не распознаётся.

```bash
sudo apt install -y tesseract-ocr tesseract-ocr-rus
sudo -u aiagent /opt/ai-agent/backend/.venv/bin/pip install pytesseract pillow
sudo systemctl restart ai-agent
```

## 4. systemd-сервис

```bash
sudo cp /opt/ai-agent/deploy/ai-agent.service /etc/systemd/system/ai-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now ai-agent
systemctl status ai-agent
```

Приложение слушает `127.0.0.1:8770` — **наружу не открыто**.

## 5. nginx + HTTPS

Убедитесь, что DNS `ai.svistoff.ru` указывает на `77.110.125.73`, затем:

```bash
sudo cp /opt/ai-agent/deploy/nginx.conf /etc/nginx/sites-available/ai.svistoff.ru
sudo ln -s /etc/nginx/sites-available/ai.svistoff.ru /etc/nginx/sites-enabled/
sudo certbot --nginx -d ai.svistoff.ru
sudo nginx -t && sudo systemctl reload nginx
```

Готово: `https://ai.svistoff.ru` (HTTP автоматически редиректится на HTTPS).

## 6. Обновление

```bash
cd /opt/ai-agent && sudo -u aiagent git pull
sudo -u aiagent backend/.venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart ai-agent
```

## Усиление изоляции терминала (рекомендуется)

По умолчанию terminal-команды выполняются от пользователя `aiagent` в корне проекта
с process-group kill и timeout. Для более строгой изоляции запускайте команды в
Docker-контейнере на проект (примонтировать только root проекта, без сети при
необходимости). Архитектура терминала это допускает — точка расширения в
`backend/app/tools/terminal.py`.
