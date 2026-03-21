---
phase: quick-001
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - diary.py
  - chat_session.py
  - handlers.py
autonomous: true
requirements: [BROWSE-01]

must_haves:
  truths:
    - "User types 'list my entries' and sees a numbered overview with recent dates, months, and years"
    - "User types a number to drill into a year, month, or week"
    - "User types 'back' to go up a level; at overview level 'back' exits browse mode"
    - "User types a number on a week view to read that specific entry"
    - "A single-entry week opens the entry directly without showing the week view"
  artifacts:
    - path: "diary.py"
      provides: "get_overview_data, get_entries_by_year_summary, get_entries_by_month_summary"
    - path: "chat_session.py"
      provides: "BrowseState dataclass, browse_state field on ChatSessionState, _handle_browse_input method"
    - path: "handlers.py"
      provides: "list_entries returns tuple, browse_year, browse_month, browse_week methods"
  key_links:
    - from: "chat_session.py ChatSession.run()"
      to: "_handle_browse_input"
      via: "check self.state.browse_state is not None before routing"
    - from: "_handle_browse_input"
      to: "handlers.browse_year / browse_month / browse_week"
      via: "option type dispatch"
    - from: "handlers.list_entries"
      to: "diary.get_overview_data"
      via: "direct call, returns (str, BrowseState)"
---

<objective>
Add a stateful hierarchical entry browser triggered by "list my entries". Users navigate
overview -> year -> month -> week -> entry using numbered selections and "back".

Purpose: Replace the flat list_entries with an interactive multi-level browser that scales
gracefully to large diaries.
Output: Three modified files — query helpers in diary.py, state management in chat_session.py,
rendering + browse methods in handlers.py.
</objective>

<execution_context>
@/Users/tanmaybhuskute/.claude/get-shit-done/workflows/execute-plan.md
@/Users/tanmaybhuskute/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@/Users/tanmaybhuskute/Documents/ai-diary/diary.py
@/Users/tanmaybhuskute/Documents/ai-diary/chat_session.py
@/Users/tanmaybhuskute/Documents/ai-diary/handlers.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add query helpers to diary.py</name>
  <files>diary.py</files>
  <action>
Add three functions after the existing `list_entry_dates` function (around line 108):

```python
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
```
  </action>
  <verify>
Run: `python -c "from diary import get_overview_data, get_entries_by_year_summary, get_entries_by_month_summary; print(get_overview_data())"` from /Users/tanmaybhuskute/Documents/ai-diary — should print a dict with keys "recent", "months", "years" without errors.
  </verify>
  <done>All three functions importable and callable; get_overview_data() returns {"recent": [...], "months": [...], "years": [...]}.</done>
</task>

<task type="auto">
  <name>Task 2: Add BrowseState and input handling to chat_session.py</name>
  <files>chat_session.py</files>
  <action>
Make the following targeted changes to chat_session.py:

1. Add `BrowseState` dataclass after the existing imports (before `ChatSessionState`):

```python
@dataclass
class BrowseState:
    level: str          # "overview" | "year" | "month" | "week"
    context: dict       # e.g. {"year": 2026} or {"year": 2026, "month": 3}
    options: list       # list of option dicts with keys: type, label, + type-specific params
    history: list       # stack of previous BrowseStates for "back"
```

2. Add `browse_state: "BrowseState | None" = None` field to `ChatSessionState`.

3. In `ChatSession.run()`, add a browse_state check BEFORE the `pending_intent` check:

```python
if self.state.browse_state is not None:
    response = self._handle_browse_input(message)
    if response:
        print(response)
    continue
```

Insert this block right after `message = input("\n> ").strip()` and before the `if self.state.pending_intent is not None:` block.

4. Replace the existing `list_entries` dispatch in `_dispatch` (currently: `return self.handlers.list_entries(limit=routed.params.get("limit"))`) with:

```python
if routed.name == "list_entries":
    text, browse_state = self.handlers.list_entries()
    self.state.browse_state = browse_state
    return text
```

5. Add the `_handle_browse_input` method to `ChatSession` (after `_resolve_pending`):

