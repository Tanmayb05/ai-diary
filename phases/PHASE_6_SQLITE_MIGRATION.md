# Phase 6 — SQLite Migration (Schema + Data)

## Goal
Migrate all data from JSON files (`entries.json`, `facts.json`, `todos.json`) into a single
SQLite database (`data/diary.db`). Replace all JSON read/write calls in `diary.py`, `facts.py`,
and `utils.py` with SQLite queries. No behaviour changes — same API, different storage backend.

## Status: NOT STARTED
## Depends on: Nothing (replaces existing storage layer)

---

## Why SQLite over JSON

- Indexed date queries — no full-file loads
- FTS5 built-in for keyword search (Phase 8)
- sqlite-vec ready for embeddings (Phase 7)
- Single `.db` file — same backup simplicity
- Atomic writes — no corruption on crash

---

## New file: `db.py` — database layer

```python
"""
db.py — SQLite connection and schema management.
All other modules import get_db() from here.
"""

import sqlite3
from pathlib import Path
from utils import DATA_DIR

DB_PATH = DATA_DIR / "diary.db"


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
    db.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(db)
    return db


def _ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,          -- YYYY-MM-DD
            entry       TEXT NOT NULL DEFAULT '',
            mood        TEXT,
            highlight   TEXT,
            sentiment   TEXT,
            sentiment_label TEXT,
            mood_alignment  TEXT,
            metadata    TEXT NOT NULL DEFAULT '{}',  -- JSON blob for all other fields
            created_at  TEXT,
            updated_at  TEXT,
            saved_at    TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_date ON entries(date);

        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
            entry,
            highlight,
            content='entries',
            content_rowid='id',
            tokenize='porter ascii'
        );

        -- Keep FTS index in sync
        CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
            INSERT INTO entries_fts(rowid, entry, highlight)
            VALUES (new.id, new.entry, new.highlight);
        END;
        CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, entry, highlight)
            VALUES ('delete', old.id, old.entry, old.highlight);
            INSERT INTO entries_fts(rowid, entry, highlight)
            VALUES (new.id, new.entry, new.highlight);
        END;
        CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, entry, highlight)
            VALUES ('delete', old.id, old.entry, old.highlight);
        END;

        CREATE TABLE IF NOT EXISTS facts (
            fact_type   TEXT PRIMARY KEY,
            value       TEXT,
            source_date TEXT,
            source_excerpt TEXT,
            updated_at  TEXT,
            history     TEXT NOT NULL DEFAULT '[]'   -- JSON array
        );

        CREATE TABLE IF NOT EXISTS todos (
            id          TEXT PRIMARY KEY,
            text        TEXT NOT NULL,
            deadline    TEXT,
            priority    TEXT,
            status      TEXT DEFAULT 'pending',
            follow_up   TEXT,
            source_excerpt TEXT,
            created_at  TEXT
        );
    """)
    db.commit()
```

---

## Migration script: `migrate_to_sqlite.py`

One-time script. Safe to re-run (idempotent via INSERT OR IGNORE).

```python
"""
migrate_to_sqlite.py — migrate JSON data files to SQLite.
Run once: python migrate_to_sqlite.py
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
```

---

## Update `diary.py` — rewrite storage calls

Replace all `load_entries()` / `save_entries()` with SQLite equivalents.

Key functions to rewrite:

```python
# diary.py — updated signatures (same return types as before)

import json
from db import get_db

def get_entry(date: str | None) -> dict | None:
    db = get_db()
    row = db.execute(
        "SELECT * FROM entries WHERE date=?", (date or _today(),)
    ).fetchone()
    if not row:
        return None
    return _row_to_entry(row)

def save_entry(date: str, entry: dict) -> None:
    db = get_db()
    metadata = {k: v for k, v in entry.items()
                if k not in {"entry","mood","highlight","sentiment",
                              "sentiment_label","mood_alignment","created_at","updated_at","saved_at"}}
    db.execute(
        """INSERT INTO entries (date,entry,mood,highlight,sentiment,sentiment_label,
           mood_alignment,metadata,created_at,updated_at,saved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(date) DO UPDATE SET
             entry=excluded.entry, mood=excluded.mood, highlight=excluded.highlight,
             sentiment=excluded.sentiment, sentiment_label=excluded.sentiment_label,
             mood_alignment=excluded.mood_alignment, metadata=excluded.metadata,
             updated_at=excluded.updated_at, saved_at=excluded.saved_at""",
        (date, entry.get("entry",""), entry.get("mood"), entry.get("highlight"),
         entry.get("sentiment"), entry.get("sentiment_label"), entry.get("mood_alignment"),
         json.dumps(metadata), entry.get("created_at"), entry.get("updated_at"), entry.get("saved_at"))
    )
    db.commit()

def get_recent_entries(limit: int = 7) -> list[tuple[str, dict]]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM entries ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    return [(r["date"], _row_to_entry(r)) for r in rows]

def _row_to_entry(row) -> dict:
    d = dict(row)
    meta = json.loads(d.pop("metadata", "{}"))
    d.pop("id", None)
    return {**d, **meta}
```

---

## Update `facts.py` — rewrite storage calls

```python
# facts.py — replace load_facts / save_facts

import json
from db import get_db

def load_facts() -> dict:
    db = get_db()
    rows = db.execute("SELECT * FROM facts").fetchall()
    return {
        r["fact_type"]: {
            "value": r["value"],
            "source_date": r["source_date"],
            "source_excerpt": r["source_excerpt"],
            "updated_at": r["updated_at"],
            "history": json.loads(r["history"] or "[]"),
        }
        for r in rows
    }

def save_fact(fact_type: str, value: str, source_date: str, source_excerpt: str) -> None:
    db = get_db()
    existing = db.execute(
        "SELECT * FROM facts WHERE fact_type=?", (fact_type,)
    ).fetchone()
    history = json.loads(existing["history"]) if existing else []
    if existing and existing["value"] != value:
        history.append({"value": existing["value"], "source_date": existing["source_date"],
                        "updated_at": existing["updated_at"]})
    from utils import timestamp
    db.execute(
        """INSERT INTO facts (fact_type, value, source_date, source_excerpt, updated_at, history)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(fact_type) DO UPDATE SET
             value=excluded.value, source_date=excluded.source_date,
             source_excerpt=excluded.source_excerpt, updated_at=excluded.updated_at,
             history=excluded.history""",
        (fact_type, value, source_date, source_excerpt, timestamp(), json.dumps(history))
    )
    db.commit()
```

---

## Testing

```bash
# 1. Run migration
python migrate_to_sqlite.py

# 2. Verify counts match original JSON
python -c "
import json; from db import get_db
db = get_db()
print('entries:', db.execute('SELECT COUNT(*) FROM entries').fetchone()[0])
print('facts:',   db.execute('SELECT COUNT(*) FROM facts').fetchone()[0])
print('todos:',   db.execute('SELECT COUNT(*) FROM todos').fetchone()[0])
"

# 3. Smoke test diary operations still work
python main.py show
python main.py ask "what did I do yesterday?"
python main.py weekly-review
```

---

## Files to create/modify
- CREATE: `db.py` — schema + connection
- CREATE: `migrate_to_sqlite.py` — one-time migration script
- MODIFY: `diary.py` — replace load_entries/save_entries/get_entry/get_recent_entries
- MODIFY: `facts.py` — replace load_facts/save_facts/save_fact
- KEEP: `utils.py` — DATA_DIR stays, remove ENTRIES_PATH/FACTS_PATH after migration
- KEEP: `data/entries.json` — archive, don't delete until Phase 7 verified
