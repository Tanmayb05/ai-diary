# Test Suite

**71 tests across 2 files.** Run everything with:

```bash
.venv/bin/python -m pytest tests/ -v
```

---

## Files

| File | Tests | Type | Requires Ollama |
|---|---|---|---|
| `test_phases.py` | 54 | Unit | No |
| `test_functional.py` | 17 | Functional / E2E | Yes |

---

## test_phases.py — Unit Tests (54)

No Ollama needed. All LLM calls are mocked. Verifies that every phase was wired up correctly.

### Phase 1 — Fact Store (19 tests)

| Test | What it checks |
|---|---|
| `test_facts_module_importable` | `facts.py` exists and imports without error |
| `test_facts_module_exports` | `load_facts`, `save_facts`, `upsert_fact`, `delete_fact`, `render_facts` are all callable |
| `test_upsert_result_dataclass` | `UpsertResult` fields: `fact_type`, `new_value`, `old_value`, `is_conflict`, `record` |
| `test_upsert_new_fact` | Inserting a new fact stores it in `facts.json` with correct value |
| `test_upsert_same_value_no_conflict` | Upserting the same value twice does not set `is_conflict` |
| `test_upsert_different_value_is_conflict` | Upserting a different value sets `is_conflict = True` |
| `test_upsert_preserves_history` | Old value moves to `history[]` before overwrite |
| `test_delete_fact` | Deleting an existing fact removes it and returns `True` |
| `test_delete_missing_fact_returns_false` | Deleting a non-existent fact returns `False` |
| `test_render_facts_empty` | `render_facts({})` returns a "no facts" message |
| `test_render_facts_shows_values` | `render_facts(...)` includes `fact_type` and `value` |
| `test_facts_path_in_data_dir` | `FACTS_PATH` resolves to `data/facts.json` |
| `test_ai_extract_facts_function_exists` | `extract_facts` and `_clean_fact_candidates` exist in `ai.py` |
| `test_clean_fact_candidates_filters_invalid` | Drops entries with empty `fact_type` or `value`, or non-dict items |
| `test_clean_fact_candidates_dedupes` | Duplicate `fact_type` keys are deduplicated |
| `test_facts_subcommand_registered_in_main` | `python main.py facts list` parses without error |
| `test_facts_set_subcommand` | `facts set birthday 1998-04-12` populates `fact_type` and `value` |
| `test_facts_delete_subcommand` | `facts delete age` populates `fact_type` |
| `test_facts_history_subcommand` | `facts history location` populates `fact_type` |

### Phase 2 — Fact-Aware Chat (8 tests)

| Test | What it checks |
|---|---|
| `test_answer_with_facts_exists` | `answer_with_facts()` exists in `ai.py` |
| `test_answer_with_facts_signature` | Accepts `question`, `facts`, `entries` parameters |
| `test_answer_with_context_accepts_facts_kwarg` | `answer_with_context()` has `facts=None` default parameter |
| `test_answer_with_facts_includes_facts_in_prompt` | The LLM prompt includes the fact block when facts are provided |
| `test_answer_with_facts_works_with_empty_facts` | Doesn't crash when `facts={}` |
| `test_answer_with_context_includes_facts_block` | Facts appear in the prompt sent by `answer_with_context` |
| `test_handle_ask_calls_answer_with_facts` | `handle_ask()` calls `answer_with_facts`, not the old `answer_from_entries` |
| `test_handle_chat_passes_facts` | `handle_chat()` passes `facts=load_facts()` into `answer_with_context` |

### Phase 3 — Conflict Detection (7 tests)

| Test | What it checks |
|---|---|
| `test_conflict_detected_on_different_value` | `upsert_fact` with a new value sets `is_conflict = True` |
| `test_no_conflict_on_first_insert` | First insert always has `old_value = None`, `is_conflict = False` |
| `test_no_conflict_case_insensitive_same_value` | `"Alice"` vs `"alice"` is not a conflict |
| `test_handle_write_surfaces_conflicts` | `handle_write()` prints a conflict warning when a fact changes |
| `test_upsert_result_has_old_value_on_conflict` | Conflict result carries correct `old_value` and `new_value` |
| `test_history_command_parses` | `facts history location` parses `facts_command = "history"` |
| `test_handle_facts_history_shows_past_values` | `handle_facts(history)` prints both current and historical values |

### Phase 4 — BM25 Search (8 tests)

| Test | What it checks |
|---|---|
| `test_resurface_entries_exists_in_diary` | `resurface_entries()` exists in `diary.py` |
| `test_resurface_entries_returns_list` | Returns a list (even when empty) |
| `test_bm25_used_when_available` | `BM25Okapi.get_scores()` is called when `rank_bm25` is installed |
| `test_fallback_when_rank_bm25_missing` | Doesn't crash when `rank_bm25` is not installed |
| `test_resurface_result_shape` | Each result has `date`, `score`, `reasons`, `excerpt` keys |
| `test_empty_query_returns_empty` | Empty or whitespace-only query returns `[]` |
| `test_rank_bm25_in_requirements` | `rank-bm25` is listed in `requirements.txt` |
| `test_keyword_fallback_function_exists` | `_resurface_keyword_fallback()` exists as the fallback |