```python
def _handle_browse_input(self, message: str) -> str:
    bs = self.state.browse_state
    if bs is None:
        return ""

    text = message.strip().lower()

    if text in {"back", "b"}:
        if bs.history:
            self.state.browse_state = bs.history[-1]
        else:
            self.state.browse_state = None
            return "Exited browse."
        return self._render_current_browse()

    if text.isdigit():
        idx = int(text) - 1
        if idx < 0 or idx >= len(bs.options):
            return "Invalid selection. Type a number or 'back'."
        opt = bs.options[idx]
        opt_type = opt["type"]

        if opt_type == "entry":
            payload = self.handlers.read_entry(date_value=opt["date"])
            self.state.browse_state = None
            return payload.get("message", "")

        prev = BrowseState(
            level=bs.level,
            context=bs.context,
            options=bs.options,
            history=bs.history,
        )

        if opt_type == "year":
            new_text, new_bs = self.handlers.browse_year(opt["year"])
            new_bs.history = [prev] + new_bs.history
            self.state.browse_state = new_bs
            return new_text

        if opt_type == "month":
            new_text, new_bs = self.handlers.browse_month(opt["year"], opt["month"])
            new_bs.history = [prev] + new_bs.history
            self.state.browse_state = new_bs
            return new_text

        if opt_type == "week":
            dates = opt["dates"]
            if len(dates) == 1:
                payload = self.handlers.read_entry(date_value=dates[0])
                self.state.browse_state = None
                return payload.get("message", "")
            new_text, new_bs = self.handlers.browse_week(
                opt["year"], opt["month"], opt["week_num"], dates
            )
            new_bs.history = [prev] + new_bs.history
            self.state.browse_state = new_bs
            return new_text

    return "Invalid selection. Type a number or 'back'."

def _render_current_browse(self) -> str:
    """Re-render the current browse state after going back."""
    bs = self.state.browse_state
    if bs is None:
        return ""
    if bs.level == "overview":
        # Re-render using stored options labels
        lines = []
        for i, opt in enumerate(bs.options, 1):
            lines.append(f"{i:>3}. {opt['label']}")
        lines.append("\nType a number to open, or 'back' to exit.")
        return "\n".join(lines)
    # For year/month/week, re-render similarly
    lines = []
    for i, opt in enumerate(bs.options, 1):
        lines.append(f"{i:>3}. {opt['label']}")
    prompt = "Type a number to open, or 'back' to go up."
    if bs.level == "week":
        prompt = "Type a number to read the entry, or 'back' to go up."
    lines.append(f"\n{prompt}")
    return "\n".join(lines)
```

Also add `from __future__ import annotations` import guard at top if not already present (it is — line 1). The `BrowseState` type is defined in the same file so no import is needed in chat_session.py itself.
  </action>
  <verify>
Run: `python -c "from chat_session import BrowseState, ChatSessionState; s = ChatSessionState(); print(s.browse_state)"` — should print `None`.
  </verify>
  <done>BrowseState dataclass exists; ChatSessionState has browse_state field; ChatSession.run() routes to _handle_browse_input when browse_state is set; list_entries dispatch updated to unpack tuple.</done>
</task>

<task type="auto">
  <name>Task 3: Add rendering + browse methods to handlers.py</name>
  <files>handlers.py</files>
  <action>
Make the following changes to handlers.py:

1. Update the import from diary at line 7 to add the three new query functions:

```python
from diary import (
    get_entries_for_date, get_entries_by_month_summary, get_entries_by_year_summary,
    get_overview_data, list_entry_dates, load_entries, load_entry_store,
    render_entries_for_day, render_task_candidate, upsert_entry,
)
```

2. Add `import calendar` near the top (after existing stdlib imports).

3. Add `from chat_session import BrowseState` import. Add it after the existing imports block. NOTE: This creates a circular import risk since chat_session imports handlers. To avoid this, use a TYPE_CHECKING guard and string annotation, OR define BrowseState in a separate small module. The simplest safe approach: copy the BrowseState definition into handlers.py as well (duplicate dataclass), or use `from __future__ import annotations` and a local inline dict instead of importing.

   BEST APPROACH: Do NOT import BrowseState into handlers.py. Instead, have handlers.py return plain dicts that chat_session wraps into BrowseState. However, the task description requires handlers to return BrowseState instances.

   ACTUAL SAFE APPROACH: Move BrowseState to a new file `browse_state.py` so both handlers.py and chat_session.py can import from it without circular dependency:

   Create `browse_state.py`:
   ```python
   from __future__ import annotations
   from dataclasses import dataclass, field

   @dataclass
   class BrowseState:
       level: str    # "overview" | "year" | "month" | "week"
       context: dict
       options: list
       history: list = field(default_factory=list)
   ```

   Then in handlers.py: `from browse_state import BrowseState`
   And in chat_session.py: `from browse_state import BrowseState` (remove the local dataclass definition added in Task 2).

4. Replace the existing `list_entries` method with the new implementation and add the browse methods:

