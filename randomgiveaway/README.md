# Random.ЕКБ ГИД — генератор победителей розыгрышей

Реализация Этапа 1 ("Ядро") из ТЗ: создание розыгрыша, импорт участников,
нормализация, фильтрация по правилам, криптостойкий случайный выбор
победителей и запасных, сохранение результата с хэш-фиксацией. Плюс
Этап 2 — фронтенд с полноэкранной анимацией розыгрыша и конфетти
(`randomgiveaway/frontend/`, React + Vite), и часть Этапа 4 — живые
Instagram- и VK-адаптеры для собственных постов ekb_guide, и Telegram —
не адаптер чтения комментариев (Bot API их не отдаёт), а бот с кнопкой
«Участвую» + реферальными ссылками, см. «Подключение Telegram» ниже. Без
админки — см. раздел «Что не сделано» ниже.

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
  внешних организаторов. Аналогично упрощены VK (пользовательский токен
  администратора сообщества ЕКБ ГИД, без OAuth-экрана для внешних
  организаторов) и Telegram (свой канал, свой бот — см. ниже).

Отсюда архитектурное следствие: адаптеры Instagram/VK/Telegram (Этап 4)
будут работать только с постами ekb_guide, не с произвольными ссылками
от сторонних организаторов. Абстракция источников (`adapters/`) при этом
не меняется — она и была спроектирована в ТЗ так, чтобы ядро не знало
про конкретное API.

## Архитектура

```text
adapters/        # SourceAdapter (абстракция) + Import (CSV/JSON/список) +
                  # Instagram/VK (чтение комментариев по ссылке на пост)
services/
  participants.py       # нормализация комментариев → участники, фильтры (§7 ТЗ)
  random_engine.py      # криптостойкий выбор победителей (secrets, не random)
  giveaways.py           # жизненный цикл розыгрыша, персистентность
  telegram_api.py         # тонкая обёртка над Telegram Bot API
  telegram_giveaway.py    # кнопка "Участвую" + рефералки — свой поток вместо
                           # SourceAdapter, см. «Подключение Telegram»
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
- **VK-адаптер** (часть Этапа 4): читает комментарии + вложенные ответы
  (до 10 на ветку) к постам сообщества ЕКБ ГИД через `wall.getComments`,
  пользовательским токеном (токен сообщества для этого не подходит —
  см. «Подключение VK» ниже), с разовой OAuth-привязкой через VK ID + PKCE
  (`/api/vk/oauth/start`) и автопродлением короткоживущего токена по
  `refresh_token` через cron (`scripts/refresh_vk_token.py`).
- **Telegram** (часть Этапа 4, механика отличается от Instagram/VK): Bot API
  не даёт боту истории уже написанных сообщений, поэтому вместо чтения
  комментариев — отдельный бот, который публикует пост розыгрыша в канал с
  кнопкой «Участвую» (реферальная ссылка-приглашение), сам засекает
  подписку на канал и обрабатывает реферальные приглашения
  (`POST /api/giveaways/{id}/telegram/publish`,
  `POST /api/telegram/webhook`) — подробности и настройка в «Подключение
  Telegram» ниже.
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
IP этого VPS (`45.146.90.128`) — это настраивается у регистратора/DNS-
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

## Подключение VK

**Важно (найдено вживую, не по документации):**

1. Токен сообщества для чтения комментариев НЕ подходит —
   `wall.getComments` отвечает ошибкой
   `27 "Group authorization failed: method is unavailable with group auth"`
   при вызове с групповым токеном, независимо от выданных прав. Нужен
   именно пользовательский access-токен.
2. У VK **два разных** сервиса создания приложений, и с виду похожий, но
   для сервера непригодный вариант — это ловушка:
   - `dev.vk.com/apps` («Новая панель управления») создаёт **VK Mini
     App** — приложение, которое обязано грузить VK Bridge JS SDK
     (`VKWebAppInit`) и работать внутри VK. Для серверного OAuth не
     годится: при попытке пройти модерацию VK прямо укажет на
     отсутствие `VKWebAppInit`.
   - Правильный путь — **id.vk.ru** → «Сервис авторизации VK ID» →
     создать **Standalone-приложение**. Именно там есть поля «Базовый
     домен» и «Доверенный Redirect URL», нужные для серверного flow.
3. Это Standalone-приложение говорит по протоколу **VK ID (OAuth 2.1 +
   обязательный PKCE)**, а не по старому классическому `oauth.vk.com`.
   Отличия: **client_secret не используется вообще** (значит,
   «Защищённый ключ»/«Сервисный ключ доступа» из настроек приложения
   копировать не нужно); вместо него — пара `code_verifier`/
   `code_challenge`, которую сервис генерирует и хранит сам. Токен —
   короткоживущий (в отличие от старой модели `scope=offline` = вечный
   токен), поэтому обязательно нужен `refresh_token` и cron-продление
   (см. шаг 4).

### 1. Создать VK ID-приложение

1. Зайти на https://id.vk.ru (под тем же VK-аккаунтом, который является
   администратором сообщества ЕКБ ГИД) → раздел «Сервис авторизации
   VK ID» → создать приложение.
2. Тип — **Standalone-приложение** (НЕ Mini App/Сайт с виджетами).
3. Заполнить:
   - **Базовый домен**: `random.ekb-guide.ru`
   - **Доверенный Redirect URL**: `https://random.ekb-guide.ru/api/vk/oauth/callback`
