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


def load_vec_extension(db: sqlite3.Connection) -> bool:
    """Load sqlite-vec extension. Returns True if available."""
    try:
        import sqlite_vec
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        return True
    except ImportError:
        return False


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

        CREATE TABLE IF NOT EXISTS characters (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT UNIQUE NOT NULL,
            relationship        TEXT,
            job                 TEXT,
            location            TEXT,
            birthday            TEXT,
            personality_traits  TEXT NOT NULL DEFAULT '[]',
            interests_hobbies   TEXT NOT NULL DEFAULT '[]',
            family_members      TEXT NOT NULL DEFAULT '[]',
            health_notes        TEXT,
            contact_info        TEXT,
            last_seen           TEXT,
            status              TEXT,
            incidents           TEXT NOT NULL DEFAULT '[]',
            fact_history        TEXT NOT NULL DEFAULT '[]',
            created_at          TEXT,
            updated_at          TEXT
        );
    """)
    db.commit()

    try:
        if load_vec_extension(db):
            db.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS entry_embeddings USING vec0(
                    entry_id INTEGER PRIMARY KEY,
                    embedding float[768]
                );
            """)
            db.commit()
    except Exception:
        pass  # sqlite-vec not installed yet
