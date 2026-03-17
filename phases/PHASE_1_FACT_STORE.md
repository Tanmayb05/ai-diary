# Phase 1 — Durable Personal Fact Store

## Goal
Extract and persist structured personal facts from diary entries into a dedicated fact store.
The magic moment: user can ask "when is my birthday?" and get an accurate answer from memory,
not from scanning recent entries.

## Status: NOT STARTED

---

## Existing codebase context

- `utils.py` — `DATA_DIR`, `load_json`, `save_json`, `timestamp()` — use these everywhere
- `ai.py` — `_generate(prompt, model, temperature, call_type)` — the raw LLM call, use this
- `diary.py` — `upsert_entry()` — add fact extraction call here after saving
- `main.py` — `handle_write()` calls `upsert_entry()`, then prints results — add fact extraction display here
- `main.py` — `parse_args()` / `main()` — add `facts` subcommand here

Data files live in `data/`. New file: `data/facts.json`.

---

## New file: `facts.py`

```python
# facts.py
from __future__ import annotations
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

def load_facts() -> dict[str, Any]:
    """Load all facts. Returns dict keyed by fact_type e.g. 'birthday'."""
    data = load_json(FACTS_PATH, {})
    return data if isinstance(data, dict) else {}


def save_facts(facts: dict[str, Any]) -> None:
    save_json(FACTS_PATH, facts)


def upsert_fact(fact_type: str, value: str, source_date: str, source_excerpt: str = "") -> dict[str, Any]:
    """
    Insert or update a fact. Moves old value to history before overwriting.
    Returns the new fact record.
    """
    facts = load_facts()
    existing = facts.get(fact_type)

    history = []
    if existing:
        history = existing.get("history", [])
        # push current into history
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
    return record


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
```

---

## New function in `ai.py`: `extract_facts()`

Add after the existing `extract_tasks()` function:

```python
# Known fact types the LLM should look for
FACT_TYPES = [
    "name", "birthday", "age", "location", "hometown",
    "job", "company", "school", "partner", "siblings",
    "pets", "nationality", "languages",
]

def extract_facts(entry_text: str, entry_date: str, model: str = DEFAULT_MODEL) -> list[dict[str, str]]:
    """
    Extract durable personal facts from a diary entry.
    Returns list of {"fact_type": ..., "value": ..., "source_excerpt": ...}
    """
    prompt = f"""
Extract personal facts about the diary author from the entry below.
Return strict JSON only using this schema:
[
  {{
    "fact_type": "birthday",
    "value": "April 12 1998",
    "source_excerpt": "today is my birthday, I turn 26"
  }}
]

Known fact types to look for: {", ".join(FACT_TYPES)}
You may also infer other stable personal facts not in this list.

Rules:
- Only include facts the writer is clearly stating about themselves.
- Normalize dates to YYYY-MM-DD if possible, otherwise keep natural language.
- Do not include temporary states (e.g. "feeling tired") — only durable facts.
- Return [] if no clear personal facts are present.
- Do not include markdown or commentary.

Today's date: {entry_date}
Diary entry:
{entry_text}
""".strip()
    raw = _generate(prompt, model=model, temperature=0.0, call_type="fact_extraction")
    parsed = _parse_json(raw)
    if not isinstance(parsed, list):
        return []
    return _clean_fact_candidates(parsed)


def _clean_fact_candidates(value: list) -> list[dict[str, str]]:
    items = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        fact_type = str(raw.get("fact_type", "")).strip().lower().replace(" ", "_")
        val = str(raw.get("value", "")).strip()
        excerpt = str(raw.get("source_excerpt", "")).strip()
        if not fact_type or not val:
            continue
        if fact_type in seen:
            continue
        seen.add(fact_type)
        items.append({"fact_type": fact_type, "value": val, "source_excerpt": excerpt})
    return items
```

---

## Wire into `main.py`: `handle_write()`

In the `if not args.skip_ai:` block, after `extract_tasks` and `analyze_entry`, add:

```python
from ai import extract_facts          # add to imports at top
from facts import upsert_fact, render_facts, load_facts  # add to imports

# Inside handle_write(), after analysis = analyze_entry(...):
extracted_facts = extract_facts(entry_text, saved_date, model=args.model)
newly_stored = []
for fact in extracted_facts:
    upsert_fact(
        fact_type=fact["fact_type"],
        value=fact["value"],
        source_date=saved_date,
        source_excerpt=fact["source_excerpt"],
    )
    newly_stored.append(fact)

if newly_stored:
    print("\nPersonal facts learned:")
    for f in newly_stored:
        print(f"  {f['fact_type']}: {f['value']}")
```

---

## Add `facts` subcommand to `main.py`

In `parse_args()`, add after the todo subparsers:

```python
facts_parser = subparsers.add_parser("facts", help="View and manage personal facts")
facts_sub = facts_parser.add_subparsers(dest="facts_command", required=True)

facts_sub.add_parser("list", help="Show all known personal facts")

facts_set = facts_sub.add_parser("set", help="Manually set a fact")
facts_set.add_argument("fact_type")
facts_set.add_argument("value")

facts_del = facts_sub.add_parser("delete", help="Delete a fact")
facts_del.add_argument("fact_type")
```

In `main()`, add handler:

```python
elif args.command == "facts":
    handle_facts(args)
```

And the handler function:

```python
def handle_facts(args: argparse.Namespace) -> None:
    from facts import load_facts, upsert_fact, delete_fact, render_facts
    from utils import today_key

    if args.facts_command == "list":
        print(render_facts(load_facts()))

    elif args.facts_command == "set":
        upsert_fact(args.fact_type, args.value, source_date=today_key(), source_excerpt="manually set")
        print(f"Set {args.fact_type} = {args.value}")

    elif args.facts_command == "delete":
        deleted = delete_fact(args.fact_type)
        if deleted:
            print(f"Deleted fact: {args.fact_type}")
        else:
            print(f"Fact not found: {args.fact_type}")
```

---

## Testing

After building, verify manually:
```bash
# Write an entry that mentions personal facts
python main.py write
# "My name is Alex, I was born on April 12 1998, and I work at Google"

# Check facts were extracted
python main.py facts list

# Manually correct a fact
python main.py facts set birthday 1998-04-12

# Delete a wrong fact
python main.py facts delete age
```

---

## Files to create/modify
- CREATE: `facts.py`
- MODIFY: `ai.py` — add `extract_facts()`, `_clean_fact_candidates()`
- MODIFY: `main.py` — wire into `handle_write()`, add `facts` subcommand + `handle_facts()`
- AUTO-CREATED: `data/facts.json` (created on first upsert)