# Phase 5 — Periodic Digest & Pattern Surfacing

## Goal
Add a daily/weekly digest command that proactively surfaces patterns the user hasn't
asked about: recurring stress triggers, goals that keep getting deferred, mood patterns
over time, and facts that may be outdated. This is the "personal assistant that notices
things" experience from the research doc.

## Status: NOT STARTED
## Depends on: Phase 1 (facts), Phase 3 (conflict detection) recommended but not required

---

## Existing codebase context

- `diary.py` — `sentiment_trends(days)`, `aggregate_goals(days)`, `detect_contradictions(days)` — reuse all of these
- `diary.py` — `get_recent_entries(limit)` — returns `list[tuple[date, entry]]`
- `ai.py` — `generate_weekly_summary(entries, model)` — already exists, reuse
- `main.py` — `handle_weekly_review()` — already exists, extend rather than replace
- `facts.py` — `load_facts()` — use to include personal context in digest

---

## New function in `ai.py`: `generate_digest()`

```python
def generate_digest(
    entries: list[tuple[str, dict[str, Any]]],
    facts: dict[str, Any],
    contradictions: list[dict[str, Any]],
    trends: dict[str, Any],
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Generate a proactive personal digest that surfaces patterns,
    deferred goals, and mood signals the user may not have noticed.
    """
    if not entries:
        return "Not enough diary entries for a digest yet."

    # Build context blocks
    facts_block = ""
    if facts:
        lines = [f"- {k}: {v['value']}" for k, v in sorted(facts.items())]
        facts_block = "Known about the user:\n" + "\n".join(lines)

    entries_block = _render_recent_context(entries, limit=14)

    contradictions_block = ""
    if contradictions:
        items = [f"- {c['goal']} (mentioned {c['mention_count']} times, no follow-through)" for c in contradictions[:5]]
        contradictions_block = "Deferred goals (mentioned repeatedly but never acted on):\n" + "\n".join(items)

    trends_block = ""
    if trends.get("top_stress_triggers"):
        triggers = [f"- {t['trigger']} ({t['count']}x)" for t in trends["top_stress_triggers"][:3]]
        trends_block = "Top stress triggers:\n" + "\n".join(triggers)

    prompt = f"""
You are a personal assistant reviewing this person's diary.
Write a short, honest, practical digest. Speak directly to them in second person.
Use exactly these sections:

What's been on your mind:
Patterns I'm noticing:
Goals you keep mentioning but haven't acted on:
Something to try this week:

Keep each section to 1-3 bullet points. Be specific, reference real things from their entries.
Do not be a therapist. Do not overclaim.

{facts_block}

{entries_block}

{contradictions_block}

{trends_block}
""".strip()
    return _generate(prompt, model=model, temperature=0.35, call_type="digest")
```

---

## New command in `main.py`: `digest`

In `parse_args()`:

```python
digest_parser = subparsers.add_parser("digest", help="Generate a proactive personal digest")
digest_parser.add_argument("--days", type=int, default=14)
```

Handler:

```python
def handle_digest(days: int, model: str) -> None:
    from facts import load_facts
    from ai import generate_digest
    from diary import get_recent_entries, detect_contradictions, sentiment_trends

    entries = get_recent_entries(limit=days)
    if not entries:
        print("Not enough diary entries yet.")
        return

    facts = load_facts()
    contradictions = detect_contradictions(days=days)
    trends = sentiment_trends(days=days)

    try:
        print(generate_digest(entries, facts, contradictions, trends, model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")
```

In `main()`:

```python
elif args.command == "digest":
    handle_digest(args.days, args.model)
```

---

## Extend weekly-review to include facts + contradictions

Optional enhancement to existing `handle_weekly_review()`:

```python
def handle_weekly_review(days: int, model: str) -> None:
    # ... existing code ...
    # After printing the weekly summary, also print contradictions if any:
    from diary import detect_contradictions
    contradictions = detect_contradictions(days=days)
    if contradictions:
        print("\nGoals mentioned but not acted on:")
        for item in contradictions[:3]:
            print(f"  - {item['goal']} ({item['mention_count']}x)")
```

---

## Testing

```bash
# After 2+ weeks of entries:
python main.py digest
python main.py digest --days 7

# Should produce something like:
# What's been on your mind:
#   - Work deadlines and the project launch
#   - Feeling disconnected from friends
# Patterns I'm noticing:
#   - You mention stress about sleep on 4 of the last 7 days
# Goals you keep mentioning but haven't acted on:
#   - "start exercising" (mentioned 6 times)
# Something to try this week:
#   - Block 30 minutes tomorrow morning just for the gym
```

---

## Files to modify
- MODIFY: `ai.py` — add `generate_digest()`
- MODIFY: `main.py` — add `digest` subcommand, `handle_digest()`, extend `handle_weekly_review()`