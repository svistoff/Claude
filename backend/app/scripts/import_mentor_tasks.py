"""Импорт задач из старого бота-ментора (mentor-bot) в базу ai-agent.

Зачем: до переезда на ai-agent личные задачи жили в `/root/mentor-bot/data/mentor.db`
(таблица `tasks`, 60 записей с историей). Новый бот использует свою таблицу
`tasks` в `agent.db` — она начиналась с нуля, поэтому номера не совпадали и
выполненные задачи не попадали в журнал работы.

Что делает:
- копирует задачи с сохранением id (номера #58, #65 остаются теми же);
- сохраняет created_at / done_at, поэтому «что сделано за неделю» считается верно;
- закрытые задачи дополнительно пишет в work_log (source="task") — из журнала
  собирается отчёт шефу;
- переносит priority / hidden_until (отложенные задачи) в текст, если поля нет
  в новой схеме.

Запуск (по умолчанию — только показать, что будет сделано):
    cd backend && .venv/bin/python -m app.scripts.import_mentor_tasks
    cd backend && .venv/bin/python -m app.scripts.import_mentor_tasks --apply

Перед записью делает резервную копию agent.db рядом с оригиналом.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_SRC = Path("/root/mentor-bot/data/mentor.db")
DEFAULT_DST = Path(__file__).resolve().parents[2] / "data" / "agent.db"


def _read_src(src: Path) -> list[dict]:
    # mode=ro — читаем старую базу, ничего в ней не меняя.
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select id, text, done, created_at, done_at, priority, hidden_until "
        "from tasks order by id"
    ).fetchall()
    con.close()

    out: list[dict] = []
    for r in rows:
        text = (r["text"] or "").strip()
        marks: list[str] = []
        if r["priority"] and r["priority"] not in ("normal", ""):
            marks.append("приоритет: " + str(r["priority"]))
        if r["hidden_until"]:
            marks.append("отложено до " + str(r["hidden_until"])[:10])
        if marks:
            text = f"{text} [{', '.join(marks)}]"
        out.append({
            "id": int(r["id"]),
            "text": text,
            "done": bool(r["done"]),
            "created_at": r["created_at"],
            "done_at": r["done_at"],
        })
    return out


def _norm_dt(value: str | None) -> str | None:
    """Привести дату к виду, который понимает SQLAlchemy DateTime (без таймзоны)."""
    if not value:
        return None
    v = str(value).replace("T", " ").strip()
    if v.endswith("Z"):
        v = v[:-1]
    if "+" in v:
        v = v.split("+", 1)[0]
    return v[:19]


def _plan(dst_rows: list[tuple], src: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    existing = {int(r[0]): r[1] for r in dst_rows}
    to_insert = [t for t in src if t["id"] not in existing]
    conflicts = [t for t in src if t["id"] in existing]
    extra = [{"id": i, "text": txt} for i, txt in existing.items()
             if i not in {t["id"] for t in src}]
    return to_insert, conflicts, extra


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Импорт задач mentor-bot → ai-agent")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--dst", type=Path, default=DEFAULT_DST)
    ap.add_argument("--apply", action="store_true", help="выполнить запись (иначе dry-run)")
    ap.add_argument("--drop-extra", action="store_true",
                    help="удалить задачи, которых нет в старой базе (мусор новой сессии)")
    ap.add_argument("--overwrite-conflicts", action="store_true",
                    help="при совпадении id заменить локальную задачу данными из старой базы "
                         "(старая база — источник истины)")
    ap.add_argument("--rebuild-worklog", action="store_true",
                    help="пересобрать work_log по закрытым задачам (очистить прежние записи source=task)")
    args = ap.parse_args(argv)

    for p in (args.src, args.dst):
        if not p.is_file():
            print(f"Нет файла: {p}", file=sys.stderr)
            return 2

    src = _read_src(args.src)
    con = sqlite3.connect(args.dst)
    dst_rows = con.execute("select id, text from tasks").fetchall()
    to_insert, conflicts, extra = _plan(dst_rows, src)

    print(f"Источник: {args.src}  (задач: {len(src)})")
    print(f"Назначение: {args.dst}  (задач: {len(dst_rows)})")
    print(f"  перенести новых: {len(to_insert)}")
    print(f"  уже есть с тем же id: {len(conflicts)}")
    print(f"  лишних в назначении: {len(extra)}")
    for e in extra:
        print(f"    #{e['id']} {e['text'][:60]}")
    if conflicts:
        for c in conflicts[:5]:
            print(f"    конфликт #{c['id']}: {c['text'][:50]}")

    if not args.apply:
        print("\nЭто dry-run. Для записи добавьте --apply")
        con.close()
        return 0

    backup = args.dst.with_suffix(args.dst.suffix + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(args.dst, backup)
    print(f"\nБэкап: {backup}")

    if args.drop_extra and extra:
        # Задачи, которых нет в старой базе, удаляем только по явному флагу.
        con.executemany("delete from tasks where id = ?", [(e["id"],) for e in extra])
        print(f"Удалено лишних: {len(extra)}")

    inserted = 0
    for t in to_insert:
        con.execute(
            "insert into tasks (id, text, done, created_at, done_at) values (?, ?, ?, ?, ?)",
            (t["id"], t["text"], 1 if t["done"] else 0,
             _norm_dt(t["created_at"]) or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             _norm_dt(t["done_at"])),
        )
        inserted += 1
    con.commit()
    print(f"Перенесено задач: {inserted}")

    if args.overwrite_conflicts and conflicts:
        for t in conflicts:
            con.execute(
                "update tasks set text=?, done=?, created_at=?, done_at=? where id=?",
                (t["text"], 1 if t["done"] else 0,
                 _norm_dt(t["created_at"]) or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 _norm_dt(t["done_at"]), t["id"]),
            )
        con.commit()
        print(f"Перезаписано конфликтующих задач: {len(conflicts)}")

    # Журнал работы: закрытые задачи = выполненная работа (для отчёта шефу).
    if args.rebuild_worklog:
        con.execute("delete from work_log where source = 'task'")
    done_rows = [t for t in src if t["done"]]
    logged = 0
    for t in done_rows:
        when = _norm_dt(t["done_at"]) or _norm_dt(t["created_at"])
        exists = con.execute(
            "select 1 from work_log where source='task' and text=? and created_at=?",
            (t["text"], when)).fetchone()
        if exists:
            continue
        con.execute(
            "insert into work_log (text, project, source, created_at) values (?, ?, ?, ?)",
            (t["text"], None, "task", when or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        logged += 1
    con.commit()
    print(f"Записей в журнал работы добавлено: {logged}")

    total = con.execute("select count(*) from tasks").fetchone()[0]
    open_n = con.execute("select count(*) from tasks where done=0").fetchone()[0]
    work_n = con.execute("select count(*) from work_log").fetchone()[0]
    print(f"\nИтог: задач {total} (открытых {open_n}), записей в журнале {work_n}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
