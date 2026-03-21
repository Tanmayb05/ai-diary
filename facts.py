from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from db import get_db
from utils import timestamp


@dataclass
class UpsertResult:
    fact_type: str
    new_value: str
    old_value: str | None       # None if this is a new fact
    is_conflict: bool           # True if new_value differs significantly from old_value
    record: dict                # the saved fact record


def load_facts() -> dict[str, Any]:
    """Load all facts. Returns dict keyed by fact_type e.g. 'birthday'."""
    db = get_db()
    rows = db.execute("SELECT * FROM facts").fetchall()
    return {
        row["fact_type"]: {
            "value": row["value"],
            "source_date": row["source_date"],
            "source_excerpt": row["source_excerpt"],
            "updated_at": row["updated_at"],
            "history": json.loads(row["history"] or "[]"),
        }
        for row in rows
    }


def upsert_fact(fact_type: str, value: str, source_date: str, source_excerpt: str = "") -> UpsertResult:
    """
    Insert or update a fact. Moves old value to history before overwriting.
    Returns an UpsertResult with conflict detection info.
    """
    db = get_db()
    existing_row = db.execute("SELECT * FROM facts WHERE fact_type=?", (fact_type,)).fetchone()

    old_value = existing_row["value"] if existing_row else None
    is_conflict = (
        old_value is not None
        and old_value.lower().strip() != value.lower().strip()
    )

    history = json.loads(existing_row["history"] or "[]") if existing_row else []
    if existing_row and existing_row["value"] != value.strip():
        history.append({
            "value": existing_row["value"],
            "source_date": existing_row["source_date"],
            "updated_at": existing_row["updated_at"],
        })

    now = timestamp()
    record = {
        "value": value.strip(),
        "source_date": source_date,
        "source_excerpt": source_excerpt,
        "updated_at": now,
        "history": history,
    }

    db.execute(
        """INSERT INTO facts (fact_type, value, source_date, source_excerpt, updated_at, history)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(fact_type) DO UPDATE SET
             value=excluded.value, source_date=excluded.source_date,
             source_excerpt=excluded.source_excerpt, updated_at=excluded.updated_at,
             history=excluded.history""",
        (fact_type, value.strip(), source_date, source_excerpt, now, json.dumps(history)),
    )
    db.commit()

    return UpsertResult(
        fact_type=fact_type,
        new_value=value.strip(),
        old_value=old_value,
        is_conflict=is_conflict,
        record=record,
    )


def delete_fact(fact_type: str) -> bool:
    """Returns True if deleted, False if not found."""
    db = get_db()
    cursor = db.execute("DELETE FROM facts WHERE fact_type=?", (fact_type,))
    db.commit()
    return cursor.rowcount > 0


def render_facts(facts: dict[str, Any]) -> str:
    if not facts:
        return "No personal facts stored yet."
    lines = []
    for fact_type, record in sorted(facts.items()):
        lines.append(f"{fact_type}: {record['value']}  (from {record['source_date']})")
    return "\n".join(lines)