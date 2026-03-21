---
phase: quick
plan: "002"
subsystem: chat
tags: [period-summary, llm, intent-routing, handlers]
key-files:
  created: []
  modified:
    - diary.py
    - ai.py
    - intent_router.py
    - handlers.py
    - chat_session.py
decisions:
  - Fast-path regex added before LLM routing for summarize intent to avoid unnecessary LLM calls on common patterns
  - Digest capped at 50 entries with truncation note to keep LLM context bounded
  - Graceful fallback to stats-only summary when AI is unavailable (AIError)
metrics:
  completed: "2026-03-21"
  tasks: 5
  files_modified: 5
---

# Phase quick Plan 002: Period Summary Feature Summary

AI-powered period summary (month or year) using structured entry digest and LLM prose generation with fast-path regex routing and stats fallback.

## What Was Built

### diary.py — `get_entries_for_period`
New function that queries the SQLite `entries` table using a LIKE prefix match on `date` for either a full year (`YYYY-%`) or a specific month (`YYYY-MM-%`). Returns a list of dicts including the date field merged with the full entry payload.

### ai.py — `generate_period_summary`
New LLM function that accepts a compact text digest of entries, a human-readable label (e.g. "March 2026"), entry count, and date range. Instructs the model to produce 150-250 words of second-person flowing prose covering emotional arc, major events, recurring themes, notable quotes, and overall tone. Uses `call_type="period_summary"` for timing logs.

### intent_router.py — `summarize` intent
- Added `summarize` intent to `_INTENT_SCHEMA` with examples for LLM-based routing.
- Added `_try_parse_summarize` fast-path function matching patterns like `summarize 2026`, `summary for march 2026`, `recap of 2025`.
- Added `summarize` case to `_build_intent` for LLM-returned intents.
- Fast-path is inserted before the existing range fast-path in `route_message`.

### handlers.py — `_build_entries_digest` + `summarize_period`
- `_build_entries_digest`: module-level helper that converts up to 50 entries into a structured text block per entry (date, mood, highlight, tags, sentiment, entry text truncated at 300 chars, wins, stress triggers). Returns `(digest, was_truncated)`.
- `summarize_period`: ChatHandlers method that fetches entries for the period, builds the digest, calls `generate_period_summary`, and returns the result. Falls back to a stats-only text block (entry count, date range, top tags) if `AIError` is raised.
- Updated `help_text` to include `show summary for 2026` and `summarize march 2026`.

### chat_session.py — `summarize` dispatch
Added handler in `_dispatch` that routes `summarize` intents to `self.handlers.summarize_period(year, month, label)`.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- `get_entries_for_period` exists in diary.py: confirmed
- `generate_period_summary` exists in ai.py: confirmed
- `_try_parse_summarize` and summarize intent in intent_router.py: confirmed
- `_build_entries_digest` and `summarize_period` in handlers.py: confirmed
- `summarize` dispatch in chat_session.py: confirmed
- All symbols import cleanly and fast-path parsing produces correct RoutedIntent output: verified via runtime check
