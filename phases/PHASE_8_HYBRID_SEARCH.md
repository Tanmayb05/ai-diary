# Phase 8 — Hybrid Search (FTS5 + Vector + RRF)

## Goal
Replace the existing BM25 `resurface_entries()` (rank-bm25 library, loads all entries into RAM)
with a hybrid search that combines SQLite FTS5 (keyword) + sqlite-vec (semantic) results via
Reciprocal Rank Fusion (RRF). Better recall, no full-file loads, sub-10ms for most queries.

## Status: NOT STARTED
## Depends on: Phase 6 (SQLite), Phase 7 (embeddings stored in entry_embeddings)

---

## How it works

```
query → FTS5 search  → ranked list A  ─┐
query → vec search   → ranked list B  ─┤→ RRF merge → top-K results
                                        └─ (no embeddings? fall back to FTS5 only)
```

**Reciprocal Rank Fusion (RRF):**
```
score(doc) = Σ  1 / (k + rank_in_list)    k=60 (standard constant)
```
Each result list contributes a score based on position. Top combined scores win.

---

## Update `diary.py` — replace `resurface_entries()`

```python
# diary.py

import json
import struct
from db import get_db, load_vec_extension

EMBED_DIM = 768
RRF_K = 60          # standard RRF constant
FTS_LIMIT = 20      # candidates per source before RRF merge
VEC_LIMIT = 20


def resurface_entries(query: str, *, limit: int = 5) -> list[dict]:
    """
    Hybrid FTS5 + vector search with Reciprocal Rank Fusion.
    Falls back to FTS5-only if embeddings are unavailable.
    """
    query = (query or "").strip()
    if not query:
        return []

    db = get_db()
    fts_results  = _fts_search(db, query, limit=FTS_LIMIT)
    vec_results  = _vec_search(db, query, limit=VEC_LIMIT)

    merged = _rrf_merge(fts_results, vec_results, limit=limit)
    return merged


def _fts_search(db, query: str, limit: int) -> list[dict]:
    """FTS5 full-text search using SQLite built-in BM25 ranking."""
    # FTS5 bm25() returns negative scores (lower = better)
    try:
        rows = db.execute("""
            SELECT
                e.id,
                e.date,
                e.entry,
                e.highlight,
                e.metadata,
                bm25(entries_fts) AS score
            FROM entries_fts
            JOIN entries e ON e.id = entries_fts.rowid
            WHERE entries_fts MATCH ?
            ORDER BY score          -- ascending: most negative = best match
            LIMIT ?
        """, (query, limit)).fetchall()
    except Exception:
        return []

    results = []
    for i, row in enumerate(rows):
        meta = json.loads(row["metadata"] or "{}")
        results.append({
            "id":        row["id"],
            "date":      row["date"],
            "score":     float(row["score"]),
            "rank":      i + 1,
            "source":    "fts",
            "highlight": row["highlight"] or "",
            "excerpt":   (row["entry"] or "")[:160],
            "reasons":   [f"fts match (rank {i+1})"],
            **{k: meta.get(k) for k in ("tags", "goals", "entities", "wins") if meta.get(k)},
        })
    return results


def _vec_search(db, query: str, limit: int) -> list[dict]:
    """Vector similarity search using sqlite-vec KNN."""
    if not load_vec_extension(db):
        return []

    try:
        from embeddings import generate_embedding
        vec = generate_embedding(query)
        packed = struct.pack(f"{EMBED_DIM}f", *vec)
    except Exception:
        return []

    try:
        rows = db.execute("""
            SELECT
                ee.entry_id,
                ee.distance,
                e.date,
                e.entry,
                e.highlight,
                e.metadata
            FROM entry_embeddings ee
            JOIN entries e ON e.id = ee.entry_id
            WHERE embedding MATCH ?
              AND k = ?
            ORDER BY distance
        """, (packed, limit)).fetchall()
    except Exception:
        return []

    results = []
    for i, row in enumerate(rows):
        meta = json.loads(row["metadata"] or "{}")
        results.append({
            "id":        row["entry_id"],
            "date":      row["date"],
            "score":     float(row["distance"]),
            "rank":      i + 1,
            "source":    "vec",
            "highlight": row["highlight"] or "",
            "excerpt":   (row["entry"] or "")[:160],
            "reasons":   [f"semantic match (rank {i+1})"],
            **{k: meta.get(k) for k in ("tags", "goals", "entities", "wins") if meta.get(k)},
        })
    return results


def _rrf_merge(
    fts: list[dict],
    vec: list[dict],
    limit: int,
    k: int = RRF_K,
) -> list[dict]:
    """
    Reciprocal Rank Fusion: combine two ranked lists into one.
    score(doc) = sum of 1/(k + rank) across all lists containing the doc.
    """
    scores: dict[int, float] = {}
    docs:   dict[int, dict]  = {}

    for result_list in (fts, vec):
        for item in result_list:
            doc_id = item["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + item["rank"])
            if doc_id not in docs:
                docs[doc_id] = item
            else:
                # merge source labels
                existing = docs[doc_id]
                existing["reasons"] = existing["reasons"] + item["reasons"]
                if item["source"] != existing["source"]:
                    existing["source"] = "hybrid"

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    results = []
    for doc_id, rrf_score in ranked[:limit]:
        doc = docs[doc_id].copy()
        doc["score"] = rrf_score
        results.append(doc)
    return results
```

