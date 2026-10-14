"""Тексты и inline-кнопки ответов бота (см. 4.5–4.6 ТЗ)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config


def news_url(slug: str) -> str:
    return f"{config.news_site_url}/n/{slug}"


def news_keyboard(news_id: str, status: str) -> InlineKeyboardMarkup:
    toggle = (
        InlineKeyboardButton(text="🙈 Скрыть", callback_data=f"h:{news_id}")
        if status == "published"
        else InlineKeyboardButton(text="↩️ Вернуть", callback_data=f"s:{news_id}")
    )
    return InlineKeyboardMarkup(inline_keyboard=[[
        toggle, InlineKeyboardButton(text="🗑 Удалить", callback_data=f"d:{news_id}"),
    ]])


def confirm_delete_keyboard(news_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, удалить", callback_data=f"D:{news_id}"),
        InlineKeyboardButton(text="Отмена", callback_data=f"c:{news_id}"),
    ]])


def media_note(photos: int, videos: int, skipped_big: int) -> str:
    parts = []
    if photos:
        parts.append(f"{photos} фото")
    if videos:
        parts.append(f"{videos} видео")
    note = ", ".join(parts) if parts else "нет"
    if skipped_big:
        note += f"; видео >{config.max_video_mb} МБ — не добавлено" + (f" ({skipped_big})" if skipped_big > 1 else "")
    return note


def published_card(title: str, summary: str | None, slug: str, media: str, warnings: list[str]) -> str:
    lines = [
        "✅ Опубликовано в «Новости одной строкой»",
        f"Заголовок: {title}",
        f"Описание: {summary or '—'}",
        f"Медиа: {media}",
        f"Ссылка: {news_url(slug)}",
    ]
    if warnings:
        lines.append("")
        lines.extend(f"⚠️ {w}" for w in warnings)
    return "\n".join(lines)


STATUS_ICON = {"published": "✅", "hidden": "🙈"}


def last_list(rows: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not rows:
        return "Новостей пока нет.", None
    lines = ["Последние новости:"]
    buttons = []
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {STATUS_ICON.get(r['status'], '')} {r['title']}\n   {news_url(r['slug'])}")
        if r["status"] == "published":
            buttons.append(InlineKeyboardButton(text=f"{i} 🙈", callback_data=f"lh:{r['id']}"))
        else:
            buttons.append(InlineKeyboardButton(text=f"{i} ↩️", callback_data=f"ls:{r['id']}"))
    rows_kb = [buttons[i : i + 5] for i in range(0, len(buttons), 5)]
    lines.append("\n🙈 — скрыть с сайта, ↩️ — вернуть.")
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows_kb)
