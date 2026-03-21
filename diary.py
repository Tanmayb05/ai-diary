from __future__ import annotations

import json
import struct
from collections import Counter
from typing import Any

from db import get_db, load_vec_extension
from prompts import list_prompts
from utils import normalize_date, timestamp

EMBED_DIM = 768
RRF_K = 60
FTS_LIMIT = 20
VEC_LIMIT = 20

_ENTRY_COLUMNS = {"entry", "mood", "highlight", "sentiment", "sentiment_label",
                  "mood_alignment", "created_at", "updated_at", "saved_at"}


def _row_to_entry(row) -> dict[str, Any]:
    d = dict(row)
    meta = json.loads(d.pop("metadata", "{}") or "{}")
    d.pop("id", None)
    d.pop("date", None)
    return {**d, **meta}


def _entry_to_row_params(date: str, entry: dict[str, Any]) -> tuple:
    metadata = {k: v for k, v in entry.items() if k not in _ENTRY_COLUMNS}
    return (
        date,
        entry.get("entry", ""),
        entry.get("mood"),
        entry.get("highlight"),
        entry.get("sentiment"),
        entry.get("sentiment_label"),
        entry.get("mood_alignment"),
        json.dumps(metadata),
        entry.get("created_at"),
        entry.get("updated_at"),
        entry.get("saved_at"),
    )


def load_entries() -> dict[str, Any]:
    db = get_db()
    rows = db.execute("SELECT * FROM entries ORDER BY date").fetchall()
    return {row["date"]: _row_to_entry(row) for row in rows}


def load_entry_store() -> dict[str, list[dict[str, Any]]]:
    # SQLite stores one aggregated entry per date; wrap in list for API compatibility
    db = get_db()
    rows = db.execute("SELECT * FROM entries ORDER BY date").fetchall()
    return {row["date"]: [_row_to_entry(row)] for row in rows}


def save_entries(entries: dict[str, Any]) -> None:
    db = get_db()
    for date, entry in entries.items():
        normalized = normalize_entry_payload(entry)
        params = _entry_to_row_params(date, normalized)
        db.execute(
            """INSERT INTO entries (date,entry,mood,highlight,sentiment,sentiment_label,
               mood_alignment,metadata,created_at,updated_at,saved_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(date) DO UPDATE SET
                 entry=excluded.entry, mood=excluded.mood, highlight=excluded.highlight,
                 sentiment=excluded.sentiment, sentiment_label=excluded.sentiment_label,
                 mood_alignment=excluded.mood_alignment, metadata=excluded.metadata,
                 updated_at=excluded.updated_at, saved_at=excluded.saved_at""",
            params,
        )
    db.commit()


def save_entry_store(entries: dict[str, list[dict[str, Any]]]) -> None:
    # Aggregate multiple entries per day then upsert
    aggregated = {date: aggregate_day_entries(items) for date, items in entries.items()}
    save_entries(aggregated)


def get_entry(entry_date: str | None = None) -> tuple[str, dict[str, Any] | None]:
    key = normalize_date(entry_date)
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE date=?", (key,)).fetchone()
    if not row:
        return key, None
    return key, _row_to_entry(row)


