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
- "journal_candidate" — message looks like a diary entry the user accidentally typed
                    params: {{}}
- "unknown"       — none of the above
                    params: {{}}

Rules:
- For dates, resolve relative words using today's date: {today}
- "yesterday" → {yesterday}
- Natural date formats like "Jan 29 2026", "January 29 2026", "29 Jan 2026" must be converted to YYYY-MM-DD
- For read_range, month is null if only a year is mentioned (e.g. "show 2024 entries")
- For read, date is null if no date is mentioned (defaults to today)
- For write, date is null if no date is mentioned (defaults to today)
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

    # Fast-path: "read <month> <year>" or "read <year> <month>"
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
    schema = _INTENT_SCHEMA.format(today=today.isoformat(), yesterday=yesterday)

    prompt = f"{schema}\n\nUser message: {message.strip()}"

    try:
        from ai import _generate
        raw = _generate(prompt, model=model, temperature=0.0, call_type="intent_routing")
        parsed = _parse_json(raw)
        if parsed and isinstance(parsed, dict):
            return _build_intent(parsed, message)
    except Exception:
        pass

    # Fallback if LLM is unavailable or returns garbage
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


def _try_parse_read_range(text: str) -> RoutedIntent | None:
    """Fast-path regex for 'read <month> <year>' or 'read <year> <month>' patterns."""
    month_pattern = "|".join(_MONTH_NAMES)
    # "read june 2026" or "read 2026 june"
    m = re.match(
        rf"^(?:read|show|display|view)\s+(?:({month_pattern})\s+(\d{{4}})|(\d{{4}})\s+({month_pattern}))$",
        text,
    )
    if m:
        if m.group(1):  # month year
            month = _MONTH_NAMES[m.group(1)]
            year = int(m.group(2))
        else:  # year month
            year = int(m.group(3))
            month = _MONTH_NAMES[m.group(4)]
        return RoutedIntent("read_range", {"year": year, "month": month})
    # "read 2026" — year only
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

    if intent == "journal_candidate":
        return RoutedIntent(
            "confirm_journal_candidate",
            {"entry_text": original_message.strip()},
            "This sounds like a diary entry. Do you want me to journal this as today's entry, or did you want me to do something else?",
        )

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
