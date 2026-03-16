"""
Synthetic diary entry generator using Ollama (llama3.1:8b).

Usage:
    python generate_synthetic.py --count 20 --start-date 2024-01-01
    python generate_synthetic.py --count 5 --output data/synthetic_entries.json
    python generate_synthetic.py --count 10 --merge  # merges into entries.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# Reuse existing project modules
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai import (
    STARTER_TAGS,
    HABIT_LABELS,
    _generate,
    analyze_entry,
    generate_reflection,
    extract_tasks,
)
from utils import DATA_DIR, load_json, save_json, timestamp


# ── Persona seeds ────────────────────────────────────────────────────────────

PERSONAS = [
    {
        "name": "university student",
        "age": 20,
        "concerns": ["exams", "assignments", "social life", "part-time job", "future career"],
        "context": "You are a university student balancing academics and social life.",
    },
    {
        "name": "early-career professional",
        "age": 26,
        "concerns": ["work deadlines", "career growth", "relationships", "fitness", "finances"],
        "context": "You are a young professional navigating your first few years of work.",
    },
    {
        "name": "remote worker",
        "age": 30,
        "concerns": ["isolation", "productivity", "work-life balance", "side projects", "health"],
        "context": "You work remotely and often struggle with motivation and connection.",
    },
    {
        "name": "parent",
        "age": 35,
        "concerns": ["kids", "work", "time management", "health", "relationships"],
        "context": "You are a working parent trying to balance family and career.",
    },
]

MOODS = [
    "happy", "content", "tired", "anxious", "stressed", "motivated",
    "sad", "reflective", "frustrated", "grateful", "excited", "overwhelmed",
    "calm", "uncertain", "proud",
]

THEMES = [
    "a challenging day at work with a difficult meeting",
    "a breakthrough moment on a personal goal",
    "reconnecting with an old friend",
    "feeling overwhelmed by responsibilities",
    "a quiet productive day at home",
    "dealing with a conflict with someone close",
    "a small but meaningful win",
    "struggling to stay motivated",
    "an unexpected pleasant surprise",
    "reflecting on a past decision",
    "making progress on a long-standing goal",
    "feeling anxious about the future",
    "a day that started badly but turned around",
    "noticing a new habit forming",
    "gratitude for everyday things",
    "feeling stuck and unsure what to do next",
    "a social event that left mixed feelings",
    "an inspiring conversation",
    "physical exercise clearing my head",
    "a creative project coming together",
]


# ── Core generation ──────────────────────────────────────────────────────────

def generate_entry_text(persona: dict, mood: str, theme: str) -> tuple[str, str]:
    """Generate diary entry text and highlight via Ollama."""
    prompt = f"""
Write a personal diary entry for a {persona['name']} (age {persona['age']}).
{persona['context']}

Today's mood: {mood}
Theme: {theme}
Persona concerns: {', '.join(random.sample(persona['concerns'], k=min(2, len(persona['concerns']))))}

Rules:
- Write entirely in first person ("I", "my", "me").
- 150 to 300 words, conversational and honest.
- Do NOT use bullet points or headers.
- Do NOT include the date or a greeting like "Dear Diary".
- Sound natural and slightly imperfect, like a real diary.

