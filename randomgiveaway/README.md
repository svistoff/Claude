# Random.ЕКБ ГИД — генератор победителей розыгрышей

Реализация Этапа 1 ("Ядро") из ТЗ: создание розыгрыша, импорт участников,
нормализация, фильтрация по правилам, криптостойкий случайный выбор
победителей и запасных, сохранение результата с хэш-фиксацией. Плюс
Этап 2 — фронтенд с полноэкранной анимацией розыгрыша и конфетти
(`randomgiveaway/frontend/`, React + Vite), и часть Этапа 4 — живой
Instagram-адаптер для собственных постов ekb_guide. Без VK/Telegram-
адаптеров и без админки — см. раздел «Что не сделано» ниже.

## Ключевое решение по скоупу (важно!)

Изначальное ТЗ предполагало, что организатор конкурса вставляет ссылку на
**любой** пост в Instagram/VK/Telegram. В процессе обсуждения выяснилось:

- **Instagram Graph API не даёт доступа к комментариям чужих постов**, даже
  с подключённым Business/Creator-аккаунтом — Business Discovery отдаёт
  только агрегированные метрики (счётчики), а не сами комментарии с
  username. Прочитать комментарии можно только для медиа, которым владеет
  сам авторизованный аккаунт.
- Чтобы читать чужие посты официально, организатор должен сам пройти OAuth
  и выдать приложению разрешение — а это требует прохождения **Meta App
  Review** (бизнес-верификация, скринкаст use-case, риск отказа для
  категории "comment picker") прежде чем это заработает для произвольных
  внешних организаторов.
- **Решение: сервис делается только для собственных розыгрышей ekb_guide.**
  Все посты, на которых проводится розыгрыш, публикуются от имени самого
  ekb_guide. Это снимает необходимость App Review — Meta-приложение
  работает в Development mode, ekb_guide добавлен как Tester/Admin,
  используется собственный long-lived access-токен, без OAuth-экрана для
  внешних организаторов. Аналогично упрощены VK (токен сообщества ЕКБ ГИД)
  и Telegram (свой канал + группа обсуждений).

Отсюда архитектурное следствие: адаптеры Instagram/VK/Telegram (Этап 4)
будут работать только с постами ekb_guide, не с произвольными ссылками
от сторонних организаторов. Абстракция источников (`adapters/`) при этом
не меняется — она и была спроектирована в ТЗ так, чтобы ядро не знало
про конкретное API.

## Архитектура

```text
adapters/        # SourceAdapter (абстракция) + Import (CSV/JSON/список) +
                  # заготовки Instagram/VK/Telegram под Этап 4
services/
  participants.py  # нормализация комментариев → участники, фильтры (§7 ТЗ)
  random_engine.py # криптостойкий выбор победителей (secrets, не random)
  giveaways.py      # жизненный цикл розыгрыша, персистентность
database/         # aiosqlite, схема как в bot/database (без ORM)
api/              # FastAPI-роуты, схемы, обработчики ошибок (§26 ТЗ)
frontend/         # React + Vite + Framer Motion + canvas-confetti (Этап 2)
  src/api/          # клиент к тому же backend API, типы
  src/pages/         # HomePage (настройка) / DrawPage (анимация) / PublicResultPage
```

Random Engine получает только нормализованный список участников и ничего
не знает об источнике (§18, §36 ТЗ). Выбор фиксируется в БД сразу при
вызове `/draw` — визуализация (когда появится в Этапе 2) не сможет повлиять
на результат.

## Что реализовано (Этап 1, критерии §35 ТЗ)

- Создание розыгрыша с указанием источника, ссылки, правил отбора
- Импорт участников: CSV, JSON, текстовый список usernames (`adapters/import_adapter.py`)
- Нормализация + дедупликация комментариев в участников
- Правила: `unique_user` (комментарий vs пользователь = 1 шанс), учёт replies,
  обязательный текст, обязательное упоминание, исключение автора поста,
  исключение по списку username
- Криптостойкий выбор победителей + запасных (`secrets`, не `random`/`math.random`)
- Хэш-фиксация состава участников и результата (§14 ТЗ)
- Защита от повторного розыгрыша одного и того же giveaway (§24 ТЗ)
- Публичная страница результата по `public_id` без авторизации (§12 ТЗ)
- Понятные тексты ошибок вместо HTTP 500 (§26 ТЗ)
- Простая защита мутирующих ручек токеном администратора (без полноценной
  регистрации пользователей — допустимо для MVP по §17 ТЗ)
