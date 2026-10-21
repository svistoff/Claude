"""Команды бота. Управление целиком из Telegram — без веб-интерфейса."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from .config import Config
from .db import DB
from . import assistant, github, stt
from . import tasks as tasks_mod
from .llm import LLMError
from .scheduler import local_now, send_advice, send_plan

MAX_VOICE_SECONDS = 300
NAME_RE = re.compile(r"^[\w-]{1,40}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

HELP = """\
Я «Мой наставник» — организую твой рабочий день.

📥 Задачи — просто пиши мне сообщением, всё попадёт во входящие:
«позвонить бухгалтеру», «доделать оплату в боте», «ответить клиенту»…
🧠 Со мной можно просто разговаривать: пойму, задача это, вопрос или мысль, и сам
запишу. Запоминаю важное о тебе (/memory, /forget N).
💡 Копилка мыслей: пересылай мне цитаты и посты, присылай картинки и ссылки
(или пиши «💡 текст») — всё сохраню. /notes [слово] — посмотреть и найти.
🎙 Можно и голосовым — разберу на задачи (можно сразу несколько).
Срочное начинай с «!» или «срочно», несрочное — с «потом».
/tasks — открытые задачи · /urgent N · /later N — сменить срочность
/done N — задача сделана · /drop N — убрать задачу
/plan — план дня прямо сейчас

Утром присылаю план: главное дело дня и что можно отложить.
Вечером — итог: что сделано, что осталось.

🎯 Проекты (по желанию) — для долгих целей, с советом раз в день:
/add имя [путь] · /goal имя текст · /path имя путь
/repo имя owner/name — GitHub-репозиторий: читаю коммиты, issue, README
/time имя ЧЧ:ММ [будни] · /on имя · /off имя · /del имя
/projects · /now [имя] — совет по проекту сейчас
/report имя текст — отчёт (или просто reply на мой совет)