After the diary entry, on a NEW line write exactly:
HIGHLIGHT: <one short phrase summarising the key theme, max 8 words>
""".strip()

    raw = _generate(prompt, temperature=0.8, call_type="entry_generation")

    # Split out the highlight
    lines = raw.strip().splitlines()
    highlight_line = ""
    entry_lines = []
    for line in lines:
        if line.upper().startswith("HIGHLIGHT:"):
            highlight_line = line.split(":", 1)[-1].strip()
        else:
            entry_lines.append(line)

    entry_text = "\n".join(entry_lines).strip()
    highlight = highlight_line or theme[:60]
    return entry_text, highlight


def build_synthetic_entry(entry_date: str, persona: dict, mood: str, theme: str) -> dict[str, Any]:
    """Generate one fully populated synthetic diary entry."""
    t0 = time.monotonic()
    print(f"  Generating entry for {entry_date} | mood={mood} | theme='{theme[:50]}...'")

    entry_text, highlight = generate_entry_text(persona, mood, theme)
    print(f"    [entry_generation done in {time.monotonic() - t0:.1f}s]")

    t1 = time.monotonic()
    reflection = generate_reflection(entry_text, mood, highlight)
    print(f"    [reflection done in {time.monotonic() - t1:.1f}s]")

    t2 = time.monotonic()
    task_candidates = extract_tasks(entry_text)
    print(f"    [task_extraction done in {time.monotonic() - t2:.1f}s]")

    t3 = time.monotonic()
    analysis = analyze_entry(entry_text, mood, highlight)
    print(f"    [analyze_metadata done in {time.monotonic() - t3:.1f}s]")
    print(f"    [total: {time.monotonic() - t0:.1f}s]")

    now = timestamp()
    return {
        "entry": entry_text,
        "mood": mood,
        "highlight": highlight,
        "prompts": {},
        "reflection": reflection,
        "suggested_tasks": task_candidates,
        "task_candidates": task_candidates,
        "tags": analysis.get("tags", []),
        "goals": analysis.get("goals", []),
        "sentiment": analysis.get("sentiment_label", ""),
        "sentiment_label": analysis.get("sentiment_label", ""),
        "mood_alignment": analysis.get("mood_alignment", ""),
        "tomorrow_plan": analysis.get("tomorrow_plan", []),
        "stress_triggers": analysis.get("stress_triggers", []),
        "habits": analysis.get("habits", []),
        "wins": analysis.get("wins", []),
        "gratitude": analysis.get("gratitude", []),
        "follow_up_questions": analysis.get("follow_up_questions", []),
        "advice": analysis.get("advice", []),
        "entities": analysis.get("entities", []),
        "embedding_text": f"{mood} {highlight} {entry_text[:200]}",
        "saved_at": now,
        "updated_at": now,
        "created_at": now,
    }


def generate_date_range(start: date, count: int, gap_days: int = 1) -> list[str]:
    """Return a list of date strings spaced roughly gap_days apart."""
    dates = []
    current = start
    for _ in range(count):
        dates.append(current.isoformat())
        # Random gap: mostly daily, occasionally skip a day or two
        current += timedelta(days=random.randint(1, gap_days + 1))
    return dates


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic diary entries using Ollama.")
    parser.add_argument("--count", type=int, default=10, help="Number of entries to generate (default: 10)")
    parser.add_argument(
        "--start-date",
        default=None,
        help="Start date in YYYY-MM-DD format (default: today minus --count days)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write entries JSON (default: data/entries.json)",
    )
    parser.add_argument(
        "--persona",
        choices=["student", "professional", "remote", "parent", "random"],
        default="random",
        help="Persona to use for all entries (default: random per entry)",
    )
    parser.add_argument(
        "--gap",
        type=int,
        default=1,
        help="Max extra days between entries for realism (default: 1)",
    )
    return parser.parse_args()


PERSONA_MAP = {
    "student": PERSONAS[0],
    "professional": PERSONAS[1],
    "remote": PERSONAS[2],
    "parent": PERSONAS[3],
}


def main() -> None:
    args = parse_args()

    if args.start_date:
        start = date.fromisoformat(args.start_date)
    else:
        start = date.today() - timedelta(days=args.count)

    target_path = Path(args.output) if args.output else DATA_DIR / "entries.json"

    print(f"Generating {args.count} synthetic entries starting {start.isoformat()}...")
    print(f"Output: {target_path}\n")

    dates = generate_date_range(start, args.count, gap_days=args.gap)

    # Always load existing store so we never overwrite existing entries
    store: dict[str, list[dict]] = load_json(target_path, {})

    used_themes = []
    for entry_date in dates:
        # Pick persona
        if args.persona == "random":
            persona = random.choice(PERSONAS)
        else:
            persona = PERSONA_MAP[args.persona]

        # Pick mood and theme (avoid repeating same theme consecutively)
        mood = random.choice(MOODS)
        available_themes = [t for t in THEMES if t not in used_themes[-3:]]
        theme = random.choice(available_themes)
        used_themes.append(theme)

        try:
            entry = build_synthetic_entry(entry_date, persona, mood, theme)
        except Exception as exc:
            print(f"  ERROR on {entry_date}: {exc}")
            continue

        store.setdefault(entry_date, []).append(entry)
        print(f"  Done: {entry_date}\n")

    save_json(target_path, store)
    total = sum(len(v) for v in store.values())
    print(f"\nSaved {args.count} new entries to {target_path} ({len(store)} dates, {total} total entries).")


if __name__ == "__main__":
    main()