### Phase 5 — Periodic Digest (12 tests)

| Test | What it checks |
|---|---|
| `test_generate_digest_exists` | `generate_digest()` exists in `ai.py` |
| `test_generate_digest_signature` | Accepts `entries`, `facts`, `contradictions`, `trends` |
| `test_generate_digest_empty_entries` | Returns a graceful message when no entries provided |
| `test_generate_digest_calls_llm` | `_generate()` is called exactly once |
| `test_generate_digest_includes_facts_in_prompt` | Known facts appear in the LLM prompt |
| `test_generate_digest_includes_contradictions_in_prompt` | Deferred goals appear in the LLM prompt |
| `test_digest_subcommand_registered` | `python main.py digest` parses with `days = 14` default |
| `test_digest_subcommand_days_arg` | `--days 7` is passed through correctly |
| `test_handle_digest_exists_in_main` | `handle_digest()` exists in `main.py` |
| `test_handle_digest_no_entries_prints_message` | Prints a "not enough entries" message when diary is empty |
| `test_handle_digest_calls_generate_digest` | `generate_digest()` is called when entries exist |
| `test_weekly_review_includes_contradictions` | `handle_weekly_review()` calls `detect_contradictions` and prints them |

---

## test_functional.py — Functional Tests (17)

**Requires Ollama running** (`ollama serve`). Auto-skipped otherwise.
All tests use temp files — no real `data/facts.json` or `data/entries.json` is touched.

```bash
# Run only functional tests
.venv/bin/python -m pytest tests/test_functional.py -v -s
```

### Extract & Store Facts (4 tests)

Real LLM call on a seeded entry: `"My name is Priya... I was born on March 15 1999... software engineer... Bangalore"`

| Test | What it checks |
|---|---|
| `test_extract_facts_finds_name` | LLM extracts `name` fact type from the entry |
| `test_extract_facts_finds_birthday` | LLM extracts `birthday` or `age` fact type |
| `test_extracted_name_value_is_correct` | Extracted name value contains `"Priya"` |
| `test_store_and_reload_extracted_facts` | Full round-trip: extract → `upsert_fact` → `load_facts` → `name` is stored with correct value |

### Answer With Facts (5 tests)

Facts seeded directly into temp store. LLM answers questions from the fact store.

| Test | What it verifies |
|---|---|
| `test_answers_birthday_from_fact_store` | "What is my birthday?" → returns `March 15, 1999` from fact store |
| `test_answers_name_from_fact_store` | "What is my name?" → returns `Priya` |
| `test_answers_job_from_fact_store` | "What do I do for work?" → returns `software engineer` |
| `test_no_hallucination_when_fact_missing` | "What is my favorite color?" with no facts/entries → LLM says "I don't know" |
| `test_facts_take_priority_over_entries` | Fact store says London; diary entry says Mumbai → answer says London |

### Full Pipeline (2 tests)

Simulates the full `handle_write()` flow end-to-end.

| Test | What it verifies |
|---|---|
| `test_write_then_ask` | Entry about Arjun → `extract_facts` → `upsert_fact` → `answer_with_facts("What is my name?")` → `"Arjun"` |
| `test_write_two_entries_conflict_then_ask` | Entry 1: Mumbai. Entry 2: London. → conflict detected on location → `answer_with_facts` returns London |

### BM25 Resurface (3 tests)

BM25 ranking with injected corpus (6 entries: 4 neutral fillers + 2 target entries).

| Test | What it verifies |
|---|---|
| `test_resurface_returns_gym_entry` | Query `"gym workout exercise"` → gym entry ranks #1 over a work entry |
| `test_resurface_returns_work_entry` | Query `"meeting roadmap sprint planning"` → work entry ranks #1 over gym entry |
| `test_bm25_surfaces_anxiety_entry` | Query `"anxiety stress exam"` → stress entry ranks #1 over a relaxing-day entry |

### Digest Output (3 tests)

Real LLM call with injected entries, facts, and contradictions.

| Test | What it verifies |
|---|---|
| `test_digest_produces_output` | `generate_digest()` returns non-empty string (>100 chars) |
| `test_digest_mentions_deferred_goal` | Output contains `"meditat"` when `meditate` appears as a deferred goal |
| `test_digest_uses_known_facts` | Digest runs without error when known facts include `name` and `location` |

---

## Bugs found during testing

Two real bugs were caught and fixed by the functional tests:

**`ai._parse_json`** — Ollama sometimes prepends prose before the JSON array (e.g. `"Here is the extracted fact:\n\n[...]"`). `json.loads` failed on the full string. Fixed by extracting the first `[...]` or `{...}` block when direct parsing fails.

**`diary._entry_keywords`** — Minimum word length was 4, silently dropping 3-letter keywords like `gym`, `job`, `age`. Fixed by lowering the minimum to 3.
