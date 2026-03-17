# Phase 4 — BM25 Search for Entry Retrieval

## Goal
Replace the current keyword-overlap scoring in `resurface_entries()` and `find_similar_entries()`
with BM25 (Best Match 25), a standard IR ranking algorithm. Better recall on `ask` and `chat`
queries. No vector DB, no embeddings — pure Python.

## Status: NOT STARTED
## Depends on: Nothing (standalone improvement to diary.py)

---

## Existing codebase context

- `diary.py` — `resurface_entries(query, limit)` — current keyword overlap scorer, replace this
- `diary.py` — `find_similar_entries(target_date, limit)` — uses `_entry_feature_sets()`, keep as-is
- `diary.py` — `_entry_keywords(text)` — stopword-filtered word tokenizer, reuse this
- `diary.py` — `load_entries()` — returns `dict[str, aggregated_entry]`
- `main.py` — `handle_resurface()` and `handle_chat()` both call `resurface_entries()`

---

## Dependency

Install `rank-bm25`:

```bash
pip install rank-bm25
```

Add to requirements if you have one:
```
rank-bm25>=0.2.2
```

---

## Update `diary.py`: replace `resurface_entries()`

```python
def resurface_entries(
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    BM25-ranked retrieval over diary entries.
    Falls back to keyword overlap if rank_bm25 is not installed.
    """
    cleaned_query = str(query or "").strip().lower()
    if not cleaned_query:
        return []

    entries = load_entries()
    if not entries:
        return []

    # Build corpus: one document per entry
    # Concatenate all searchable text for each entry
    dates = sorted(entries.keys(), reverse=True)
    corpus_texts = []
    for d in dates:
        item = entries[d]
        parts = [
            item.get("entry", ""),
            item.get("highlight", ""),
            " ".join(item.get("goals", []) or []),
            " ".join(item.get("entities", []) or []),
            " ".join(item.get("tags", []) or []),
            " ".join(item.get("wins", []) or []),
        ]
        corpus_texts.append(" ".join(parts))

    try:
        from rank_bm25 import BM25Okapi

        # Tokenize corpus and query using existing _entry_keywords tokenizer
        tokenized_corpus = [list(_entry_keywords(text)) for text in corpus_texts]
        tokenized_query = list(_entry_keywords(cleaned_query))

        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(tokenized_query)

        # Collect results above threshold
        results = []
        for i, score in enumerate(scores):
            if score <= 0:
                continue
            entry_date = dates[i]
            item = entries[entry_date]
            results.append({
                "date": entry_date,
                "score": float(score),
                "reasons": [f"bm25 score: {score:.2f}"],
                "highlight": item.get("highlight", ""),
                "excerpt": str(item.get("entry", "")).strip()[:160],
            })

        results.sort(key=lambda x: -x["score"])
        return results[:limit]

    except ImportError:
        # Fallback to original keyword overlap if rank_bm25 not installed
        return _resurface_keyword_fallback(cleaned_query, entries, limit)


def _resurface_keyword_fallback(
    cleaned_query: str,
    entries: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    """Original keyword overlap scoring — kept as fallback."""
    query_terms = _entry_keywords(cleaned_query)
    matches = []
    for entry_date, item in entries.items():
        features = _entry_feature_sets(item)
        score = 0
        reasons = []

        for field_name in ("tags", "goals", "entities", "habits", "wins", "gratitude"):
            if cleaned_query in features[field_name]:
                score += 6
                reasons.append(f"matched {field_name}")

        matching_terms = sorted(query_terms & features["keywords"])
        if matching_terms:
            score += len(matching_terms) * 2
            reasons.append(f"keyword overlap: {', '.join(matching_terms[:4])}")

        if score <= 0:
            continue

        matches.append({
            "date": entry_date,
            "score": score,
            "reasons": reasons,
            "highlight": item.get("highlight", ""),
            "excerpt": str(item.get("entry", "")).strip()[:160],
        })

    matches.sort(key=lambda x: (-x["score"], x["date"]))
    return matches[:limit]
```

---

## Testing

```bash
pip install rank-bm25

# Test retrieval quality — compare before/after
python main.py resurface --query "gym workout exercise"
python main.py resurface --query "anxiety stress deadline"
python main.py chat "when did I last feel really productive?"
```

Expected improvement: BM25 should surface entries with partial word overlap that keyword
matching misses, and rank by TF-IDF-like weighting rather than simple count.

---

## Files to modify
- MODIFY: `diary.py` — replace `resurface_entries()`, add `_resurface_keyword_fallback()`
- OPTIONAL: add `rank-bm25` to `requirements.txt` if it exists