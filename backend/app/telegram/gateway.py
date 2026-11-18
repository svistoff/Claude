"""Telegram-шлюз: сообщения владельца идут тому же агенту, что и веб-чат.

- Обычный текст → агент (в текущем проекте, в текущем разговоре).
- Опасные действия → кнопки «Разрешить / Отменить» прямо в Telegram.
- Команды: проекты, новый разговор, стоп, модель, личные задачи и план дня.
Разговоры из Telegram хранятся в той же БД и видны в веб-интерфейсе.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from .. import projects_store, settings_store
from ..agent.loop import run_agent
from ..agent.prompts import SYSTEM_PROMPT
from ..agent.runtime import registry
from ..agent.session import persist_delta
from ..config import get_app_config, get_settings
from ..database import repo
from ..llm import get_provider
from ..tools.base import ToolContext
from .client import TelegramClient, redact
from .format import md_to_html, split_markdown

log = logging.getLogger("telegram")

KEY_PROJECT = "tg_project"
KEY_CONVERSATION = "tg_conversation"

TELEGRAM_NOTE = """

Сейчас пользователь пишет тебе через Telegram с телефона:
- отвечай коротко и по делу, без длинных таблиц;
- если вопрос не про текущий проект (личные задачи, поиск, советы) — всё равно помогай;
- личные задачи веди инструментом tasks («запиши задачу» → tasks add)."""

HELP = """\
Я твой ИИ-помощник — тот же агент, что на ai.svistoff.ru.
Просто пиши, что сделать: «почему не работает бот», «запиши задачу позвонить бухгалтеру», «что в проекте нового».

Работа:
/projects — выбрать проект · /project имя
/new — начать новый разговор
/stop — остановить текущую работу
/model — сменить модель ИИ

Задачи:
/tasks — открытые задачи · /done N · /drop N
/plan — план дня