/id — показать chat_id"""


def _fmt_project(p: dict) -> str:
    when = p["time_local"] + (" будни" if p["weekdays_only"] else " ежедневно")
    state = "вкл" if p["enabled"] else "выкл"
    lines = [f"• {p['name']} — {when}, {state}"]
    if p["path"]:
        lines.append(f"  папка: {p['path']}")
    if p.get("repo"):
        lines.append(f"  GitHub: {p['repo']}")
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
        voice = message.get("voice")
        photo = message.get("photo")
        if chat_id is None or not (text or voice or photo):
            return

        # Режим настройки: владелец ещё не указан — подсказываем chat_id.
        if not self.cfg.owner_chat_id:
            await self.reply(chat_id, f"Твой chat_id: {chat_id}\n"
                             f"Впиши в .env строку OWNER_CHAT_ID={chat_id} и перезапусти бота.")
            return
        if chat_id != self.cfg.owner_chat_id:
            await self.reply(chat_id, "Это личный бот-наставник, он отвечает только владельцу.")
            return

        # Копилка: картинки и пересылки сохраняем сразу, не превращая в задачи.
        caption = (message.get("caption") or "").strip()
        source = tasks_mod.forward_source(message)
        if photo or (source and not text.startswith("/")):
            await self.save_note(chat_id, message, text or caption, source, photo)
            return
        if voice and not text:
            await self.voice_message(chat_id, message, voice)
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
        elif cmd == "/repo":
            await self.cmd_repo(chat_id, args)
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
        elif cmd == "/tasks":
            await self.cmd_tasks(chat_id)
        elif cmd == "/memory":
            await self.cmd_memory(chat_id)
        elif cmd == "/forget":
            await self.cmd_forget(chat_id, args)
        elif cmd == "/notes":
            await self.cmd_notes(chat_id, rest)
        elif cmd == "/unnote":
            await self.cmd_unnote(chat_id, args)
        elif cmd in ("/urgent", "/later"):
            await self.cmd_priority(chat_id, args, cmd[1:])
        elif cmd in ("/done", "/drop"):
            await self.cmd_close(chat_id, args, cmd == "/done")
        elif cmd == "/plan":
            await self.reply(chat_id, "Раскладываю задачи…")
            await send_plan(self.cfg, self.db, self.tg)
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
            await self.reply(chat_id, "Формат: /add имя [путь]\nНапример: /add my-shop /root/my-shop")
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

    async def cmd_repo(self, chat_id: int, args: list[str]) -> None:
        p = await self._need_project(chat_id, args[0] if args else None)
        if p is None:
            return
        if len(args) < 2:
            await self.reply(chat_id, f"Формат: /repo {p['name']} owner/name\n"
                             f"Сейчас: {p['repo'] or '— не задан'} · убрать: /repo {p['name']} -")
            return
        if args[1] == "-":
            self.db.update_project(p["name"], repo="")
            await self.reply(chat_id, f"GitHub у «{p['name']}» отвязан.")
            return
        repo = github.parse_repo(args[1])
        if repo is None:
            await self.reply(chat_id, "Не похоже на репозиторий. Пример: /repo shop svistoff/my-shop")
            return
        try:
            await github.fetch_context(repo, self.cfg.github_token)
        except github.GitHubError as exc:
            await self.reply(chat_id, f"⚠ {exc}")
            return
        self.db.update_project(p["name"], repo=repo)
        await self.reply(chat_id, f"Привязал {repo} к «{p['name']}». Теперь советы учитывают "
                         f"коммиты, issue и README. Проверить: /now {p['name']}")

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

    # --- Задачи --------------------------------------------------------------
    async def cmd_tasks(self, chat_id: int) -> None:
        tasks = self.db.open_tasks()
        if not tasks:
            await self.reply(chat_id, "📭 Открытых задач нет. Просто напиши мне задачу сообщением.")
            return
        marks = {"urgent": "🔥", "normal": "•", "later": "🕓"}
        order = {"urgent": 0, "normal": 1, "later": 2}
        tasks.sort(key=lambda t: (order[t["priority"]], t["id"]))
        await self.reply(chat_id, "📋 Открытые задачи:\n" +
                         "\n".join(f"{marks[t['priority']]} #{t['id']} {t['text']}" for t in tasks) +
                         "\n\nСделал — /done номер. План дня — /plan")

    async def cmd_priority(self, chat_id: int, args: list[str], prio: str) -> None:
        cmd = "/urgent" if prio == "urgent" else "/later"
        if not args or not args[0].lstrip("#").isdigit():
            await self.reply(chat_id, f"Формат: {cmd} номер (номера — в /tasks)")
            return
        task_id = int(args[0].lstrip("#"))
        task = self.db.set_priority(task_id, prio)
        if task is None:
            await self.reply(chat_id, f"Открытой задачи #{task_id} нет. /tasks — список.")
            return
        mark = "🔥 срочная" if prio == "urgent" else "🕓 на потом"
        await self.reply(chat_id, f"#{task_id} теперь {mark}: {task['text']}")

    async def cmd_close(self, chat_id: int, args: list[str], done: bool) -> None:
        cmd = "/done" if done else "/drop"
        if not args or not args[0].lstrip("#").isdigit():
            await self.reply(chat_id, f"Формат: {cmd} номер (номера — в /tasks)")
            return
        task_id = int(args[0].lstrip("#"))
        task = self.db.complete_task(task_id) if done else self.db.delete_task(task_id)
        if task is None:
            await self.reply(chat_id, f"Открытой задачи #{task_id} нет. /tasks — список.")
            return
        left = len(self.db.open_tasks())
        mark = "✅ Сделано" if done else "🗑 Убрал"
        await self.reply(chat_id, f"{mark}: {task['text']}\nОсталось открытых: {left}")

    # --- Обычное сообщение: отчёт (reply на совет) или новая задача ---------
    async def plain_report(self, chat_id: int, message: dict, text: str) -> None:
        reply_to = message.get("reply_to_message")
        project = self.db.project_by_message(reply_to.get("message_id")) if reply_to else None
        if project is not None:
            self.db.add_report(project, text)
            await self.reply(chat_id, f"Записал отчёт по «{project}». Учту в следующем совете.")
            return
        is_note, note_text = tasks_mod.parse_note(text)
        if is_note:
            await self.save_note(chat_id, message, note_text, "", None)
            return
        prio, clean = tasks_mod.parse_priority(text)
        if prio != "normal":  # явная пометка «!» / «потом» — без раздумий записываем
            task_id = self.db.add_task(clean, prio)
            label = "🔥 срочную" if prio == "urgent" else "🕓 «на потом»"
            await self.tg.send(chat_id, f"📥 Записал {label} задачу #{task_id}. "
                               f"Открытых: {len(self.db.open_tasks())}.",
                               buttons=tasks_mod.new_task_buttons(task_id))
            return
        await self.converse(chat_id, text)

    # --- Диалог: секретарь понимает сообщение и сам ведёт базу ----------------
    async def converse(self, chat_id: int, text: str, prefix: str = "") -> None:
        try:
            result = await assistant.respond(self.cfg, self.db, local_now(self.cfg), text)
        except LLMError as exc:
            result, why = None, str(exc)
        else:
            why = "ответ не по формату"
        if result is None:
            # ИИ недоступен: вопрос не превращаем в задачу, остальное не теряем.
            if "?" in text:
                await self.reply(chat_id, f"{prefix}⚠ Сейчас не могу ответить ({why}). Повтори чуть позже.")
                return
            prio, clean = tasks_mod.parse_priority(text)
            tid = self.db.add_task(clean, prio)
            await self.reply(chat_id, f"{prefix}📥 ИИ недоступен ({why}), записал как задачу #{tid}.")
            return
        reply, summary = result
        one = summary["added"] if len(summary["added"]) == 1 and not summary["done"] else []
        await self.tg.send(chat_id, prefix + reply,
                           buttons=tasks_mod.new_task_buttons(one[0]) if one else None)

    async def cmd_memory(self, chat_id: int) -> None:
        facts = self.db.list_facts()
        await self.reply(chat_id, "🧠 Что я помню о тебе:\n" +
                         "\n".join(f"[{f['id']}] {f['text']}" for f in facts) +
                         "\n\nЗабыть: /forget номер" if facts else
                         "Пока ничего не запомнил. Расскажи о себе и проектах — запомню важное.")

    async def cmd_forget(self, chat_id: int, args: list[str]) -> None:
        if not args or not args[0].lstrip("#").isdigit():
            await self.reply(chat_id, "Формат: /forget номер (номера — в /memory)")
            return
        fid = int(args[0].lstrip("#"))
        await self.reply(chat_id, "Забыл." if self.db.delete_fact(fid) else f"Факта #{fid} нет.")

    # --- Копилка мыслей --------------------------------------------------------
    async def save_note(self, chat_id: int, message: dict, text: str, source: str,
                        photo: list | None) -> None:
        url_m = tasks_mod.URL_RE.search(text)
        file_id = photo[-1]["file_id"] if photo else ""  # последний размер — самый крупный
        kind = "photo" if photo else "link" if url_m and len(text) < 400 else "text"
        nid = self.db.add_note(text, kind, url_m.group(0) if url_m else "", file_id, source)
        what = {"photo": "картинку", "link": "ссылку", "text": "мысль"}[kind]
        await self.reply(chat_id, f"💡 Сохранил {what} в копилку (#{nid}, всего {self.db.count_notes()}).\n"
                         "/notes — посмотреть · /unnote N — убрать")

    async def cmd_notes(self, chat_id: int, query: str) -> None:
        notes = self.db.list_notes(query)
        if not notes:
            await self.reply(chat_id, "Копилка пуста. Перешли мне мысль, пришли картинку, "
                             "ссылку или напиши «💡 текст»." if not query else "Ничего не нашёл.")
            return
        icon = {"photo": "🖼", "link": "🔗", "text": "💬"}
        lines = []
        for n in notes:
            body = n["text"][:200] or "(без подписи)"
            src = f" — {n['source']}" if n["source"] else ""
            lines.append(f"{icon[n['kind']]} #{n['id']} {body}{src}")
        head = f"💡 Копилка (последние {len(notes)} из {self.db.count_notes()}):" if not query \
            else f"🔎 Нашёл {len(notes)}:"
        await self.reply(chat_id, head + "\n" + "\n".join(lines))

    async def cmd_unnote(self, chat_id: int, args: list[str]) -> None:
        if not args or not args[0].lstrip("#").isdigit():
            await self.reply(chat_id, "Формат: /unnote номер (номера — в /notes)")
            return
        nid = int(args[0].lstrip("#"))
        await self.reply(chat_id, "🗑 Убрал из копилки." if self.db.delete_note(nid)
                         else f"Мысли #{nid} нет.")

    # --- Голосовые: расшифровка → отчёт или задачи ---------------------------
    async def voice_message(self, chat_id: int, message: dict, voice: dict) -> None:
        if not self.cfg.stt_api_key:
            await self.reply(chat_id, "🎙 Голосовые пока не включены: добавь STT_API_KEY в .env "
                             "(см. .env.example) и перезапусти бота.")
            return
        if voice.get("duration", 0) > MAX_VOICE_SECONDS or voice.get("file_size", 0) > 19_000_000:
            await self.reply(chat_id, "🎙 Слишком длинное голосовое — запиши покороче (до 5 минут).")
            return
        try:
            audio = await self.tg.download_file(voice["file_id"])
            transcript = await stt.transcribe(self.cfg.stt_api_key, self.cfg.stt_base_url,
                                              self.cfg.stt_model, audio)
        except stt.STTError as exc:
            await self.reply(chat_id, f"⚠ Не смог расшифровать голосовое: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 — скачивание из Telegram
            await self.reply(chat_id, f"⚠ Не смог скачать голосовое: {exc}")
            return
        if not transcript:
            await self.reply(chat_id, "🎙 Ничего не расслышал — попробуй ещё раз.")
            return
        # Ответ голосом на совет — это отчёт, как и обычный текстовый reply.
        reply_to = message.get("reply_to_message")
        project = self.db.project_by_message(reply_to.get("message_id")) if reply_to else None
        if project is not None:
            self.db.add_report(project, transcript)
            await self.reply(chat_id, f"🎙 «{transcript}»\nЗаписал отчёт по «{project}».")
            return
        is_note, note_text = tasks_mod.parse_note(transcript)
        if is_note:
            await self.save_note(chat_id, message, note_text, "", None)
            return
        await self.converse(chat_id, transcript, prefix=f"🎙 «{transcript[:300]}»\n\n")

    # --- Нажатия на inline-кнопки -------------------------------------------
    async def handle_callback(self, cb: dict) -> None:
        msg = cb.get("message") or {}
        chat_id = msg.get("chat", {}).get("id")
        if not self.cfg.owner_chat_id or chat_id != self.cfg.owner_chat_id:
            await self.tg.answer_callback(cb["id"])
            return
        action, _, raw = (cb.get("data") or "").partition(":")
        if not raw.isdigit():
            await self.tg.answer_callback(cb["id"])
            return
        task_id = int(raw)
        db = self.db
        if action == "done":
            ok, toast = db.complete_task(task_id) is not None, "✅ Сделано"
        elif action == "drop":
            ok, toast = db.delete_task(task_id) is not None, "🗑 Убрал"
        elif action == "snooze":
            tomorrow = (local_now(self.cfg) + timedelta(days=1)).strftime("%Y-%m-%d")
            ok, toast = db.postpone_task(task_id, tomorrow) is not None, "⏸ Вернётся завтра"
        elif action in ("urgent", "later"):
            ok = db.set_priority(task_id, action) is not None
            toast = "🔥 Срочно" if action == "urgent" else "🕓 На потом"
        else:
            ok, toast = False, ""
        await self.tg.answer_callback(cb["id"], toast if ok else "Уже неактуально")
        # Убираем кнопки закрытой задачи; у остальных строк клавиатура остаётся.
        if ok and action in ("done", "drop", "snooze") and msg.get("message_id"):
            rows = msg.get("reply_markup", {}).get("inline_keyboard", [])
            keep = [r for r in rows if not any(b.get("callback_data", "").endswith(f":{task_id}")
                                               for b in r)]
            await self.tg.set_buttons(chat_id, msg["message_id"], keep)
        elif ok:  # смена срочности на карточке новой задачи — кнопки больше не нужны
            await self.tg.set_buttons(chat_id, msg["message_id"], [])
