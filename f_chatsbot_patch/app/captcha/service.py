"""
Сервис капчи: мьют новичков, выдача капчи, таймеры, попытки, бан.

Основной поток:
  1. Новый участник вступает в группу → on_new_member()
     - если капча OFF или юзер в whitelist/админ → ничего не делаем
     - иначе: мьютим, сохраняем исходные права, шлём капчу в ЛС (если можем),
       в группе показываем короткое сообщение с кнопкой «Пройти проверку»
  2. Юзер жмёт кнопку → deep-link в ЛС → send_captcha_to_user()
  3. Юзер отвечает → check_answer()
     - правильно → снимаем мьют, добавляем в базу для рассылки
     - неправильно → +1 попытка; после 3 → бан на 24ч
  4. Таймаут 60с → capcha expired, предлагаем пройти заново
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot
from aiogram.types import ChatPermissions
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from .generator import generate_captcha
from .keyboards import captcha_keyboard, group_verify_keyboard

logger = logging.getLogger("captcha")

# Режимы
MODE_OFF = "OFF"
MODE_NORMAL = "NORMAL"
MODE_STRICT = "STRICT"

# Параметры
TIMEOUT_NORMAL = 60      # сек на прохождение
TIMEOUT_STRICT = 30
MAX_ATTEMPTS = 3
BAN_HOURS = 24
OPTIONS_NORMAL = 4
OPTIONS_STRICT = 5

# Не прошёл капчу за отведённое время → удаляем из группы (kick, не перманентный бан),
# чтобы не копились замьюченные "зависшие" участники: они раздувают счётчик
# участников и создают волны вступлений/выходов, когда потом уходят сами.
# until_date для unban должен быть > 30 сек от текущего момента (иначе Telegram
# считает это перманентным баном) — даём небольшое окно, чтобы попытка
# повторного вступления не была мгновенной петлёй для скриптов.
EXPIRED_KICK_COOLDOWN_MINUTES = 10

# Права полного мьюта (ничего нельзя)
MUTED_PERMS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

# Права разблокировки (обычный участник)
UNMUTED_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)


def _now():
    return datetime.now(timezone.utc)


class CaptchaService:
    def __init__(self, bot: Bot, db, settings):
        self._bot = bot
        self._db = db
        self._settings = settings
        # активные таймеры: captcha_id -> asyncio.Task
        self._timers: dict[str, asyncio.Task] = {}
        # временное хранение group-сообщений с кнопкой: (chat_id, user_id) -> message_id
        self._group_prompts: dict[tuple, int] = {}
        self._bot_username: str | None = None

    async def setup(self):
        """Кэшируем username бота и восстанавливаем таймеры после рестарта."""
        me = await self._bot.get_me()
        self._bot_username = me.username
        await self._restore_timers()

    # ── Режим ─────────────────────────────────────────────────────────────

    async def get_mode(self) -> str:
        mode = await self._db.get_setting("captcha_mode")
        return mode or MODE_OFF

    async def set_mode(self, mode: str):
        await self._db.set_setting("captcha_mode", mode)
        logger.info(f"[CAPTCHA] режим переключён на {mode}")

    def _timeout(self, mode: str) -> int:
        return TIMEOUT_STRICT if mode == MODE_STRICT else TIMEOUT_NORMAL

    def _num_options(self, mode: str) -> int:
        return OPTIONS_STRICT if mode == MODE_STRICT else OPTIONS_NORMAL

    # ── Whitelist / админы ────────────────────────────────────────────────

    async def _is_excluded(self, chat_id: int, user_id: int) -> bool:
        # Админы бота
        if user_id in self._settings.admins:
            return True
        # Whitelist из настроек (CAPTCHA_EXCLUDED_USERS)
        excluded_raw = await self._db.get_setting("captcha_excluded") or ""
        excluded = {int(x) for x in excluded_raw.split(",") if x.strip().isdigit()}
        if user_id in excluded:
            return True
        # Админы самой группы
        try:
            member = await self._bot.get_chat_member(chat_id, user_id)
            if member.status in ("administrator", "creator"):
                return True
        except Exception:
            pass
        return False

    # ── Новый участник ────────────────────────────────────────────────────

    async def on_new_member(self, chat_id: int, user):
        mode = await self.get_mode()
        if mode == MODE_OFF:
            return
        if user.is_bot:
            return
        if await self._is_excluded(chat_id, user.id):
            logger.info(f"[CAPTCHA] user={user.id} исключён (админ/whitelist)")
            return

        # Мьютим
        try:
            await self._bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=MUTED_PERMS,
            )
            logger.info(f"[CAPTCHA] user={user.id} joined chat={chat_id}, замьючен")
        except TelegramBadRequest as e:
            logger.warning(f"[CAPTCHA] не удалось замьютить user={user.id}: {e}")
            return

        # Создаём капчу в БД
        num_opts = self._num_options(mode)
        cap = generate_captcha(num_opts)
        timeout = self._timeout(mode)
        expires = (_now() + timedelta(seconds=timeout)).isoformat()
        await self._db.captcha_create(
            user_id=user.id,
            chat_id=chat_id,
            captcha_id=cap["captcha_id"],
            correct_answer=cap["correct"],
            expires_at=expires,
            options=",".join(cap["options"]),
        )

        # Пытаемся отправить капчу в ЛС
        sent_to_dm = await self._try_send_dm(chat_id, user, cap)

        # В группе — короткое сообщение с кнопкой (независимо от ЛС)
        await self._send_group_prompt(chat_id, user, sent_to_dm)

        # Запускаем таймер
        self._start_timer(cap["captcha_id"], timeout)

    async def _try_send_dm(self, chat_id: int, user, cap: dict) -> bool:
        text = (
            "🤖 <b>Быстрая проверка</b>\n\n"
            f"Чтобы получить доступ к группе, нажмите на <b>{cap['task_word']}</b>:"
        )
        try:
            await self._bot.send_message(
                chat_id=user.id,
                text=text,
                reply_markup=captcha_keyboard(cap["captcha_id"], cap["options"]),
            )
            logger.info(f"[CAPTCHA] sent user={user.id} (ЛС)")
            return True
        except (TelegramForbiddenError, TelegramBadRequest):
            logger.info(f"[CAPTCHA] ЛС недоступно user={user.id}, только кнопка в группе")
            return False

    async def _send_group_prompt(self, chat_id: int, user, sent_to_dm: bool):
        name = user.first_name or "Участник"
        if sent_to_dm:
            text = (
                f"👋 {name}, отправил вам проверку в личные сообщения. "
                "Пройдите её, чтобы писать в группе."
            )
        else:
            text = (
                f"👋 {name}, нажмите кнопку ниже и пройдите быструю проверку, "
                "чтобы получить доступ к группе."
            )
        try:
            msg = await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=group_verify_keyboard(self._bot_username, chat_id),
            )
            self._group_prompts[(chat_id, user.id)] = msg.message_id
            # Раньше тут было принудительное удаление этого сообщения через
            # 10 секунд, независимо от того, успел ли человек нажать кнопку.
            # При таймауте капчи (60с) это резало живым людям окно на реакцию
            # с 60 секунд до фактических 10 — кнопка пропадала, пока человек
            # ещё грузил ленту/читал уведомление, и он оставался замьюченным
            # без видимого способа пройти проверку. Удалять это сообщение не
            # нужно принудительно по таймеру: оно и так корректно убирается
            # через _delete_group_prompt() в момент реального разрешения
            # капчи — либо при успехе (_pass), либо при таймауте (_timer_task).
        except Exception as e:
            logger.warning(f"[CAPTCHA] не удалось отправить сообщение в группу: {e}")

    # ── Deep-link: юзер открыл ЛС по кнопке ───────────────────────────────

    async def send_captcha_via_deeplink(self, user, chat_id: int) -> bool:
        """Вызывается из /start cap_<chatid>. Показывает капчу в ЛС."""
        session = await self._db.captcha_get_active_for_user(user.id, chat_id)
        if not session:
            return False  # нет активной капчи (уже прошёл / истекла / не вступал)

        # Выдаём свежую капчу (новые варианты) для показа в ЛС
        mode = await self.get_mode()
        cap = generate_captcha(self._num_options(mode))
        timeout = self._timeout(mode)
        expires = (_now() + timedelta(seconds=timeout)).isoformat()
        await self._db.captcha_create(
            user_id=user.id, chat_id=chat_id,
            captcha_id=cap["captcha_id"], correct_answer=cap["correct"],
            expires_at=expires, options=",".join(cap["options"]),
        )
        text = (
            "🤖 <b>Быстрая проверка</b>\n\n"
            f"Нажмите на <b>{cap['task_word']}</b>:"
        )
        await self._bot.send_message(
            chat_id=user.id, text=text,
            reply_markup=captcha_keyboard(cap["captcha_id"], cap["options"]),
        )
        self._start_timer(cap["captcha_id"], timeout)
        logger.info(f"[CAPTCHA] sent user={user.id} (deep-link)")
        return True

    # ── Проверка ответа ───────────────────────────────────────────────────

    async def check_answer(self, captcha_id: str, option_index: int, from_user_id: int) -> dict:
        """
        Возвращает: {"result": "passed"|"wrong"|"banned"|"expired"|"not_yours"|"gone", ...}
        """
        session = await self._db.captcha_get(captcha_id)
        if not session:
            return {"result": "gone"}

        # Защита: нажать может только владелец капчи
        if session["user_id"] != from_user_id:
            return {"result": "not_yours"}

        if session["status"] != "active":
            return {"result": "gone"}

        # Резолвим индекс в emoji по сохранённым options
        options = (session.get("options") or "").split(",")
        if option_index < 0 or option_index >= len(options):
            return {"result": "gone"}
        chosen_emoji = options[option_index]

        if chosen_emoji == session["correct_answer"]:
            await self._pass(session)
            return {"result": "passed"}
        else:
            attempts = await self._db.captcha_incr_attempts(captcha_id)
            if attempts >= MAX_ATTEMPTS:
                await self._ban(session)
                return {"result": "banned"}
            return {"result": "wrong", "attempts_left": MAX_ATTEMPTS - attempts}

    async def _pass(self, session: dict):
        captcha_id = session["captcha_id"]
        chat_id = session["chat_id"]
        user_id = session["user_id"]

        self._cancel_timer(captcha_id)
        await self._db.captcha_set_status(captcha_id, "passed", passed=True)

        # Снимаем мьют
        try:
            await self._bot.restrict_chat_member(
                chat_id=chat_id, user_id=user_id, permissions=UNMUTED_PERMS,
            )
        except Exception as e:
            logger.warning(f"[CAPTCHA] не удалось снять мьют user={user_id}: {e}")

        # Добавляем в базу для рассылки (source_chat_id = группа)
        try:
            member = await self._bot.get_chat_member(chat_id, user_id)
            u = member.user
            await self._db.add_or_update_user(
                user_id=u.id,
                username=u.username or "",
                first_name=u.first_name or "",
                last_name=u.last_name or "",
                language=u.language_code or "",
                source_chat_id=chat_id,
            )
        except Exception as e:
            logger.warning(f"[CAPTCHA] не удалось добавить в базу user={user_id}: {e}")

        # Удаляем сообщение с кнопкой в группе
        await self._delete_group_prompt(chat_id, user_id)

        # Кнопка «Перейти в группу» — макс. близко к автопереходу, что позволяет Bot API
        await self._send_group_return_button(chat_id, user_id)

        logger.info(f"[CAPTCHA] passed user={user_id}")

    async def _ban(self, session: dict):
        captcha_id = session["captcha_id"]
        chat_id = session["chat_id"]
        user_id = session["user_id"]

        self._cancel_timer(captcha_id)
        await self._db.captcha_set_status(captcha_id, "failed")

        until = _now() + timedelta(hours=BAN_HOURS)
        try:
            await self._bot.ban_chat_member(
                chat_id=chat_id, user_id=user_id, until_date=until,
            )
            logger.info(f"[CAPTCHA] removed user={user_id} (бан на {BAN_HOURS}ч)")
        except Exception as e:
            logger.warning(f"[CAPTCHA] не удалось забанить user={user_id}: {e}")

        # Уведомление в ЛС (если можем)
        try:
            await self._bot.send_message(
                user_id,
                f"❌ Проверка не пройдена ({MAX_ATTEMPTS} неудачных попытки).\n"
                f"Вы сможете вступить снова через {BAN_HOURS} часа.",
            )
        except Exception:
            pass

        await self._delete_group_prompt(chat_id, user_id)

    # ── Таймер ────────────────────────────────────────────────────────────

    def _start_timer(self, captcha_id: str, timeout: int):
        self._cancel_timer(captcha_id)
        self._timers[captcha_id] = asyncio.create_task(
            self._timer_task(captcha_id, timeout)
        )

    def _cancel_timer(self, captcha_id: str):
        t = self._timers.pop(captcha_id, None)
        if t and not t.done():
            t.cancel()

    async def _timer_task(self, captcha_id: str, timeout: int):
        try:
            await asyncio.sleep(timeout)
            session = await self._db.captcha_get(captcha_id)
            if not session or session["status"] != "active":
                return
            # Таймаут
            await self._db.captcha_set_status(captcha_id, "expired")
            chat_id = session["chat_id"]
            user_id = session["user_id"]
            logger.info(f"[CAPTCHA] timeout user={user_id} chat={chat_id}")

            # Удаляем из группы вместо того, чтобы оставлять замьюченным навсегда.
            # Раньше эти участники копились в группе бесконечно (замьюченные, но
            # всё ещё "в группе"), а когда уходили сами — это выглядело как волна
            # вступлений/выходов. Теперь неподтверждённый участник убирается сразу,
            # но может вступить и попробовать снова через EXPIRED_KICK_COOLDOWN_MINUTES.
            until = _now() + timedelta(minutes=EXPIRED_KICK_COOLDOWN_MINUTES)
            try:
                await self._bot.ban_chat_member(
                    chat_id=chat_id, user_id=user_id, until_date=until,
                )
                logger.info(
                    f"[CAPTCHA] user={user_id} удалён из group={chat_id} "
                    f"(не прошёл проверку за {timeout}с)"
                )
            except Exception as e:
                logger.warning(f"[CAPTCHA] не удалось удалить user={user_id}: {e}")

            await self._delete_group_prompt(chat_id, user_id)

            # Уведомление в ЛС, если бот может писать этому пользователю
            try:
                await self._bot.send_message(
                    user_id,
                    "⏰ Время проверки истекло — вы были удалены из группы.\n"
                    "Вы можете вступить снова и пройти проверку заново.",
                )
            except Exception:
                pass
        except asyncio.CancelledError:
            pass

    async def _restore_timers(self):
        """После рестарта: восстанавливаем таймеры активных капч."""
        active = await self._db.captcha_get_all_active()
        restored = 0
        for s in active:
            try:
                expires = datetime.fromisoformat(s["expires_at"])
                remaining = (expires - _now()).total_seconds()
            except Exception:
                remaining = 0
            if remaining <= 0:
                await self._db.captcha_set_status(s["captcha_id"], "expired")
            else:
                self._start_timer(s["captcha_id"], int(remaining))
                restored += 1
        if restored:
            logger.info(f"[CAPTCHA] восстановлено таймеров: {restored}")

    # ── Выход из группы ───────────────────────────────────────────────────

    async def on_member_left(self, chat_id: int, user_id: int):
        await self._db.captcha_cancel_user_sessions(user_id, chat_id)
        await self._delete_group_prompt(chat_id, user_id)

    async def _delete_group_prompt(self, chat_id: int, user_id: int):
        msg_id = self._group_prompts.pop((chat_id, user_id), None)
        if msg_id:
            try:
                await self._bot.delete_message(chat_id, msg_id)
            except Exception:
                pass

    async def _send_group_return_button(self, chat_id: int, user_id: int):
        """После успешной капчи — кнопка одним тапом обратно в группу."""
        try:
            chat = await self._bot.get_chat(chat_id)
            if chat.username:
                url = f"https://t.me/{chat.username}"
            else:
                url = await self._bot.export_chat_invite_link(chat_id)
        except Exception as e:
            logger.warning(f"[CAPTCHA] не удалось получить ссылку на группу {chat_id}: {e}")
            return

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Перейти в группу", url=url)
        kb.adjust(1)
        try:
            await self._bot.send_message(
                user_id,
                "🎉 Проверка пройдена! Возвращайтесь в группу:",
                reply_markup=kb.as_markup(),
            )
        except Exception:
            pass
