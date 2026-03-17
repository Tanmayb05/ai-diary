# Build Phases — AI Diary CLI

Quick reference for what's been built and what's next.
Each phase file has full context, skeleton code, and exact file locations.

## Phases

| Phase | File | Status | Description |
|-------|------|--------|-------------|
| 1 | PHASE_1_FACT_STORE.md | NOT STARTED | Extract + persist personal facts from entries |
| 2 | PHASE_2_FACT_AWARE_CHAT.md | NOT STARTED | Use fact store in ask/chat answers |
| 3 | PHASE_3_CONFLICT_DETECTION.md | NOT STARTED | Detect when new facts contradict old ones |
| 4 | PHASE_4_BM25_SEARCH.md | NOT STARTED | Better entry retrieval with BM25 ranking |
| 5 | PHASE_5_PERIODIC_DIGEST.md | NOT STARTED | Proactive weekly digest + pattern surfacing |

## Dependency order
1 → 2 → 3 (linear)
4 → standalone (can be done anytime)
5 → benefits from 1+3 but works without them

## Codebase quick reference

```
main.py          — CLI entrypoint, all subcommands, all handle_*() functions
ai.py            — all LLM calls (_generate, extract_*, generate_*, answer_*)
diary.py         — entry CRUD, resurface_entries, sentiment_trends, detect_contradictions
intent_router.py — NLP intent routing for chat-ui mode
chat_session.py  — interactive REPL loop
handlers.py      — ChatHandlers class (used by chat-ui)
utils.py         — DATA_DIR, ENTRIES_PATH, load_json, save_json, timestamp()
facts.py         — CREATED IN PHASE 1
data/entries.json
data/facts.json  — CREATED IN PHASE 1
data/todos.json
```

## How to start a phase
1. Read the phase `.md` file — it has full context, no need to re-read all source files
2. Create/modify only the files listed in the "Files to create/modify" section
3. Update the Status line in this README and the phase file when done