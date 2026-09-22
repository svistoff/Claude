"""Типы результатов выдачи и статусы проверки.

См. разделы 3 и 6 ТЗ v2:
- позиция считается по органической выдаче (`ResultType.ORGANIC`);
- колдунщики и реклама в органическую позицию не входят;
- блок Яндекс.Бизнеса (`ResultType.BUSINESS`) трекается отдельной метрикой.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .normalize import normalize_host


class ResultType(str, Enum):
    """Тип элемента поисковой выдачи.

    Только ORGANIC участвует в расчёте органической позиции.
    BUSINESS участвует в отдельной метрике «позиция в блоке Бизнеса».
    Остальные типы сохраняются в БД для аудита, но в нумерации позиции
    не участвуют.
    """

    ORGANIC = "organic"          # обычный органический результат
    AD_TOP = "ad_top"            # реклама сверху (Директ)
    AD_BOTTOM = "ad_bottom"      # реклама снизу
    BUSINESS = "business"        # элемент блока Яндекс.Бизнеса / организаций
    MAPS = "maps"                # блок Карт
    VIDEO = "video"              # видео-колдунщик
    IMAGES = "images"            # картинки
    MARKET = "market"            # товары / Маркет
    FAST_ANSWER = "fast_answer"  # быстрый ответ / featured-блок
    OTHER = "other"              # прочие вертикальные блоки


class CheckStatus(str, Enum):
    """Статус проверки / прогона выборки выдачи (разделы 35-36 ТЗ)."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"        # выдача получена, сайт найден
    NOT_FOUND = "NOT_FOUND"    # выдача получена, сайт не найден в пределах глубины
    ERROR = "ERROR"            # техническая ошибка — позиция НЕ записывается
    BLOCKED = "BLOCKED"        # блокировка Яндекса — позиция НЕ записывается
    CAPTCHA = "CAPTCHA"        # капча не решена — позиция НЕ записывается

    @property
    def is_confirmed(self) -> bool:
        """Статус, при котором результат считается подтверждённым.

        Только SUCCESS и NOT_FOUND формируют историю позиций и служат базой
        для сравнений «было → стало» (раздел 4.1 ТЗ). ERROR/BLOCKED/CAPTCHA
        не записываются как позиция и пропускаются при выборе базы.
        """
        return self in (CheckStatus.SUCCESS, CheckStatus.NOT_FOUND)


@dataclass(slots=True)
class SerpResult:
    """Один элемент поисковой выдачи, как он получен от провайдера.

    `raw_position` — порядковый номер в ПОЛНОЙ выдаче (включая рекламу и
    колдунщиков), как её отдал источник. Органическая позиция вычисляется
    отдельно в `posmon.domain.position` и с `raw_position` не совпадает.
    """

    url: str
    result_type: ResultType = ResultType.ORGANIC
    title: str | None = None
    snippet: str | None = None
    raw_position: int | None = None

    @property
    def host(self) -> str:
        """Нормализованный хост результата (lowercase, без схемы/пути/порта)."""
        return normalize_host(self.url)
