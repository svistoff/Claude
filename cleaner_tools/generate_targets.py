"""
Генерирует свежие цели для telegram-cleaner на основе боевой базы F_chatsBot.

Идея: любой, кто вступил в группу и попал в captcha_sessions, но НИ РАЗУ
не прошёл проверку (status='passed') для этой группы — почти гарантированно
бот (в текущей базе так помечено 98%+ вступивших). Берём таких людей и
добавляем в CSV, которые уже использует cleaner.py — он сам пропустит всех,
кто там уже был обработан раньше (см. progress_*.txt), и обработает только
новых.

Группа определяется НЕ по username из config.ini (он мог смениться —
именно это и произошло: старый username из config.ini сейчас никем не
занят), а напрямую по chat_id: скрипт сканирует реальные диалоги
telethon-аккаунта и сверяет их с chat_id, которые уже встречались в
captcha_sessions. Если для какого-то chat_id из базы не находится
соответствия в config.ini по текущему username — скрипт это явно покажет,
ничего не угадывая молча.

ВАЖНО: запускать НА СЕРВЕРЕ, там же где telegram-cleaner (нужна его
telethon-сессия) и где лежит datewell.db (база F_chatsBot).

Использование:
    cd /root/telegram-cleaner
    source venv/bin/activate
    python3 generate_targets.py

Скрипт НИЧЕГО не удаляет сам — только готовит CSV. Удаление делает
как обычно cleaner.py при следующем запуске (медленно, с паузами).
"""

import asyncio
import configparser
import csv
import sqlite3
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

CLEANER_DIR = Path("/root/telegram-cleaner")
CONFIG_FILE = CLEANER_DIR / "config.ini"
SESSION_FILE = CLEANER_DIR / "cleaner_session"

# Путь к базе F_chatsBot. Поправь, если бот лежит в другой папке.
DB_PATH = Path("/root/F_chatsBot/datewell.db")

# Поля, которые мы реально можем заполнить из datewell.db.
# Остальные колонки существующего CSV (is_bot, is_deleted, current_* и т.п.)
# оставляем пустыми — этих данных в базе CAPTCHA просто нет.
DEFAULT_FIELDS = ["user_id", "join_datetime", "first_name", "last_name", "username"]


def load_cleaner_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    api_id = config.getint("telegram", "api_id")
    api_hash = config.get("telegram", "api_hash")

    groups = []
    for section in ("group1", "group2"):
        if config.has_section(section) and config.getboolean(section, "enabled", fallback=False):
            groups.append({
                "name": section,
                "username": config.get(section, "username").lstrip("@").lower(),
                "file": Path(config.get(section, "file")),
            })
    return api_id, api_hash, groups


def db_chat_ids(db_path: Path) -> list[tuple[int, int]]:
    """[(chat_id, число сессий), ...] по убыванию активности — чтобы видеть, что вообще есть в базе."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT chat_id, COUNT(*) FROM captcha_sessions GROUP BY chat_id ORDER BY COUNT(*) DESC")
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_never_passed(db_path: Path, chat_id: int) -> list[dict]:
    """Все, кто вступал в этот чат и НИ РАЗУ не прошёл капчу для него."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT cs.user_id AS user_id,
               MIN(cs.created_at) AS join_datetime,
               COALESCE(MAX(u.first_name), '') AS first_name,
               COALESCE(MAX(u.last_name), '') AS last_name,
               COALESCE(MAX(u.username), '') AS username
        FROM captcha_sessions cs
        LEFT JOIN users u ON u.user_id = cs.user_id
        WHERE cs.chat_id = ?
          AND cs.user_id NOT IN (
              SELECT user_id FROM captcha_sessions
              WHERE chat_id = ? AND status = 'passed'
          )
        GROUP BY cs.user_id
        """,
        (chat_id, chat_id),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def read_csv_header(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        try:
            return next(csv.reader(f))
        except StopIteration:
            return None


def merge_into_csv(path: Path, new_rows: list[dict]) -> int:
    """Добавляет новые строки в CSV, сохраняя существующий формат колонок
    (если файла ещё нет — создаёт с DEFAULT_FIELDS) и не дублируя user_id."""
    header = read_csv_header(path)
    fieldnames = header or DEFAULT_FIELDS

    existing_ids = set()
    if header:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    existing_ids.add(int(row["user_id"]))
                except (KeyError, ValueError, TypeError):
                    pass

    fresh = [r for r in new_rows if int(r["user_id"]) not in existing_ids]

    write_header = header is None
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for r in fresh:
            row = {k: "" for k in fieldnames}
            row.update({k: v for k, v in r.items() if k in fieldnames})
            writer.writerow(row)

    return len(fresh)


async def main():
    if not DB_PATH.exists():
        print(f"❌ Не найдена база {DB_PATH}. Поправь DB_PATH в скрипте.")
        return

    api_id, api_hash, groups = load_cleaner_config()
    if not groups:
        print("❌ В config.ini нет включённых групп.")
        return

    chat_stats = db_chat_ids(DB_PATH)
    target_chat_ids = {cid for cid, _ in chat_stats}
    by_username = {g["username"]: g for g in groups}

    print("В базе CAPTCHA найдены чаты:")
    for cid, cnt in chat_stats:
        print(f"  chat_id={cid}: {cnt} сессий")
    print()

    client = TelegramClient(str(SESSION_FILE), api_id, api_hash)
    await client.start()

    matched_chat_ids = set()

    print("Сканирую диалоги аккаунта и сверяю с chat_id из базы...\n")
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel):
            chat_id = int(f"-100{entity.id}")
        elif isinstance(entity, Chat):
            chat_id = -entity.id
        else:
            continue

        if chat_id not in target_chat_ids:
            continue

        matched_chat_ids.add(chat_id)
        username = (getattr(entity, "username", None) or "").lower()
        title = getattr(entity, "title", "?")

        group = by_username.get(username)
        if group is None:
            candidates = fetch_never_passed(DB_PATH, chat_id)
            print(
                f"⚠️  chat_id={chat_id} title=\"{title}\" username=@{username or '(нет)'}\n"
                f"    Не совпадает ни с одним username из config.ini ({', '.join('@' + u for u in by_username)}).\n"
                f"    Похоже, публичный username этой группы сменился с момента настройки config.ini.\n"
                f"    Кандидатов на удаление в базе для этого чата: {len(candidates)}.\n"
                f"    Чтобы обработать — поправь username в config.ini на \"{username or '(текущий)'}\" и запусти скрипт заново.\n"
            )
            continue

        candidates = fetch_never_passed(DB_PATH, chat_id)
        added = merge_into_csv(group["file"], candidates)
        print(
            f"✅ {group['name']} (@{username or '?'}, chat_id={chat_id}, \"{title}\"): "
            f"кандидатов в базе {len(candidates)}, добавлено новых в {group['file'].name}: {added}"
        )

    missing = target_chat_ids - matched_chat_ids
    if missing:
        print(f"\n⚠️  Не найдены среди диалогов аккаунта: {sorted(missing)}")
        print("    Возможно, этот telethon-аккаунт больше не состоит в этой группе/канале.")

    await client.disconnect()
    print("\nГотово. Если выше есть ✅ — можно запускать: python3 cleaner.py")


if __name__ == "__main__":
    asyncio.run(main())
