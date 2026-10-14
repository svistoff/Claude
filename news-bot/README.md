# news-bot — «Новости одной строкой»

Бот **@EG_newsbot** + сайт **https://news.ekb-guide.ru** + виджет для Tilda.

Пользователь пересылает боту готовую новость из канала «На выкладку»
(текст, фото, видео, альбом). Бот:

1. делит пост на **заголовок** (жирная первая строка), **описание**
   (курсив под ней) и **полный текст**. Нет разметки — разбор через OpenAI,
   AI недоступен — первая строка / вторая строка / остальное;
2. копирует фото/видео (по `file_id`, без перезаливки) в приватный
   канал-хранилище `-1004302958010` — тот же, что у афиши;
3. **сразу публикует**: строки в `news` + `news_media` (Supabase, service_role);
4. отвечает карточкой со ссылкой и кнопками «🙈 Скрыть» / «🗑 Удалить».

Повторная пересылка того же поста (`origin_key = <chat_id>:<message_id>`)
дубль не создаёт. Видео > 20 МБ пропускается (Bot API не отдаёт такие файлы).
Команды: `/start`, `/help`, `/last` (последние 10, со скрытием/возвратом).

## Где что лежит на сервере (`magic-copper`, 45.146.90.128)

| Что | Где |
|---|---|
| Код бота и прокси | `/root/news-bot` (копия `news-bot/` без `site/`), свой `venv` |
| Секреты | `/root/news-bot/bot/.env` (`chmod 600`, в git не попадает) |
| Supervisor | `news-bot` (`python -m bot.bot`), `news-media-proxy` (`python -m bot.proxy.server`, `127.0.0.1:8093`) |
| Логи | `/var/log/news-bot.err.log`, `/var/log/news-media-proxy.err.log` (logging пишет в `.err.log` — это норма) |
| Медиа в браузер | `https://video.ekb-guide.ru/m/<token>` → `location /m/` в `/etc/nginx/sites-available/video.ekb-guide.ru.conf` → 8093 (`/v/` — по-прежнему афиша, 8092) |
| Сайт | nginx `/etc/nginx/sites-available/news.ekb-guide.ru`, `root /root/afisha-news-bot/news-bot/site`, PHP 8.3-FPM, SSL от certbot |
| Клон репозитория для сайта | `/root/afisha-news-bot`, ветка `claude/news-bot` — **отдельный** от `/root/claude-repo` (там ветка и сайт афиши) |
| БД | Supabase, таблицы `news`, `news_media` — `sql/news.sql` (запускать в SQL Editor, повторный запуск безопасен) |

## Сайт `site/`

- `index.html` — лента (по 20, «Показать ещё»). Пункты — настоящие ссылки на
  `/n/<slug>`; клик открывает окно (полный текст, фото/видео, «Поделиться») и
  через `history.pushState` ставит `/n/<slug>` в адресную строку, «Назад»
  закрывает окно. Старый вид ссылки `https://news.ekb-guide.ru/#<slug>` тоже открывает окно.
- `news.php` — SEO-страница `/n/<slug>`: title/description, Open Graph
  (`og:image` = первое фото), Schema.org `NewsArticle`. Скрытая/удалённая → 404.
- `sitemap.php` (`/sitemap.xml`), `robots.txt`, `sb-config.php` (наружу не отдаётся).
- `news-embed.js` — виджет для Tilda.

Браузер ходит только на `https://sb.ekb-guide.ru` (прокси Supabase, anon-ключ)
и `https://video.ekb-guide.ru` (медиа). RLS отдаёт только `status='published'`,
служебные колонки (`file_id`, `origin_key`, …) anon не видит.

## Виджет для Tilda

Блок «Другое → T123 HTML-код»:

```html
<div id="ekb-news-widget"></div>
<script src="https://news.ekb-guide.ru/news-embed.js?v=4" defer></script>
```

Атрибуты `<script>`: `data-target` (id контейнера), `data-limit` (по умолчанию 5).
Рендер в Shadow DOM, окно — `position:fixed; z-index:2147483000` прямо в `<body>`.
Открытая новость отражается в адресе страницы как `?news=<slug>` (адрес другого домена
браузер поставить не даёт); по такой ссылке страница Tilda открывается сразу с новостью.
При изменении `news-embed.js` поднимать `?v=` в коде на Tilda. В редакторе Tilda
скрипты не выполняются — проверять на опубликованной странице.

## Обновление

```bash
# сайт (index.html, news.php, news-embed.js …)
cd /root/afisha-news-bot && git pull --ff-only

# бот / прокси
cd /root/afisha-news-bot && git pull --ff-only
rsync -a --delete --exclude venv --exclude bot/.env --exclude __pycache__ --exclude site \
  /root/afisha-news-bot/news-bot/ /root/news-bot/
/root/news-bot/venv/bin/pip install -q -r /root/news-bot/requirements.txt
supervisorctl restart news-bot news-media-proxy
```

## Первичная установка (уже сделано 14.10.2026, для справки)

```bash
mkdir -p /root/news-bot && rsync -a --exclude site /root/afisha-news-bot/news-bot/ /root/news-bot/
cd /root/news-bot && python3.12 -m venv venv && venv/bin/pip install -r requirements.txt
# .env: длинные секреты копируем из афиши, руками не вставляем
grep -E '^(OPENAI_API_KEY|OPENAI_MODEL|SUPABASE_URL|SUPABASE_SERVICE_KEY|ALLOWED_USER_ID|TELEGRAM_STORAGE_CHANNEL_ID|TZ_OFFSET)=' \
  /root/afisha-bot/bot/.env > /root/news-bot/bot/.env
# + остальные ключи из .env.example; токен — через `read -rsp` (не в истории)
cp deploy/supervisor/*.conf /etc/supervisor/conf.d/ && supervisorctl reread && supervisorctl update
# nginx: deploy/nginx/video.ekb-guide.ru.location-m.conf → в 443-server video.ekb-guide.ru перед location /
#        deploy/nginx/news.ekb-guide.ru.conf → sites-available + ссылка в sites-enabled, certbot --nginx -d news.ekb-guide.ru
nginx -t && systemctl reload nginx
```

Проверка: `curl -s -o /dev/null -w "%{http_code}" https://video.ekb-guide.ru/m/test` → 404,
`…/v/test` → 404 (афиша жива), `https://news.ekb-guide.ru/` → 200.

Бот должен быть администратором канала-хранилища (публикация и удаление сообщений).