- **Instagram-адаптер** (часть Этапа 4): читает комментарии + ответы к
  постам самого ekb_guide через Instagram API with Instagram Login,
  находит медиа по permalink, поддерживает пагинацию. Плюс разовая
  OAuth-привязка (`/api/instagram/oauth/start`) и автопродление
  long-lived токена по cron — см. «Подключение Instagram» ниже.
- **Фронтенд (Этап 2)** — `randomgiveaway/frontend/` (React + Vite +
  Framer Motion + canvas-confetti): выбор источника/импорт, настройка
  правил, предпросмотр участников, полноэкранный экран розыгрыша
  (прокрутка реальных usernames → замедление → победитель → конфетти,
  последовательно для нескольких позиций), финальный экран, публичная
  страница результата (`/result/:publicId`). Выбор победителя всегда
  выполняется на сервере (`POST /draw`) до начала анимации — фронтенд
  только визуализирует уже готовый результат (§9, §22 ТЗ), никогда не
  выбирает сам.

## Что не сделано (следующие этапы)

- **Этап 3** — брендирование, QR-код результата, экспорт в PNG (по желанию)
- **Этап 4 (остальное)** — `VKAdapter`/`TelegramAdapter` — пока заглушки с
  понятным `NotImplementedError`, см. `adapters/`
- **Этап 5** — админка, логи, история розыгрышей для пользователя

## Локальный запуск

Бэкенд:
```bash
cd randomgiveaway
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
venv/bin/uvicorn randomgiveaway.main:app --reload --port 8001
```

Открыть `http://127.0.0.1:8001/docs` — интерактивная документация API.

Фронтенд (в отдельном терминале, Node.js 20+):
```bash
cd randomgiveaway/frontend
npm install
npm run dev
```
Открыть `http://127.0.0.1:5173` — dev-сервер сам проксирует `/api`, `/health`,
`/privacy`, `/terms` на бэкенд (см. `vite.config.ts`), поднятый на 8001.

## Тесты

Бэкенд:
```bash
cd randomgiveaway
venv/bin/pytest
```

Фронтенд — типы и сборка (тестов уровня unit пока нет, есть только ручная
сквозная проверка через Playwright при разработке):
```bash
cd randomgiveaway/frontend
npm run build
```

## Деплой на VPS (Supervisor + Nginx)

По конвенции этого репозитория (см. корневой `CLAUDE.md`) — через
**Supervisor**, не systemd, код в `/root/<имя>`, не в `/opt/...`.

```bash
# 1. Клонировать репозиторий (отдельная папка под этот сервис)
cd /root
git clone https://github.com/svistoff/Claude.git random-giveaway
cd random-giveaway
git checkout claude/analyze-requirements-rqi4m3   # или main, после мерджа

# 2. Окружение (бэкенд)
python3 -m venv venv
venv/bin/pip install -r randomgiveaway/requirements.txt
cp randomgiveaway/.env.example randomgiveaway/.env
nano randomgiveaway/.env   # задать ADMIN_TOKEN (случайная строка), остальное можно оставить по умолчанию

# 2а. Сборка фронтенда (нужен Node.js 20+; если на сервере его нет —
# https://github.com/nodesource/distributions, пакет nodejs включает npm)
cd randomgiveaway/frontend
npm install
npm run build          # создаёт randomgiveaway/frontend/dist — это и отдаёт Nginx
cd /root/random-giveaway

# 3. Проверить руками перед Supervisor
venv/bin/uvicorn randomgiveaway.main:app --host 127.0.0.1 --port 8001
# в другом окне: curl http://127.0.0.1:8001/health  →  {"status":"ok"}
# Ctrl+C после проверки

# 4. Supervisor
sudo apt update && sudo apt install -y supervisor   # если ещё не стоит
sudo cp deploy/supervisor/random-giveaway-api.conf /etc/supervisor/conf.d/
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start random-giveaway-api
sudo supervisorctl status random-giveaway-api
tail -f /var/log/random-giveaway-api.out.log /var/log/random-giveaway-api.err.log

# 5. Nginx (домен)
sudo apt install -y nginx   # если ещё не стоит
sudo cp deploy/nginx/random-giveaway.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/random-giveaway.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 6. HTTPS
sudo apt install -y certbot python3-certbot-nginx   # если ещё не стоит
sudo certbot --nginx -d random.ekb-guide.ru
```

