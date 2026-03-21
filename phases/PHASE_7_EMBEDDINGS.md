# Phase 7 — Embeddings Pipeline

## Goal
Generate embeddings for all diary entries using `nomic-embed-text` via Ollama (already installed,
no cloud required) and store them in SQLite using `sqlite-vec`. New entries get embedded
automatically on save. This is the foundation for semantic search in Phase 8.

## Status: NOT STARTED
## Depends on: Phase 6 (SQLite schema must exist)

---

## Install sqlite-vec

```bash
pip install sqlite-vec
```

Add to requirements.txt:
```
sqlite-vec>=0.1.7
```

---

## Pull embedding model (one-time)

```bash
ollama pull nomic-embed-text
```

`nomic-embed-text` outputs 768-dimension float vectors. Fast, small, runs fully locally.

---

## Update `db.py` — add vec table to schema

Add to `_ensure_schema()` in `db.py`:

```python
# After the existing CREATE TABLE statements, add:

try:
    import sqlite_vec
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS entry_embeddings USING vec0(
            entry_id INTEGER PRIMARY KEY,
            embedding float[768]
        );
    """)
except ImportError:
    pass  # sqlite-vec not installed yet; Phase 7 will add it
```

Also add a helper to load the extension on any connection:

```python
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
```

---

## New file: `embeddings.py`

```python
"""
embeddings.py — generate and store entry embeddings via Ollama nomic-embed-text.
"""

import json
import struct
from typing import Optional
import requests
from db import get_db, load_vec_extension

EMBED_MODEL = "nomic-embed-text"
OLLAMA_URL  = "http://127.0.0.1:11434/api/embeddings"
EMBED_DIM   = 768


def generate_embedding(text: str) -> list[float]:
    """Call Ollama to generate a 768-dim embedding for text."""
    resp = requests.post(OLLAMA_URL, json={"model": EMBED_MODEL, "prompt": text}, timeout=30)
    resp.raise_for_status()
    return resp.json()["embedding"]


def _serialize(vec: list[float]) -> bytes:
    """Pack float list into bytes for sqlite-vec storage."""
    return struct.pack(f"{len(vec)}f", *vec)


def _build_embed_text(entry: dict) -> str:
    """Build the text to embed from an entry — same fields used for BM25."""
    parts = [
        entry.get("entry", ""),
        entry.get("highlight", ""),
        " ".join(entry.get("goals", []) or []),
        " ".join(entry.get("tags", []) or []),
        " ".join(entry.get("entities", []) or []),
        " ".join(entry.get("wins", []) or []),
    ]
    return " ".join(p for p in parts if p).strip()


def embed_entry(entry_id: int, entry: dict) -> None:
    """Generate and store embedding for a single entry."""
    db = get_db()
    if not load_vec_extension(db):
        return  # sqlite-vec not available

    text = _build_embed_text(entry)
    if not text:
        return

    vec = generate_embedding(text)
    packed = _serialize(vec)

    db.execute(
        "INSERT OR REPLACE INTO entry_embeddings(entry_id, embedding) VALUES (?, ?)",
        (entry_id, packed),
    )
    db.commit()


def backfill_embeddings(verbose: bool = True) -> int:
    """
    Generate embeddings for all entries that don't have one yet.
    Safe to re-run — skips already-embedded entries.
    """
    db = get_db()
    if not load_vec_extension(db):
        print("sqlite-vec not installed. Run: pip install sqlite-vec")
        return 0

    rows = db.execute("""
        SELECT e.id, e.entry, e.mood, e.highlight, e.metadata
        FROM entries e
        LEFT JOIN entry_embeddings ee ON ee.entry_id = e.id
        WHERE ee.entry_id IS NULL
        ORDER BY e.date
    """).fetchall()

    count = 0
    for row in rows:
        entry_id = row["id"]
        entry = dict(row)
        entry.update(json.loads(entry.pop("metadata", "{}")))

        if verbose:
            print(f"  Embedding entry {entry_id}...", end="\r")

        try:
            embed_entry(entry_id, entry)
            count += 1
        except Exception as exc:
            print(f"\n  Warning: failed to embed entry {entry_id}: {exc}")

    if verbose:
        print(f"\nDone. {count} entries embedded.")
    return count


def get_embedding(entry_id: int) -> Optional[list[float]]:
    """Retrieve stored embedding for an entry."""
    db = get_db()
    if not load_vec_extension(db):
        return None
    row = db.execute(
        "SELECT embedding FROM entry_embeddings WHERE entry_id=?", (entry_id,)
    ).fetchone()
    if not row:
        return None
    return list(struct.unpack(f"{EMBED_DIM}f", row[0]))
```

---

## Auto-embed on save — update `diary.py`

In `save_entry()`, after `db.commit()`, add:

```python
# diary.py — inside save_entry(), after db.commit():
try:
    from embeddings import embed_entry
    row = db.execute("SELECT id FROM entries WHERE date=?", (date,)).fetchone()
    if row:
        embed_entry(row["id"], entry)
except Exception:
    pass  # embedding is non-blocking; never fail a save because of it
```

---

## Backfill script: `backfill_embeddings.py`

```python
"""
backfill_embeddings.py — generate embeddings for all existing entries.
Run once after Phase 6 migration: python backfill_embeddings.py

Requires Ollama running: ollama serve
Requires model pulled:   ollama pull nomic-embed-text
"""

from embeddings import backfill_embeddings

if __name__ == "__main__":
    print("Backfilling embeddings (this may take a few minutes)...")
    print("Make sure Ollama is running: ollama serve\n")
    n = backfill_embeddings(verbose=True)
    print(f"\nTotal embedded: {n}")
```

---

## Testing

```bash
# 1. Pull the model
ollama pull nomic-embed-text

# 2. Install sqlite-vec
pip install sqlite-vec

# 3. Backfill all existing entries
python backfill_embeddings.py

# 4. Verify embeddings stored
python -c "
from db import get_db, load_vec_extension
db = get_db()
load_vec_extension(db)
count = db.execute('SELECT COUNT(*) FROM entry_embeddings').fetchone()[0]
print(f'Embeddings stored: {count}')
"

# 5. Test single embedding generation
python -c "
from embeddings import generate_embedding
vec = generate_embedding('feeling anxious about work deadline')
print(f'Embedding dim: {len(vec)}, first 5: {vec[:5]}')
"
```

---

## Files to create/modify
- MODIFY: `db.py` — add vec0 table to schema, add `load_vec_extension()`
- CREATE: `embeddings.py` — embedding generation + storage
- CREATE: `backfill_embeddings.py` — one-time backfill script
- MODIFY: `diary.py` — call `embed_entry()` in `save_entry()`
