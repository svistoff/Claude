"""VK-адаптер — заготовка под Этап 4, не реализован в Этапе 1.

В отличие от Instagram, VK API (wall.getComments по owner_id+post_id)
не требует авторизации от автора поста — достаточно токена сообщества
ЕКБ ГИД, чтобы читать комментарии к публичным постам ЕКБ ГИД. Скоуп по
факту совпадает с общим решением (см. instagram_adapter.py и README.md):
розыгрыши проводятся в постах самого ekb_guide, не сторонних организаторов.
"""
from __future__ import annotations

from randomgiveaway.adapters.base import RawComment, SourceAdapter


class VKAdapter(SourceAdapter):
    name = "vk"

    def __init__(self, community_token: str | None):
        self._community_token = community_token

    async def fetch_comments(self, post_url: str) -> list[RawComment]:
        raise NotImplementedError(
            "VK-адаптер ещё не реализован (Этап 4: wall.getComments для "
            "постов сообщества ekb_guide). "
            "На Этапе 1 используйте ImportAdapter (CSV/JSON) для тестирования ядра."
        )
