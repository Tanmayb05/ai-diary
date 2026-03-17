from __future__ import annotations

from collections import Counter
from typing import Any

from prompts import list_prompts
from utils import ENTRIES_PATH, load_json, normalize_date, save_json, timestamp


def load_entries() -> dict[str, Any]:
    entries = load_entry_store()
    return {str(entry_date): aggregate_day_entries(items) for entry_date, items in entries.items()}


def load_entry_store() -> dict[str, list[dict[str, Any]]]:
    entries = load_json(ENTRIES_PATH, {})
    if not isinstance(entries, dict):
        return {}
    return {str(entry_date): normalize_entry_list(item) for entry_date, item in entries.items()}


def save_entries(entries: dict[str, Any]) -> None:
    save_entry_store({key: [normalize_entry_payload(value)] for key, value in entries.items()})


def save_entry_store(entries: dict[str, list[dict[str, Any]]]) -> None:
    save_json(ENTRIES_PATH, {key: normalize_entry_list(value) for key, value in entries.items()})


def get_entry(entry_date: str | None = None) -> tuple[str, dict[str, Any] | None]:
    key = normalize_date(entry_date)
    entries = load_entries()
    return key, entries.get(key)


def get_entries_for_date(entry_date: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    key = normalize_date(entry_date)
    entries = load_entry_store()
    return key, entries.get(key, [])


def list_entry_dates(limit: int | None = None) -> list[str]:
    entries = load_entry_store()
    dates = sorted(entries.keys(), reverse=True)
    if limit is not None:
        return dates[:limit]
    return dates


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
    entries = load_entry_store()
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
    entries.setdefault(key, []).append(normalize_entry_payload(payload))
    save_entry_store(entries)
    return key, entries[key][-1]


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
    entries = load_entries()
    dates = sorted(entries.keys(), reverse=True)[:days]
    return [(day, entries[day].get("mood", "-")) for day in reversed(dates)]


def get_recent_entries(limit: int = 7) -> list[tuple[str, dict[str, Any]]]:
    entries = load_entries()
    dates = sorted(entries.keys(), reverse=True)[:limit]
    return [(entry_date, entries[entry_date]) for entry_date in dates]


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
                reasons.append(f"matched {field_name[:-1] if field_name.endswith('s') else field_name}")

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
        if len(cleaned) >= 4 and cleaned not in stopwords:
            words.append(cleaned)
    return set(words)