---

## Remove rank-bm25 dependency

After this phase, `rank-bm25` is no longer needed. Remove from requirements.txt:
```
# rank-bm25>=0.2.2   ← delete this line
```

And remove the import + `_resurface_keyword_fallback()` from `diary.py` if Phase 4 added them.

---

## FTS5 query escaping

FTS5 special chars (`"`, `*`, `-`, etc.) can cause syntax errors. Add a sanitizer:

```python
def _fts_escape(query: str) -> str:
    """Escape user query for safe FTS5 MATCH."""
    # Wrap in quotes for phrase search; remove chars FTS5 can't handle
    safe = query.replace('"', ' ').strip()
    return f'"{safe}"' if safe else ""
```

Use in `_fts_search`: `WHERE entries_fts MATCH ?` with `_fts_escape(query)`.

---

## Testing

```bash
# 1. Basic hybrid search
python main.py resurface --query "gym workout exercise"
python main.py resurface --query "anxiety stress deadline"
python main.py chat "when did I last feel really productive?"

# 2. Compare: FTS-only vs hybrid
python -c "
from diary import _fts_search, _vec_search, _rrf_merge
from db import get_db
db = get_db()
query = 'anxiety about work'
fts = _fts_search(db, query, 10)
vec = _vec_search(db, query, 10)
merged = _rrf_merge(fts, vec, 5)
print('FTS:', [r['date'] for r in fts[:5]])
print('VEC:', [r['date'] for r in vec[:5]])
print('RRF:', [r['date'] for r in merged])
"

# 3. Edge cases
python main.py resurface --query ""           # should return nothing
python main.py resurface --query "xyzzy123"   # no match — should return []
```

---

## Expected improvement over Phase 4 BM25

| Scenario | Phase 4 BM25 | Phase 8 Hybrid |
|---|---|---|
| Exact keyword match | Good | Good (FTS5) |
| Synonym / paraphrase | Misses | Finds (vec) |
| Short vague query | Weak | Strong (vec) |
| Date-range filtering | Not supported | Add WHERE clause |
| RAM usage | Loads all entries | Index-only |

---

## Files to modify
- MODIFY: `diary.py` — replace `resurface_entries()` + helpers with hybrid version
- MODIFY: `db.py` — ensure FTS5 triggers are in schema (already in Phase 6)
- MODIFY: `requirements.txt` — remove rank-bm25, keep sqlite-vec
- NO CHANGES needed to `main.py`, `ai.py`, `handlers.py` — same function signature