/id — показать chat_id"""

_TOOL_LABELS = {
    "read_file": "📄 читаю {path}",
    "list_files": "📁 смотрю папку {path}",
    "search_files": "🔎 ищу «{query}»",
    "write_file": "✏️ пишу {path}",
    "edit_file": "✏️ правлю {path}",
    "terminal": "💻 {command}",
    "git": "⑂ git",
    "github": "🐙 GitHub",
    "browser": "🌐 браузер: {action}",
    "generate_image": "🎨 рисую",
    "tasks": "📋 задачи",
}


def _tool_label(name: str, args: dict) -> str:
    tpl = _TOOL_LABELS.get(name, f"🔧 {name}")
    try:
        return tpl.format(**{k: str(v)[:60] for k, v in (args or {}).items()})
    except (KeyError, IndexError):
        return tpl.split(" {")[0]


def _media_path(url: str) -> Path | None:
    """Путь к файлу картинки по её URL в API (скриншот браузера или генерация)."""
    try:
        if url.startswith("/api/files/media/"):
            from ..tools.image import media_dir
            sid = url.rsplit("/", 1)[-1]
            return next(iter(media_dir().glob(sid + ".*")), None)
        if url.startswith("/api/browser/screenshot/"):
            from ..browser import screenshots_dir
            p = screenshots_dir() / f"{url.rsplit('/', 1)[-1]}.png"
            return p if p.is_file() else None
    except Exception:  # noqa: BLE001
        return None
    return None


class Gateway:
    def __init__(self, token: str, owner_chat_id: str) -> None:
        self.tg = TelegramClient(token)
        self.owner = str(owner_chat_id or "")
        # Короткий id для кнопок (callback_data ≤ 64 байт) → (conversation_id, call_id).
        self.pending: dict[str, tuple[str, str]] = {}
        self.busy: dict[str, asyncio.Task] = {}

    # --- Цикл опроса -------------------------------------------------------
    async def run(self) -> None:
        offset = None
        while True:
            try:
                updates = await self.tg.get_updates(offset)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — сеть: просто повторяем
                # redact() — защита в глубину: в тексте ошибки не должно быть токена.
                log.warning("getUpdates: %s", redact(exc))
                await asyncio.sleep(5)
                continue
            for upd in updates:
                offset = upd["update_id"] + 1
                try:
                    await self.handle_update(upd)
                except Exception:  # noqa: BLE001 — одна ошибка не роняет шлюз
                    log.exception("ошибка обработки update")

    async def handle_update(self, upd: dict) -> None:
        if "callback_query" in upd:
            await self.handle_callback(upd["callback_query"])
        elif "message" in upd:
            await self.handle_message(upd["message"])

    # --- Сообщения ---------------------------------------------------------
    async def handle_message(self, msg: dict) -> None:
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if not chat_id:
            return
        if not self.owner:
            await self.tg.send(chat_id, f"Твой chat_id: {chat_id}\nВпиши в /opt/ai-agent/.env строку "
                               f"TELEGRAM_CHAT_ID={chat_id} и перезапусти ai-agent.")
            return
        if chat_id != self.owner:
            await self.tg.send(chat_id, "Это личный помощник, он отвечает только владельцу.")
            return
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if not text:
            await self.tg.send(chat_id, "Пока понимаю только текст.")
            return
        if text.startswith("/"):
            cmd, _, rest = text.partition(" ")
            await self.command(chat_id, cmd.split("@")[0].lower(), rest.strip())
            return
        await self.start_agent(chat_id, text)

    async def command(self, chat_id: str, cmd: str, rest: str) -> None:
        if cmd in ("/start", "/help"):
            await self.tg.send(chat_id, HELP)
        elif cmd == "/id":
            await self.tg.send(chat_id, f"chat_id: {chat_id}")
        elif cmd == "/projects":
            await self.cmd_projects(chat_id)
        elif cmd == "/project":
            await self.set_project(chat_id, rest)
        elif cmd == "/new":
            repo.set_setting(KEY_CONVERSATION, "")
            await self.tg.send(chat_id, f"🆕 Новый разговор. Проект: {self.current_project() or '—'}")
        elif cmd == "/stop":
            conv = repo.get_setting(KEY_CONVERSATION) or ""
            ok = registry.stop(conv) if conv else False
            await self.tg.send(chat_id, "⏹ Останавливаю." if ok else "Сейчас ничего не выполняется.")
        elif cmd == "/model":
            await self.cmd_model(chat_id)
        elif cmd == "/tasks":
            tasks = repo.open_tasks()
            await self.tg.send(chat_id, ("📋 Открытые задачи:\n" + "\n".join(
                f"#{t['id']} {t['text']}" for t in tasks) + "\n\nСделал — /done N · план — /plan")
                if tasks else "📭 Открытых задач нет. Просто напиши: «запиши задачу …»")
        elif cmd in ("/done", "/drop"):
            await self.cmd_close_task(chat_id, rest, cmd == "/done")
        elif cmd == "/plan":
            await self.tg.typing(chat_id)
            from ..mentor import advisor
            try:
                plan = await advisor.plan_day()
            except Exception as exc:  # noqa: BLE001
                plan = f"⚠ Не смог составить план: {exc}"
            await self.send_markdown(chat_id, plan)
        else:
            await self.tg.send(chat_id, "Не знаю такой команды. /help — список.")

    async def cmd_close_task(self, chat_id: str, rest: str, done: bool) -> None:
        num = rest.lstrip("#").strip()
        if not num.isdigit():
            await self.tg.send(chat_id, f"Формат: {'/done' if done else '/drop'} номер (номера — в /tasks)")
            return
        t = repo.complete_task(int(num)) if done else repo.delete_task(int(num))
        if t is None:
            await self.tg.send(chat_id, f"Открытой задачи #{num} нет. /tasks — список.")
            return
        mark = "✅ Сделано" if done else "🗑 Убрал"
        await self.tg.send(chat_id, f"{mark}: {t['text']}\nОсталось открытых: {len(repo.open_tasks())}")

    # --- Проекты и модель --------------------------------------------------
    def current_project(self) -> str | None:
        available = [p["name"] for p in projects_store.all_projects() if p["available"]]
        saved = repo.get_setting(KEY_PROJECT)
        if saved in available:
            return saved
        return available[0] if available else None

    async def cmd_projects(self, chat_id: str) -> None:
        projects = [p for p in projects_store.all_projects() if p["available"]]
        if not projects:
            await self.tg.send(chat_id, "Нет доступных проектов. Добавь их на ai.svistoff.ru (📁).")
            return
        cur = self.current_project()
        buttons = [[(("✓ " if p["name"] == cur else "") + p["name"], f"p:{i}")]
                   for i, p in enumerate(projects)]
        await self.tg.send(chat_id, f"Текущий проект: {cur}\nВыбери другой:", buttons=buttons)

    async def set_project(self, chat_id: str, name: str) -> None:
        names = [p["name"] for p in projects_store.all_projects() if p["available"]]
        if name not in names:
            await self.tg.send(chat_id, "Такого проекта нет. /projects — список.")
            return
        repo.set_setting(KEY_PROJECT, name)
        repo.set_setting(KEY_CONVERSATION, "")  # новый проект — новый разговор
        await self.tg.send(chat_id, f"📂 Проект: {name}. Начинаю новый разговор.")

    async def cmd_model(self, chat_id: str) -> None:
        models = settings_store.available_models_detailed()
        cur = settings_store.current_model()
        buttons = [[(("✓ " if m["id"] == cur else "") + m.get("label", m["id"]), f"m:{i}")]
                   for i, m in enumerate(models)]
        await self.tg.send(chat_id, f"Модель сейчас: {cur}\nДругие появятся, если добавить ключ "
                           "OpenRouter/OpenAI в .env.", buttons=buttons)

    # --- Кнопки ------------------------------------------------------------
    async def handle_callback(self, cq: dict) -> None:
        chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
        data = cq.get("data", "")
        if chat_id != self.owner:
            await self.tg.answer_callback(cq["id"], "Нет доступа")
            return
        kind, _, arg = data.partition(":")
        if kind == "c":  # подтверждение действия агента
            short, _, verdict = arg.partition(":")
            target = self.pending.pop(short, None)
            ok = bool(target) and registry.confirm(target[0], target[1], verdict == "1")
            note = ("✅ Разрешено" if verdict == "1" else "✖ Отменено") if ok else "Уже неактуально"
            await self.tg.answer_callback(cq["id"], note)
            mid = cq.get("message", {}).get("message_id")
            if mid:
                await self.tg.edit(chat_id, mid, (cq["message"].get("text") or "") + f"\n\n{note}")
        elif kind == "p":
            projects = [p for p in projects_store.all_projects() if p["available"]]
            await self.tg.answer_callback(cq["id"])
            if arg.isdigit() and int(arg) < len(projects):
                await self.set_project(chat_id, projects[int(arg)]["name"])
        elif kind == "m":
            models = settings_store.available_models_detailed()
            await self.tg.answer_callback(cq["id"])
            if arg.isdigit() and int(arg) < len(models):
                try:
                    settings_store.set_model(models[int(arg)]["id"])
                    await self.tg.send(chat_id, f"🧠 Модель: {models[int(arg)].get('label')}")
                except ValueError as exc:
                    await self.tg.send(chat_id, str(exc))
        else:
            await self.tg.answer_callback(cq["id"])

    # --- Запуск агента -----------------------------------------------------
    async def start_agent(self, chat_id: str, text: str) -> None:
        running = self.busy.get(chat_id)
        if running and not running.done():
            await self.tg.send(chat_id, "⏳ Ещё работаю над прошлым сообщением. /stop — остановить.")
            return
        # Отдельной задачей: цикл опроса должен принимать нажатия кнопок, пока агент ждёт.
        self.busy[chat_id] = asyncio.create_task(self.run_agent_turn(chat_id, text))

    def _conversation(self, project: str, text: str) -> str:
        conv_id = repo.get_setting(KEY_CONVERSATION) or ""
        conv = repo.get_conversation(conv_id) if conv_id else None
        if conv is None or conv["project"] != project:
            conv_id = repo.create_conversation(project, "📱 " + text[:57])
            repo.set_setting(KEY_CONVERSATION, conv_id)
        return conv_id

    async def run_agent_turn(self, chat_id: str, text: str) -> None:
        project = self.current_project()
        if project is None:
            await self.tg.send(chat_id, "Нет доступных проектов. Добавь их на ai.svistoff.ru (📁).")
            return
        root = projects_store.project_root(project)
        config = get_app_config()
        conv_id = self._conversation(project, text)
        repo.add_message(conv_id, "user", text)
        messages = [{"role": "system", "content": SYSTEM_PROMPT + TELEGRAM_NOTE},
                    *repo.get_history_for_llm(conv_id)]
        preloaded = len(messages)
        run = registry.create(conv_id)
        ctx = ToolContext(project_name=project, project_root=root, config=config, run=run)

        status_id = await self.tg.send(chat_id, "⏳ Думаю…")
        last_edit = 0.0
        steps = 0
        final = ""
        tool_meta: dict[str, dict] = {}
        try:
            await self.tg.typing(chat_id)
            async for ev in run_agent(run=run, provider=get_provider(), ctx=ctx,
                                      history=messages, config=config):
                t = ev.get("type")
                if t == "tool_start":
                    steps += 1
                    if status_id and time.monotonic() - last_edit > 2:
                        last_edit = time.monotonic()
                        await self.tg.edit(chat_id, status_id,
                                           f"⏳ Шаг {steps}: {_tool_label(ev['name'], ev.get('args', {}))}")
                elif t == "tool_result":
                    tool_meta[ev["id"]] = {"ok": ev["ok"], "summary": ev["summary"], "name": ev["name"]}
                    url = (ev.get("extra") or {}).get("screenshot_url")
                    path = _media_path(url) if url else None
                    if path:
                        await self.tg.send_photo(chat_id, path)
                elif t == "confirm_required":
                    short = uuid.uuid4().hex[:10]
                    self.pending[short] = (conv_id, ev["id"])
                    await self.tg.send(
                        chat_id, f"⚠ Нужно подтверждение\n{ev.get('reason', '')}\n\n{ev.get('preview', '')}",
                        buttons=[[("✅ Разрешить", f"c:{short}:1"), ("✖ Отменить", f"c:{short}:0")]])
                elif t == "final":
                    final = ev.get("content", "")
                elif t == "error":
                    await self.tg.send(chat_id, "❌ " + ev.get("message", "ошибка"))
                elif t == "limit":
                    await self.tg.send(chat_id, "⚠ Дошёл до лимита шагов. Напиши «продолжай» — продолжу.")
                elif t == "stopped":
                    await self.tg.send(chat_id, "⏹ Остановлено.")
        except Exception as exc:  # noqa: BLE001
            log.exception("ошибка запуска агента")
            await self.tg.send(chat_id, f"❌ Ошибка: {exc}")
        finally:
            persist_delta(conv_id, messages, preloaded, tool_meta)
            registry.finish(conv_id, run)
            if status_id:
                await self.tg.edit(chat_id, status_id, f"✅ Готово · шагов: {steps}" if steps else "✅ Готово")
        if final.strip():
            await self.send_markdown(chat_id, final)

    async def send_markdown(self, chat_id: str, text: str) -> None:
        for chunk in split_markdown(text):
            if chunk.strip():
                await self.tg.send(chat_id, md_to_html(chunk), html=True)


# --- Жизненный цикл (вызывается из lifespan приложения) ------------------------

_task: asyncio.Task | None = None
_gateway: Gateway | None = None


def start() -> None:
    global _task, _gateway
    s = get_settings()
    if not s.telegram_bot_token or (_task and not _task.done()):
        return
    _gateway = Gateway(s.telegram_bot_token, s.telegram_chat_id)
    _task = asyncio.create_task(_gateway.run())


async def stop() -> None:
    global _task, _gateway
    if _task:
        _task.cancel()
        _task = None
    if _gateway:
        await _gateway.tg.close()
        _gateway = None
