# AI-компаньон бот (aiogram 3 + OpenAI + Telegram Stars)

Telegram-бот с одним AI-персонажем — Лиза, универсальный дружелюбный
характер. Общение бесплатно в пределах дневного лимита сообщений; после
лимита — донат через Telegram Stars продлевает общение на сегодня
(вместо жёсткого paywall).

Персонаж явно представляется как AI в приветственном сообщении и обязан
честно подтверждать это при прямом вопросе — см. `persona.py`.

## Архитектура

- `persona.py` — характер персонажа как шаблон (`Persona`, `PERSONAS`),
  задел на несколько архетипов в будущем; сейчас подключён только
  `universal`.
- `services/ai.py` — вызов OpenAI с системным промтом персонажа и
  историей диалога.
- `services/history.py` — хранение/выборка последних сообщений для
  контекста AI (`HISTORY_LIMIT` в `.env`).
- `services/usage.py` — дневной бесплатный лимит сообщений + бонусные
  сообщения, начисленные за донат.
- `services/payments.py` — инвойс на Telegram Stars (`currency="XTR"`,
  `provider_token=""` — так требует Telegram именно для Stars).
- `handlers/payments.py` — подтверждение `pre_checkout_query` и
  обработка `successful_payment` (начисление бонусных сообщений).
- `database/database.py` — SQLite: `users`, `messages` (история для
  контекста AI), `payments` (для будущих метрик — MRR, ARPPU).

## Установка

```bash
cd companion_bot
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # обязательны BOT_TOKEN и OPENAI_API_KEY
```

Запуск из корня репозитория (интерактивно, чтобы сразу увидеть логи):

```bash
python -m companion_bot.bot
```

Проверка: напишите боту `/start`, затем любое сообщение — должен ответить
персонаж. Отправьте больше `FREE_MESSAGES_PER_DAY` сообщений подряд —
должен прийти инвойс на Stars.

## Деплой на VPS через Supervisor

Конфиг — `deploy/supervisor/ai-companion-bot.conf` (общие правила деплоя
на этом VPS — в корневом `CLAUDE.md`: всё через Supervisor, боты живут в
`/root/<имя>`, логи — в `/var/log/<имя>.{out,err}.log`).

```bash
sudo cp deploy/supervisor/ai-companion-bot.conf /etc/supervisor/conf.d/
sudo supervisorctl reread && sudo supervisorctl update
sudo supervisorctl start ai-companion-bot
```

Бот сам создаёт SQLite-файл и таблицы при первом старте.

## Что дальше (следующие этапы, не реализовано)

- Долгосрочная память фактов о пользователе (сейчас — только последние
  `HISTORY_LIMIT` сообщений диалога, без выжимки/summary).
- Фото и голосовые сообщения персонажа.
- Несколько архетипов персонажа (`PERSONAS`) и выбор при `/start`.
- Подписка (Premium) как альтернатива разовым донатам.
- Простая админка/дашборд по `users`/`payments` для метрик (конверсия,
  ARPPU, MRR).
