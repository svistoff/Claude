"""Instagram-адаптер — заготовка под Этап 4, не реализован в Этапе 1.

Решение по скоупу (принято в обсуждении задачи, см. randomgiveaway/README.md):

Instagram Graph API не даёт доступа к комментариям ЧУЖИХ постов, даже если
у нас есть свой подключённый Business/Creator-аккаунт — Business Discovery
отдаёт только агрегированные метрики (счётчики), а не сами комментарии.
Прочитать содержимое комментариев с username автора можно только для медиа,
которым владеет сам авторизованный аккаунт.

Поэтому раздел ТЗ "организатор вставляет ссылку на произвольный пост"
для Instagram сужен до: розыгрыши проводятся только в постах самого
ekb_guide. Доступ — через собственный long-lived access-токен, полученный
один раз через Meta App в Development mode (ekb_guide добавлен как
Tester/Admin приложения), без App Review и без OAuth-экрана для внешних
организаторов — их аккаунты в этой схеме не участвуют.

Токен живёт ограниченное время (~60 дней) и требует программного
продления (refresh) до истечения — это отдельная фоновая задача,
не входящая в Этап 1.
"""
from __future__ import annotations

from randomgiveaway.adapters.base import RawComment, SourceAdapter


class InstagramAdapter(SourceAdapter):
    name = "instagram"

    def __init__(self, access_token: str | None):
        self._access_token = access_token

    async def fetch_comments(self, post_url: str) -> list[RawComment]:
        raise NotImplementedError(
            "Instagram-адаптер ещё не реализован (Этап 4: /{media-id}/comments "
            "через Graph API, только для постов ekb_guide). "
            "На Этапе 1 используйте ImportAdapter (CSV/JSON) для тестирования ядра."
        )