4. Сохранить и скопировать только **ID приложения** (Application ID) —
   это `VK_APP_ID`. «Защищённый ключ» здесь не нужен, его копировать не
   надо.

### 2. Прописать .env и перезапустить сервис

```bash
nano /root/random-giveaway/randomgiveaway/.env
```
```
VK_APP_ID=...
VK_OAUTH_REDIRECT_URI=https://random.ekb-guide.ru/api/vk/oauth/callback
```
```bash
sudo supervisorctl restart random-giveaway-api
```

### 3. Пройти разовую авторизацию

Как и с Instagram, `/api/vk/oauth/start` защищён `ADMIN_TOKEN` — берём
ссылку curl'ом, открываем в браузере:

```bash
cd /root/random-giveaway
ADMIN=$(grep '^ADMIN_TOKEN=' randomgiveaway/.env | cut -d= -f2)
curl -si -H "X-Admin-Token: $ADMIN" https://random.ekb-guide.ru/api/vk/oauth/start | grep -i '^location'
```

Открыть полученную ссылку в браузере, залогинившись в VK тем аккаунтом,
что администрирует ЕКБ ГИД → разрешить доступ. VK редиректнёт на
`/callback` вместе с `device_id`, который тоже нужно сохранить — сервис
делает это сам вместе с обменом кода на `access_token`/`refresh_token` и
записью в `.env`. Страница ответит «VK подключён».

Перезапустить сервис:
```bash
sudo supervisorctl restart random-giveaway-api
```

### 4. Автопродление токена (обязательно, в отличие от старой модели)

Токен VK ID короткоживущий — без автопродления по `refresh_token`
перестанет работать в течение суток. Добавить в cron под root:

```bash
crontab -e
```
```
0 * * * * cd /root/random-giveaway && venv/bin/python -m randomgiveaway.scripts.refresh_vk_token >> /var/log/random-giveaway-vk-token-refresh.log 2>&1
```

### 5. Проверка

```bash
curl -s -X POST https://random.ekb-guide.ru/api/giveaways \
  -H "X-Admin-Token: $ADMIN" -H "Content-Type: application/json" \
  -d '{"source":"vk","post_url":"https://vk.com/wall-XXXXXXX_YYY","settings":{"winners_count":1}}'
```
дальше `POST /api/giveaways/{id}/load-comments` с тем же заголовком —
должен вернуться тот же формат предпросмотра, что и для `/import`.

Ссылку на пост можно скопировать прямо из VK (кнопка «Поделиться» → «Скопировать ссылку
на запись», либо из адресной строки при открытом посте) — адаптер
распознаёт разные формы ссылки (`vk.com/wall-123_456`,
`vk.com/club123?w=wall-123_456` и т.п.), важно только чтобы в ней
присутствовал фрагмент `wall<id>_<id>`.

**Если VK ответит ошибкой про версию API** (`error_code` про
устаревший/неподдерживаемый `v`) — версия API захардкожена в
`randomgiveaway/adapters/vk_adapter.py` и `services/vk_oauth.py`
(`VK_API_VERSION`), актуальный список версий смотреть на `dev.vk.com`,
поправить константу на свежую.

## Подключение Telegram

**Важно, отличается от Instagram/VK:** Telegram Bot API не даёт боту читать
историю уже написанных сообщений — только то, что приходит, пока бот
подключён. Поэтому Telegram реализован не как адаптер чтения комментариев,
а как отдельный бот с механикой «нажми Участвую → приглашай друзей за
дополнительные шансы»:

1. Организатор пишет текст поста на сайте (и опционально прикладывает
   картинку — тогда пост уходит через `sendPhoto`, текст становится
   подписью с лимитом Telegram в 1024 символа вместо обычных 4096) →
   `POST /telegram/publish` публикует его в канал ekb_guide с кнопкой-
   ссылкой **«Участвую 🎉»**, которая открывает приватный чат с ботом
   (`t.me/<бот>?start=join_<id>`) — именно поэтому это ссылка-кнопка, а не
   обычный callback: только так бот может сразу ответить пользователю
   личным сообщением без ограничений на «холодные» DM от ботов.
