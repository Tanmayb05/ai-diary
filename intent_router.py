from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass
class RoutedIntent:
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    follow_up: str = ""


# Intents the LLM can return and their expected params
_INTENT_SCHEMA = """
Return a JSON object with "intent" and "params" fields. Choose exactly one intent:

- "write"         — user wants to create/add a new diary entry
                    params: {{"date": "YYYY-MM-DD or null"}}
- "read"          — user wants to read a single specific date
                    params: {{"date": "YYYY-MM-DD or null"}}
- "read_range"    — user wants entries for a whole month or year (no specific day)
                    params: {{"year": <int>, "month": <int or null>, "limit": <int or null>}}
                    (limit = max number of entries to show; null means show all)
- "todo_list"     — user wants to see their todo/task list
                    params: {{}}
- "todo_add"      — user wants to add a task
                    params: {{"task": "<task text>"}}
- "todo_done"     — user wants to mark a task complete
                    params: {{"id": <int or null>}}
- "todo_delete"   — user wants to delete a task
                    params: {{"id": <int or null>}}
- "help"          — user wants help or a list of commands
                    params: {{}}
- "show_facts"    — user wants to see stored personal facts (e.g. "show facts", "list my facts", "what do you know about me")
                    params: {{}}
- "ask"           — user is asking a question about themselves or their diary (e.g. "when is my birthday", "what mood was I in last week", "do I exercise")
                    params: {{"question": "<the question text>"}}
- "journal_candidate" — message reads like personal diary content: expressing feelings, describing what happened in their day, venting, reflecting, or sharing a personal experience or emotion. Use this when the user types something that sounds like they're journaling even if they didn't explicitly say "write" or "journal".
                    params: {{"entry_text": "<the full message text>"}}
- "list_entries"  — user wants to see a list of entry dates/titles (e.g. "show my entries", "list entries", "what entries do I have", "show entry titles", "list all my diary entries")
                    params: {{"limit": <int or null>}}
- "summarize"     — user wants a summary of a time period
                    params: {{"year": <int>, "month": <int or null>, "label": "<human readable label like 'March 2026' or '2026'>"}}
                    Examples: "show summary for 2026", "summarize march 2026", "how was my year", "what happened in january", "give me a recap of last month"
- "show_characters" — user wants to see all known characters (e.g. "show characters", "who do I know", "list people")
                    params: {{}}
- "show_character"  — user wants details about one specific person (e.g. "tell me about Alice", "who is mom", "what do I know about Rahul")
                    params: {{"name": "<person name>"}}
- "add_character_fact" — user wants to add or update a fact about a named person (e.g. "add fact about Alice", "Alice is now at Google", "update Alice", "edit Rahul")
                    params: {{"name": "<person name>", "raw_text": "<the full statement>"}}
- "unknown"       — none of the above
                    params: {{}}

Rules:
- For dates, resolve relative words using today's date: {today}
- "yesterday" → {yesterday}
- "last month" → year={last_month_year}, month={last_month_month}
- "this month" → year={today_year}, month={today_month}
- "last year" → year={last_year}, month=null
- "this year" → year={today_year}, month=null
- Natural date formats like "Jan 29 2026", "January 29 2026", "29 Jan 2026" must be converted to YYYY-MM-DD
- "show entries in the month of feb 2026" → read_range year=2026 month=2
- "show entries in 2023" → read_range year=2023 month=null
- For read_range, month is null if only a year is mentioned
- For read, date is null if no date is mentioned (defaults to today)
- For write, date is null if no date is mentioned (defaults to today)
- If a message expresses personal feelings, describes daily events, or sounds like journaling, prefer "journal_candidate" over "unknown".
- Return only the JSON object. No markdown, no explanation.
"""


