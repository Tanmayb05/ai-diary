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
