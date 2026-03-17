from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib import error, request


OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "llama3.1:8b"

_TIMING_LOG = Path(__file__).resolve().parent / "data" / "llm_timing.jsonl"


class AIError(RuntimeError):
    pass


def _log_timing(model: str, call_type: str, prompt_chars: int, elapsed_s: float, response_chars: int) -> None:
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "call_type": call_type,
        "prompt_chars": prompt_chars,
        "response_chars": response_chars,
        "elapsed_s": round(elapsed_s, 3),
    }
    try:
        with _TIMING_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


STARTER_TAGS = [
    "work",
    "school",
    "research",
    "career",
    "health",
    "relationships",
    "finance",
    "stress",
    "productivity",
    "gratitude",
]

HABIT_LABELS = [
    "sleep",
    "exercise",
    "study",
    "socializing",
    "screen_time",
    "eating",
    "planning",
    "procrastination",
]


def _generate(prompt: str, model: str = DEFAULT_MODEL, temperature: float = 0.2, call_type: str = "unknown") -> str:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
    ).encode("utf-8")

    req = request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        t0 = time.perf_counter()
        with request.urlopen(req, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
            result = body.get("response", "").strip()
        elapsed = time.perf_counter() - t0
        _log_timing(model, call_type, len(prompt), elapsed, len(result))
        return result
    except error.URLError as exc:
        raise AIError(
            "Could not reach Ollama at http://127.0.0.1:11434. Start it with `ollama serve`."
        ) from exc


def generate_reflection(entry_text: str, mood: str, highlight: str, model: str = DEFAULT_MODEL) -> str:
    prompt = f"""
You are writing a personal reflection for the person's diary — in their own voice, not as an outside observer.

Rules:
- Write entirely in first person ("I", "me", "my"). Never use "you" or "they".
- Mirror the writer's tone and energy exactly. If they sound exhausted, write tired. If sarcastic, be sarcastic. If upbeat, be upbeat. If venting, let it breathe.
- Reference specific details from the entry — real events, names, places, feelings they mentioned. Do not be vague or generic.
- Length should match the entry: short entry → 1-2 sentences. Long entry → 3-5 sentences. Never pad or over-explain.
- Sound like a real person talking to themselves, not a therapist or motivational poster.
- No bullet points. No headers. Just natural, conversational prose.

Mood: {mood}
Highlight: {highlight}
Diary entry:
{entry_text}
""".strip()
    return _generate(prompt, model=model, temperature=0.5, call_type="reflection")


# Known fact types the LLM should look for
FACT_TYPES = [
    "name", "birthday", "age", "location", "hometown",
    "job", "company", "school", "partner", "siblings",
    "pets", "nationality", "languages",
]


def extract_facts(entry_text: str, entry_date: str, model: str = DEFAULT_MODEL) -> list[dict[str, str]]:
    """
    Extract durable personal facts from a diary entry.
    Returns list of {"fact_type": ..., "value": ..., "source_excerpt": ...}
    """
    prompt = f"""
Extract personal facts about the diary author from the entry below.
Return strict JSON only using this schema:
[
  {{
    "fact_type": "birthday",
    "value": "April 12 1998",
    "source_excerpt": "today is my birthday, I turn 26"
  }}
]

Known fact types to look for: {", ".join(FACT_TYPES)}
You may also infer other stable personal facts not in this list.

Rules:
- Only include facts the writer is clearly stating about themselves.
- Normalize dates to YYYY-MM-DD if possible, otherwise keep natural language.
- Do not include temporary states (e.g. "feeling tired") — only durable facts.
- Return [] if no clear personal facts are present.
- Do not include markdown or commentary.

Today's date: {entry_date}
Diary entry:
{entry_text}
""".strip()
    raw = _generate(prompt, model=model, temperature=0.0, call_type="fact_extraction")
    parsed = _parse_json(raw)
    if not isinstance(parsed, list):
        return []
    return _clean_fact_candidates(parsed)


def _clean_fact_candidates(value: list) -> list[dict[str, str]]:
    items = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        fact_type = str(raw.get("fact_type", "")).strip().lower().replace(" ", "_")
        val = str(raw.get("value", "")).strip()
        excerpt = str(raw.get("source_excerpt", "")).strip()
        if not fact_type or not val:
            continue
        if fact_type in seen:
            continue
        seen.add(fact_type)
        items.append({"fact_type": fact_type, "value": val, "source_excerpt": excerpt})
    return items


def extract_tasks(entry_text: str, model: str = DEFAULT_MODEL) -> list[dict[str, str]]:
    prompt = f"""
Extract actionable tasks from the diary entry.
Return strict JSON only using this schema:
[
  {{
    "task": "short task",
    "deadline": "YYYY-MM-DD or empty string",
    "priority": "low|medium|high or empty string",
    "follow_up": "next step or empty string",
    "source_excerpt": "supporting excerpt"
  }}
]

Rules:
- Only include tasks that the writer could realistically act on.
- Return [] if there are no clear tasks.
- Keep at most 5 tasks.
- Do not include markdown or commentary.

Diary entry:
{entry_text}
""".strip()
    raw = _generate(prompt, model=model, temperature=0.1, call_type="task_extraction")
    parsed = _parse_json(raw)
    return _clean_task_candidates(parsed)


def analyze_entry(
    entry_text: str,
    mood: str,
    highlight: str,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    metadata_prompt = f"""
Analyze the diary entry and return strict JSON only.

Use exactly this schema:
{{
  "tags": ["..."],
  "goals": ["..."],
  "tomorrow_plan": ["..."],
  "sentiment_label": "positive|mixed|negative|neutral",
  "mood_alignment": "aligned|slightly_mismatched|mismatched|unclear",
  "stress_triggers": [
    {{
      "trigger": "short phrase",
      "evidence": "supporting excerpt"
    }}
  ],
  "habits": ["..."],
  "wins": ["..."],
  "gratitude": ["..."],
  "entities": ["..."]
}}

Rules:
- "tags" must come only from: {", ".join(STARTER_TAGS)}
- "habits" must come only from: {", ".join(HABIT_LABELS)}
- Return up to 4 tags, 4 goals, 3 tomorrow_plan items, 3 stress_triggers, 4 habits, 3 wins, 3 gratitude items, and 6 entities.
- Goals should be short normalized phrases.
- Tomorrow plan items must be concrete actions explicitly supported by the entry.
- Only include tomorrow_plan items if the writer clearly mentioned a next step, intention, deadline, or tomorrow-facing plan.
- Do not infer social, entertainment, or routine activities unless the writer explicitly said they plan to do them next.
- If there is no clear next-day plan, return an empty list for "tomorrow_plan".
- Entities should be people, organizations, projects, places, or topics that matter later.
- If something is missing, return an empty list or the safest enum value.
- Do not include markdown or explanation.

Mood: {mood}
Highlight: {highlight}
Diary entry:
{entry_text}
""".strip()

    coaching_prompt = f"""
Read the diary entry and return strict JSON only using this schema:
{{
  "follow_up_questions": ["..."],
  "advice": ["..."]
}}

Rules:
- Generate 2 to 3 short follow-up questions.
- Generate 1 to 3 practical advice bullets.
- Avoid therapy language and avoid overclaiming.
- Keep each item concise.
- Do not include markdown or explanation.

Mood: {mood}
Highlight: {highlight}
Diary entry:
{entry_text}
""".strip()

    metadata = _clean_metadata_analysis(_parse_json(_generate(metadata_prompt, model=model, temperature=0.1, call_type="analyze_metadata")))
    coaching = _clean_coaching_analysis(_parse_json(_generate(coaching_prompt, model=model, temperature=0.2, call_type="analyze_coaching")))

    metadata["follow_up_questions"] = coaching["follow_up_questions"]
    metadata["advice"] = coaching["advice"]
    metadata["sentiment"] = metadata["sentiment_label"]
    return metadata


def answer_from_entries(question: str, entries: dict[str, Any], model: str = DEFAULT_MODEL) -> str:
    if not entries:
        return "No diary entries found yet."

    context_lines = []
    for entry_date in sorted(entries.keys(), reverse=True)[:14]:
        item = entries[entry_date]
        context_lines.append(
            "\n".join(
                [
                    f"Date: {entry_date}",
                    f"Mood: {item.get('mood', '-')}",
                    f"Highlight: {item.get('highlight', '-')}",
                    f"Tags: {', '.join(item.get('tags', []) or []) or '-'}",
                    f"Goals: {', '.join(item.get('goals', []) or []) or '-'}",
                    f"Entities: {', '.join(item.get('entities', []) or []) or '-'}",
                    f"Entry: {item.get('entry', '')}",
                ]
            )
        )
    context = "\n\n".join(context_lines)

    prompt = f"""
Answer the question using only the diary context below.
If the answer is unclear, say so explicitly.
Be concise and specific.

Question: {question}

Diary context:
{context}
""".strip()
    return _generate(prompt, model=model, temperature=0.2, call_type="answer_from_entries")


def generate_insight(entries: dict[str, Any], model: str = DEFAULT_MODEL) -> str:
    if not entries:
        return "No diary entries found yet."

    context_lines = []
    for entry_date in sorted(entries.keys(), reverse=True)[:7]:
        item = entries[entry_date]
        context_lines.append(
            f"{entry_date}: mood={item.get('mood', '-')}; sentiment={item.get('sentiment_label', item.get('sentiment', '-'))}; goals={', '.join(item.get('goals', []) or []) or '-'}; entry={item.get('entry', '')}"
        )
    context = "\n".join(context_lines)

    prompt = f"""
You are a diary insights assistant.
Based on the last 7 diary entries, write one short practical insight.
Keep it to 2 sentences max and avoid overclaiming.

Entries:
{context}
""".strip()
    return _generate(prompt, model=model, temperature=0.3, call_type="insight")


def generate_weekly_summary(entries: list[tuple[str, dict[str, Any]]], model: str = DEFAULT_MODEL) -> str:
    if not entries:
        return "No diary entries found yet."

    context_lines = []
    for entry_date, item in entries[:7]:
        context_lines.append(
            "\n".join(
                [
                    f"Date: {entry_date}",
                    f"Mood: {item.get('mood', '-')}",
                    f"Sentiment: {item.get('sentiment_label', item.get('sentiment', '-'))}",
                    f"Highlight: {item.get('highlight', '-')}",
                    f"Tags: {', '.join(item.get('tags', []) or []) or '-'}",
                    f"Goals: {', '.join(item.get('goals', []) or []) or '-'}",
                    f"Wins: {', '.join(item.get('wins', []) or []) or '-'}",
                    f"Stress: {', '.join(trigger.get('trigger', '') for trigger in item.get('stress_triggers', []) or []) or '-'}",
                    f"Entry: {item.get('entry', '')}",
                ]
            )
        )
    context = "\n\n".join(context_lines)

    prompt = f"""
Summarize the last 7 days of diary entries.
Use exactly these sections:
Main themes:
Wins:
Challenges:
What to focus on next week:

Each section should be concise and practical.

Diary context:
{context}
""".strip()
    return _generate(prompt, model=model, temperature=0.3, call_type="weekly_summary")


def generate_digest(
    entries: list[tuple[str, dict[str, Any]]],
    facts: dict[str, Any],
    contradictions: list[dict[str, Any]],
    trends: dict[str, Any],
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Generate a proactive personal digest that surfaces patterns,
    deferred goals, and mood signals the user may not have noticed.
    """
    if not entries:
        return "Not enough diary entries for a digest yet."

    facts_block = ""
    if facts:
        lines = [f"- {k}: {v['value']}" for k, v in sorted(facts.items())]
        facts_block = "Known about the user:\n" + "\n".join(lines)

    entries_block = _render_recent_context(entries, limit=14)

    contradictions_block = ""
    if contradictions:
        items = [f"- {c['goal']} (mentioned {c['mention_count']} times, no follow-through)" for c in contradictions[:5]]
        contradictions_block = "Deferred goals (mentioned repeatedly but never acted on):\n" + "\n".join(items)

    trends_block = ""
    if trends.get("top_stress_triggers"):
        triggers = [f"- {t['trigger']} ({t['count']}x)" for t in trends["top_stress_triggers"][:3]]
        trends_block = "Top stress triggers:\n" + "\n".join(triggers)

    prompt = f"""
You are a personal assistant reviewing this person's diary.
Write a short, honest, practical digest. Speak directly to them in second person.
Use exactly these sections:

What's been on your mind:
Patterns I'm noticing:
Goals you keep mentioning but haven't acted on:
Something to try this week:

Keep each section to 1-3 bullet points. Be specific, reference real things from their entries.
Do not be a therapist. Do not overclaim.

{facts_block}

{entries_block}

{contradictions_block}

{trends_block}
""".strip()
    return _generate(prompt, model=model, temperature=0.35, call_type="digest")


def rewrite_entry(entry_text: str, mode: str, model: str = DEFAULT_MODEL) -> str:
    if mode not in {"clean", "bullets"}:
        raise ValueError(f"Unsupported rewrite mode: {mode}")

    style_instruction = (
        "Rewrite the diary entry into clean, readable prose while preserving meaning."
        if mode == "clean"
        else "Rewrite the diary entry into concise bullet points."
    )
    prompt = f"""
{style_instruction}
Do not invent details.

Diary entry:
{entry_text}
""".strip()
    return _generate(prompt, model=model, temperature=0.2, call_type="rewrite")


def generate_coaching(
    entry: dict[str, Any],
    recent_entries: list[tuple[str, dict[str, Any]]],
    model: str = DEFAULT_MODEL,
) -> str:
    context = _render_recent_context(recent_entries, limit=5)
    prompt = f"""
You are a practical journaling coach.
Use the current entry and recent context to give concise guidance.
Use exactly these sections:
What stands out:
What to do next:
Question to carry forward:

Current entry:
{_render_single_entry("current", entry)}

Recent context:
{context}
""".strip()
    return _generate(prompt, model=model, temperature=0.3, call_type="coaching")


def generate_plan_next(
    entry: dict[str, Any],
    recent_entries: list[tuple[str, dict[str, Any]]],
    model: str = DEFAULT_MODEL,
) -> str:
    context = _render_recent_context(recent_entries, limit=5)
    prompt = f"""
Create a realistic plan for the next day based on the diary entry and recent context.
Use exactly these sections:
Top priorities:
Risks to manage:
Small wins to aim for:

Keep it concrete and concise.

Current entry:
{_render_single_entry("current", entry)}

Recent context:
{context}
""".strip()
    return _generate(prompt, model=model, temperature=0.25, call_type="plan_next")


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
    facts_block = ""
    if facts:
        lines = [f"- {k}: {v['value']}" for k, v in sorted(facts.items())]
        facts_block = "Known personal facts:\n" + "\n".join(lines)

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


def answer_with_context(
    question: str,
    current_entry: tuple[str, dict[str, Any]] | None,
    recent_entries: list[tuple[str, dict[str, Any]]],
    retrieved_entries: list[tuple[str, dict[str, Any]]],
    facts: dict[str, Any] | None = None,
    model: str = DEFAULT_MODEL,
) -> str:
    sections = []
    if facts:
        lines = [f"- {k}: {v['value']}" for k, v in sorted(facts.items())]
        sections.append("Known personal facts:\n" + "\n".join(lines))
    if current_entry:
        entry_date, entry = current_entry
        sections.append(f"Current entry:\n{_render_single_entry(entry_date, entry)}")
    if recent_entries:
        sections.append(f"Recent entries:\n{_render_recent_context(recent_entries, limit=5)}")
    if retrieved_entries:
        sections.append(f"Relevant past entries:\n{_render_recent_context(retrieved_entries, limit=4)}")

    prompt = f"""
Answer the user's diary question using the provided context only.
If the context is insufficient, say that clearly.
Be concise, specific, and reflective without sounding clinical.

Question: {question}

{chr(10).join(sections)}
""".strip()
    return _generate(prompt, model=model, temperature=0.25, call_type="chat")


def _clean_metadata_analysis(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _empty_analysis()

    sentiment_label = str(value.get("sentiment_label", "neutral")).strip().lower()
    if sentiment_label not in {"positive", "mixed", "negative", "neutral"}:
        sentiment_label = "neutral"

    mood_alignment = str(value.get("mood_alignment", "unclear")).strip().lower()
    if mood_alignment not in {"aligned", "slightly_mismatched", "mismatched", "unclear"}:
        mood_alignment = "unclear"

    return {
        "tags": _clean_string_list(value.get("tags"), allowed_values=set(STARTER_TAGS), limit=4),
        "goals": _clean_string_list(value.get("goals"), limit=4),
        "tomorrow_plan": _clean_string_list(value.get("tomorrow_plan"), limit=3),
        "sentiment_label": sentiment_label,
        "mood_alignment": mood_alignment,
        "stress_triggers": _clean_stress_triggers(value.get("stress_triggers")),
        "habits": _clean_string_list(value.get("habits"), allowed_values=set(HABIT_LABELS), limit=4),
        "wins": _clean_string_list(value.get("wins"), limit=3),
        "gratitude": _clean_string_list(value.get("gratitude"), limit=3),
        "entities": _clean_string_list(value.get("entities"), limit=6),
    }


def _clean_coaching_analysis(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"follow_up_questions": [], "advice": []}

    return {
        "follow_up_questions": _clean_string_list(value.get("follow_up_questions"), limit=3),
        "advice": _clean_string_list(value.get("advice"), limit=3),
    }


def _clean_task_candidates(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    items = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue

        task = str(raw.get("task", "")).strip()
        if not task:
            continue

        deadline = str(raw.get("deadline", "")).strip()
        priority = str(raw.get("priority", "")).strip().lower()
        if priority not in {"low", "medium", "high"}:
            priority = ""
        follow_up = str(raw.get("follow_up", "")).strip()
        source_excerpt = str(raw.get("source_excerpt", "")).strip()

        dedupe_key = (task.lower(), deadline.lower(), follow_up.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        items.append(
            {
                "task": task,
                "deadline": deadline,
                "priority": priority,
                "follow_up": follow_up,
                "source_excerpt": source_excerpt,
            }
        )

        if len(items) >= 5:
            break

    return items


def _clean_stress_triggers(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    items = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        trigger = str(raw.get("trigger", "")).strip()
        evidence = str(raw.get("evidence", "")).strip()
        if not trigger:
            continue
        lowered = trigger.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        items.append({"trigger": trigger, "evidence": evidence})
        if len(items) >= 3:
            break
    return items


def _clean_string_list(
    value: Any,
    *,
    allowed_values: set[str] | None = None,
    limit: int | None = None,
) -> list[str]:
    if not isinstance(value, list):
        return []

    items = []
    seen = set()
    for raw in value:
        cleaned = " ".join(str(raw).strip().split())
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if allowed_values is not None and lowered not in allowed_values:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        items.append(lowered if allowed_values is not None else cleaned)
        if limit is not None and len(items) >= limit:
            break
    return items


def _parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _empty_analysis() -> dict[str, Any]:
    return {
        "tags": [],
        "goals": [],
        "tomorrow_plan": [],
        "sentiment_label": "neutral",
        "mood_alignment": "unclear",
        "stress_triggers": [],
        "habits": [],
        "wins": [],
        "gratitude": [],
        "entities": [],
    }


def _render_single_entry(entry_date: str, item: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Date: {entry_date}",
            f"Mood: {item.get('mood', '-')}",
            f"Highlight: {item.get('highlight', '-')}",
            f"Sentiment: {item.get('sentiment_label', item.get('sentiment', '-'))}",
            f"Goals: {', '.join(item.get('goals', []) or []) or '-'}",
            f"Entities: {', '.join(item.get('entities', []) or []) or '-'}",
            f"Entry: {item.get('entry', '')}",
        ]
    )


def _render_recent_context(entries: list[tuple[str, dict[str, Any]]], limit: int) -> str:
    return "\n\n".join(_render_single_entry(entry_date, item) for entry_date, item in entries[:limit])
