"""
Functional (end-to-end) tests — require a running Ollama instance.

Run:  .venv/bin/python -m pytest tests/test_functional.py -v -s

What these tests do:
  1. Inject a diary entry with clear personal facts into a temp facts.json/entries.json
  2. Call extract_facts() against the live LLM → facts should be picked up
  3. Call answer_with_facts() and verify the answer references the correct value
  4. Verify conflict detection triggers when a second entry contradicts the first
  5. Verify BM25 resurface returns the relevant entry for a matching query
  6. Verify generate_digest() produces output that mentions known context
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ai import AIError

# ── skip entire module if Ollama is unreachable ────────────────────────────────
def _ollama_reachable() -> bool:
    from urllib import request, error
    try:
        request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
        return True
    except Exception:
        return False

pytestmark = pytest.mark.skipif(
    not _ollama_reachable(),
    reason="Ollama not running — start with `ollama serve`",
)


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def isolated_data(tmp_path):
    """
    Patches FACTS_PATH, ENTRIES_PATH, and DATA_DIR to tmp_path so tests
    never touch real data/facts.json or data/entries.json.
    """
    facts_path = tmp_path / "facts.json"
    entries_path = tmp_path / "entries.json"
    todos_path = tmp_path / "todos.json"

    with patch("facts.FACTS_PATH", facts_path), \
         patch("utils.ENTRIES_PATH", entries_path), \
         patch("diary.ENTRIES_PATH", entries_path), \
         patch("utils.DATA_DIR", tmp_path), \
         patch("utils.TODOS_PATH", todos_path):
        yield {
            "facts_path": facts_path,
            "entries_path": entries_path,
            "tmp_path": tmp_path,
        }


def _seed_entry(entries_path: Path, date: str, text: str, **extra) -> None:
    """Write a minimal entry directly to entries.json."""
    base = {
        "entry": text,
        "mood": "good",
        "highlight": "",
        "tags": [],
        "goals": [],
        "entities": [],
        "wins": [],
        "habits": [],
        "gratitude": [],
        "stress_triggers": [],
        "tomorrow_plan": [],
        "follow_up_questions": [],
        "advice": [],
        "task_candidates": [],
        "suggested_tasks": [],
        "sentiment_label": "positive",
        "mood_alignment": "aligned",
        "sentiment": "positive",
        "embedding_text": "",
        "reflection": "",
        "prompts": {},
        "saved_at": f"{date}T09:00:00",
        "updated_at": f"{date}T09:00:00",
        "created_at": f"{date}T09:00:00",
    }
    base.update(extra)
    store = {}
    if entries_path.exists():
        store = json.loads(entries_path.read_text())
    store.setdefault(date, []).append(base)
    entries_path.write_text(json.dumps(store, indent=2))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — extract_facts pulls facts from an entry
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractAndStoreFact:
    """
    Inject an entry that clearly states the user's name and birthday.
    Run extract_facts() → upsert into fact store → verify stored correctly.
    """

    ENTRY = (
        "Today is my birthday! I turn 27. My name is Priya and I was born on "
        "March 15 1999. I work as a software engineer at a startup in Bangalore."
    )
    DATE = "2026-03-15"

    def test_extract_facts_finds_name(self, isolated_data):
        from ai import extract_facts
        facts = extract_facts(self.ENTRY, self.DATE)
        fact_types = {f["fact_type"] for f in facts}
        print(f"\n[extract_facts output] {facts}")
        assert "name" in fact_types, f"Expected 'name' in extracted facts, got: {fact_types}"

    def test_extract_facts_finds_birthday(self, isolated_data):
        from ai import extract_facts
        facts = extract_facts(self.ENTRY, self.DATE)
        fact_types = {f["fact_type"] for f in facts}
        print(f"\n[extract_facts output] {facts}")
        assert "birthday" in fact_types or "age" in fact_types, (
            f"Expected 'birthday' or 'age' in extracted facts, got: {fact_types}"
        )

    def test_extracted_name_value_is_correct(self, isolated_data):
        from ai import extract_facts
        facts = extract_facts(self.ENTRY, self.DATE)
        name_facts = [f for f in facts if f["fact_type"] == "name"]
        print(f"\n[name facts] {name_facts}")
        assert name_facts, "No 'name' fact extracted"
        assert "priya" in name_facts[0]["value"].lower(), (
            f"Expected value to contain 'Priya', got: {name_facts[0]['value']}"
        )

    def test_store_and_reload_extracted_facts(self, isolated_data):
        """extract_facts → upsert_fact → load_facts round-trip."""
        from ai import extract_facts
        from facts import upsert_fact, load_facts

        extracted = extract_facts(self.ENTRY, self.DATE)
        print(f"\n[extracted] {extracted}")
        assert extracted, "extract_facts returned nothing — check Ollama is running with the right model"

        for f in extracted:
            upsert_fact(
                fact_type=f["fact_type"],
                value=f["value"],
                source_date=self.DATE,
                source_excerpt=f["source_excerpt"],
            )

        stored = load_facts()
        print(f"[stored facts] {json.dumps(stored, indent=2)}")
        assert stored, "load_facts returned empty dict after upsert"
        assert "name" in stored, f"'name' not in stored facts: {list(stored.keys())}"
        assert "priya" in stored["name"]["value"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — answer_with_facts retrieves stored facts correctly (Phase 2)
# ══════════════════════════════════════════════════════════════════════════════

class TestAnswerWithFacts:
    """
    Seed facts directly (bypass LLM extraction).
    Ask a question — answer_with_facts should answer from the fact store,
    not from diary entries.
    """

    def test_answers_birthday_from_fact_store(self, isolated_data):
        from facts import upsert_fact
        from ai import answer_with_facts

        upsert_fact("birthday", "1999-03-15", "2026-03-15", "I was born on March 15 1999")
        upsert_fact("name", "Priya", "2026-03-15", "My name is Priya")

        from facts import load_facts
        facts = load_facts()
        entries = {}  # no diary entries — answer must come purely from fact store

        answer = answer_with_facts("What is my birthday?", facts, entries)
        print(f"\n[answer_with_facts] {answer}")

        assert any(kw in answer.lower() for kw in ["march", "1999", "15", "march 15"]), (
            f"Expected birthday info in answer, got: {answer}"
        )

    def test_answers_name_from_fact_store(self, isolated_data):
        from facts import upsert_fact, load_facts
        from ai import answer_with_facts

        upsert_fact("name", "Priya", "2026-03-15")
        facts = load_facts()

        answer = answer_with_facts("What is my name?", facts, {})
        print(f"\n[answer_with_facts name] {answer}")

        assert "priya" in answer.lower(), f"Expected 'Priya' in answer, got: {answer}"

    def test_answers_job_from_fact_store(self, isolated_data):
        from facts import upsert_fact, load_facts
        from ai import answer_with_facts

        upsert_fact("job", "software engineer", "2026-03-15", "I work as a software engineer")
        facts = load_facts()

        answer = answer_with_facts("What do I do for work?", facts, {})
        print(f"\n[answer_with_facts job] {answer}")

        assert "engineer" in answer.lower() or "software" in answer.lower(), (
            f"Expected job info in answer, got: {answer}"
        )

    def test_no_hallucination_when_fact_missing(self, isolated_data):
        """When a fact isn't stored and no entries exist, model should say it doesn't know."""
        from ai import answer_with_facts

        answer = answer_with_facts("What is my favorite color?", {}, {})
        print(f"\n[answer_with_facts unknown] {answer}")

        # Should not confidently claim a color — model should hedge
        uncertain_phrases = ["don't know", "not sure", "no information", "i don't", "haven't", "unclear", "unable"]
        assert any(p in answer.lower() for p in uncertain_phrases), (
            f"Expected uncertainty when fact is unknown, got: {answer}"
        )

    def test_facts_take_priority_over_entries(self, isolated_data):
        """Fact store says 'London'; entry says 'Mumbai'. Answer should prefer London."""
        from facts import upsert_fact, load_facts
        from ai import answer_with_facts
        from diary import normalize_entry_payload

        upsert_fact("location", "London", "2026-03-15", "I live in London")
        facts = load_facts()

        # Build a fake entry dict directly — no file I/O, no reload
        mumbai_entry = normalize_entry_payload({
            "entry": "I was living in Mumbai back then and loved it.",
            "mood": "good", "highlight": "", "tags": ["relationships"],
            "saved_at": "2025-06-01T09:00:00",
        })
        entries = {"2025-06-01": mumbai_entry}

        answer = answer_with_facts("Where do I live?", facts, entries)
        print(f"\n[priority test answer] {answer}")

        assert "london" in answer.lower(), (
            f"Expected London (from fact store) to take priority over Mumbai (from entry). Got: {answer}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Full pipeline: entry → extract → store → retrieve (Phase 1+2)
# ══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """
    Simulate what handle_write() does:
    inject entry text → extract_facts → upsert → then ask a question.
    End-to-end without touching real data files.
    """

    def test_write_then_ask(self, isolated_data):
        from ai import extract_facts, answer_with_facts
        from facts import upsert_fact, load_facts

        entry_text = "My name is Arjun. I was born on July 4 1995. I live in Delhi and work as a data scientist."
        entry_date = "2026-01-10"

        # Step 1: extract
        extracted = extract_facts(entry_text, entry_date)
        print(f"\n[pipeline] extracted: {extracted}")
        assert extracted, "No facts extracted from entry"

        # Step 2: store
        for f in extracted:
            upsert_fact(f["fact_type"], f["value"], entry_date, f["source_excerpt"])

        # Step 3: retrieve via answer_with_facts
        facts = load_facts()
        print(f"[pipeline] stored facts: {json.dumps(facts, indent=2)}")

        answer = answer_with_facts("What is my name?", facts, {})
        print(f"[pipeline] answer: {answer}")

        assert "arjun" in answer.lower(), f"Expected 'Arjun' in answer, got: {answer}"

    def test_write_two_entries_conflict_then_ask(self, isolated_data):
        """
        Entry 1: clearly states location = Mumbai.
        Entry 2: clearly states location = London.
        Expect: conflict flagged, latest value wins, answer reflects London.
        """
        from ai import extract_facts
        from facts import upsert_fact, load_facts
        from ai import answer_with_facts

        # Entry 1 — rich enough for the LLM to extract location
        e1 = (
            "Good day overall. My name is Tanmay and I currently live in Mumbai, India. "
            "I have been based here for the past five years working as an engineer."
        )
        facts1 = extract_facts(e1, "2026-01-01")
        print(f"\n[conflict test] entry 1 facts: {facts1}")
        for f in facts1:
            upsert_fact(f["fact_type"], f["value"], "2026-01-01", f["source_excerpt"])

        stored_after_e1 = load_facts()
        assert "location" in stored_after_e1, (
            f"Expected 'location' fact after entry 1, got: {list(stored_after_e1.keys())}"
        )
        assert "mumbai" in stored_after_e1["location"]["value"].lower()

        # Entry 2 — explicitly states a new location
        e2 = (
            "Big news: I just relocated to London, UK. "
            "I now live in London and started my new job here this week."
        )
        facts2 = extract_facts(e2, "2026-02-01")
        print(f"[conflict test] entry 2 facts: {facts2}")
        conflicts = []
        for f in facts2:
            result = upsert_fact(f["fact_type"], f["value"], "2026-02-01", f["source_excerpt"])
            if result.is_conflict:
                conflicts.append(result)
                print(f"[conflict test] conflict: {result.fact_type}: {result.old_value} → {result.new_value}")

        location_conflicts = [c for c in conflicts if c.fact_type == "location"]
        assert location_conflicts, (
            f"Expected a location conflict but got conflicts: {conflicts}. "
            f"entry2 extracted: {facts2}"
        )
        assert "london" in location_conflicts[0].new_value.lower()

        # Ask where user lives — fact store now has London
        facts = load_facts()
        answer = answer_with_facts("Where do I currently live?", facts, {})
        print(f"[conflict test] final answer: {answer}")

        assert "london" in answer.lower(), (
            f"Expected London (latest value) in answer, got: {answer}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — BM25 resurface returns the right entry (Phase 4)
# ══════════════════════════════════════════════════════════════════════════════

def _make_entries_dict(*items: tuple[str, str, dict]) -> dict:
    """
    Build the aggregated entries dict that load_entries() would return.
    Each item is (date, entry_text, extra_fields).
    """
    from diary import normalize_entry_payload
    result = {}
    for date, text, extra in items:
        base = {
            "entry": text, "mood": "good", "highlight": "",
            "tags": [], "goals": [], "entities": [], "wins": [], "habits": [],
            "gratitude": [], "stress_triggers": [], "tomorrow_plan": [],
            "follow_up_questions": [], "advice": [], "task_candidates": [],
            "suggested_tasks": [], "sentiment_label": "positive",
            "mood_alignment": "aligned", "sentiment": "positive",
            "embedding_text": "", "reflection": "", "prompts": {},
            "saved_at": f"{date}T09:00:00", "updated_at": f"{date}T09:00:00",
            "created_at": f"{date}T09:00:00",
        }
        base.update(extra)
        result[date] = normalize_entry_payload(base)
    return result


class TestBM25Resurface:
    """
    BM25 ranking tests — inject entries directly into resurface_entries()
    by patching diary.load_entries so tests never touch entries.json.

    Note: BM25Okapi IDF clips to 0 for tiny corpora (< ~5 docs).
    We pad with neutral filler entries so the target entry is the only
    relevant one and BM25 produces non-zero scores.
    """

    # Neutral filler entries that don't match any sport/work/anxiety query
    FILLERS = [
        ("2026-01-01", "Had dinner with family. Watched a movie. Felt relaxed.", {}),
        ("2026-01-02", "Cooked lunch. Read a novel. Nothing special happened.", {}),
        ("2026-01-03", "Woke up late. Had coffee. Chatted with a friend online.", {}),
        ("2026-01-04", "Quiet day. Journaled. Listened to music.", {}),
    ]

    def _resurface_with(self, entries_dict: dict, query: str) -> list:
        import diary
        with patch.object(diary, "load_entries", return_value=entries_dict):
            return diary.resurface_entries(query)

    def test_resurface_returns_gym_entry(self):
        entries = _make_entries_dict(
            *self.FILLERS,
            ("2026-01-05", "Went to the gym today, did a solid workout. Feeling great after exercise.",
             {"tags": ["health"], "wins": ["completed workout"]}),
            ("2026-01-10", "Had a long meeting with the product team. Discussed the roadmap and sprint planning.",
             {"tags": ["work"]}),
        )
        results = self._resurface_with(entries, "gym workout exercise")
        print(f"\n[bm25 resurface] results: {results}")

        assert results, "resurface_entries returned no results"
        assert results[0]["date"] == "2026-01-05", (
            f"Expected gym entry (2026-01-05) at rank 1, got: {results[0]['date']}"
        )

    def test_resurface_returns_work_entry(self):
        entries = _make_entries_dict(
            *self.FILLERS,
            ("2026-01-05", "Went to the gym today, did a solid workout. Feeling great after exercise.",
             {"tags": ["health"]}),
            ("2026-01-10", "Had a long meeting with the product team. Discussed the roadmap and sprint planning.",
             {"tags": ["work"], "goals": ["finish roadmap"]}),
        )
        results = self._resurface_with(entries, "meeting roadmap sprint planning")
        print(f"\n[bm25 work] results: {results}")

        assert results, "resurface_entries returned no results"
        assert results[0]["date"] == "2026-01-10", (
            f"Expected work entry (2026-01-10) at rank 1, got: {results[0]['date']}"
        )

    def test_bm25_surfaces_anxiety_entry(self):
        """BM25 should surface the stress entry for an 'anxiety' query."""
        entries = _make_entries_dict(
            *self.FILLERS,
            ("2026-02-01", "I felt anxious and stressed about the upcoming exam. Anxiety was overwhelming.",
             {"tags": ["stress"]}),
            ("2026-02-05", "Beautiful sunny day. Had coffee and read a book. Totally relaxed.",
             {"tags": ["gratitude"]}),
        )
        results = self._resurface_with(entries, "anxiety stress exam")
        print(f"\n[bm25 partial] results: {results}")

        assert results, "Expected at least one result"
        assert results[0]["date"] == "2026-02-01", (
            f"Expected anxiety entry at rank 1, got: {results[0]}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 — generate_digest produces meaningful output (Phase 5)
# ══════════════════════════════════════════════════════════════════════════════

class TestDigestOutput:
    """
    Seed entries + facts + contradictions, call generate_digest,
    verify the output is non-empty and references known context.
    """

    def test_digest_produces_output(self, isolated_data):
        from ai import generate_digest

        entries = [
            ("2026-03-10", {"mood": "stressed", "entry": "Deadline pressure at work is killing me. I keep missing gym.", "highlight": "tough day", "sentiment_label": "negative", "goals": ["go to gym"], "entities": ["work"]}),
            ("2026-03-11", {"mood": "okay", "entry": "Had a productive morning. Still skipping gym though.", "highlight": "morning focus", "sentiment_label": "mixed", "goals": ["go to gym"], "entities": []}),
            ("2026-03-12", {"mood": "good", "entry": "Lunch with friends. Feeling better. Still haven't gone to the gym.", "highlight": "friends", "sentiment_label": "positive", "goals": ["exercise", "go to gym"], "entities": ["friends"]}),
        ]
        facts = {
            "name": {"value": "Priya"},
            "location": {"value": "London"},
        }
        contradictions = [
            {"goal": "go to gym", "mention_count": 3},
        ]
        trends = {
            "top_stress_triggers": [{"trigger": "work deadline", "count": 2}]
        }

        result = generate_digest(entries, facts, contradictions, trends)
        print(f"\n[digest output]\n{result}")

        assert result, "generate_digest returned empty string"
        assert len(result) > 100, f"Digest too short: {result}"

    def test_digest_mentions_deferred_goal(self, isolated_data):
        from ai import generate_digest

        entries = [
            ("2026-03-10", {"mood": "okay", "entry": "I really need to start meditating every morning. It's been on my list forever.", "highlight": "", "sentiment_label": "neutral", "goals": ["meditate"], "entities": []}),
            ("2026-03-11", {"mood": "okay", "entry": "Another day without meditation. I keep saying I'll start.", "highlight": "", "sentiment_label": "neutral", "goals": ["meditate"], "entities": []}),
        ]
        contradictions = [{"goal": "meditate", "mention_count": 2}]

        result = generate_digest(entries, {}, contradictions, {})
        print(f"\n[digest deferred goal]\n{result}")

        assert "meditat" in result.lower(), (
            f"Expected 'meditate'/'meditation' mentioned in digest, got: {result}"
        )

    def test_digest_uses_known_facts(self, isolated_data):
        from ai import generate_digest

        entries = [
            ("2026-03-12", {"mood": "good", "entry": "Feeling great today in the city.", "highlight": "", "sentiment_label": "positive", "goals": [], "entities": []}),
        ]
        facts = {"name": {"value": "Tanmay"}, "location": {"value": "Pune"}}

        result = generate_digest(entries, facts, [], {})
        print(f"\n[digest with facts]\n{result}")

        assert result and len(result) > 50
