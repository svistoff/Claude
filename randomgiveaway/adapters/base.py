"""Абстрактный слой источников (§3, §18 ТЗ) — ядро не должно знать об API конкретной платформы."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RawComment:
    """Единый нормализованный формат комментария независимо от источника."""

    comment_id: str
    source_user_id: str
    username: str | None
    display_name: str | None
    text: str
    is_reply: bool
    parent_comment_id: str | None = None


class SourceAdapterError(Exception):
    """Ошибка получения данных из источника — сообщение уже готово для показа
    пользователю (§6, §26 ТЗ: «Не удалось получить комментарии. Причина: ...»)."""


class SourceAdapter(ABC):
    """Общий интерфейс для Instagram/VK/Telegram/Import-адаптеров.

    Random Engine и остальное ядро работают только со списком RawComment —
    смена/поломка API конкретной площадки не должна требовать переделки
    механизма розыгрыша (§18, §36 ТЗ).
    """

    name: str

    @abstractmethod
    async def fetch_comments(self, post_url: str) -> list[RawComment]:
        """Возвращает нормализованный список комментариев к посту."""
