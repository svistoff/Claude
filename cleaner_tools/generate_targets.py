"""
Генерирует свежие цели для telegram-cleaner на основе боевой базы F_chatsBot.

Идея: любой, кто вступил в группу и попал в captcha_sessions, но НИ РАЗУ
не прошёл проверку (status='passed') для этой группы — почти гарантированно
бот (в текущей базе так помечено 98%+ вступивших). Берём таких людей и
добавляем в group1.csv/group2.csv, которые уже использует cleaner.py —
он сам пропустит всех, кто там уже был обработан раньше (see progress_*.txt),
и обработает только новых.

ВАЖНО: запускать НА СЕРВЕРЕ, там же где telegram-cleaner (нужна его
telethon-сессия, чтобы правильно определить chat_id каждой группы по
username) и где лежит datewell.db (база F_chatsBot).

Использование:
    cd /root/telegram-cleaner
    source venv/bin/activate          # если ставили telethon в venv
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

CLEANER_DIR = Path("/root/telegram-cleaner")
CONFIG_FILE = CLEANER_DIR / "config.ini"
SESSION_FILE = CLEANER_DIR / "cleaner_session"

# Путь к базе F_chatsBot. Поправь, если у тебя бот лежит в другой папке.
DB_PATH = Path("/root/F_chatsBot/datewell.db")

CSV_FIELDS = ["user_id", "join_datetime", "first_name", "username"]


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
                "username": config.get(section, "username"),
                "file": Path(config.get(section, "file")),
            })
    return api_id, api_hash, groups


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


def merge_into_csv(path: Path, new_rows: list[dict]) -> int:
    """Добавляет новые строки в CSV, не дублируя уже присутствующие user_id."""
    existing_ids = set()
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    existing_ids.add(int(row["user_id"]))
                except (KeyError, ValueError, TypeError):
                    pass

    fresh = [r for r in new_rows if int(r["user_id"]) not in existing_ids]

    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        for r in fresh:
            writer.writerow({k: r.get(k, "") for k in CSV_FIELDS})

    return len(fresh)


async def main():
    if not DB_PATH.exists():
        print(f"❌ Не найдена база {DB_PATH}. Поправь DB_PATH в скрипте.")
        return

    api_id, api_hash, groups = load_cleaner_config()
    if not groups:
        print("❌ В config.ini нет включённых групп.")
        return

    client = TelegramClient(str(SESSION_FILE), api_id, api_hash)
    await client.start()

    for group in groups:
        entity = await client.get_entity(group["username"])
        # Telethon отдаёт "голый" id супергруппы/канала, Bot API всегда
        # использует его с префиксом -100 — приводим к тому же виду,
        # в котором chat_id хранится в captcha_sessions.
        chat_id = int(f"-100{entity.id}")

        candidates = fetch_never_passed(DB_PATH, chat_id)
        added = merge_into_csv(group["file"], candidates)

        print(
            f"{group['name']} ({group['username']}, chat_id={chat_id}): "
            f"кандидатов в базе {len(candidates)}, добавлено новых в {group['file'].name}: {added}"
        )

    await client.disconnect()
    print("\nГотово. Теперь можно запускать: python3 cleaner.py")


if __name__ == "__main__":
    asyncio.run(main())
