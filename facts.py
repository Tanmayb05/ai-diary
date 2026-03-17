from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from utils import DATA_DIR, load_json, save_json, timestamp

FACTS_PATH = DATA_DIR / "facts.json"

# Schema for a single fact entry:
# {
#   "value": "1998-04-12",
#   "source_date": "2026-01-15",       # which diary entry it came from
#   "source_excerpt": "today is my birthday...",
#   "updated_at": "2026-01-15T10:22:00",
#   "history": [                        # previous values before overwrite
#     {"value": "...", "source_date": "...", "updated_at": "..."}
#   ]
# }


@dataclass
class UpsertResult:
    fact_type: str
    new_value: str
    old_value: str | None       # None if this is a new fact
    is_conflict: bool           # True if new_value differs significantly from old_value
    record: dict                # the saved fact record


def load_facts() -> dict[str, Any]:
    """Load all facts. Returns dict keyed by fact_type e.g. 'birthday'."""
    data = load_json(FACTS_PATH, {})
    return data if isinstance(data, dict) else {}


def save_facts(facts: dict[str, Any]) -> None:
    save_json(FACTS_PATH, facts)


def upsert_fact(fact_type: str, value: str, source_date: str, source_excerpt: str = "") -> UpsertResult:
    """
    Insert or update a fact. Moves old value to history before overwriting.
    Returns an UpsertResult with conflict detection info.
    """
    facts = load_facts()
    existing = facts.get(fact_type)

    old_value = existing["value"] if existing else None
    is_conflict = (
        old_value is not None
        and old_value.lower().strip() != value.lower().strip()
    )

    history = []
    if existing:
        history = existing.get("history", [])
        history.append({
            "value": existing["value"],
            "source_date": existing["source_date"],
            "updated_at": existing["updated_at"],
        })

    record = {
        "value": value.strip(),
        "source_date": source_date,
        "source_excerpt": source_excerpt,
        "updated_at": timestamp(),
        "history": history,
    }
    facts[fact_type] = record
    save_facts(facts)

    return UpsertResult(
        fact_type=fact_type,
        new_value=value.strip(),
        old_value=old_value,
        is_conflict=is_conflict,
        record=record,
    )


def delete_fact(fact_type: str) -> bool:
    """Returns True if deleted, False if not found."""
    facts = load_facts()
    if fact_type not in facts:
        return False
    del facts[fact_type]
    save_facts(facts)
    return True


def render_facts(facts: dict[str, Any]) -> str:
    if not facts:
        return "No personal facts stored yet."
    lines = []
    for fact_type, record in sorted(facts.items()):
        lines.append(f"{fact_type}: {record['value']}  (from {record['source_date']})")
    return "\n".join(lines)