# Phase 9 — Character Facts System

## Goal
When a diary entry is written, the LLM identifies named people mentioned and extracts structured
facts (relationship, job, location, incidents, etc.) about them. Facts are stored persistently
and can be queried via chat commands or the `ask` flow.

The magic moment: user writes "had lunch with Alice, she got promoted at Google" and later asks
"what does Alice do?" — and gets an accurate answer from memory.

## Status: COMPLETE

---

## Files changed

### New file: `characters.py`
Core persistence module for character facts.

- `load_characters()` → `dict[str, dict]` keyed by name
- `get_character(name)` → `dict | None`
- `get_all_characters()` → `list[{name, relationship}]`
- `upsert_character(name, fields_dict, entry_date)` — create or update, tracking history for conflicts
- `add_incident(name, summary, entry_date)` — appends incident; checks for duplicates via LLM
- `render_character_card(char)` — formats profile card + incident list for display

### `db.py`
Added `characters` table to `_ensure_schema()`:

```sql
CREATE TABLE IF NOT EXISTS characters (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT UNIQUE NOT NULL,
    relationship        TEXT,
    job                 TEXT,
    location            TEXT,
    birthday            TEXT,
    personality_traits  TEXT NOT NULL DEFAULT '[]',  -- JSON array
    interests_hobbies   TEXT NOT NULL DEFAULT '[]',  -- JSON array
    family_members      TEXT NOT NULL DEFAULT '[]',  -- JSON array
    health_notes        TEXT,
    contact_info        TEXT,
    last_seen           TEXT,
    status              TEXT,
    incidents           TEXT NOT NULL DEFAULT '[]',  -- JSON array of {date, summary}
    fact_history        TEXT NOT NULL DEFAULT '[]',  -- JSON array of {field, old_value, new_value, date}
    created_at          TEXT,
    updated_at          TEXT
);
```

### `utils.py`
Added `SETTINGS_PATH`, `get_setting(key, default)`, `set_setting(key, value)` — backed by
`data/settings.json`. Used to control `character_manual_entry_mode` ("interactive" | "auto").

### `ai.py`
Added:
- `extract_character_facts(entry_text, entry_date, model)` → `list[{name, facts, incidents}]`
  LLM identifies named people and extracts structured facts + notable incidents per person.
- `detect_duplicate_incident(existing_incidents, new_incident, model)` → `bool`
  LLM checks if a new incident is the same real-world event as an existing one.

Updated:
- `answer_with_facts(question, facts, entries, characters=None, model)` — now accepts character
  facts and injects a "Known people in the diary" block into the prompt.

### `handlers.py`
Added imports: `extract_character_facts`, `add_incident`, `get_all_characters`, `get_character`,
`load_characters`, `render_character_card`, `upsert_character`, `get_setting`, `set_setting`,
`today_key`.

Modified:
- `run_write_flow()` — after `upsert_entry()`, calls `extract_character_facts()` and upserts
  results (facts + incidents) for every named person found in the entry.
- `ask()` — now passes `characters=load_characters()` to `answer_with_facts`.
- `help_text()` — added "Characters" section.

New handlers:
- `show_characters()` — lists all known characters as "Name — relationship"
- `show_character(name)` — shows full profile card via `render_character_card()`
- `add_character_fact_interactive(name, raw_text)` — interactive field-by-field update prompt
  (or auto mode if `character_manual_entry_mode` setting is "auto")

### `intent_router.py`
Added three new intents to `_INTENT_SCHEMA`:
- `show_characters` — "show characters", "who do I know", "list people"
- `show_character` — "tell me about Alice", "who is mom" — params: `{name}`
- `add_character_fact` — "add fact about Alice", "update Alice" — params: `{name, raw_text}`

Added fast-path regexes (no LLM call needed):
- `show characters` / `list people` / `who do I know` → `show_characters`
- `tell me about <name>` / `who is <name>` / `what do I know about <name>` → `show_character`
- `add fact about <name>` / `update <name>` / `edit <name>` → `add_character_fact`

Added handling in `_build_intent()` for all three intents.

### `chat_session.py`
Wired three new intents in `_dispatch()`:
- `show_characters` → `handlers.show_characters()`
- `show_character` → `handlers.show_character(name)`
- `add_character_fact` → `handlers.add_character_fact_interactive(name, raw_text)`

### `main.py`
Added:
- `backfill-characters` subcommand — re-processes all existing entries to extract character facts,
  tracking progress in `data/character_backfill_progress.json` (safe to interrupt and re-run).
- `handle_backfill_characters(model)` function — iterates entries by date, skips already-processed
  IDs, prints per-entry progress.
- Updated `handle_ask()` to also pass `characters=load_characters()` to `answer_with_facts`.

---

## Design decisions

| Decision | Choice | Reason |
|---|---|---|
| Name matching | Exact match after `.title()` normalization | No auto-merge; keep separate characters |
| Conflicting scalar facts | Keep both with dates in `fact_history` | User asked for history, not overwrite |
| Array fields | Set-union merge (no duplicates) | Accumulate over time without repetition |
| Incident deduplication | LLM detects same real-world event | Handles different dates / wording |
| Manual entry mode | Interactive by default, auto optional | User prefers to confirm before saving |
| Character context in `ask` | Summary line per character (name, rel, job) | Full profiles would bloat the prompt |
| Backfill progress | Per-entry save to JSON | Safe to interrupt and re-run |

---

## How to use

### Automatic (happens on every new entry)
Write a diary entry as normal. Character facts are extracted silently after saving.

### Backfill existing entries
```
python3 main.py backfill-characters
```
Safe to run multiple times — skips already-processed entries.

### Chat commands
```
show characters                  → list all known people
tell me about Alice              → full profile card
who is mom                       → same
what do I know about Rahul       → same
update Alice                     → interactive fact editor
add fact about Alice             → same
what does Alice do?              → answered via ask + character context
```

### Change manual entry mode
```python
from utils import set_setting
set_setting("character_manual_entry_mode", "auto")   # or "interactive"
```