Перед шагом 5 нужно, чтобы A-запись `random.ekb-guide.ru` уже указывала на
IP этого VPS (`77.110.125.73`) — это настраивается у регистратора/DNS-
провайдера домена `ekb-guide.ru`, не на самом сервере.

Если в `/etc/nginx` уже используется другая структура (например, всё в
`conf.d/`, без `sites-available`/`sites-enabled`) — положите файл туда же,
где лежат остальные конфиги на этом сервере, схема из примера не единственно
возможная.

Проверка после выпуска сертификата:

```bash
curl https://random.ekb-guide.ru/health   # {"status":"ok"}
```

`https://random.ekb-guide.ru/docs` откроет интерактивную документацию API,
а сам `https://random.ekb-guide.ru` — интерфейс с анимацией розыгрыша.

После обновления кода на сервере:
```bash
git pull
venv/bin/pip install -r randomgiveaway/requirements.txt   # если менялся backend
cd randomgiveaway/frontend && npm install && npm run build && cd /root/random-giveaway   # если менялся frontend
sudo supervisorctl restart random-giveaway-api
sudo nginx -t && sudo systemctl reload nginx   # если менялся deploy/nginx/random-giveaway.conf
```

**Если у вас уже настроен HTTPS через certbot** (сертификат уже выпущен
на этот домен) — не заменяйте `/etc/nginx/sites-available/random-giveaway.conf`
целиком файлом из репозитория: certbot дописал в него блок `listen 443 ssl`
и пути к сертификату, которых нет в версии из репо. Вместо этого точечно
добавьте в уже существующий файл (внутри блока `server { listen 443 ssl; ... }`)
три вещи из актуального `deploy/nginx/random-giveaway.conf`: `root`/`index`,
location `/api/`, location для `docs|openapi.json|health|privacy|terms`, и
замените старый `location / { proxy_pass ...; }` на `location / { try_files
$uri /index.html; }`.

## Подключение Instagram

Часть шагов — только руками, через браузер, с логином в Meta for Developers
и в сам Instagram как ekb_guide. Их не может сделать ассистент — только
человек, у которого есть эти учётные данные.

### 1. Создать Meta-приложение

1. https://developers.facebook.com/apps → **Create App** → тип **Business**.
2. В приложении добавить продукт **Instagram** → сценарий **API setup with
   Instagram login** (это и есть "Instagram API with Instagram Login" —
   не путать с устаревшим Instagram Basic Display, он не даёт доступа к
   комментариям, и не нужен вариант через Facebook Login/привязанную
   Facebook-страницу).
3. В настройках продукта:
   - **Add Instagram account** → указать ekb_guide как tester. ekb_guide
     должен подтвердить приглашение: в самом Instagram →
     Настройки → Apps and websites → Tester invites → Accept.
   - **Valid OAuth Redirect URIs** — вписать ровно
     `https://random.ekb-guide.ru/api/instagram/oauth/callback`
   - Убедиться, что аккаунт ekb_guide — **Business или Creator**
     (professional account), не личный — иначе Instagram Login не сработает.
4. Скопировать **Instagram App ID** и **Instagram App Secret** — это
   значения для `INSTAGRAM_APP_ID`/`INSTAGRAM_APP_SECRET`.

App Review проходить не нужно — авторизоваться через приложение смогут
только аккаунты, добавленные тестировщиками (по нашему решению это
только ekb_guide, см. раздел «Ключевое решение по скоупу» выше).

### 1а. Опубликовать приложение (обязательно, проверено на практике)

Важно и неочевидно: пока приложение в статусе **«Не опубликовано»**
(Development), эндпоинт `/comments` отвечает `200 OK` с пустым `data: []`
для **любого** поста — даже своего, даже с ненулевым `comments_count`, без
какой-либо ошибки о нехватке прав. Это не связано с App Review и не
требует его — приложение можно и нужно опубликовать, оставаясь при этом
закрытым для всех, кроме тестировщиков.

Для публикации Meta требует заполненные:
- **URL Политики конфиденциальности**: `https://random.ekb-guide.ru/privacy`
- **URL-адрес Пользовательского соглашения**: `https://random.ekb-guide.ru/terms`
  (по умолчанию там подставлена заглушка `facebook.com` — обязательно
  заменить)
