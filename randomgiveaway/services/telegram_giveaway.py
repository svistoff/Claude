"""Розыгрыши в Telegram: кнопка "Участвую" + реферальные ссылки вместо
чтения истории комментариев (Bot API не даёт её боту — см. обсуждение в
README.md, «Подключение Telegram»).

Поток:
  1. Админ пишет текст поста на сайте → publish_giveaway_post публикует его
     в канал с кнопкой-ссылкой на приватный чат с ботом.
  2. /start join_<id> и /start ref_<id>_<referrer> — обрабатываются в
     handle_update (единая точка входа для вебхука, см. api/routes.py).
  3. Каждое новое событие (join/referral) пишется в telegram_entries и сразу
     пересчитывает participants целиком через уже существующий
     giveaways.load_comments — общая логика §7/§8 ТЗ (фильтры, вес участника
     через comment_count) переиспользуется без изменений.
  4. Перед самим розыгрышем resync_membership_and_exclude ещё раз проверяет
     подписку всех участников — засчитывать нужно на момент розыгрыша, а не
     клика (см. обсуждение антифрода в README.md).
"""
from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite
import httpx

from randomgiveaway.adapters.base import RawComment
from randomgiveaway.config import config
from randomgiveaway.database.database import get_conn
from randomgiveaway.database.models import Giveaway
from randomgiveaway.services import giveaways as giveaway_service
from randomgiveaway.services import telegram_api
from randomgiveaway.services.participants import ParticipantsPreview

_bot_username_cache: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_bot_username() -> str:
    global _bot_username_cache
    if _bot_username_cache is None:
        me = await telegram_api.get_me(config.telegram_bot_token)
        _bot_username_cache = me["username"]
    return _bot_username_cache


async def publish_giveaway_post(giveaway_id: int, text: str) -> Giveaway:
    giveaway = await giveaway_service.get_giveaway(giveaway_id)
    if giveaway.source != "telegram":
        raise giveaway_service.GiveawayError(
            "Публикация в Telegram доступна только для розыгрышей с source=telegram"
        )
    if giveaway.telegram_message_id:
        raise giveaway_service.GiveawayError("Этот розыгрыш уже опубликован в Telegram")
    if not (config.telegram_bot_token and config.telegram_channel):
        raise giveaway_service.GiveawayError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL не заданы в .env")

    bot_username = await _get_bot_username()
    markup = telegram_api.join_button_markup(bot_username, giveaway_id)
    result = await telegram_api.send_message(config.telegram_bot_token, config.telegram_channel, text, markup)

    chat_id = str(result["chat"]["id"])
    message_id = result["message_id"]
    channel_handle = config.telegram_channel.lstrip("@")
    post_url = f"https://t.me/{channel_handle}/{message_id}"

    conn = get_conn()
    await conn.execute(
        "UPDATE giveaways SET telegram_chat_id = ?, telegram_message_id = ?, post_url = ? WHERE id = ?",
        (chat_id, message_id, post_url, giveaway_id),
    )
    await conn.commit()
    return await giveaway_service.get_giveaway(giveaway_id)


