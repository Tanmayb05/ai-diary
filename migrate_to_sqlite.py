"""
migrate_to_sqlite.py — migrate JSON data files to SQLite.
Run once: python migrate_to_sqlite.py
Safe to re-run (idempotent via INSERT OR IGNORE).
"""

import json
import sqlite3
from pathlib import Path
from utils import DATA_DIR
from db import get_db

ENTRIES_JSON = DATA_DIR / "entries.json"
FACTS_JSON   = DATA_DIR / "facts.json"
TODOS_JSON   = DATA_DIR / "todos.json"


def migrate_entries(db: sqlite3.Connection) -> int:
    if not ENTRIES_JSON.exists():
        print("  entries.json not found, skipping.")
        return 0
    data = json.loads(ENTRIES_JSON.read_text())
    count = 0
    for date, entry_list in data.items():
        for raw in (entry_list if isinstance(entry_list, list) else [entry_list]):
            # Extract top-level columns; everything else goes in metadata JSON
            known = {"entry", "mood", "highlight", "sentiment", "sentiment_label",
                     "mood_alignment", "created_at", "updated_at", "saved_at"}
            metadata = {k: v for k, v in raw.items() if k not in known}
            db.execute(
                """INSERT OR IGNORE INTO entries
                   (date, entry, mood, highlight, sentiment, sentiment_label,
                    mood_alignment, metadata, created_at, updated_at, saved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    date,
                    raw.get("entry", ""),
                    raw.get("mood"),
                    raw.get("highlight"),
                    raw.get("sentiment"),
                    raw.get("sentiment_label"),
                    raw.get("mood_alignment"),
                    json.dumps(metadata),
                    raw.get("created_at"),
                    raw.get("updated_at"),
                    raw.get("saved_at"),
                ),
            )
            count += 1
    db.commit()
    return count


def migrate_facts(db: sqlite3.Connection) -> int:
    if not FACTS_JSON.exists():
        print("  facts.json not found, skipping.")
        return 0
    data = json.loads(FACTS_JSON.read_text())
    count = 0
    for fact_type, fact in data.items():
        db.execute(
            """INSERT OR REPLACE INTO facts
               (fact_type, value, source_date, source_excerpt, updated_at, history)
               VALUES (?,?,?,?,?,?)""",
            (
                fact_type,
                fact.get("value"),
                fact.get("source_date"),
                fact.get("source_excerpt"),
                fact.get("updated_at"),
                json.dumps(fact.get("history", [])),
            ),
        )
        count += 1
    db.commit()
    return count


def migrate_todos(db: sqlite3.Connection) -> int:
    if not TODOS_JSON.exists():
        print("  todos.json not found, skipping.")
        return 0
    data = json.loads(TODOS_JSON.read_text())
    todos = data if isinstance(data, list) else data.get("todos", [])
    count = 0
    for todo in todos:
        db.execute(
            """INSERT OR IGNORE INTO todos
               (id, text, deadline, priority, status, follow_up, source_excerpt, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                todo.get("id", str(count)),
                todo.get("task") or todo.get("text", ""),
                todo.get("deadline"),
                todo.get("priority"),
                todo.get("status", "pending"),
                todo.get("follow_up"),
                todo.get("source_excerpt"),
                todo.get("created_at"),
            ),
        )
        count += 1
    db.commit()
    return count


if __name__ == "__main__":
    print("Migrating to SQLite...")
    db = get_db()
    n = migrate_entries(db)
    print(f"  entries: {n} migrated")
    n = migrate_facts(db)
    print(f"  facts:   {n} migrated")
    n = migrate_todos(db)
    print(f"  todos:   {n} migrated")
    db.close()
    print("Done. diary.db created in data/")
