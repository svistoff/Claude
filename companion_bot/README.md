# AI-компаньон бот (aiogram 3 + OpenAI + Telegram Stars)

Telegram-бот с одним AI-персонажем — Лиза, универсальный дружелюбный
характер. Общение бесплатно в пределах дневного лимита сообщений; после
лимита — донат через Telegram Stars продлевает общение на сегодня
(вместо жёсткого paywall). Персонаж помнит долгосрочные факты о
пользователе, иногда "занята" и отвечает с задержкой, и иногда пишет
первой, если давно не общались.

Персонаж явно представляется как AI в приветственном сообщении и обязан
честно подтверждать это при прямом вопросе — см. `persona.py`.

## Архитектура

- `persona.py` — характер персонажа как шаблон (`Persona`, `PERSONAS`),
  задел на несколько архетипов в будущем; сейчас подключён только
  `universal`.
- `services/ai.py` — вызов OpenAI с системным промтом персонажа и
  историей диалога.
- `services/history.py` — хранение/выборка последних сообщений для
  краткосрочного контекста AI (`HISTORY_LIMIT` в `.env`).
- `services/memory.py` — долгосрочная память: раз в
  `MEMORY_SUMMARY_EVERY_N_MESSAGES` новых сообщений AI обновляет краткую
  сводку фактов о пользователе (`users.memory_summary`), которая
  передаётся в system prompt вместе с последними сообщениями — а не
  вместо них.
- `services/usage.py` — дневной бесплатный лимит сообщений + бонусные
  сообщения, начисленные за донат; `record_payment`/`add_bonus_messages`
  пишут в `payments` для будущих метрик.
- `services/payments.py` — два инвойса на Telegram Stars
  (`currency="XTR"`, `provider_token=""` — так требует Telegram именно
  для Stars): продление дневного лимита и "ответить сейчас" (пропустить
  задержку "занятости").
- `handlers/messages.py` — с вероятностью `BUSY_PROBABILITY` персонаж
  "занята": сразу шлёт короткое сообщение об этом и кладёт реальный
  ответ в очередь `pending_replies` на случайную задержку
  (`BUSY_DELAY_MIN/MAX_MINUTES`), вместо мгновенного ответа.
- `worker/scheduler.py` — два фоновых цикла (опрос БД, не
  `asyncio.sleep` на сообщение — переживают перезапуск бота):
  доставка отложенных ("занята") ответов и проактивные сообщения
  персонажа ("как дела?") пользователям, которые давно не писали
  (`PROACTIVE_MIN/MAX_HOURS_SINCE_LAST_MESSAGE`, `PROACTIVE_PROBABILITY`,
  не чаще раза в 24 часа на пользователя).
- `handlers/payments.py` — подтверждение `pre_checkout_query`;
  `successful_payment` либо начисляет бонусные сообщения, либо (для
  "ответить сейчас") сразу доставляет последний отложенный ответ.
- `database/database.py` — SQLite: `users` (лимиты, бонусы, память,
  когда персонаж писал первой), `messages` (история для контекста AI),
  `payments` (для будущих метрик — MRR, ARPPU), `pending_replies`
  (очередь отложенных ответов).

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

- Фото и голосовые сообщения персонажа — требует решения по провайдеру
  (TTS: OpenAI TTS vs ElevenLabs; фото: заранее подготовленный набор
  изображений одного персонажа vs генерация на лету) до начала работы.
- Несколько архетипов персонажа (`PERSONAS`) и выбор при `/start`.
- Подписка (Premium) как альтернатива разовым донатам.
- Простая админка/дашборд по `users`/`payments` для метрик (конверсия,
  ARPPU, MRR).