def get_entries_for_date(entry_date: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    key = normalize_date(entry_date)
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE date=?", (key,)).fetchone()
    if not row:
        return key, []
    return key, [_row_to_entry(row)]


def list_entry_dates(limit: int | None = None) -> list[str]:
    db = get_db()
    if limit is not None:
        rows = db.execute("SELECT date FROM entries ORDER BY date DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = db.execute("SELECT date FROM entries ORDER BY date DESC").fetchall()
    return [row["date"] for row in rows]


def get_entries_for_period(year: int, month: int | None = None) -> list[dict[str, Any]]:
    db = get_db()
    if month is not None:
        prefix = f"{year}-{month:02d}-"
        rows = db.execute(
            "SELECT * FROM entries WHERE date LIKE ? ORDER BY date",
            (prefix + "%",)
        ).fetchall()
    else:
        prefix = f"{year}-"
        rows = db.execute(
            "SELECT * FROM entries WHERE date LIKE ? ORDER BY date",
            (prefix + "%",)
        ).fetchall()
    return [{"date": row["date"], **_row_to_entry(row)} for row in rows]


def get_overview_data() -> dict:
    """Returns recent dates, last 3 months with entries, and all years with counts."""
    db = get_db()
    recent_rows = db.execute(
        "SELECT date FROM entries ORDER BY date DESC LIMIT 7"
    ).fetchall()
    recent = [row["date"] for row in recent_rows]

    month_rows = db.execute(
        """SELECT strftime('%Y', date) AS year, strftime('%m', date) AS month, COUNT(*) AS cnt
           FROM entries
           GROUP BY year, month
           ORDER BY year DESC, month DESC
           LIMIT 3"""
    ).fetchall()
    months = [(int(r["year"]), int(r["month"]), r["cnt"]) for r in month_rows]

    year_rows = db.execute(
        """SELECT strftime('%Y', date) AS year, COUNT(*) AS cnt
           FROM entries
           GROUP BY year
           ORDER BY year DESC"""
    ).fetchall()
    years = [(int(r["year"]), r["cnt"]) for r in year_rows]

    return {"recent": recent, "months": months, "years": years}


def get_entries_by_year_summary(year: int) -> dict[int, list[str]]:
    """Returns mapping of month_num -> [dates] for the given year."""
    db = get_db()
    rows = db.execute(
        "SELECT date FROM entries WHERE strftime('%Y', date) = ? ORDER BY date",
        (str(year),),
    ).fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        month_num = int(row["date"][5:7])
        result.setdefault(month_num, []).append(row["date"])
    return result


def get_entries_by_month_summary(year: int, month: int) -> dict[int, list[str]]:
    """Returns mapping of ISO week_num -> [dates] for the given year+month."""
    import datetime as _dt
    db = get_db()
    prefix = f"{year}-{month:02d}-"
    rows = db.execute(
        "SELECT date FROM entries WHERE date LIKE ? ORDER BY date",
        (prefix + "%",),
    ).fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        d = _dt.date.fromisoformat(row["date"])
        week_num = d.isocalendar()[1]
        result.setdefault(week_num, []).append(row["date"])
    return result


def upsert_entry(
    entry_date: str | None,
    free_text: str,
    mood: str,
    highlights: str,
    prompt_answers: dict[str, str],
    reflection: str = "",
    extracted_tasks: list[dict[str, Any]] | list[str] | None = None,
    tags: list[str] | None = None,
    goals: list[str] | None = None,
    sentiment: str = "",
    tomorrow_plan: list[str] | None = None,
    embedding_text: str = "",
    stress_triggers: list[dict[str, str]] | None = None,
    habits: list[str] | None = None,
    sentiment_label: str = "",
    mood_alignment: str = "",
    wins: list[str] | None = None,
    gratitude: list[str] | None = None,
    follow_up_questions: list[str] | None = None,
    advice: list[str] | None = None,
    entities: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    key = normalize_date(entry_date)
    current_timestamp = timestamp()

    payload = {
        "entry": str(free_text or ""),
        "mood": str(mood or ""),
        "highlight": str(highlights or ""),
        "prompts": {str(question): str(answer or "") for question, answer in prompt_answers.items()},
        "reflection": str(reflection or ""),
        "suggested_tasks": normalize_task_candidates(extracted_tasks),
        "task_candidates": normalize_task_candidates(extracted_tasks),
        "tags": normalize_string_list(tags),
        "goals": normalize_string_list(goals),
        "sentiment": str(sentiment or ""),
        "sentiment_label": str(sentiment_label or sentiment or ""),
        "mood_alignment": str(mood_alignment or ""),
        "tomorrow_plan": normalize_string_list(tomorrow_plan),
        "stress_triggers": normalize_stress_triggers(stress_triggers),
        "habits": normalize_string_list(habits),
        "wins": normalize_string_list(wins),
        "gratitude": normalize_string_list(gratitude),
        "follow_up_questions": normalize_string_list(follow_up_questions),
        "advice": normalize_string_list(advice),
        "entities": normalize_string_list(entities),
        "embedding_text": str(embedding_text or ""),
        "saved_at": current_timestamp,
        "updated_at": current_timestamp,
        "created_at": current_timestamp,
    }
    normalized = normalize_entry_payload(payload)
    db = get_db()

    # If an existing entry exists for this date, merge (aggregate) before saving
    existing_row = db.execute("SELECT * FROM entries WHERE date=?", (key,)).fetchone()
    if existing_row:
        existing = _row_to_entry(existing_row)
        merged = aggregate_day_entries([existing, normalized])
        merged["updated_at"] = current_timestamp
        merged["saved_at"] = current_timestamp
        final = normalize_entry_payload(merged)
    else:
        final = normalized

    params = _entry_to_row_params(key, final)
    db.execute(
        """INSERT INTO entries (date,entry,mood,highlight,sentiment,sentiment_label,
           mood_alignment,metadata,created_at,updated_at,saved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(date) DO UPDATE SET
             entry=excluded.entry, mood=excluded.mood, highlight=excluded.highlight,
             sentiment=excluded.sentiment, sentiment_label=excluded.sentiment_label,
             mood_alignment=excluded.mood_alignment, metadata=excluded.metadata,
             updated_at=excluded.updated_at, saved_at=excluded.saved_at""",
        params,
    )
    db.commit()

    try:
        from embeddings import embed_entry
        row = db.execute("SELECT id FROM entries WHERE date=?", (key,)).fetchone()
        if row:
            embed_entry(row["id"], final)
    except Exception:
        pass  # embedding is non-blocking; never fail a save because of it

    return key, final


def render_entry(entry_date: str, entry: dict[str, Any]) -> str:
    entry = normalize_entry_payload(entry)
    lines = [
        f"Date: {entry_date}",
        f"Mood: {entry.get('mood', '-')}",
        f"Highlight: {entry.get('highlight', '-')}",
        f"Saved at: {entry.get('saved_at', '-')}",
        "",
        "Entry:",
        entry.get("entry", ""),
    ]

    prompts = entry.get("prompts", {})
    if prompts:
        lines.extend(["", "Prompt answers:"])
        for question in list_prompts():
            answer = prompts.get(question)
            if answer:
                lines.append(f"- {question} {answer}")

    reflection = entry.get("reflection")
    if reflection:
        lines.extend(["", "Reflection:", reflection])

    tasks = normalize_task_candidates(entry.get("suggested_tasks") or [])
    if tasks:
        lines.extend(["", "Suggested tasks:"])
        lines.extend(f"- {render_task_candidate(task)}" for task in tasks)

    tags = entry.get("tags") or []
    if tags:
        lines.extend(["", f"Tags: {', '.join(tags)}"])

    goals = entry.get("goals") or []
    if goals:
        lines.extend(["", "Goals:"])
        lines.extend(f"- {goal}" for goal in goals)

    tomorrow_plan = entry.get("tomorrow_plan") or []
    if tomorrow_plan:
        lines.extend(["", "Tomorrow plan:"])
        lines.extend(f"- {item}" for item in tomorrow_plan)

    sentiment = entry.get("sentiment")
    if sentiment:
        lines.extend(["", f"Sentiment: {sentiment}"])

    mood_alignment = entry.get("mood_alignment")
    if mood_alignment:
        lines.extend(["", f"Mood alignment: {mood_alignment}"])

    wins = entry.get("wins") or []
    if wins:
        lines.extend(["", "Wins:"])
        lines.extend(f"- {item}" for item in wins)

    gratitude = entry.get("gratitude") or []
    if gratitude:
        lines.extend(["", "Gratitude:"])
        lines.extend(f"- {item}" for item in gratitude)

    habits = entry.get("habits") or []
    if habits:
        lines.extend(["", f"Habits: {', '.join(habits)}"])

    stress_triggers = entry.get("stress_triggers") or []
    if stress_triggers:
        lines.extend(["", "Stress triggers:"])
        for item in stress_triggers:
            trigger = item.get("trigger", "").strip() or "-"
            evidence = item.get("evidence", "").strip()
            lines.append(f"- {trigger}" + (f" ({evidence})" if evidence else ""))

    entities = entry.get("entities") or []
    if entities:
        lines.extend(["", f"Entities: {', '.join(entities)}"])

    questions = entry.get("follow_up_questions") or []
    if questions:
        lines.extend(["", "Follow-up questions:"])
        lines.extend(f"- {item}" for item in questions)

    advice = entry.get("advice") or []
    if advice:
        lines.extend(["", "Advice:"])
        lines.extend(f"- {item}" for item in advice)

    return "\n".join(lines)


def render_entries_for_day(entry_date: str, entries: list[dict[str, Any]]) -> str:
    if not entries:
        return f"No entry found for {entry_date}."

    lines = [f"Date: {entry_date}", f"Entries: {len(entries)}"]
    for index, item in enumerate(entries, start=1):
        lines.extend(
            [
                "",
                f"Entry {index}",
                f"Saved at: {item.get('saved_at', '-')}",
                f"Mood: {item.get('mood', '-')}",
                f"Highlight: {item.get('highlight', '-')}",
                "",
                "Entry:",
                item.get("entry", ""),
            ]
        )

        reflection = item.get("reflection")
        if reflection:
            lines.extend(["", "Reflection:", reflection])

        tasks = normalize_task_candidates(item.get("suggested_tasks") or [])
        if tasks:
            lines.extend(["", "Suggested tasks:"])
            lines.extend(f"- {render_task_candidate(task)}" for task in tasks)

        goals = item.get("goals") or []
        if goals:
            lines.extend(["", "Goals:"])
            lines.extend(f"- {goal}" for goal in goals)

        tomorrow_plan = item.get("tomorrow_plan") or []
        if tomorrow_plan:
            lines.extend(["", "Tomorrow plan:"])
            lines.extend(f"- {plan}" for plan in tomorrow_plan)

    return "\n".join(lines)


def mood_trend(days: int = 7) -> list[tuple[str, str]]:
    db = get_db()
    rows = db.execute(
        "SELECT date, mood FROM entries ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    return [(row["date"], row["mood"] or "-") for row in reversed(rows)]


def get_recent_entries(limit: int = 7) -> list[tuple[str, dict[str, Any]]]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM entries ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    return [(row["date"], _row_to_entry(row)) for row in rows]


def get_entry_tags(entry_date: str | None = None) -> tuple[str, list[str]]:
    key, entry = get_entry(entry_date)
    if not entry:
        return key, []
    return key, [str(tag) for tag in entry.get("tags", []) if str(tag).strip()]


def aggregate_goals(days: int | None = None) -> list[dict[str, Any]]:
    entries = load_entries()
    dates = sorted(entries.keys())
    if days is not None:
        dates = dates[-days:]

    goals: dict[str, dict[str, Any]] = {}
    for entry_date in dates:
        item = entries[entry_date]
        for raw_goal in item.get("goals", []) or []:
            goal = str(raw_goal).strip()
            if not goal:
                continue
            record = goals.setdefault(
                goal,
                {
                    "goal": goal,
                    "first_mentioned": entry_date,
                    "last_mentioned": entry_date,
                    "mention_count": 0,
                    "moods": Counter(),
                },
            )
            record["first_mentioned"] = min(record["first_mentioned"], entry_date)
            record["last_mentioned"] = max(record["last_mentioned"], entry_date)
            record["mention_count"] += 1
            mood = str(item.get("mood", "")).strip()
            if mood:
                record["moods"][mood] += 1

    results = []
    for item in goals.values():
        results.append(
            {
                "goal": item["goal"],
                "first_mentioned": item["first_mentioned"],
                "last_mentioned": item["last_mentioned"],
                "mention_count": item["mention_count"],
                "moods": [mood for mood, _count in item["moods"].most_common(3)],
            }
        )

    return sorted(results, key=lambda item: (-item["mention_count"], item["goal"].lower()))


def find_similar_entries(target_date: str | None, limit: int = 3) -> tuple[str, list[dict[str, Any]]]:
    key, target = get_entry(target_date)
    if not target:
        return key, []

    entries = load_entries()
    target_features = _entry_feature_sets(target)

    matches = []
    for entry_date, item in entries.items():
        if entry_date == key:
            continue

        item_features = _entry_feature_sets(item)
        shared_tags = sorted(target_features["tags"] & item_features["tags"])
        shared_goals = sorted(target_features["goals"] & item_features["goals"])
        shared_entities = sorted(target_features["entities"] & item_features["entities"])
        shared_habits = sorted(target_features["habits"] & item_features["habits"])
        shared_stress = sorted(target_features["stress_triggers"] & item_features["stress_triggers"])
        shared_wins = sorted(target_features["wins"] & item_features["wins"])
        shared_words = sorted(target_features["keywords"] & item_features["keywords"])

        score = (
            (len(shared_tags) * 3)
            + (len(shared_goals) * 4)
            + (len(shared_entities) * 4)
            + (len(shared_habits) * 2)
            + (len(shared_stress) * 3)
            + (len(shared_wins) * 2)
            + min(len(shared_words), 5)
        )
        if target.get("sentiment_label") and target.get("sentiment_label") == item.get("sentiment_label"):
            score += 2
        if score <= 0:
            continue

        reasons = []
        if shared_tags:
            reasons.append(f"shared tags: {', '.join(shared_tags[:3])}")
        if shared_goals:
            reasons.append(f"shared goals: {', '.join(shared_goals[:3])}")
        if shared_entities:
            reasons.append(f"shared entities: {', '.join(shared_entities[:3])}")
        if shared_habits:
            reasons.append(f"shared habits: {', '.join(shared_habits[:3])}")
        if shared_stress:
            reasons.append(f"shared stress: {', '.join(shared_stress[:3])}")
        if target.get("sentiment_label") and target.get("sentiment_label") == item.get("sentiment_label"):
            reasons.append(f"same sentiment: {item.get('sentiment_label')}")
        if shared_words:
            reasons.append(f"keyword overlap: {', '.join(shared_words[:4])}")

        matches.append(
            {
                "date": entry_date,
                "score": score,
                "reasons": reasons,
                "highlight": item.get("highlight", ""),
                "excerpt": str(item.get("entry", "")).strip()[:160],
            }
        )

    matches.sort(key=lambda item: (-item["score"], item["date"]), reverse=False)
    return key, matches[:limit]


def resurface_entries(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """
    Hybrid FTS5 + vector search with Reciprocal Rank Fusion.
    Falls back to FTS5-only if embeddings are unavailable.
    """
    query = (query or "").strip()
    if not query:
        return []

    db = get_db()
    fts_results = _fts_search(db, query, limit=FTS_LIMIT)
    vec_results = _vec_search(db, query, limit=VEC_LIMIT)

    return _rrf_merge(fts_results, vec_results, limit=limit)


def _fts_escape(query: str) -> str:
    """Escape user query for safe FTS5 MATCH.
    Strips FTS5 special chars and returns a simple AND-of-terms query.
    Wraps each token in quotes to prevent FTS5 syntax errors.
    """
    # Remove FTS5 operator chars
    safe = query.replace('"', ' ').replace('*', ' ').replace('-', ' ')
    safe = safe.replace('(', ' ').replace(')', ' ').replace('^', ' ')
    tokens = safe.split()
    if not tokens:
        return ""
    # Wrap each token so FTS5 treats them as literals
    return " ".join(f'"{t}"' for t in tokens)


def _fts_search(db, query: str, limit: int) -> list[dict]:
    """FTS5 full-text search using SQLite built-in BM25 ranking."""
    escaped = _fts_escape(query)
    if not escaped:
        return []
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
            ORDER BY score
            LIMIT ?
        """, (escaped, limit)).fetchall()
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


def sentiment_trends(days: int = 30) -> dict[str, Any]:
    entries = get_recent_entries(limit=days)
    sentiment_counts = Counter()
    mood_alignment_counts = Counter()
    habit_counts = Counter()
    stress_counts = Counter()

    for _entry_date, item in entries:
        sentiment = str(item.get("sentiment_label") or item.get("sentiment") or "").strip().lower()
        if sentiment:
            sentiment_counts[sentiment] += 1

        alignment = str(item.get("mood_alignment") or "").strip().lower()
        if alignment:
            mood_alignment_counts[alignment] += 1

        for habit in normalize_string_list(item.get("habits", [])):
            habit_counts[habit] += 1

        for stress in normalize_stress_triggers(item.get("stress_triggers", [])):
            trigger = stress.get("trigger", "").strip().lower()
            if trigger:
                stress_counts[trigger] += 1

    return {
        "days": days,
        "entry_count": len(entries),
        "sentiments": dict(sentiment_counts.most_common()),
        "mood_alignment": dict(mood_alignment_counts.most_common()),
        "top_habits": [{"habit": habit, "count": count} for habit, count in habit_counts.most_common(5)],
        "top_stress_triggers": [{"trigger": trigger, "count": count} for trigger, count in stress_counts.most_common(5)],
    }


def detect_contradictions(days: int = 30) -> list[dict[str, Any]]:
    entries = get_recent_entries(limit=days)
    goal_mentions: dict[str, list[dict[str, Any]]] = {}
    for entry_date, item in entries:
        tasks = normalize_task_candidates(item.get("task_candidates", item.get("suggested_tasks", [])))
        task_text = " ".join(task.get("task", "") for task in tasks).lower()
        tomorrow_text = " ".join(normalize_string_list(item.get("tomorrow_plan", []))).lower()
        entry_text = str(item.get("entry", "")).lower()

        for goal in normalize_string_list(item.get("goals", [])):
            record = {
                "date": entry_date,
                "has_task": goal.lower() in task_text,
                "has_follow_through": goal.lower() in tomorrow_text or goal.lower() in entry_text,
            }
            goal_mentions.setdefault(goal, []).append(record)

    contradictions = []
    for goal, mentions in goal_mentions.items():
        if len(mentions) < 2:
            continue

        task_count = sum(1 for item in mentions if item["has_task"])
        follow_through_count = sum(1 for item in mentions if item["has_follow_through"])
        if task_count > 0 and follow_through_count > 0:
            continue

        contradictions.append(
            {
                "goal": goal,
                "mention_count": len(mentions),
                "task_count": task_count,
                "follow_through_count": follow_through_count,
                "dates": [item["date"] for item in mentions],
            }
        )

    contradictions.sort(key=lambda item: (-item["mention_count"], item["goal"].lower()))
    return contradictions


def normalize_entry_payload(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}

    tasks = normalize_task_candidates(entry.get("task_candidates", entry.get("suggested_tasks", [])))
    sentiment = str(entry.get("sentiment_label") or entry.get("sentiment") or "").strip().lower()

    return {
        "entry": str(entry.get("entry", "")),
        "mood": str(entry.get("mood", "")),
        "highlight": str(entry.get("highlight", "")),
        "prompts": _normalize_prompt_answers(entry.get("prompts", {})),
        "reflection": str(entry.get("reflection", "")),
        "suggested_tasks": tasks,
        "task_candidates": tasks,
        "tags": normalize_string_list(entry.get("tags", [])),
        "goals": normalize_string_list(entry.get("goals", [])),
        "sentiment": sentiment,
        "sentiment_label": sentiment,
        "mood_alignment": str(entry.get("mood_alignment", "")).strip().lower(),
        "tomorrow_plan": normalize_string_list(entry.get("tomorrow_plan", [])),
        "stress_triggers": normalize_stress_triggers(entry.get("stress_triggers", [])),
        "habits": normalize_string_list(entry.get("habits", [])),
        "wins": normalize_string_list(entry.get("wins", [])),
        "gratitude": normalize_string_list(entry.get("gratitude", [])),
        "follow_up_questions": normalize_string_list(entry.get("follow_up_questions", [])),
        "advice": normalize_string_list(entry.get("advice", [])),
        "entities": normalize_string_list(entry.get("entities", [])),
        "embedding_text": str(entry.get("embedding_text", "")),
        "saved_at": str(entry.get("saved_at", entry.get("created_at", ""))),
        "updated_at": str(entry.get("updated_at", "")),
        "created_at": str(entry.get("created_at", "")),
    }


def normalize_entry_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [normalize_entry_payload(item) for item in value]
    if isinstance(value, dict):
        return [normalize_entry_payload(value)]
    return []


def aggregate_day_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_entries = normalize_entry_list(entries)
    if not normalized_entries:
        return normalize_entry_payload({})

    tasks = []
    stress_triggers = []
    for item in normalized_entries:
        tasks.extend(normalize_task_candidates(item.get("task_candidates", item.get("suggested_tasks", []))))
        stress_triggers.extend(normalize_stress_triggers(item.get("stress_triggers", [])))

    moods = [item.get("mood", "").strip() for item in normalized_entries if item.get("mood", "").strip()]
    highlights = [item.get("highlight", "").strip() for item in normalized_entries if item.get("highlight", "").strip()]
    reflections = [item.get("reflection", "").strip() for item in normalized_entries if item.get("reflection", "").strip()]
    entries_text = []
    for index, item in enumerate(normalized_entries, start=1):
        text = item.get("entry", "").strip()
        if text:
            entries_text.append(f"[Entry {index} at {item.get('saved_at', '-')}] {text}")

    combined = {
        "entry": "\n\n".join(entries_text),
        "mood": " | ".join(dict.fromkeys(moods)),
        "highlight": " | ".join(dict.fromkeys(highlights)),
        "prompts": {},
        "reflection": "\n\n".join(reflections),
        "suggested_tasks": tasks,
        "task_candidates": tasks,
        "tags": normalize_string_list([tag for item in normalized_entries for tag in item.get("tags", [])]),
        "goals": normalize_string_list([goal for item in normalized_entries for goal in item.get("goals", [])]),
        "sentiment": _last_non_empty(normalized_entries, "sentiment"),
        "sentiment_label": _last_non_empty(normalized_entries, "sentiment_label"),
        "mood_alignment": _last_non_empty(normalized_entries, "mood_alignment"),
        "tomorrow_plan": normalize_string_list([plan for item in normalized_entries for plan in item.get("tomorrow_plan", [])]),
        "stress_triggers": stress_triggers,
        "habits": normalize_string_list([habit for item in normalized_entries for habit in item.get("habits", [])]),
        "wins": normalize_string_list([win for item in normalized_entries for win in item.get("wins", [])]),
        "gratitude": normalize_string_list([item for entry in normalized_entries for item in entry.get("gratitude", [])]),
        "follow_up_questions": normalize_string_list([item for entry in normalized_entries for item in entry.get("follow_up_questions", [])]),
        "advice": normalize_string_list([item for entry in normalized_entries for item in entry.get("advice", [])]),
        "entities": normalize_string_list([item for entry in normalized_entries for item in entry.get("entities", [])]),
        "embedding_text": "",
        "saved_at": normalized_entries[0].get("saved_at", ""),
        "updated_at": normalized_entries[-1].get("updated_at", ""),
        "created_at": normalized_entries[0].get("created_at", ""),
    }
    return normalize_entry_payload(combined)


def _last_non_empty(entries: list[dict[str, Any]], key: str) -> str:
    for item in reversed(entries):
        value = str(item.get(key, "")).strip()
        if value:
            return value
    return ""


def normalize_task_candidates(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    items = []
    seen = set()
    for raw in value:
        if isinstance(raw, str):
            task_text = raw.strip()
            if not task_text:
                continue
            candidate = {
                "task": task_text,
                "deadline": "",
                "priority": "",
                "follow_up": "",
                "source_excerpt": "",
            }
        elif isinstance(raw, dict):
            candidate = {
                "task": str(raw.get("task", "")).strip(),
                "deadline": str(raw.get("deadline", "")).strip(),
                "priority": str(raw.get("priority", "")).strip().lower(),
                "follow_up": str(raw.get("follow_up", "")).strip(),
                "source_excerpt": str(raw.get("source_excerpt", "")).strip(),
            }
            if candidate["priority"] not in {"low", "medium", "high"}:
                candidate["priority"] = ""
        else:
            continue

        if not candidate["task"]:
            continue

        dedupe_key = (
            candidate["task"].lower(),
            candidate["deadline"].lower(),
            candidate["follow_up"].lower(),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(candidate)

    return items


def normalize_string_list(value: Any, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []

    items = []
    seen = set()
    for raw in value:
        cleaned = " ".join(str(raw).strip().split())
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        items.append(cleaned)
        if limit is not None and len(items) >= limit:
            break
    return items


def normalize_stress_triggers(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    items = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        trigger = " ".join(str(raw.get("trigger", "")).strip().split())
        evidence = " ".join(str(raw.get("evidence", "")).strip().split())
        if not trigger:
            continue
        lowered = trigger.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        items.append({"trigger": trigger, "evidence": evidence})
    return items


def render_task_candidate(task: dict[str, Any]) -> str:
    parts = [task.get("task", "").strip()]
    if task.get("priority"):
        parts.append(f"priority={task['priority']}")
    if task.get("deadline"):
        parts.append(f"deadline={task['deadline']}")
    if task.get("follow_up"):
        parts.append(f"follow_up={task['follow_up']}")
    return " | ".join(part for part in parts if part)


def _normalize_prompt_answers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(question): str(answer or "") for question, answer in value.items()}


def _entry_feature_sets(entry: dict[str, Any]) -> dict[str, set[str]]:
    normalized = normalize_entry_payload(entry)
    return {
        "tags": {item.lower() for item in normalized.get("tags", [])},
        "goals": {item.lower() for item in normalized.get("goals", [])},
        "entities": {item.lower() for item in normalized.get("entities", [])},
        "habits": {item.lower() for item in normalized.get("habits", [])},
        "wins": {item.lower() for item in normalized.get("wins", [])},
        "gratitude": {item.lower() for item in normalized.get("gratitude", [])},
        "stress_triggers": {item.get("trigger", "").lower() for item in normalized.get("stress_triggers", []) if item.get("trigger", "")},
        "keywords": _entry_keywords(
            " ".join(
                [
                    normalized.get("entry", ""),
                    normalized.get("highlight", ""),
                    " ".join(normalized.get("goals", [])),
                    " ".join(normalized.get("wins", [])),
                    " ".join(normalized.get("entities", [])),
                ]
            )
        ),
    }


def _entry_keywords(text: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "had",
        "have",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "today",
        "was",
        "with",
    }
    words = []
    for raw in str(text).lower().split():
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if len(cleaned) >= 3 and cleaned not in stopwords:
            words.append(cleaned)
    return set(words)