def route_message(message: str, model: str = "llama3.1:8b") -> RoutedIntent:
    text = " ".join(message.strip().lower().split())
    if not text:
        return RoutedIntent("empty")

    # Fast-path: trivial exact matches that don't need LLM
    if text in {"exit", "quit", "bye"}:
        return RoutedIntent("exit")
    if text in {"help", "?", "commands", "what can you do"}:
        return RoutedIntent("help")
    if re.match(r"^(?:show|list|display|view)\s+(?:my\s+)?facts?$", text):
        return RoutedIntent("show_facts")
    if re.match(r"^(?:show|list|display|view)\s+(?:my\s+|all\s+)?(?:diary\s+)?entries?(?:\s+titles?)?$", text):
        return RoutedIntent("list_entries", {"limit": None})
    if re.match(r"^(?:show|list|display|view)\s+(?:all\s+)?(?:characters?|people|persons?)$", text):
        return RoutedIntent("show_characters")
    if re.match(r"^who\s+do\s+i\s+know$", text):
        return RoutedIntent("show_characters")
    m = re.match(r"^(?:tell\s+me\s+about|who\s+is|what\s+do\s+i\s+know\s+about)\s+(.+)$", text)
    if m:
        return RoutedIntent("show_character", {"name": m.group(1).strip().title()})
    m = re.match(r"^(?:add\s+fact\s+about|update|edit)\s+([a-z][a-z\s]*)$", text)
    if m:
        return RoutedIntent("add_character_fact", {"name": m.group(1).strip().title(), "raw_text": ""})

    # Fast-path: "summary/summarize for <period>"
    _sum = _try_parse_summarize(text)
    if _sum is not None:
        return _sum

    # Fast-path: relative date ranges (last month, last year, yesterday)
    _rel = _try_parse_relative_range(text)
    if _rel is not None:
        return _rel

    # Fast-path: "show entries in the month of feb 2026" / "show entries in 2023"
    _range = _try_parse_read_range(text)
    if _range is not None:
        return _range

    # Fast-path: "read/show <natural date>" with a specific day
    _read = _try_parse_read_date(text)
    if _read is not None:
        return _read

    # Fast-path: "write/journal for <natural date>"
    _write = _try_parse_write_date(text)
    if _write is not None:
        return _write

    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    first_of_this = today.replace(day=1)
    last_month_date = first_of_this - timedelta(days=1)
    schema = _INTENT_SCHEMA.format(
        today=today.isoformat(),
        yesterday=yesterday,
        last_month_year=last_month_date.year,
        last_month_month=last_month_date.month,
        today_year=today.year,
        today_month=today.month,
        last_year=today.year - 1,
    )

    prompt = f"{schema}\n\nUser message: {message.strip()}"

    try:
        from ai import _generate
        raw = _generate(prompt, model=model, temperature=0.0, call_type="intent_routing")
        parsed = _parse_json(raw)
        if parsed and isinstance(parsed, dict):
            intent = _build_intent(parsed, message)
            if intent.name != "unknown":
                return intent
    except Exception:
        pass

    # If message looks like a browse/read/show attempt but we couldn't parse it,
    # ask for clarification rather than falling through to chitchat
    _BROWSE_KEYWORDS = r"\b(?:show|list|display|view|read|entries|entry|diary)\b"
    if re.search(_BROWSE_KEYWORDS, text):
        return RoutedIntent(
            "clarify",
            {"original": message.strip()},
            "I didn't quite get that. Could you rephrase? For example:\n"
            "  'show entries for March 2026'\n"
            "  'show entries in 2023'\n"
            "  'read Jan 29 2026'\n"
            "  'show last month's entries'",
        )

    return RoutedIntent("unknown", {"text": message.strip()})


def _parse_natural_date(text: str) -> str | None:
    """Parse natural date strings like 'Jan 29 2026', '29 January 2026' into YYYY-MM-DD."""
    month_pattern = "|".join(_MONTH_NAMES)
    # "Jan 29 2026" or "January 29 2026"
    m = re.search(rf"\b({month_pattern})\s+(\d{{1,2}})[,\s]+(\d{{4}})\b", text)
    if m:
        month = _MONTH_NAMES[m.group(1)]
        day = int(m.group(2))
        year = int(m.group(3))
        return f"{year}-{month:02d}-{day:02d}"
    # "29 Jan 2026" or "29 January 2026"
    m = re.search(rf"\b(\d{{1,2}})\s+({month_pattern})[,\s]+(\d{{4}})\b", text)
    if m:
        day = int(m.group(1))
        month = _MONTH_NAMES[m.group(2)]
        year = int(m.group(3))
        return f"{year}-{month:02d}-{day:02d}"
    return None


