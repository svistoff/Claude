# Браузерный сбор (персонализированные профили + боевая выдача с рекламой)

Браузерный сбор через Playwright + Chromium нужен для:
- **боевого режима** (`battle`) — реальная выдача с рекламой (API рекламу не отдаёт);
- **персонализированных профилей** «Екатеринбуржец» и «Приезжий».

Всё выполняется на VPS в `/root/posmon`.

## Шаг 1. Установить Chromium для Playwright

```bash
cd /root/posmon
.venv/bin/pip install -r posmon/requirements.txt      # подтянет beautifulsoup4
.venv/bin/playwright install chromium
.venv/bin/playwright install-deps chromium            # системные библиотеки (apt)
```

Проверка:
```bash
.venv/bin/python -c "from playwright.sync_api import sync_playwright;
p=sync_playwright().start(); b=p.chromium.launch(); print('chromium ok'); b.close(); p.stop()"
```

## Шаг 2. Настройки в `.env`

```
BROWSER_HEADLESS=true            # на сервере без экрана
BROWSER_SAVE_HTML=true           # сохранять HTML выдачи (для подгонки парсера)
# опционально:
CAPTCHA_PROVIDER=rucaptcha       # решение SmartCaptcha
CAPTCHA_API_KEY=...
BROWSER_PROXY=                    # http://user:pass@host:port (если начнёт блокировать)
BATTLE_CHECK_ENABLED=true         # дневной боевой автопрогон
BATTLE_CHECK_TIME=19:00
```
Перезапуск: `supervisorctl restart posmon-web posmon-scheduler`.

## Шаг 3. Создать браузерный профиль

В админке: проект → Профили → добавить профиль с источником **browser**
(например «Екатеринбуржец», устройство desktop). Путь профиля создаётся
автоматически в `posmon/browser_profiles/profile-<id>`.

## Шаг 4. Пробный запуск и подгонка парсера

Нажми «Проверить — боевой» (или для браузерного профиля — «Проверить — SEO»).
Первый прогон сохранит HTML выдачи в `posmon/artifacts/`.

Проверить статусы:
```bash
cd /root/posmon
.venv/bin/python -c "
import asyncio
from sqlalchemy import select, func
from posmon.db import get_sessionmaker
from posmon.models import CheckRun
async def main():
    async with get_sessionmaker()() as s:
        rows=(await s.execute(select(CheckRun.status, func.count()).group_by(CheckRun.status))).all()
        print(dict(rows))
asyncio.run(main())
"
```

Если позиции по браузерному профилю не распарсились (пусто/NOT_FOUND там, где
ожидается), пришли **один свежий HTML** из `posmon/artifacts/` — по нему точно
настрою селекторы парсера под текущую верстку Яндекса:
```bash
ls -t /root/posmon/posmon/artifacts/*.html | head -1
```

## Замечания

- **Пейсинг** (`BROWSER_PACE_MIN/MAX`) держит паузы между выборками — не убирай,
  это защита от блокировок.
- **Капча**: без ключа сервиса прогон, встретив капчу, вернёт статус `CAPTCHA`
  (позиция не пишется). С ключом — попробует решить.
- **Прокси**: датацентр-IP VPS может капчить чаще; при росте блокировок добавь
  резидентский прокси в `BROWSER_PROXY`.