async def register_join(
    giveaway_id: int, telegram_user_id: str, username: str | None, display_name: str | None
) -> bool:
    """Возвращает True, если участник зарегистрирован впервые (False — уже
    участвовал, но данные профиля на всякий случай освежены)."""
    conn = get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO telegram_entries (giveaway_id, telegram_user_id, username, display_name, kind, created_at)
            VALUES (?, ?, ?, ?, 'join', ?)
            """,
            (giveaway_id, telegram_user_id, username, display_name, _now()),
        )
        await conn.commit()
        return True
    except aiosqlite.IntegrityError:
        await conn.execute(
            """
            UPDATE telegram_entries SET username = ?, display_name = ?
            WHERE giveaway_id = ? AND telegram_user_id = ? AND kind = 'join'
            """,
            (username, display_name, giveaway_id, telegram_user_id),
        )
        await conn.commit()
        return False


async def _has_joined(giveaway_id: int, telegram_user_id: str) -> bool:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT 1 FROM telegram_entries WHERE giveaway_id = ? AND telegram_user_id = ? AND kind = 'join'",
        (giveaway_id, telegram_user_id),
    )
    return await cur.fetchone() is not None


async def _count_referrals(giveaway_id: int, referrer_user_id: str) -> int:
    conn = get_conn()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM telegram_entries WHERE giveaway_id = ? AND telegram_user_id = ? AND kind = 'referral'",
        (giveaway_id, referrer_user_id),
    )
    row = await cur.fetchone()
    return row["cnt"] if row else 0


async def register_referral(giveaway_id: int, referrer_user_id: str) -> bool:
    """Начисляет пригласившему дополнительный "билет". Отказывает, если
    сам пригласивший ещё не участвует (защита от ссылок с произвольным
    telegram_user_id) или если достигнут потолок TELEGRAM_MAX_REFERRALS."""
    if not await _has_joined(giveaway_id, referrer_user_id):
        return False
    if await _count_referrals(giveaway_id, referrer_user_id) >= config.telegram_max_referrals:
        return False
    conn = get_conn()
    await conn.execute(
        """
        INSERT INTO telegram_entries (giveaway_id, telegram_user_id, username, display_name, kind, created_at)
        VALUES (?, ?, NULL, NULL, 'referral', ?)
        """,
        (giveaway_id, referrer_user_id, _now()),
    )
    await conn.commit()
    return True


async def rebuild_participants(giveaway_id: int) -> ParticipantsPreview:
    """Пересобирает participants из всех накопленных telegram_entries —
    переиспользует ту же нормализацию/фильтры, что и остальные источники."""
    conn = get_conn()
    cur = await conn.execute(
        "SELECT * FROM telegram_entries WHERE giveaway_id = ? ORDER BY id ASC", (giveaway_id,)
    )
    rows = await cur.fetchall()
    comments = [
        RawComment(
            comment_id=f"tg-{row['id']}",
            source_user_id=row["telegram_user_id"],
            username=row["username"],
            display_name=row["display_name"],
            text="",
            is_reply=False,
        )
        for row in rows
    ]
    return await giveaway_service.load_comments(giveaway_id, comments)


async def resync_membership_and_exclude(giveaway_id: int) -> int:
    """Перед розыгрышем — исключает тех, кто уже отписался от канала
    (подписка должна быть в силе на момент розыгрыша, не клика). Возвращает
    число исключённых."""
    if not (config.telegram_bot_token and config.telegram_channel):
        return 0
    participants = await giveaway_service.get_active_participants(giveaway_id)
    if not participants:
        return 0

    conn = get_conn()
    excluded = 0
    async with httpx.AsyncClient(timeout=15) as client:
        for p in participants:
            is_member = await telegram_api.is_channel_member(
                config.telegram_bot_token, config.telegram_channel, p.source_user_id, client
            )
            if not is_member:
                await conn.execute(
                    "UPDATE participants SET is_excluded = 1, exclusion_reason = ? WHERE id = ?",
                    ("отписался от канала", p.id),
                )
                excluded += 1
    await conn.commit()
    return excluded


async def handle_update(update: dict) -> None:
    """Единая точка входа для вебхука Telegram (api/routes.py:/telegram/webhook).
    Обрабатывает только `/start join_<id>` и `/start ref_<id>_<referrer>` —
    остальные апдейты (произвольные сообщения, callback_query и т.п.)
    молча игнорируются, у бота нет других сценариев."""
    message = update.get("message")
    if not message:
        return
    text = (message.get("text") or "").strip()
    if not text.startswith("/start"):
        return

    from_user = message.get("from") or {}
    user_id = str(from_user.get("id") or "")
    if not user_id:
        return
    username = from_user.get("username")
    display_name = " ".join(filter(None, [from_user.get("first_name"), from_user.get("last_name")])) or None

    parts = text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    referrer_id: str | None = None
    if payload.startswith("join_"):
        giveaway_id_str = payload[len("join_"):]
    elif payload.startswith("ref_"):
        rest = payload[len("ref_"):]
        giveaway_id_str, _, referrer_id = rest.partition("_")
    else:
        return

    if not giveaway_id_str.isdigit():
        return
    giveaway_id = int(giveaway_id_str)

    if not (config.telegram_bot_token and config.telegram_channel):
        return

    try:
        giveaway = await giveaway_service.get_giveaway(giveaway_id)
    except giveaway_service.GiveawayError:
        return
    if giveaway.source != "telegram":
        return

    channel_url = f"https://t.me/{config.telegram_channel.lstrip('@')}"
    is_member = await telegram_api.is_channel_member(config.telegram_bot_token, config.telegram_channel, user_id)
    if not is_member:
        await telegram_api.send_message(
            config.telegram_bot_token,
            user_id,
            "Чтобы участвовать, сначала подпишись на канал, а потом снова перейди по этой же ссылке.",
            {"inline_keyboard": [[{"text": "Открыть канал", "url": channel_url}]]},
        )
        return

    newly_joined = await register_join(giveaway_id, user_id, username, display_name)

    if referrer_id and referrer_id != user_id:
        await register_referral(giveaway_id, referrer_id)

    await rebuild_participants(giveaway_id)

    bot_username = await _get_bot_username()
    personal_link = telegram_api.referral_deep_link(bot_username, giveaway_id, user_id)
    greeting = "Ты участвуешь в розыгрыше! 🎉" if newly_joined else "Ты уже участвуешь в этом розыгрыше."
    await telegram_api.send_message(
        config.telegram_bot_token,
        user_id,
        f"{greeting}\n\n"
        f"Пригласи друзей — за каждого, кто подпишется на канал по твоей ссылке, "
        f"дополнительный шанс на победу (максимум {config.telegram_max_referrals}):\n{personal_link}",
    )