- **Категория** приложения (любая подходящая)

Это в «Настройки приложения» → «Основное». Оба URL уже реализованы в
сервисе (`randomgiveaway/api/legal.py`) — ничего дополнительно писать не
нужно, только вписать ссылки. После заполнения — раздел «Опубликовать» в
левом меню приложения → кнопка публикации.

Если токен для ekb_guide был выдан **до** публикации — его нужно
перевыпустить заново (см. шаг 3) после того, как приложение станет Live,
старый токен реальные комментарии не увидит.

### 2. Прописать .env и перезапустить сервис

```bash
nano /root/random-giveaway/randomgiveaway/.env
```
```
INSTAGRAM_APP_ID=...
INSTAGRAM_APP_SECRET=...
INSTAGRAM_OAUTH_REDIRECT_URI=https://random.ekb-guide.ru/api/instagram/oauth/callback
```
```bash
sudo supervisorctl restart random-giveaway-api
```

### 3. Пройти разовую авторизацию

`/api/instagram/oauth/start` защищён тем же `ADMIN_TOKEN`, что и остальные
мутирующие ручки — обычная ссылка в браузере кастомный заголовок не
передаёт, поэтому редирект-URL сначала берём curl'ом, а открываем уже его:

```bash
curl -sI -H "X-Admin-Token: <ADMIN_TOKEN из .env>" \
  https://random.ekb-guide.ru/api/instagram/oauth/start | grep -i '^location'
```

Полученную ссылку (`https://www.instagram.com/oauth/authorize?...`)
открыть в браузере, залогинившись в Instagram как ekb_guide → **Allow**.
Instagram редиректнёт на `/callback`, который сам обменяет код на
long-lived токен и запишет его в `.env`. Страница ответит
«Instagram подключён».

Перезапустить сервис, чтобы он подхватил новый токен:
```bash
sudo supervisorctl restart random-giveaway-api
```

### 4. Настроить автопродление токена (cron)

Long-lived токен живёт ~60 дней. Без продления он молча истечёт, и
Instagram-адаптер начнёт падать с ошибкой авторизации.

```bash
crontab -e
```
добавить строку (раз в сутки в 4:00):
```
0 4 * * * cd /root/random-giveaway && venv/bin/python -m randomgiveaway.scripts.refresh_instagram_token >> /var/log/random-giveaway-token-refresh.log 2>&1
```

Проверить руками, что скрипт работает (после шага 3, когда токен уже есть):
```bash
cd /root/random-giveaway
venv/bin/python -m randomgiveaway.scripts.refresh_instagram_token
```

### 5. Проверка

```bash
curl -X POST https://random.ekb-guide.ru/api/giveaways \
  -H "X-Admin-Token: <ADMIN_TOKEN>" -H "Content-Type: application/json" \
  -d '{"source":"instagram","post_url":"https://www.instagram.com/p/XXXXXXX/","settings":{"winners_count":1}}'
```
дальше вызвать `POST /api/giveaways/{id}/load-comments` с тем же
заголовком — если всё настроено верно, вернётся тот же формат
предпросмотра, что и для `/import`.

**Важно:** это подключает только собственные посты ekb_guide. Ссылка на
пост стороннего организатора вернёт понятную ошибку «Пост не найден среди
публикаций ekb_guide» — это ожидаемое поведение (см. «Ключевое решение по
скоупу» в начале файла), не баг.

## API (§20 ТЗ, пути ориентировочные)

```text
POST /api/giveaways
GET  /api/giveaways/{id}
POST /api/giveaways/{id}/import                # CSV/JSON/список (form-data: file, format)
POST /api/giveaways/{id}/load-comments          # живой источник; для instagram — реализовано, vk/telegram — 501
POST /api/giveaways/{id}/participants/process   # предпросмотр (§8 ТЗ)
GET  /api/giveaways/{id}/participants           # список участников — для анимации на фронтенде
POST /api/giveaways/{id}/draw
GET  /api/giveaways/{id}/result
GET  /api/results/{public_id}                   # публично, без авторизации

GET  /api/instagram/oauth/start                 # разовая привязка ekb_guide, требует ADMIN_TOKEN
GET  /api/instagram/oauth/callback              # редирект от Instagram, вызывать вручную не нужно
```