def _try_parse_write_date(text: str) -> RoutedIntent | None:
    """Fast-path for 'write/journal for <natural date>' patterns."""
    if not re.search(r"\b(?:write|journal|entry|log)\b", text):
        return None
    date_str = _parse_natural_date(text)
    if date_str:
        return RoutedIntent("write", {"date": date_str})
    return None


def _try_parse_read_date(text: str) -> RoutedIntent | None:
    """Fast-path for 'read/show <natural date>' patterns with a specific day."""
    if not re.search(r"\b(?:read|show|display|view)\b", text):
        return None
    date_str = _parse_natural_date(text)
    if date_str:
        return RoutedIntent("read", {"date": date_str})
    return None


def _try_parse_summarize(text: str) -> RoutedIntent | None:
    """Fast-path for 'summary/summarize for <period>' patterns."""
    month_pattern = "|".join(_MONTH_NAMES)
    # "summary for 2026" or "summarize 2026" or "recap of 2026"
    m = re.match(r"^(?:show\s+)?(?:summary|summarize|recap|overview)\s+(?:for\s+|of\s+)?(\d{4})$", text)
    if m:
        year = int(m.group(1))
        return RoutedIntent("summarize", {"year": year, "month": None, "label": str(year)})
    # "summary for march 2026" or "summarize march 2026"
    m = re.match(
        rf"^(?:show\s+)?(?:summary|summarize|recap|overview)\s+(?:for\s+|of\s+)?({month_pattern})\s+(\d{{4}})$",
        text,
    )
    if m:
        month = _MONTH_NAMES[m.group(1)]
        year = int(m.group(2))
        import calendar as _cal
        label = f"{_cal.month_name[month]} {year}"
        return RoutedIntent("summarize", {"year": year, "month": month, "label": label})
    return None


def _try_parse_relative_range(text: str) -> RoutedIntent | None:
    """Fast-path for relative date references: yesterday, last month, last year."""
    today = date.today()

    # "yesterday's entries" / "show yesterday" / "yesterday entry"
    if re.search(r"\byesterday\b", text):
        yesterday = (today - timedelta(days=1)).isoformat()
        return RoutedIntent("read", {"date": yesterday})

    # "last month's entries" / "show last month" / "entries from last month"
    if re.search(r"\blast\s+month\b", text):
        first_of_this = today.replace(day=1)
        last_month = first_of_this - timedelta(days=1)
        return RoutedIntent("read_range", {"year": last_month.year, "month": last_month.month})

    # "last year's entries" / "show last year"
    if re.search(r"\blast\s+year\b", text):
        return RoutedIntent("read_range", {"year": today.year - 1, "month": None})

    # "this month" / "this month's entries"
    if re.search(r"\bthis\s+month\b", text):
        return RoutedIntent("read_range", {"year": today.year, "month": today.month})

    # "this year" / "this year's entries"
    if re.search(r"\bthis\s+year\b", text):
        return RoutedIntent("read_range", {"year": today.year, "month": None})

    return None


def _try_parse_read_range(text: str) -> RoutedIntent | None:
    """Fast-path regex for month/year range patterns in many phrasings."""
    month_pattern = "|".join(_MONTH_NAMES)

    # "show entries in the month of feb 2026" / "entries in march 2026" / "show march 2026 entries"
    # The standalone "in|for" branch requires "the month of" to avoid matching question phrasing
    # like "i celebrated whose birthday in march 2026"
    m = re.search(
        rf"(?:entries?\s+(?:in|for|of|from)\s+(?:the\s+month\s+of\s+)?|(?:in|for)\s+the\s+month\s+of\s+)({month_pattern})\s+(\d{{4}})",
        text,
    )
    if m:
        month = _MONTH_NAMES[m.group(1)]
        year = int(m.group(2))
        return RoutedIntent("read_range", {"year": year, "month": month})

    # "show entries in the year 2023" / "entries in 2023" / "show 2023 entries"
    m = re.search(
        r"(?:entries?\s+(?:in|for|of|from)\s+(?:the\s+year\s+)?|(?:in|for)\s+the\s+year\s+)(\d{4})\b",
        text,
    )
    if m:
        return RoutedIntent("read_range", {"year": int(m.group(1)), "month": None})

    # "read june 2026" or "read 2026 june" or "show june 2026"
    m = re.match(
        rf"^(?:read|show|display|view)\s+(?:({month_pattern})\s+(\d{{4}})|(\d{{4}})\s+({month_pattern}))$",
        text,
    )
    if m:
        if m.group(1):
            month = _MONTH_NAMES[m.group(1)]
            year = int(m.group(2))
        else:
            year = int(m.group(3))
            month = _MONTH_NAMES[m.group(4)]
        return RoutedIntent("read_range", {"year": year, "month": month})

    # "read 2026" / "show 2026" — year only
    m = re.match(r"^(?:read|show|display|view)\s+(\d{4})$", text)
    if m:
        return RoutedIntent("read_range", {"year": int(m.group(1)), "month": None})

    return None


