# Phase 2 — Fact-Aware Chat & Ask

## Goal
When the user asks a question via `ask` or `chat`, check the fact store first before
doing RAG over diary entries. Canonical personal facts ("when is my birthday?",
"where do I live?") should be answered instantly from the fact store, not guessed
from scanning entries.

## Status: NOT STARTED
## Depends on: Phase 1 (facts.py + data/facts.json must exist)

---

## Existing codebase context

- `ai.py` — `answer_from_entries(question, entries, model)` — current ask handler, scans last 14 entries
- `ai.py` — `answer_with_context(question, current_entry, recent_entries, retrieved_entries, model)` — used by `chat` command
- `main.py` — `handle_ask()` calls `answer_from_entries`
- `main.py` — `handle_chat()` calls `answer_with_context`
- `facts.py` — `load_facts()` — returns `dict[str, Any]` keyed by fact_type (built in Phase 1)

---

## New function in `ai.py`: `answer_with_facts()`

Add after `answer_with_context()`:

```python
def answer_with_facts(
    question: str,
    facts: dict[str, Any],
    entries: dict[str, Any],
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Answer a question using the fact store as the primary source,
    falling back to recent diary entries for context.
    """
    # Render known facts as a clean block
    facts_block = ""
    if facts:
        lines = [f"- {k}: {v['value']}" for k, v in sorted(facts.items())]
        facts_block = "Known personal facts:\n" + "\n".join(lines)

    # Render recent entry context (last 7)
    context_lines = []
    for entry_date in sorted(entries.keys(), reverse=True)[:7]:
        item = entries[entry_date]
        context_lines.append(
            f"Date: {entry_date}\nMood: {item.get('mood', '-')}\n"
            f"Tags: {', '.join(item.get('tags', []) or []) or '-'}\n"
            f"Entry: {item.get('entry', '')}"
        )
    entries_block = "\n\n".join(context_lines)

    prompt = f"""
Answer the user's question using the sources below.
Prefer the Known personal facts section for direct personal questions.
Use diary entries only for questions about events, feelings, or patterns over time.
If you cannot answer from the provided context, say "I don't know yet."
Be concise and specific.

Question: {question}

{facts_block}

Recent diary entries:
{entries_block}
""".strip()
    return _generate(prompt, model=model, temperature=0.2, call_type="answer_with_facts")
```

---

## Update `main.py`: `handle_ask()`

Replace current implementation:

```python
# BEFORE:
def handle_ask(question: str, model: str) -> None:
    try:
        print(answer_from_entries(question, load_entries(), model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")

# AFTER:
def handle_ask(question: str, model: str) -> None:
    from facts import load_facts
    from ai import answer_with_facts
    try:
        print(answer_with_facts(question, load_facts(), load_entries(), model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")
```

---

## Update `main.py`: `handle_chat()`

Add facts to the context passed to `answer_with_context`:

```python
# In ai.py, update answer_with_context signature to accept facts:
def answer_with_context(
    question: str,
    current_entry: tuple[str, dict[str, Any]] | None,
    recent_entries: list[tuple[str, dict[str, Any]]],
    retrieved_entries: list[tuple[str, dict[str, Any]]],
    facts: dict[str, Any] | None = None,   # ADD THIS
    model: str = DEFAULT_MODEL,
) -> str:
    # At the top of the function, prepend facts block to sections:
    sections = []
    if facts:
        lines = [f"- {k}: {v['value']}" for k, v in sorted(facts.items())]
        sections.append("Known personal facts:\n" + "\n".join(lines))
    # ... rest unchanged ...
```

In `main.py`, update `handle_chat()`:

```python
def handle_chat(question: str, model: str) -> None:
    from facts import load_facts
    # ... existing setup code unchanged ...
    try:
        print(answer_with_context(
            question, current_entry, recent_entries, resurfaced,
            facts=load_facts(),   # ADD THIS
            model=model,
        ))
    except AIError as exc:
        print(f"AI unavailable: {exc}")
```

---

## Update `chat_session.py` (interactive chat-ui)

The `ChatHandlers` in `handlers.py` uses `answer_with_context`. Same change applies there:
- Import `load_facts` from `facts`
- Pass `facts=load_facts()` into each `answer_with_context` call

---

## Testing

```bash
# After writing an entry that mentions birthday/location/job:
python main.py ask "when is my birthday?"
# Should answer from fact store, not scan entries

python main.py ask "where do I live?"
# Should answer from fact store

python main.py ask "how have I been feeling about work lately?"
# Should use diary entries (no fact for this), not hallucinate
```

---

## Files to modify
- MODIFY: `ai.py` — add `answer_with_facts()`, update `answer_with_context()` signature
- MODIFY: `main.py` — update `handle_ask()` and `handle_chat()`
- MODIFY: `handlers.py` — pass facts into `answer_with_context` calls