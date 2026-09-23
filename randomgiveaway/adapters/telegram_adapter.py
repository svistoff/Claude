"""Telegram-адаптер — заготовка под Этап 4, не реализован в Этапе 1.

Комментарии к посту в канале — это сообщения в привязанной группе
обсуждений. Если группа обсуждений канала ekb_guide публичная, доступ
не требует авторизации от организатора: бот (добавленный в группу) или
MTProto-сессия читают сообщения напрямую. Скоуп совпадает с общим решением
(см. instagram_adapter.py и README.md): только собственные посты ekb_guide.
"""
from __future__ import annotations

from randomgiveaway.adapters.base import RawComment, SourceAdapter


class TelegramAdapter(SourceAdapter):
    name = "telegram"

    def __init__(self, session: str | None):
        self._session = session

    async def fetch_comments(self, post_url: str) -> list[RawComment]:
        raise NotImplementedError(
            "Telegram-адаптер ещё не реализован (Этап 4: чтение сообщений "
            "группы обсуждений канала ekb_guide). "
            "На Этапе 1 используйте ImportAdapter (CSV/JSON) для тестирования ядра."
        )
