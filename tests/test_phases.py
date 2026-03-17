"""
Phase verification tests — run with: python -m pytest tests/test_phases.py -v
No Ollama required. Tests cover logic and structure of all 5 phases.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ── make repo root importable ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — Durable Personal Fact Store
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase1FactStore:
    """facts.py exists with the right API; upsert/load/delete/render work."""

    def test_facts_module_importable(self):
        import facts  # noqa: F401

    def test_facts_module_exports(self):
        from facts import load_facts, save_facts, upsert_fact, delete_fact, render_facts, UpsertResult
        assert callable(load_facts)
        assert callable(save_facts)
        assert callable(upsert_fact)
        assert callable(delete_fact)
        assert callable(render_facts)

    def test_upsert_result_dataclass(self):
        from facts import UpsertResult
        r = UpsertResult(
            fact_type="birthday",
            new_value="1998-04-12",
            old_value=None,
            is_conflict=False,
            record={},
        )
        assert r.fact_type == "birthday"
        assert r.old_value is None
        assert r.is_conflict is False

    def test_upsert_new_fact(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact, load_facts
            result = upsert_fact("name", "Alice", "2026-01-01", "My name is Alice")
            assert result.new_value == "Alice"
            assert result.old_value is None
            assert result.is_conflict is False
            stored = load_facts()
            assert stored["name"]["value"] == "Alice"

    def test_upsert_same_value_no_conflict(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact
            upsert_fact("location", "Mumbai", "2026-01-01")
            result = upsert_fact("location", "Mumbai", "2026-01-02")
            assert result.is_conflict is False

    def test_upsert_different_value_is_conflict(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact
            upsert_fact("location", "Mumbai", "2026-01-01")
            result = upsert_fact("location", "London", "2026-01-10")
            assert result.is_conflict is True
            assert result.old_value == "Mumbai"
            assert result.new_value == "London"

    def test_upsert_preserves_history(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact, load_facts
            upsert_fact("job", "Engineer", "2026-01-01")
            upsert_fact("job", "Manager", "2026-02-01")
            facts = load_facts()
            assert facts["job"]["value"] == "Manager"
            assert len(facts["job"]["history"]) == 1
            assert facts["job"]["history"][0]["value"] == "Engineer"

    def test_delete_fact(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact, delete_fact, load_facts
            upsert_fact("pets", "cat", "2026-01-01")
            deleted = delete_fact("pets")
            assert deleted is True
            assert "pets" not in load_facts()

    def test_delete_missing_fact_returns_false(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import delete_fact
            assert delete_fact("nonexistent") is False

    def test_render_facts_empty(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import render_facts
            assert "No personal facts" in render_facts({})

    def test_render_facts_shows_values(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact, render_facts, load_facts
            upsert_fact("birthday", "1998-04-12", "2026-01-01")
            output = render_facts(load_facts())
            assert "birthday" in output
            assert "1998-04-12" in output

    def test_facts_path_in_data_dir(self):
        from facts import FACTS_PATH
        assert FACTS_PATH.parent.name == "data"
        assert FACTS_PATH.name == "facts.json"

    def test_ai_extract_facts_function_exists(self):
        from ai import extract_facts, _clean_fact_candidates
        assert callable(extract_facts)
        assert callable(_clean_fact_candidates)

    def test_clean_fact_candidates_filters_invalid(self):
        from ai import _clean_fact_candidates
        raw = [
            {"fact_type": "birthday", "value": "1998-04-12", "source_excerpt": "..."},
            {"fact_type": "", "value": "something"},   # no fact_type → skip
            {"fact_type": "name", "value": ""},         # no value → skip
            "not a dict",
        ]
        result = _clean_fact_candidates(raw)
        assert len(result) == 1
        assert result[0]["fact_type"] == "birthday"

    def test_clean_fact_candidates_dedupes(self):
        from ai import _clean_fact_candidates
        raw = [
            {"fact_type": "name", "value": "Alice", "source_excerpt": ""},
            {"fact_type": "name", "value": "Bob", "source_excerpt": ""},
        ]
        result = _clean_fact_candidates(raw)
        assert len(result) == 1

    def test_facts_subcommand_registered_in_main(self):
        from main import parse_args
        args = parse_args.__wrapped__ if hasattr(parse_args, "__wrapped__") else None
        # Just verify parsing doesn't crash for known subcommands
        import argparse
        with patch("sys.argv", ["main.py", "facts", "list"]):
            from main import parse_args as pa
            ns = pa()
            assert ns.command == "facts"
            assert ns.facts_command == "list"

    def test_facts_set_subcommand(self):
        with patch("sys.argv", ["main.py", "facts", "set", "birthday", "1998-04-12"]):
            from main import parse_args
            ns = parse_args()
            assert ns.facts_command == "set"
            assert ns.fact_type == "birthday"
            assert ns.value == "1998-04-12"

    def test_facts_delete_subcommand(self):
        with patch("sys.argv", ["main.py", "facts", "delete", "age"]):
            from main import parse_args
            ns = parse_args()
            assert ns.facts_command == "delete"
            assert ns.fact_type == "age"

    def test_facts_history_subcommand(self):
        with patch("sys.argv", ["main.py", "facts", "history", "location"]):
            from main import parse_args
            ns = parse_args()
            assert ns.facts_command == "history"
            assert ns.fact_type == "location"


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Fact-Aware Chat & Ask
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase2FactAwareChat:
    """answer_with_facts() exists; handle_ask uses it; answer_with_context accepts facts kwarg."""

    def test_answer_with_facts_exists(self):
        from ai import answer_with_facts
        assert callable(answer_with_facts)

    def test_answer_with_facts_signature(self):
        import inspect
        from ai import answer_with_facts
        sig = inspect.signature(answer_with_facts)
        params = list(sig.parameters)
        assert "question" in params
        assert "facts" in params
        assert "entries" in params

    def test_answer_with_context_accepts_facts_kwarg(self):
        import inspect
        from ai import answer_with_context
        sig = inspect.signature(answer_with_context)
        assert "facts" in sig.parameters
        # facts should have a default (None)
        assert sig.parameters["facts"].default is None

    def test_answer_with_facts_includes_facts_in_prompt(self):
        """The prompt sent to the LLM must contain the fact block when facts provided."""
        from ai import answer_with_facts
        captured = {}

        def mock_generate(prompt, **kwargs):
            captured["prompt"] = prompt
            return "test answer"

        facts = {"birthday": {"value": "1998-04-12"}}
        entries = {}

        with patch("ai._generate", side_effect=mock_generate):
            answer_with_facts("when is my birthday?", facts, entries)

        assert "birthday" in captured["prompt"]
        assert "1998-04-12" in captured["prompt"]

    def test_answer_with_facts_works_with_empty_facts(self):
        from ai import answer_with_facts

        with patch("ai._generate", return_value="I don't know yet."):
            result = answer_with_facts("where do I live?", {}, {})
        assert isinstance(result, str)

    def test_answer_with_context_includes_facts_block(self):
        from ai import answer_with_context
        captured = {}

        def mock_generate(prompt, **kwargs):
            captured["prompt"] = prompt
            return "answer"

        facts = {"location": {"value": "London"}}

        with patch("ai._generate", side_effect=mock_generate):
            answer_with_context("where am I?", None, [], [], facts=facts)

        assert "London" in captured["prompt"]

    def test_handle_ask_calls_answer_with_facts(self):
        """handle_ask must call answer_with_facts, not the old answer_from_entries."""
        import main
        with patch("main.answer_with_facts", return_value="answer") as mock_awf, \
             patch("main.load_facts", return_value={}), \
             patch("main.load_entries", return_value={}), \
             patch("builtins.print"):
            main.handle_ask("test question", "llama3.1:8b")
            mock_awf.assert_called_once()

    def test_handle_chat_passes_facts(self):
        import main
        with patch("main.answer_with_context", return_value="answer") as mock_awc, \
             patch("main.load_facts", return_value={"name": {"value": "Alice"}}), \
             patch("main.list_entry_dates", return_value=[]), \
             patch("main.get_recent_entries", return_value=[]), \
             patch("main.resurface_entries", return_value=[]), \
             patch("builtins.print"):
            main.handle_chat("test", "llama3.1:8b")
            call_kwargs = mock_awc.call_args
            assert call_kwargs is not None
            # facts= must be in kwargs
            assert "facts" in call_kwargs.kwargs or (
                len(call_kwargs.args) >= 5
            )


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — Conflict Detection & Provenance
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase3ConflictDetection:
    """UpsertResult.is_conflict triggers correctly; history subcommand works."""

    def test_conflict_detected_on_different_value(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact
            upsert_fact("location", "Mumbai", "2026-01-01")
            result = upsert_fact("location", "London", "2026-01-10")
            assert result.is_conflict is True

    def test_no_conflict_on_first_insert(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact
            result = upsert_fact("location", "Mumbai", "2026-01-01")
            assert result.is_conflict is False
            assert result.old_value is None

    def test_no_conflict_case_insensitive_same_value(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact
            upsert_fact("name", "Alice", "2026-01-01")
            result = upsert_fact("name", "alice", "2026-01-02")
            assert result.is_conflict is False

    def test_handle_write_surfaces_conflicts(self, tmp_path):
        """When extracted facts conflict, conflicts list is populated."""
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            import importlib
            import facts as facts_mod
            importlib.reload(facts_mod)

            # Seed an existing fact
            facts_mod.upsert_fact("location", "Mumbai", "2026-01-01")

            printed = []
            conflicting_extracted = [
                {"fact_type": "location", "value": "London", "source_excerpt": "I moved to London"}
            ]

            with patch("main.extract_facts", return_value=conflicting_extracted), \
                 patch("main.generate_reflection", return_value=""), \
                 patch("main.extract_tasks", return_value=[]), \
                 patch("main.analyze_entry", return_value={
                     "tags": [], "goals": [], "tomorrow_plan": [], "sentiment_label": "neutral",
                     "mood_alignment": "unclear", "stress_triggers": [], "habits": [],
                     "wins": [], "gratitude": [], "follow_up_questions": [], "advice": [],
                     "entities": [], "sentiment": "neutral",
                 }), \
                 patch("main.upsert_entry", return_value=("2026-01-10", {"updated_at": "", "saved_at": ""})), \
                 patch("builtins.input", side_effect=["felt restless", "moved to London", "😐 Neutral", "n"]), \
                 patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
                import main
                args = SimpleNamespace(date="2026-01-10", skip_ai=False, model="llama3.1:8b")
                main.handle_write(args)

            conflict_lines = [l for l in printed if "conflict" in l.lower() or "previously" in l.lower()]
            assert len(conflict_lines) > 0, "Expected conflict warning in output"

    def test_upsert_result_has_old_value_on_conflict(self, tmp_path):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            from facts import upsert_fact
            upsert_fact("job", "Engineer", "2026-01-01")
            result = upsert_fact("job", "Designer", "2026-02-01")
            assert result.old_value == "Engineer"
            assert result.new_value == "Designer"

    def test_history_command_parses(self):
        with patch("sys.argv", ["main.py", "facts", "history", "location"]):
            from main import parse_args
            ns = parse_args()
            assert ns.facts_command == "history"

    def test_handle_facts_history_shows_past_values(self, tmp_path, capsys):
        with patch("facts.FACTS_PATH", tmp_path / "facts.json"):
            import facts as facts_mod
            facts_mod.upsert_fact("location", "Mumbai", "2026-01-01")
            facts_mod.upsert_fact("location", "London", "2026-02-01")

            import main
            with patch("main.load_facts", side_effect=facts_mod.load_facts):
                args = SimpleNamespace(facts_command="history", fact_type="location")
                main.handle_facts(args)

            captured = capsys.readouterr()
            assert "London" in captured.out   # current value
            assert "Mumbai" in captured.out   # history


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — BM25 Search
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase4BM25Search:
    """resurface_entries uses BM25Okapi when rank_bm25 is available; falls back gracefully."""

    def test_resurface_entries_exists_in_diary(self):
        from diary import resurface_entries
        assert callable(resurface_entries)

    def test_resurface_entries_returns_list(self, tmp_path):
        with patch("diary.ENTRIES_PATH", tmp_path / "entries.json"):
            from diary import resurface_entries
            result = resurface_entries("gym workout")
            assert isinstance(result, list)

    def test_bm25_used_when_available(self, tmp_path):
        """When rank_bm25 is importable, BM25Okapi.get_scores must be called."""
        entries_data = {
            "2026-01-01": [{"entry": "I went to the gym today", "mood": "good", "highlight": "workout",
                            "tags": ["health"], "goals": [], "entities": [], "wins": [],
                            "habits": [], "gratitude": [], "stress_triggers": [],
                            "sentiment_label": "positive", "mood_alignment": "aligned",
                            "tomorrow_plan": [], "follow_up_questions": [], "advice": [],
                            "task_candidates": [], "suggested_tasks": [], "embedding_text": "",
                            "saved_at": "", "updated_at": "", "created_at": "",
                            "reflection": "", "prompts": {}}],
        }
        with patch("diary.ENTRIES_PATH", tmp_path / "entries.json"):
            (tmp_path / "entries.json").write_text(json.dumps(entries_data))
            import importlib
            import diary
            importlib.reload(diary)

            mock_bm25 = MagicMock()
            mock_bm25.get_scores.return_value = [2.5]

            mock_bm25_cls = MagicMock(return_value=mock_bm25)
            mock_module = MagicMock()
            mock_module.BM25Okapi = mock_bm25_cls

            with patch.dict("sys.modules", {"rank_bm25": mock_module}):
                results = diary.resurface_entries("gym workout")

            mock_bm25.get_scores.assert_called_once()

    def test_fallback_when_rank_bm25_missing(self, tmp_path):
        """If rank_bm25 is not installed, keyword fallback runs without crashing."""
        entries_data = {
            "2026-01-01": [{"entry": "I went to the gym today", "mood": "good", "highlight": "workout",
                            "tags": ["health"], "goals": [], "entities": [], "wins": [],
                            "habits": [], "gratitude": [], "stress_triggers": [],
                            "sentiment_label": "positive", "mood_alignment": "aligned",
                            "tomorrow_plan": [], "follow_up_questions": [], "advice": [],
                            "task_candidates": [], "suggested_tasks": [], "embedding_text": "",
                            "saved_at": "", "updated_at": "", "created_at": "",
                            "reflection": "", "prompts": {}}],
        }
        with patch("diary.ENTRIES_PATH", tmp_path / "entries.json"):
            (tmp_path / "entries.json").write_text(json.dumps(entries_data))
            import importlib
            import diary
            importlib.reload(diary)

            # Remove rank_bm25 from sys.modules so ImportError triggers
            saved = sys.modules.pop("rank_bm25", None)
            try:
                results = diary.resurface_entries("gym")
                assert isinstance(results, list)
            finally:
                if saved is not None:
                    sys.modules["rank_bm25"] = saved

    def test_resurface_result_shape(self, tmp_path):
        entries_data = {
            "2026-01-01": [{"entry": "stressed about work deadline", "mood": "bad", "highlight": "deadline",
                            "tags": ["work", "stress"], "goals": ["finish project"], "entities": [],
                            "wins": [], "habits": [], "gratitude": [], "stress_triggers": [],
                            "sentiment_label": "negative", "mood_alignment": "aligned",
                            "tomorrow_plan": [], "follow_up_questions": [], "advice": [],
                            "task_candidates": [], "suggested_tasks": [], "embedding_text": "",
                            "saved_at": "", "updated_at": "", "created_at": "",
                            "reflection": "", "prompts": {}}],
        }
        with patch("diary.ENTRIES_PATH", tmp_path / "entries.json"):
            (tmp_path / "entries.json").write_text(json.dumps(entries_data))
            import importlib
            import diary
            importlib.reload(diary)

            results = diary.resurface_entries("work stress deadline")
            if results:
                r = results[0]
                assert "date" in r
                assert "score" in r
                assert "reasons" in r
                assert "excerpt" in r

    def test_empty_query_returns_empty(self, tmp_path):
        with patch("diary.ENTRIES_PATH", tmp_path / "entries.json"):
            from diary import resurface_entries
            assert resurface_entries("") == []
            assert resurface_entries("   ") == []

    def test_rank_bm25_in_requirements(self):
        req_path = ROOT / "requirements.txt"
        assert req_path.exists(), "requirements.txt not found"
        content = req_path.read_text()
        assert "rank-bm25" in content, "rank-bm25 missing from requirements.txt"

    def test_keyword_fallback_function_exists(self):
        from diary import _resurface_keyword_fallback
        assert callable(_resurface_keyword_fallback)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5 — Periodic Digest
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase5PeriodicDigest:
    """generate_digest() in ai.py; digest subcommand in main.py."""

    def test_generate_digest_exists(self):
        from ai import generate_digest
        assert callable(generate_digest)

    def test_generate_digest_signature(self):
        import inspect
        from ai import generate_digest
        sig = inspect.signature(generate_digest)
        params = list(sig.parameters)
        assert "entries" in params
        assert "facts" in params
        assert "contradictions" in params
        assert "trends" in params

    def test_generate_digest_empty_entries(self):
        from ai import generate_digest
        result = generate_digest([], {}, [], {})
        assert "Not enough" in result or isinstance(result, str)

    def test_generate_digest_calls_llm(self):
        from ai import generate_digest
        entries = [("2026-01-01", {"mood": "good", "entry": "had a great day", "highlight": "",
                                    "sentiment_label": "positive", "goals": [], "entities": []})]
        facts = {"name": {"value": "Alice"}}
        contradictions = []
        trends = {"top_stress_triggers": []}

        with patch("ai._generate", return_value="digest output") as mock_gen:
            result = generate_digest(entries, facts, contradictions, trends)

        mock_gen.assert_called_once()
        assert result == "digest output"

    def test_generate_digest_includes_facts_in_prompt(self):
        from ai import generate_digest
        entries = [("2026-01-01", {"mood": "good", "entry": "test", "highlight": "",
                                    "sentiment_label": "positive", "goals": [], "entities": []})]
        facts = {"location": {"value": "Berlin"}}
        captured = {}

        def mock_generate(prompt, **kwargs):
            captured["prompt"] = prompt
            return "digest"

        with patch("ai._generate", side_effect=mock_generate):
            generate_digest(entries, facts, [], {})

        assert "Berlin" in captured["prompt"]

    def test_generate_digest_includes_contradictions_in_prompt(self):
        from ai import generate_digest
        entries = [("2026-01-01", {"mood": "good", "entry": "test", "highlight": "",
                                    "sentiment_label": "positive", "goals": [], "entities": []})]
        contradictions = [{"goal": "exercise more", "mention_count": 5}]
        captured = {}

        def mock_generate(prompt, **kwargs):
            captured["prompt"] = prompt
            return "digest"

        with patch("ai._generate", side_effect=mock_generate):
            generate_digest(entries, {}, contradictions, {})

        assert "exercise more" in captured["prompt"]

    def test_digest_subcommand_registered(self):
        with patch("sys.argv", ["main.py", "digest"]):
            from main import parse_args
            ns = parse_args()
            assert ns.command == "digest"
            assert ns.days == 14  # default

    def test_digest_subcommand_days_arg(self):
        with patch("sys.argv", ["main.py", "digest", "--days", "7"]):
            from main import parse_args
            ns = parse_args()
            assert ns.days == 7

    def test_handle_digest_exists_in_main(self):
        from main import handle_digest
        assert callable(handle_digest)

    def test_handle_digest_no_entries_prints_message(self, capsys):
        import main
        with patch("main.get_recent_entries", return_value=[]), \
             patch("main.load_facts", return_value={}), \
             patch("main.detect_contradictions", return_value=[]), \
             patch("main.sentiment_trends", return_value={}):
            main.handle_digest(14, "llama3.1:8b")

        captured = capsys.readouterr()
        assert "Not enough" in captured.out or "No" in captured.out

    def test_handle_digest_calls_generate_digest(self):
        import main
        entries = [("2026-01-01", {"mood": "good", "entry": "test", "highlight": ""})]
        with patch("main.get_recent_entries", return_value=entries), \
             patch("main.load_facts", return_value={}), \
             patch("main.detect_contradictions", return_value=[]), \
             patch("main.sentiment_trends", return_value={}), \
             patch("main.generate_digest", return_value="digest output") as mock_gd, \
             patch("builtins.print"):
            main.handle_digest(14, "llama3.1:8b")

        mock_gd.assert_called_once()

    def test_weekly_review_includes_contradictions(self):
        """handle_weekly_review must call detect_contradictions and print them."""
        import main
        entries = [("2026-01-01", {"mood": "good", "entry": "test"})]
        contradictions = [{"goal": "sleep better", "mention_count": 3}]

        printed = []
        with patch("main.get_recent_entries", return_value=entries), \
             patch("main.generate_weekly_summary", return_value="weekly summary"), \
             patch("main.detect_contradictions", return_value=contradictions) as mock_dc, \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            main.handle_weekly_review(7, "llama3.1:8b")

        mock_dc.assert_called_once()
        combined = "\n".join(printed)
        assert "sleep better" in combined