2. `/start join_<id>` → бот проверяет подписку на канал (`getChatMember`) →
   регистрирует участника → присылает его личную реферальную ссылку
   `t.me/<бот>?start=ref_<id>_<user_id>`.
3. `/start ref_<id>_<referrer>` → так же регистрирует нового участника
   (после проверки подписки) и добавляет пригласившему дополнительный
   «билет» — до потолка `TELEGRAM_MAX_REFERRALS` (антифрод, засчитывается
   только если пригласивший сам уже участвует).
4. Вес участника — то же поле `comment_count`, что и для «1 комментарий = 1
   шанс» у Instagram/VK (§7.3 ТЗ), просто переиспользуется под число
   билетов — отдельного движка розыгрыша для Telegram нет.
5. Подписка засчитывается **на момент розыгрыша, а не клика** — прямо перед
   `POST /draw` для Telegram-розыгрыша сервис ещё раз проверяет подписку
   всех участников и исключает отписавшихся
   (`services/telegram_giveaway.resync_membership_and_exclude`).

Никакого отдельного долгоживущего процесса/Supervisor-сервиса для этого не
заводится — всё внутри уже работающего FastAPI-приложения (`/api/telegram/webhook`),
нужна только отдельная «личность» бота (токен).

### 1. Завести бота

1. В Telegram написать **@BotFather** → `/newbot` → задать имя и username
   (например `ekb_guide_giveaway_bot`). Это **новый, отдельный бот**, не
   тот, что в `bot/` (тот занят AI-рерайтом контента, не розыгрышами).
2. Скопировать выданный токен — это `TELEGRAM_BOT_TOKEN`.
3. Добавить бота **администратором канала ekb_guide** с правом публикации
   сообщений (без этого он не сможет опубликовать пост розыгрыша).

### 2. Прописать .env и перезапустить сервис

```bash
nano /root/random-giveaway/randomgiveaway/.env
```
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHANNEL=@ekb_guide
TELEGRAM_WEBHOOK_SECRET=<любая случайная строка>
TELEGRAM_MAX_REFERRALS=15
```
```bash
sudo supervisorctl restart random-giveaway-api
```

### 3. Зарегистрировать вебхук (разово)

Telegram должен знать, куда слать апдейты — один HTTP-запрос (можно прямо
curl'ом, отдельного эндпоинта в самом сервисе для этого нет):

```bash
TOKEN=<TELEGRAM_BOT_TOKEN>
SECRET=<тот же TELEGRAM_WEBHOOK_SECRET, что и в .env>
curl -s "https://api.telegram.org/bot$TOKEN/setWebhook" \
  -d "url=https://random.ekb-guide.ru/api/telegram/webhook" \
  -d "secret_token=$SECRET"
```
Ответ должен содержать `"ok":true`.

### 4. Проверка

На сайте выбрать источник «Telegram», ввести текст поста → «Опубликовать в
Telegram» — пост должен появиться в канале с кнопкой «Участвую». Нажать её
(с любого Telegram-аккаунта, подписанного на канал) — бот должен ответить
в личном чате подтверждением и личной реферальной ссылкой. Счётчик
участников на сайте обновится в течение нескольких секунд (опрос раз в
4 секунды).

## API (§20 ТЗ, пути ориентировочные)

```text
POST /api/giveaways
GET  /api/giveaways/{id}
POST /api/giveaways/{id}/import                # CSV/JSON/список (form-data: file, format)
POST /api/giveaways/{id}/load-comments          # живой источник по ссылке; instagram/vk
POST /api/giveaways/{id}/participants/process   # предпросмотр (§8 ТЗ)
GET  /api/giveaways/{id}/participants           # список участников — для анимации на фронтенде
POST /api/giveaways/{id}/draw
GET  /api/giveaways/{id}/result
GET  /api/results/{public_id}                   # публично, без авторизации

GET  /api/instagram/oauth/start                 # разовая привязка ekb_guide, требует ADMIN_TOKEN
GET  /api/instagram/oauth/callback              # редирект от Instagram, вызывать вручную не нужно
GET  /api/vk/oauth/start                        # разовая привязка ekb_guide, требует ADMIN_TOKEN
GET  /api/vk/oauth/callback                     # редирект от VK, вызывать вручную не нужно
POST /api/giveaways/{id}/telegram/publish       # публикует пост с кнопкой "Участвую", требует ADMIN_TOKEN
POST /api/telegram/webhook                      # апдейты от Telegram, вызывать вручную не нужно
```
