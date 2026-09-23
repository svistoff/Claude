"""Импорт участников из CSV/JSON/текстового списка (§19 ТЗ).

Позволяет тестировать и использовать генератор независимо от готовности
живых интеграций с соцсетями — на Этапе 1 это единственный рабочий источник.
"""
from __future__ import annotations

import csv
import io
import json

from randomgiveaway.adapters.base import RawComment, SourceAdapter, SourceAdapterError


class ImportAdapter(SourceAdapter):
    """Не получает данные по URL (это push-источник — данные приходят файлом),
    поэтому используется через parse_csv/parse_json/parse_username_list,
    а не через fetch_comments."""

    name = "import"

    async def fetch_comments(self, post_url: str) -> list[RawComment]:
        raise NotImplementedError(
            "ImportAdapter не работает по ссылке на пост — используйте "
            "parse_csv / parse_json / parse_username_list с загруженным файлом."
        )

    @staticmethod
    def parse_csv(raw: bytes) -> list[RawComment]:
        """Ожидаемые колонки: user_id,username,display_name,comment_id,text,is_reply,parent_comment_id.
        Обязательна только user_id (или username, если user_id пуст)."""
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SourceAdapterError("Файл должен быть в кодировке UTF-8") from exc

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise SourceAdapterError("Пустой CSV-файл или отсутствует заголовок")

        comments: list[RawComment] = []
        for i, row in enumerate(reader):
            user_id = (row.get("user_id") or row.get("username") or "").strip()
            if not user_id:
                raise SourceAdapterError(f"Строка {i + 2}: не указан user_id или username")
            username = (row.get("username") or "").strip() or None
            comments.append(
                RawComment(
                    comment_id=(row.get("comment_id") or "").strip() or f"csv-{i}",
                    source_user_id=user_id,
                    username=username,
                    display_name=(row.get("display_name") or "").strip() or None,
                    text=(row.get("text") or "").strip(),
                    is_reply=str(row.get("is_reply") or "").strip().lower() in ("1", "true", "yes"),
                    parent_comment_id=(row.get("parent_comment_id") or "").strip() or None,
                )
            )
        return comments

    @staticmethod
    def parse_json(raw: bytes) -> list[RawComment]:
        """Ожидается JSON-массив объектов с теми же полями, что и CSV."""
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceAdapterError("Не удалось разобрать JSON-файл") from exc

        if not isinstance(data, list):
            raise SourceAdapterError("JSON должен быть массивом объектов-комментариев")

        comments: list[RawComment] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise SourceAdapterError(f"Элемент {i}: ожидался объект")
            user_id = str(item.get("user_id") or item.get("username") or "").strip()
            if not user_id:
                raise SourceAdapterError(f"Элемент {i}: не указан user_id или username")
            comments.append(
                RawComment(
                    comment_id=str(item.get("comment_id") or f"json-{i}"),
                    source_user_id=user_id,
                    username=(str(item["username"]).strip() if item.get("username") else None),
                    display_name=(str(item["display_name"]).strip() if item.get("display_name") else None),
                    text=str(item.get("text") or ""),
                    is_reply=bool(item.get("is_reply", False)),
                    parent_comment_id=(str(item["parent_comment_id"]) if item.get("parent_comment_id") else None),
                )
            )
        return comments

    @staticmethod
    def parse_username_list(raw: bytes) -> list[RawComment]:
        """Текстовый список usernames, по одному в строке (пустые строки и '#'-комментарии пропускаются)."""
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SourceAdapterError("Файл должен быть в кодировке UTF-8") from exc

        comments: list[RawComment] = []
        for i, line in enumerate(text.splitlines()):
            username = line.strip().lstrip("@")
            if not username or username.startswith("#"):
                continue
            comments.append(
                RawComment(
                    comment_id=f"list-{i}",
                    source_user_id=username,
                    username=username,
                    display_name=None,
                    text="",
                    is_reply=False,
                )
            )
        return comments
