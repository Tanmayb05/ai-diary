# Phase 3 — Fact Conflict Detection & Provenance

## Goal
When a newly extracted fact contradicts an existing one, surface the conflict to the user
instead of silently overwriting. Show them what they said before vs. what they said now,
and let them decide which is correct.

## Status: NOT STARTED
## Depends on: Phase 1 (facts.py)

---

## Existing codebase context

- `facts.py` — `upsert_fact(fact_type, value, source_date, source_excerpt)` — currently overwrites silently
- `facts.py` — `load_facts()` — returns current fact store
- `main.py` — `handle_write()` — iterates over `extracted_facts` and calls `upsert_fact()` for each
- `ai.py` — `extract_facts()` — returns `list[{"fact_type", "value", "source_excerpt"}]`

---

## Update `facts.py`: add conflict detection

Add a `ConflictResult` dataclass and update `upsert_fact` to return conflict info:

```python
from dataclasses import dataclass

@dataclass
class UpsertResult:
    fact_type: str
    new_value: str
    old_value: str | None       # None if this is a new fact
    is_conflict: bool           # True if new_value differs significantly from old_value
    record: dict                # the saved fact record


def upsert_fact(
    fact_type: str,
    value: str,
    source_date: str,
    source_excerpt: str = "",
) -> UpsertResult:
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
```

---

## Update `main.py`: `handle_write()` — show conflicts

Replace the current fact-display block with:

```python
from facts import upsert_fact, UpsertResult

newly_stored = []
conflicts = []

for fact in extracted_facts:
    result = upsert_fact(
        fact_type=fact["fact_type"],
        value=fact["value"],
        source_date=saved_date,
        source_excerpt=fact["source_excerpt"],
    )
    if result.is_conflict:
        conflicts.append(result)
    else:
        newly_stored.append(result)

if newly_stored:
    print("\nPersonal facts learned:")
    for r in newly_stored:
        label = "(new)" if r.old_value is None else "(updated)"
        print(f"  {r.fact_type}: {r.new_value}  {label}")

if conflicts:
    print("\n⚠ Fact conflicts detected:")
    for r in conflicts:
        print(f"  {r.fact_type}:")
        print(f"    previously: {r.old_value}")
        print(f"    now says:   {r.new_value}")
    print("  Run `python main.py facts list` to review. Use `facts set` to correct.")
```

---

## Add `facts history` subcommand

Show provenance — all past values for a given fact.

In `parse_args()`, add to the facts subparser:

```python
facts_history = facts_sub.add_parser("history", help="Show history for a fact")
facts_history.add_argument("fact_type")
```

In `handle_facts()`:

```python
elif args.facts_command == "history":
    facts = load_facts()
    record = facts.get(args.fact_type)
    if not record:
        print(f"No fact found: {args.fact_type}")
        return
    print(f"{args.fact_type}: {record['value']}  (from {record['source_date']})")
    history = record.get("history", [])
    if history:
        print("History:")
        for h in reversed(history):
            print(f"  {h['value']}  (from {h['source_date']}, updated {h['updated_at']})")
    else:
        print("No history.")
```

---

## Testing

```bash
# Write two entries with conflicting location info
python main.py write   # "I live in Mumbai"
python main.py write   # "Just moved to London last week"

# Should show conflict on second write:
# ⚠ Fact conflicts detected:
#   location:
#     previously: Mumbai
#     now says:   London

# Confirm the history
python main.py facts history location

# Resolve manually
python main.py facts set location London
```

---

## Files to modify
- MODIFY: `facts.py` — add `UpsertResult` dataclass, update `upsert_fact()` return type
- MODIFY: `main.py` — update conflict display in `handle_write()`, add `facts history` subcommand