# Установка posmon на VPS (stat.xmassage.vip)

Всё выполняется на сервере под `root` (`ssh root@77.110.125.73`).
Боты на этом VPS живут в `/root/<имя>` и запускаются через Supervisor.

---

## Шаг 0. Что понадобится заранее

**Ключ Yandex Search API** (для живого сбора непесонализированных профилей):

1. Зайти в консоль **Yandex Cloud**: <https://console.yandex.cloud/>.
2. Создать платёжный аккаунт (услуга платная) и каталог (folder).
3. Подключить сервис **Yandex Search API** (раздел «Поиск в интернете» / Search API).
4. Создать **сервисный аккаунт** и **API-ключ** к нему; скопировать:
   - **folder id** (идентификатор каталога, вида `b1g...`);
   - **API key**.

Эти два значения позже впишем в `.env` (шаг 3). Без них админка и планировщик
запустятся, но живой сбор через API будет отдавать ошибку — это нормально до
внесения ключа.

> Ключ капчи (2captcha/rucaptcha) нужен только для браузерных профилей — на
> первом этапе не требуется.

---

## Шаг 1. Забрать код

```bash
cd /root
git clone https://github.com/svistoff/Claude.git posmon
cd /root/posmon
git checkout claude/loving-cray-2zx242
```

(Обновление позже: `cd /root/posmon && git pull`.)

## Шаг 2. Виртуальное окружение и зависимости

```bash
cd /root/posmon
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r posmon/requirements.txt
```

## Шаг 3. Файл настроек `.env`

```bash
cp posmon/.env.example posmon/.env
nano posmon/.env
```

Минимум, что задать:

- `POSMON_SECRET_KEY` — длинная случайная строка (например `openssl rand -hex 32`).
- `POSMON_ADMIN_LOGIN` / `POSMON_ADMIN_PASSWORD` — логин и пароль для входа в админку.
- `YANDEX_API_FOLDER_ID` / `YANDEX_API_KEY` — из шага 0 (можно вписать позже).
- `DATABASE_URL` — см. ниже.

### Быстрый старт (SQLite) — чтобы сразу увидеть админку

Оставить в `.env`:

```
DATABASE_URL=sqlite+aiosqlite:///./posmon.db
```

Проверить запуск руками:

```bash
cd /root/posmon
.venv/bin/uvicorn posmon.asgi:app --host 127.0.0.1 --port 8010
```

Открыть с сервера `http://127.0.0.1:8010/healthz` — должно вернуть `{"status":"ok"}`.
Остановить (Ctrl+C) и перейти к шагу 4.

### Прод (PostgreSQL) — рекомендуется

```bash
apt update && apt install -y postgresql
sudo -u postgres psql -c "CREATE USER posmon WITH PASSWORD 'ПРИДУМАЙ_ПАРОЛЬ';"
sudo -u postgres psql -c "CREATE DATABASE posmon OWNER posmon;"
```

В `.env`:

```
DATABASE_URL=postgresql+asyncpg://posmon:ПРИДУМАЙ_ПАРОЛЬ@127.0.0.1:5432/posmon
```

Таблицы и первичный админ создаются автоматически при первом запуске.

## Шаг 4. Supervisor (веб + планировщик)

```bash
cp /root/posmon/deploy/supervisor/posmon-web.conf /etc/supervisor/conf.d/
cp /root/posmon/deploy/supervisor/posmon-scheduler.conf /etc/supervisor/conf.d/
supervisorctl reread
supervisorctl update
supervisorctl status
```

Должны появиться `posmon-web` и `posmon-scheduler` в состоянии RUNNING.
Логи: `/var/log/posmon-web.*.log`, `/var/log/posmon-scheduler.*.log`.

## Шаг 5. nginx + домен

Убедиться, что DNS-запись `stat.xmassage.vip` указывает на IP этого VPS.

```bash
apt install -y nginx
cp /root/posmon/deploy/nginx/stat.xmassage.vip.conf /etc/nginx/sites-available/stat.xmassage.vip
ln -s /etc/nginx/sites-available/stat.xmassage.vip /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## Шаг 6. TLS (HTTPS) через Let's Encrypt

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d stat.xmassage.vip
```

certbot сам перепишет конфиг под HTTPS и настроит автопродление.

---

## Готово

Открыть <https://stat.xmassage.vip>, войти логином/паролем из `.env`.

### Обновление после новых коммитов

```bash
cd /root/posmon
git pull
.venv/bin/pip install -r posmon/requirements.txt
supervisorctl restart posmon-web posmon-scheduler
```
