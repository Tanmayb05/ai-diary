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
        entry.update(json.loads(entry.pop("metadata", "{}") or "{}"))

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
