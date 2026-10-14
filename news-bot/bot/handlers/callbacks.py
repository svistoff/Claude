"""Inline-кнопки: скрыть / вернуть / удалить (см. 4.5 ТЗ).

callback_data: h:<id> скрыть, s:<id> вернуть, d:<id> спросить про удаление,
D:<id> удалить, c:<id> отмена; lh:/ls: — скрыть/вернуть из списка /last.
"""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, LinkPreviewOptions

from bot.config import config
from bot.services import cards, media_storage, supabase_client

logger = logging.getLogger(__name__)

router = Router(name="callbacks")
router.callback_query.filter(F.from_user.id.in_(config.allowed_user_ids))

_DATA_RE = re.compile(r"^(h|s|d|D|c|lh|ls):([0-9a-f-]{36})$")


async def _edit_markup(cb: CallbackQuery, markup) -> None:
    try:
        await cb.message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest as exc:  # «message is not modified» и т.п.
        logger.debug("edit_reply_markup: %s", exc)


@router.callback_query(F.data.regexp(_DATA_RE))
async def on_news_button(cb: CallbackQuery) -> None:
    action, news_id = _DATA_RE.match(cb.data).groups()
    news = await supabase_client.get_news(news_id)
    if news is None:
        await cb.answer("Новость уже удалена", show_alert=True)
        await _edit_markup(cb, None)
        return

    if action in ("h", "s", "lh", "ls"):
        status = "hidden" if action in ("h", "lh") else "published"
        await supabase_client.set_status(news_id, status)
        await cb.answer("Скрыто с сайта" if status == "hidden" else "Снова на сайте")
        if action in ("lh", "ls"):
            text, kb = cards.last_list(await supabase_client.list_latest(10))
            try:
                await cb.message.edit_text(text, reply_markup=kb, link_preview_options=LinkPreviewOptions(is_disabled=True))
            except TelegramBadRequest as exc:
                logger.debug("edit_text: %s", exc)
        else:
            await _edit_markup(cb, cards.news_keyboard(news_id, status))
        return

    if action == "d":
        await cb.answer()
        await _edit_markup(cb, cards.confirm_delete_keyboard(news_id))
        return

    if action == "c":
        await cb.answer("Отменено")
        await _edit_markup(cb, cards.news_keyboard(news_id, news["status"]))
        return

    # action == "D": удаляем медиа из канала-хранилища, затем строку news (медиа — каскадом)
    message_ids = [m["channel_message_id"] for m in news.get("news_media") or []]
    await media_storage.delete_from_channel(cb.bot, message_ids)
    await supabase_client.delete_news(news_id)
    logger.info("Удалена новость %s (медиа: %s)", news["slug"], len(message_ids))
    await cb.answer("Удалено")
    try:
        await cb.message.edit_text(
            f"🗑 Удалено: {news['title']}", link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except TelegramBadRequest as exc:
        logger.debug("edit_text: %s", exc)