```python
def list_entries(self) -> tuple[str, "BrowseState"]:
    import datetime as _dt
    data = get_overview_data()
    total_rows = get_db_count()  # see note below — use inline query instead

    # Get total count inline
    from db import get_db
    total = get_db().execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    options = []
    lines = [f"Your diary  —  {total} entries", "", "Recent"]

    for d in data["recent"]:
        date_obj = _dt.date.fromisoformat(d)
        day_name = date_obj.strftime("%a")
        options.append({"type": "entry", "date": d, "label": f"{d}  {day_name}"})
        lines.append(f"{len(options):>3}. {d}  {day_name}")

    if data["months"]:
        lines.append("")
        lines.append("Months")
        for year, month, count in data["months"]:
            label = f"{calendar.month_name[month]} {year}"
            entry_word = "entry" if count == 1 else "entries"
            opt_label = f"{label:<18} {count} {entry_word}"
            options.append({"type": "month", "year": year, "month": month, "label": opt_label})
            lines.append(f"{len(options):>3}. {opt_label}")

    if data["years"]:
        lines.append("")
        lines.append("Years")
        for year, count in data["years"]:
            entry_word = "entry" if count == 1 else "entries"
            opt_label = f"{year}  {count} {entry_word}"
            options.append({"type": "year", "year": year, "label": opt_label})
            lines.append(f"{len(options):>3}. {opt_label}")

    lines.append("")
    lines.append("Type a number to open, or 'back' to exit.")
    text = "\n".join(lines)
    bs = BrowseState(level="overview", context={}, options=options, history=[])
    return text, bs


def browse_year(self, year: int) -> tuple[str, "BrowseState"]:
    month_map = get_entries_by_year_summary(year)
    total = sum(len(v) for v in month_map.values())
    lines = [f"{year}  —  {total} entries", ""]
    options = []
    for month_num in sorted(month_map.keys()):
        dates = month_map[month_num]
        count = len(dates)
        entry_word = "entry" if count == 1 else "entries"
        label = f"{calendar.month_name[month_num]:<12} {count} {entry_word}"
        options.append({"type": "month", "year": year, "month": month_num, "label": label})
        lines.append(f"{len(options):>3}. {label}")
    lines.append("")
    lines.append("Type a number to open, or 'back' to go up.")
    text = "\n".join(lines)
    return text, BrowseState(level="year", context={"year": year}, options=options, history=[])


def browse_month(self, year: int, month: int) -> tuple[str, "BrowseState"]:
    import datetime as _dt
    week_map = get_entries_by_month_summary(year, month)
    total = sum(len(v) for v in week_map.values())
    month_label = f"{calendar.month_name[month]} {year}"
    lines = [f"{month_label}  —  {total} entries", ""]
    options = []
    for week_num in sorted(week_map.keys()):
        dates = week_map[week_num]
        count = len(dates)
        first = _dt.date.fromisoformat(dates[0])
        last = _dt.date.fromisoformat(dates[-1])
        # Range label like "Mar 1–7"
        range_label = f"{first.strftime('%b %-d')}–{last.day}"
        entry_word = "entry" if count == 1 else "entries"
        label = f"Week {week_num - min(week_map.keys()) + 1}  {range_label:<12} {count} {entry_word}"
        options.append({
            "type": "week", "year": year, "month": month,
            "week_num": week_num, "dates": dates, "label": label,
        })
        lines.append(f"{len(options):>3}. {label}")
    lines.append("")
    lines.append("Type a number to open, or 'back' to go up.")
    text = "\n".join(lines)
    return text, BrowseState(level="month", context={"year": year, "month": month}, options=options, history=[])


def browse_week(self, year: int, month: int, week_num: int, dates: list[str]) -> tuple[str, "BrowseState"]:
    import datetime as _dt
    month_label = f"{calendar.month_name[month]} {year}"
    # Compute display week number within the month (1-based position among weeks)
    lines = [f"{month_label}, Week {week_num}  —  {len(dates)} entries", ""]
    options = []
    for d in dates:
        date_obj = _dt.date.fromisoformat(d)
        day_name = date_obj.strftime("%a")
        label = f"{d}  {day_name}"
        options.append({"type": "entry", "date": d, "label": label})
        lines.append(f"{len(options):>3}. {label}")
    lines.append("")
    lines.append("Type a number to read the entry, or 'back' to go up.")
    text = "\n".join(lines)
    return text, BrowseState(level="week", context={"year": year, "month": month, "week_num": week_num}, options=options, history=[])
```

NOTE on `strftime('%-d')`: This is Linux/macOS specific (no zero-padding). On Windows use `%#d`. Since this project runs on darwin (macOS), `%-d` is fine.
  </action>
  <verify>
Run: `python -c "from handlers import ChatHandlers; h = ChatHandlers(); text, bs = h.list_entries(); print(text[:200]); print('options:', len(bs.options))"` from /Users/tanmaybhuskute/Documents/ai-diary — should print the overview text and a count of options without errors.
  </verify>
  <done>list_entries() returns (str, BrowseState); browse_year/browse_month/browse_week exist and return correct tuples; full drill-down flow works end-to-end in the chat session.</done>
</task>

</tasks>

<verification>
After all three tasks:
1. `python -c "from diary import get_overview_data; print(get_overview_data())"` — no errors, returns dict with recent/months/years.
2. `python -c "from chat_session import ChatSessionState, BrowseState; s = ChatSessionState(); print(s.browse_state)"` — prints `None`.
3. `python -c "from handlers import ChatHandlers; h = ChatHandlers(); t, bs = h.list_entries(); print(bs.level)"` — prints `overview`.
4. Manual smoke test: run `python diary.py chat`, type "list my entries", verify numbered overview appears; type "1", verify entry opens or drill-down proceeds; type "back", verify navigation works.
</verification>

<success_criteria>
- "list my entries" triggers the numbered overview (recent, months, years sections)
- Typing a number drills into the selected year / month / week / entry
- "back" at any level goes up one level; "back" at overview exits with "Exited browse."
- Single-entry weeks open directly without showing the week list
- Out-of-range numbers return "Invalid selection. Type a number or 'back'."
- No circular import errors on startup
</success_criteria>

<output>
After completion, create `.planning/quick/001-hierarchical-entry-browser/001-SUMMARY.md`
</output>
