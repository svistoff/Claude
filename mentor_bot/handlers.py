"""Команды бота. Управление целиком из Telegram — без веб-интерфейса."""

from __future__ import annotations

import re
from pathlib import Path

from .config import Config
from .db import DB
from .scheduler import send_advice

NAME_RE = re.compile(r"^[\w-]{1,40}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

HELP = """\
Я наставник: каждый день присылаю ОДИН шаг к первой выручке по твоим проектам,
а вечером спрашиваю, как прошло. Твои ответы учитываю в следующих советах.

Проекты:
/add имя [путь] — добавить проект (путь к папке на сервере — по желанию)
/goal имя текст — цель: кто клиент, за что платит, что мешает первому рублю
/path имя путь — привязать папку проекта (смотрю git-лог и README)
/time имя ЧЧ:ММ [будни] — во сколько присылать совет
/on имя · /off имя — включить/выключить советы
/del имя — удалить проект
/projects — список проектов

Работа:
/now [имя] — совет прямо сейчас
/report имя текст — отчёт о сделанном
Или просто ответь (reply) на мой совет — запишу как отчёт.

/id — показать chat_id"""


def _fmt_project(p: dict) -> str:
    when = p["time_local"] + (" будни" if p["weekdays_only"] else " ежедневно")
    state = "вкл" if p["enabled"] else "выкл"
    lines = [f"• {p['name']} — {when}, {state}"]
    if p["path"]:
        lines.append(f"  папка: {p['path']}")
    lines.append(f"  цель: {p['goal'][:200] if p['goal'] else '— не задана (/goal)'}")
    return "\n".join(lines)


class Handler:
    def __init__(self, cfg: Config, db: DB, tg) -> None:
        self.cfg, self.db, self.tg = cfg, db, tg

    async def reply(self, chat_id: int, text: str) -> None:
        await self.tg.send(chat_id, text)

    async def handle(self, message: dict) -> None:
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or not text:
            return

        # Режим настройки: владелец ещё не указан — подсказываем chat_id.
        if not self.cfg.owner_chat_id:
            await self.reply(chat_id, f"Твой chat_id: {chat_id}\n"
                             f"Впиши в .env строку OWNER_CHAT_ID={chat_id} и перезапусти бота.")
            return
        if chat_id != self.cfg.owner_chat_id:
            await self.reply(chat_id, "Это личный бот-наставник, он отвечает только владельцу.")
            return

        if text.startswith("/"):
            cmd, _, rest = text.partition(" ")
            cmd = cmd.split("@")[0].lower()
            await self.command(chat_id, cmd, rest.strip())
            return
        await self.plain_report(chat_id, message, text)

    # --- Команды -----------------------------------------------------------
    async def command(self, chat_id: int, cmd: str, rest: str) -> None:
        args = rest.split()
        if cmd in ("/start", "/help"):
            await self.reply(chat_id, HELP)
        elif cmd == "/id":
            await self.reply(chat_id, f"chat_id: {chat_id}")
        elif cmd in ("/projects", "/list"):
            ps = self.db.list_projects()
            await self.reply(chat_id, "\n\n".join(_fmt_project(p) for p in ps)
                             if ps else "Проектов нет. Добавь: /add имя [путь]")
        elif cmd == "/add":
            await self.cmd_add(chat_id, args)
        elif cmd == "/goal":
            await self.cmd_goal(chat_id, rest)
        elif cmd == "/path":
            await self.cmd_path(chat_id, args)
        elif cmd == "/time":
            await self.cmd_time(chat_id, args)
        elif cmd in ("/on", "/off"):
            await self.cmd_toggle(chat_id, args, cmd == "/on")
        elif cmd == "/del":
            await self.cmd_del(chat_id, args)
        elif cmd == "/now":
            await self.cmd_now(chat_id, args)
        elif cmd == "/report":
            await self.cmd_report(chat_id, rest)
        else:
            await self.reply(chat_id, "Не знаю такой команды. /help — список.")

    def _project(self, name: str) -> dict | None:
        return self.db.get_project(name.lower())

    async def _need_project(self, chat_id: int, name: str | None) -> dict | None:
        if not name:
            await self.reply(chat_id, "Укажи имя проекта. /projects — список.")
            return None
        p = self._project(name)
        if p is None:
            await self.reply(chat_id, f"Проекта «{name}» нет. /projects — список.")
        return p

    @staticmethod
    def _bad_path(path: str) -> bool:
        return not Path(path).expanduser().is_dir()

    async def cmd_add(self, chat_id: int, args: list[str]) -> None:
        if not args:
            await self.reply(chat_id, "Формат: /add имя [путь]\nНапример: /add ai-companion /root/ai-companion")
            return
        name = args[0].lower()
        if not NAME_RE.match(name):
            await self.reply(chat_id, "Имя: буквы, цифры, дефис или подчёркивание, до 40 символов.")
            return
        if self.db.get_project(name):
            await self.reply(chat_id, f"Проект «{name}» уже есть.")
            return
        path = " ".join(args[1:])
        if path and self._bad_path(path):
            await self.reply(chat_id, f"Папка не найдена: {path}")
            return
        self.db.add_project(name, path, self.cfg.default_time)
        await self.reply(chat_id, f"Добавил «{name}». Совет буду присылать в {self.cfg.default_time}.\n"
                         f"Теперь главное — цель:\n/goal {name} кто клиент, за что заплатит, что мешает")

    async def cmd_goal(self, chat_id: int, rest: str) -> None:
        name, _, goal = rest.partition(" ")
        p = await self._need_project(chat_id, name)
        if p is None:
            return
        if not goal.strip():
            await self.reply(chat_id, f"Текущая цель «{p['name']}»:\n{p['goal'] or '— не задана'}\n\n"
                             f"Изменить: /goal {p['name']} текст")
            return
        self.db.update_project(p["name"], goal=goal.strip())
        await self.reply(chat_id, f"Цель «{p['name']}» сохранена. Совет сейчас: /now {p['name']}")

    async def cmd_path(self, chat_id: int, args: list[str]) -> None:
        p = await self._need_project(chat_id, args[0] if args else None)
        if p is None:
            return
        path = " ".join(args[1:])
        if not path or self._bad_path(path):
            await self.reply(chat_id, f"Папка не найдена: {path or '—'}")
            return
        self.db.update_project(p["name"], path=path)
        await self.reply(chat_id, f"Папка «{p['name']}»: {path}")

    async def cmd_time(self, chat_id: int, args: list[str]) -> None:
        p = await self._need_project(chat_id, args[0] if args else None)
        if p is None:
            return
        if len(args) < 2 or not TIME_RE.match(args[1]):
            await self.reply(chat_id, f"Формат: /time {p['name']} 09:00 [будни]")
            return
        weekdays = len(args) > 2 and args[2].lower().startswith("будн")
        self.db.update_project(p["name"], time_local=args[1], weekdays_only=int(weekdays),
                               last_sent_date=None)
        await self.reply(chat_id, f"«{p['name']}»: {args[1]}" + (" по будням" if weekdays else " ежедневно"))

    async def cmd_toggle(self, chat_id: int, args: list[str], on: bool) -> None:
        p = await self._need_project(chat_id, args[0] if args else None)
        if p is None:
            return
        self.db.update_project(p["name"], enabled=int(on))
        await self.reply(chat_id, f"«{p['name']}»: советы {'включены' if on else 'выключены'}.")

    async def cmd_del(self, chat_id: int, args: list[str]) -> None:
        p = await self._need_project(chat_id, args[0] if args else None)
        if p is None:
            return
        self.db.delete_project(p["name"])
        await self.reply(chat_id, f"Проект «{p['name']}» удалён из наставника (файлы на сервере не тронуты).")

    async def cmd_now(self, chat_id: int, args: list[str]) -> None:
        if args:
            p = await self._need_project(chat_id, args[0])
        else:
            ps = self.db.list_projects()
            if len(ps) == 1:
                p = ps[0]
            elif not ps:
                await self.reply(chat_id, "Проектов нет. Добавь: /add имя [путь]")
                return
            else:
                await self.reply(chat_id, "По какому проекту? " +
                                 ", ".join(f"/now {x['name']}" for x in ps))
                return
        if p is None:
            return
        await self.reply(chat_id, "Думаю над задачей на сегодня…")
        await send_advice(self.cfg, self.db, self.tg, p)

    async def cmd_report(self, chat_id: int, rest: str) -> None:
        name, _, text = rest.partition(" ")
        p = await self._need_project(chat_id, name)
        if p is None:
            return
        if not text.strip():
            await self.reply(chat_id, f"Формат: /report {p['name']} что сделал")
            return
        self.db.add_report(p["name"], text.strip())
        await self.reply(chat_id, f"Записал отчёт по «{p['name']}». Учту в следующем совете.")

    # --- Отчёт обычным сообщением ------------------------------------------
    async def plain_report(self, chat_id: int, message: dict, text: str) -> None:
        project = None
        reply_to = message.get("reply_to_message")
        if reply_to:
            project = self.db.project_by_message(reply_to.get("message_id"))
        if project is None:
            ps = self.db.list_projects()
            if len(ps) == 1:
                project = ps[0]["name"]
            elif reply_to is None:
                last = self.db.get_state("last_project")
                project = last if last and self.db.get_project(last) else None
        if project is None:
            await self.reply(chat_id, "Не понял, к какому проекту это отчёт. "
                             "Ответь (reply) на мой совет или напиши /report имя текст.")
            return
        self.db.add_report(project, text)
        await self.reply(chat_id, f"Записал отчёт по «{project}». Учту в следующем совете.")