def _build_intent(parsed: dict, original_message: str) -> RoutedIntent:
    intent = str(parsed.get("intent", "unknown")).strip().lower()
    params = parsed.get("params", {})
    if not isinstance(params, dict):
        params = {}

    if intent == "write":
        return RoutedIntent("write", {"date": _str_or_none(params.get("date"))})

    if intent == "read":
        return RoutedIntent("read", {"date": _str_or_none(params.get("date"))})

    if intent == "read_range":
        year = _int_or_none(params.get("year"))
        month = _int_or_none(params.get("month"))
        limit = _int_or_none(params.get("limit"))
        if year:
            return RoutedIntent("read_range", {"year": year, "month": month, "limit": limit})
        return RoutedIntent("unknown", {"text": original_message})

    if intent == "todo_list":
        return RoutedIntent("todo_list")

    if intent == "todo_add":
        return RoutedIntent("todo_add", {"task": str(params.get("task", "")).strip()})

    if intent == "todo_done":
        return RoutedIntent("todo_done", {"id": _int_or_none(params.get("id"))})

    if intent == "todo_delete":
        return RoutedIntent("todo_delete", {"id": _int_or_none(params.get("id"))})

    if intent == "help":
        return RoutedIntent("help")

    if intent == "show_facts":
        return RoutedIntent("show_facts")

    if intent == "list_entries":
        limit = _int_or_none(params.get("limit"))
        return RoutedIntent("list_entries", {"limit": limit})

    if intent == "ask":
        question = str(params.get("question", "")).strip() or original_message.strip()
        return RoutedIntent("ask", {"question": question})

    if intent == "journal_candidate":
        entry_text = str(params.get("entry_text", "")).strip() or original_message.strip()
        return RoutedIntent(
            "confirm_journal_candidate",
            {"entry_text": entry_text},
            "That sounds like a diary entry. Would you like me to save this to your journal? (yes / no)",
        )

    if intent == "summarize":
        year = _int_or_none(params.get("year"))
        month = _int_or_none(params.get("month"))
        label = str(params.get("label", "")).strip() or (str(year) if year else "")
        if year:
            return RoutedIntent("summarize", {"year": year, "month": month, "label": label})
        return RoutedIntent("unknown", {"text": original_message})

    if intent == "show_characters":
        return RoutedIntent("show_characters")

    if intent == "show_character":
        name = str(params.get("name", "")).strip()
        if name:
            return RoutedIntent("show_character", {"name": name})
        return RoutedIntent("unknown", {"text": original_message})

    if intent == "add_character_fact":
        name = str(params.get("name", "")).strip()
        raw_text = str(params.get("raw_text", "")).strip() or original_message.strip()
        if name:
            return RoutedIntent("add_character_fact", {"name": name, "raw_text": raw_text})
        return RoutedIntent("unknown", {"text": original_message})

    return RoutedIntent("unknown", {"text": original_message.strip()})


def _parse_json(raw: str) -> Any:
    # Strip markdown fences if present
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try extracting first {...} block
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _str_or_none(value: Any) -> str | None:
    if not value or str(value).strip().lower() in {"null", "none", ""}:
        return None
    return str(value).strip()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
