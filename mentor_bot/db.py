"""SQLite-хранилище: входящие задачи, проекты, советы, отчёты, служебное состояние."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL DEFAULT '',
    repo TEXT NOT NULL DEFAULT '',
    time_local TEXT NOT NULL DEFAULT '09:00',
    weekdays_only INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_sent_date TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS advice (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'advice',  -- advice | evening
    message_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    done_at TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',  -- urgent | normal | later
    postponed INTEGER NOT NULL DEFAULT 0,
    hidden_until TEXT,   -- локальная дата YYYY-MM-DD: до неё задача не попадает в план
    last_shown TEXT      -- локальная дата, когда задача в последний раз была в плане
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'text',  -- text | link | photo
    text TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    file_id TEXT NOT NULL DEFAULT '',   -- Telegram file_id картинки
    source TEXT NOT NULL DEFAULT '',    -- откуда переслано
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,  -- user | assistant
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

PRIORITIES = ("urgent", "normal", "later")
TASK_MIGRATIONS = {
    "priority": "TEXT NOT NULL DEFAULT 'normal'",
    "postponed": "INTEGER NOT NULL DEFAULT 0",
    "hidden_until": "TEXT",
    "last_shown": "TEXT",
}

PROJECT_FIELDS = {"path", "repo", "goal", "time_local", "weekdays_only", "enabled", "last_sent_date"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # Базы, созданные до появления приоритетов, дополняем недостающими колонками.
        have = {r["name"] for r in self.conn.execute("PRAGMA table_info(tasks)")}
        for col, ddl in TASK_MIGRATIONS.items():
            if col not in have:
                self.conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
        pcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(projects)")}
        if "repo" not in pcols:
            self.conn.execute("ALTER TABLE projects ADD COLUMN repo TEXT NOT NULL DEFAULT ''")
        self.conn.commit()

    # --- Проекты -----------------------------------------------------------
    def add_project(self, name: str, path: str = "", time_local: str = "09:00") -> None:
        self.conn.execute(
            "INSERT INTO projects (name, path, time_local, created_at) VALUES (?, ?, ?, ?)",
            (name, path, time_local, _now()),
        )
        self.conn.commit()

    def get_project(self, name: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    def list_projects(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def update_project(self, name: str, **fields) -> None:
        fields = {k: v for k, v in fields.items() if k in PROJECT_FIELDS}
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE projects SET {cols} WHERE name = ?", (*fields.values(), name))
        self.conn.commit()

    def delete_project(self, name: str) -> bool:
        cur = self.conn.execute("DELETE FROM projects WHERE name = ?", (name,))
        self.conn.commit()
        return cur.rowcount > 0

    # --- Советы ------------------------------------------------------------
    def add_advice(self, project: str, text: str, message_id: int | None,
                   kind: str = "advice") -> None:
        self.conn.execute(
            "INSERT INTO advice (project, text, kind, message_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project, text, kind, message_id, _now()),
        )
        self.conn.commit()

    def recent_advice(self, project: str, limit: int = 5) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM advice WHERE project = ? AND kind = 'advice' ORDER BY id DESC LIMIT ?",
            (project, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def project_by_message(self, message_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT project FROM advice WHERE message_id = ? ORDER BY id DESC LIMIT 1", (message_id,)
        ).fetchone()
        return row["project"] if row else None

    # --- Отчёты ------------------------------------------------------------
    def add_report(self, project: str, text: str) -> None:
        self.conn.execute(
            "INSERT INTO reports (project, text, created_at) VALUES (?, ?, ?)",
            (project, text, _now()),
        )
        self.conn.commit()

    def recent_reports(self, project: str, limit: int = 5) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM reports WHERE project = ? ORDER BY id DESC LIMIT ?", (project, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def has_report_since(self, project: str, since_iso: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM reports WHERE project = ? AND created_at >= ? LIMIT 1", (project, since_iso)
        ).fetchone()
        return row is not None

    # --- Входящие задачи ----------------------------------------------------
    def add_task(self, text: str, priority: str = "normal") -> int:
        cur = self.conn.execute("INSERT INTO tasks (text, priority, created_at) VALUES (?, ?, ?)",
                                (text, priority, _now()))
        self.conn.commit()
        return cur.lastrowid

    def open_tasks(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM tasks WHERE done = 0 ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def set_priority(self, task_id: int, priority: str) -> dict | None:
        if priority not in PRIORITIES:
            raise ValueError(priority)
        cur = self.conn.execute("UPDATE tasks SET priority = ? WHERE id = ? AND done = 0",
                                (priority, task_id))
        self.conn.commit()
        return self.get_task(task_id) if cur.rowcount else None

    def append_task(self, task_id: int, extra: str) -> dict | None:
        """Дополнить открытую задачу деталью (план и советы видят её в тексте задачи)."""
        task = self.get_task(task_id)
        if not task or task["done"]:
            return None
        text = f"{task['text']} — {extra}"[:600]
        self.conn.execute("UPDATE tasks SET text = ? WHERE id = ?", (text, task_id))
        self.conn.commit()
        return self.get_task(task_id)

    def postpone_task(self, task_id: int, until: str) -> dict | None:
        """Отложить: скрыть из плана до даты `until` и учесть перенос."""
        cur = self.conn.execute(
            "UPDATE tasks SET postponed = postponed + 1, hidden_until = ? "
            "WHERE id = ? AND done = 0", (until, task_id))
        self.conn.commit()
        return self.get_task(task_id) if cur.rowcount else None

    def mark_shown(self, task_ids: list[int], day: str) -> None:
        self.conn.executemany("UPDATE tasks SET last_shown = ? WHERE id = ?",
                              [(day, i) for i in task_ids])
        self.conn.commit()

    def done_tasks_since(self, since_iso: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE done = 1 AND done_at >= ? ORDER BY done_at", (since_iso,)
        ).fetchall()
        return [dict(r) for r in rows]

    def complete_task(self, task_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ? AND done = 0", (task_id,)).fetchone()
        if row is None:
            return None
        self.conn.execute("UPDATE tasks SET done = 1, done_at = ? WHERE id = ?", (_now(), task_id))
        self.conn.commit()
        return dict(row)

    def delete_task(self, task_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()
        return dict(row)

    # --- Копилка мыслей ------------------------------------------------------
    def add_note(self, text: str = "", kind: str = "text", url: str = "",
                 file_id: str = "", source: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO notes (kind, text, url, file_id, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", (kind, text, url, file_id, source, _now()))
        self.conn.commit()
        return cur.lastrowid

    def list_notes(self, query: str = "", limit: int = 10) -> list[dict]:
        if query:
            like = f"%{query}%"
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE text LIKE ? OR url LIKE ? OR source LIKE ? "
                "ORDER BY id DESC LIMIT ?", (like, like, like, limit)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM notes ORDER BY id DESC LIMIT ?",
                                     (limit,)).fetchall()
        return [dict(r) for r in rows]

    def count_notes(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]

    def delete_note(self, note_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # --- Память: факты о владельце и история диалога -------------------------
    def add_fact(self, text: str) -> int | None:
        text = text.strip()
        # lower() в SQLite не понимает кириллицу — сравниваем в Python.
        if any(f["text"].lower() == text.lower() for f in self.list_facts(1000)):
            return None
        cur = self.conn.execute("INSERT INTO facts (text, created_at) VALUES (?, ?)", (text, _now()))
        self.conn.commit()
        return cur.lastrowid

    def list_facts(self, limit: int = 60) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM facts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def delete_fact(self, fact_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def add_chat(self, role: str, text: str, keep: int = 200) -> None:
        self.conn.execute("INSERT INTO chat (role, text, created_at) VALUES (?, ?, ?)",
                          (role, text[:2000], _now()))
        self.conn.execute("DELETE FROM chat WHERE id <= (SELECT MAX(id) FROM chat) - ?", (keep,))
        self.conn.commit()

    def recent_chat(self, limit: int = 12) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM chat ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    # --- Состояние ---------------------------------------------------------
    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()
