"""Статические страницы Privacy Policy / Terms — обязательны для публикации
Meta-приложения (см. randomgiveaway/README.md, раздел «Подключение Instagram»).

Текст намеренно простой и честный, без юридического шаблона общего назначения —
описывает ровно то, что сервис реально делает на Этапе 1.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_STYLE = """
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 720px;
         margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #1a1a1a; }
  h1 { font-size: 1.6rem; } h2 { font-size: 1.2rem; margin-top: 2rem; }
  a { color: #0b5fff; }
</style>
"""

_PRIVACY_HTML = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Политика конфиденциальности — Random.ЕКБ ГИД</title>{_STYLE}</head>
<body>
<h1>Политика конфиденциальности</h1>
<p>Сервис Random.ЕКБ ГИД (random.ekb-guide.ru) — инструмент для проведения
розыгрышей ЕКБ ГИД (ekb_guide) в социальных сетях.</p>

<h2>Какие данные обрабатываются</h2>
<p>Для проведения розыгрыша сервис получает публичные комментарии к постам
аккаунта ekb_guide через официальный Instagram API (с согласия владельца
аккаунта ekb_guide), либо через ручной импорт файла (CSV/JSON) — в обоих
случаях: username автора комментария, текст комментария, отметку об ответе
на другой комментарий. Полные тексты комментариев не хранятся дольше, чем
требуется для формирования списка участников розыгрыша.</p>

<h2>Зачем это нужно</h2>
<p>Данные используются исключительно для формирования списка участников
розыгрыша, применения условий отбора (заданных организатором) и случайного
выбора победителей. Результат розыгрыша (username победителей, дата,
количество участников) публикуется на публичной странице результата
сервиса.</p>

<h2>Передача третьим лицам</h2>
<p>Данные не продаются и не передаются третьим лицам, за исключением
инфраструктуры, необходимой для работы сервиса (хостинг).</p>

<h2>Удаление данных</h2>
<p>Запросить удаление данных, связанных с конкретным розыгрышем или
комментарием, можно, написав в Instagram
<a href="https://www.instagram.com/ekb_guide/">@ekb_guide</a>.</p>

<h2>Контакты</h2>
<p>По вопросам обработки данных — через Instagram
<a href="https://www.instagram.com/ekb_guide/">@ekb_guide</a>.</p>
</body></html>
"""

_TERMS_HTML = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Условия использования — Random.ЕКБ ГИД</title>{_STYLE}</head>
<body>
<h1>Условия использования</h1>
<p>Random.ЕКБ ГИД (random.ekb-guide.ru) — внутренний инструмент ЕКБ ГИД
(ekb_guide) для проведения розыгрышей в социальных сетях: случайный выбор
победителей среди участников, оставивших комментарии к посту, с фиксацией
и публикацией результата.</p>

<h2>Кто использует сервис</h2>
<p>Сервис используется для проведения розыгрышей на собственных публикациях
ekb_guide. Подключение сторонних Instagram-аккаунтов через этот сервис не
предусмотрено.</p>

<h2>Случайный выбор</h2>
<p>Выбор победителей выполняется криптостойким генератором случайных чисел,
независимо от визуального представления процесса. Состав участников и
результат фиксируются хэшем на момент проведения розыгрыша.</p>

<h2>Контакты</h2>
<p>По вопросам использования сервиса — через Instagram
<a href="https://www.instagram.com/ekb_guide/">@ekb_guide</a>.</p>
</body></html>
"""


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_policy() -> str:
    return _PRIVACY_HTML


@router.get("/terms", response_class=HTMLResponse, include_in_schema=False)
async def terms_of_service() -> str:
    return _TERMS_HTML
