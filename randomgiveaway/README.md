# Random.ЕКБ ГИД — генератор победителей розыгрышей

Реализация Этапа 1 ("Ядро") из ТЗ: создание розыгрыша, импорт участников,
нормализация, фильтрация по правилам, криптостойкий случайный выбор
победителей и запасных, сохранение результата с хэш-фиксацией. Без
фронтенда/анимации (Этап 2) и без живых интеграций с соцсетями (Этап 4) —
см. раздел «Что не сделано» ниже.

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

## Что не сделано (следующие этапы)

- **Этап 2** — фронтенд, полноэкранная анимация, конфетти
- **Этап 3** — публичная HTML-страница результата (сейчас есть только JSON API)
- **Этап 4** — реализация `InstagramAdapter`/`VKAdapter`/`TelegramAdapter`
  (сейчас — заглушки с понятным `NotImplementedError`, см. `adapters/`);
  плюс фоновая задача обновления Instagram-токена (~60 дней)
- **Этап 5** — админка, логи, история розыгрышей для пользователя

## Локальный запуск

```bash
cd randomgiveaway
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
venv/bin/uvicorn randomgiveaway.main:app --reload --port 8001
```

Открыть `http://127.0.0.1:8001/docs` — интерактивная документация API.

## Тесты

```bash
cd randomgiveaway
venv/bin/pytest
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

# 2. Окружение
python3 -m venv venv
venv/bin/pip install -r randomgiveaway/requirements.txt
cp randomgiveaway/.env.example randomgiveaway/.env
nano randomgiveaway/.env   # задать ADMIN_TOKEN (случайная строка), остальное можно оставить по умолчанию

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

`https://random.ekb-guide.ru/docs` откроет интерактивную документацию API.
Открыть в браузере сам `random.ekb-guide.ru` пока бессмысленно — фронтенда
нет (Этап 2), есть только JSON API.

После обновления кода на сервере: `git pull`, при необходимости
`venv/bin/pip install -r randomgiveaway/requirements.txt`, затем
`sudo supervisorctl restart random-giveaway-api`.

## API (§20 ТЗ, пути ориентировочные)

```text
POST /api/giveaways
GET  /api/giveaways/{id}
POST /api/giveaways/{id}/import                # CSV/JSON/список (form-data: file, format)
POST /api/giveaways/{id}/load-comments          # живые источники — 501 на Этапе 1
POST /api/giveaways/{id}/participants/process   # предпросмотр (§8 ТЗ)
POST /api/giveaways/{id}/draw
GET  /api/giveaways/{id}/result
GET  /api/results/{public_id}                   # публично, без авторизации
```
