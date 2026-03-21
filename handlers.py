from __future__ import annotations

import argparse
import calendar
from typing import Any

from ai import DEFAULT_MODEL, AIError, analyze_entry, answer_with_facts, chitchat, extract_character_facts, extract_tasks, generate_period_summary, generate_reflection
from characters import add_incident, get_all_characters, get_character, load_characters, render_character_card, upsert_character
from utils import get_setting, set_setting, today_key
from browse_state import BrowseState
from diary import (
    get_entries_by_month_summary, get_entries_by_year_summary,
    get_entries_for_date, get_entries_for_period, get_overview_data, list_entry_dates, load_entries,
    load_entry_store, render_entries_for_day, render_task_candidate, upsert_entry,
)
from facts import load_facts, render_facts
from prompts import mood_choices
from todo import add_task, bulk_add_tasks, delete_task, list_tasks, mark_done, render_tasks


def _build_entries_digest(entries: list[dict[str, Any]], max_entries: int = 50) -> tuple[str, bool]:
    """Build a compact text digest of entries for LLM summarization.
    Returns (digest_text, was_truncated)."""
    truncated = len(entries) > max_entries
    subset = entries[:max_entries]
    parts = []
    for e in subset:
        lines = [f"Date: {e['date']}"]
        if e.get("mood"):
            lines.append(f"Mood: {e['mood']}")
        if e.get("highlight"):
            lines.append(f"Highlight: {e['highlight']}")
        tags = e.get("tags") or []
        if tags:
            lines.append(f"Tags: {', '.join(tags)}")
        if e.get("sentiment_label"):
            lines.append(f"Sentiment: {e['sentiment_label']}")
        entry_text = (e.get("entry") or "")[:300]
        if entry_text:
            lines.append(f"Entry: {entry_text}")
        wins = e.get("wins") or []
        if wins:
            lines.append(f"Wins: {', '.join(str(w) for w in wins)}")
        stress = e.get("stress_triggers") or []
        if stress:
            # stress_triggers may be strings or dicts
            stress_strs = []
            for s in stress:
                if isinstance(s, dict):
                    stress_strs.append(s.get("trigger", str(s)))
                else:
                    stress_strs.append(str(s))
            lines.append(f"Stress: {', '.join(stress_strs)}")
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts), truncated


def prompt_input(label: str, default: str = "") -> str:
    prompt = label
    if default:
        prompt += f" [{default}]"
    prompt += "\n> "
    value = input(prompt).strip()
    return value or default


class ChatHandlers:
    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model

    def help_text(self) -> str:
        return "\n".join(
            [
                "What I can do:",
                "",
                "Writing",
                "  i want to write",
                "  write an entry for yesterday",
                "",
                "Reading",
                "  read today's entry",
                "  read Jan 29 2026",
                "  show march 2026",
                "",
                "Browse entries",
                "  list my entries          (hierarchical browser)",
                "",
                "Summaries",
                "  show summary for 2026    (full year summary)",
                "  summarize march 2026     (month summary)",
                "  recap of 2024",
                "",
                "Todos",
                "  show my todos",
                "  add todo finish thesis draft",
                "  mark task 2 done",
                "  delete task 3",
                "",
                "Facts & questions",
                "  show facts",
                "  when is my birthday",
                "  what mood was I in last week",
                "",
                "Characters",
                "  show characters             (list all known people)",
                "  tell me about Alice         (full profile card)",
                "  who is mom",
                "  update Alice                (add/edit a fact interactively)",
                "  add fact about Rahul",
                "",
                "  exit",
            ]
        )

    def run_write_flow(self, initial_date: str | None = None, initial_entry_text: str = "") -> dict[str, Any]:
        entry_date, _existing_entries = get_entries_for_date(initial_date)
        mood_map = mood_choices()

        entry_default = initial_entry_text
        entry_text = prompt_input("How was your day?", entry_default)
        highlight = prompt_input("Highlight of the day", "")

        mood_default = "🙂 Good"
        print("Mood options:", ", ".join(mood_map.values()))
        mood = prompt_input("Mood", mood_default)

        reflection = ""
        extracted_tasks = []
        tags = []
        goals = []
        tomorrow_plan = []
        sentiment = ""
        stress_triggers = []
        habits = []
        mood_alignment = ""
        wins = []
        gratitude = []
        follow_up_questions = []
        advice = []
        entities = []

        try:
            reflection = generate_reflection(entry_text, mood, highlight, model=self.model)
            extracted_tasks = extract_tasks(entry_text, model=self.model)
            analysis = analyze_entry(entry_text, mood, highlight, model=self.model)
            tags = analysis["tags"]
            goals = analysis["goals"]
            tomorrow_plan = analysis["tomorrow_plan"]
            sentiment = analysis["sentiment_label"]
            stress_triggers = analysis["stress_triggers"]
            habits = analysis["habits"]
            mood_alignment = analysis["mood_alignment"]
            wins = analysis["wins"]
            gratitude = analysis["gratitude"]
            follow_up_questions = analysis["follow_up_questions"]
            advice = analysis["advice"]
            entities = analysis["entities"]
        except AIError as exc:
            print(f"AI unavailable: {exc}")

        saved_date, payload = upsert_entry(
            entry_date=entry_date,
            free_text=entry_text,
            mood=mood,
            highlights=highlight,
            prompt_answers={},
            reflection=reflection,
            extracted_tasks=extracted_tasks,
            tags=tags,
            goals=goals,
            sentiment=sentiment,
            tomorrow_plan=tomorrow_plan,
            stress_triggers=stress_triggers,
            habits=habits,
            sentiment_label=sentiment,
            mood_alignment=mood_alignment,
            wins=wins,
            gratitude=gratitude,
            follow_up_questions=follow_up_questions,
            advice=advice,
            entities=entities,
        )

        # Extract and store character facts from entry
        try:
            char_results = extract_character_facts(entry_text, saved_date, model=self.model)
            for char in char_results:
                char_name = char.get("name", "").strip()
                if not char_name:
                    continue
                upsert_character(char_name, char.get("facts") or {}, saved_date)
                for incident_text in char.get("incidents") or []:
                    add_incident(char_name, incident_text, saved_date)
        except AIError:
            pass

        lines = [f"Saved entry for {saved_date} at {payload.get('updated_at', payload.get('saved_at', ''))}."]
        if payload.get("reflection"):
            lines.extend(["", "AI reflection:", payload["reflection"]])

        tasks = payload.get("suggested_tasks") or []
        if tasks:
            lines.extend(["", "Suggested tasks:"])
            lines.extend(f"- {render_task_candidate(task)}" for task in tasks)
            add_now = prompt_input("Add these tasks to your todo list? (y/n)", "y").lower()
            if add_now == "y":
                added = bulk_add_tasks(tasks, source=f"entry:{saved_date}")
                lines.append(f"Added {len(added)} task(s).")

        return {"date": saved_date, "tasks": tasks, "message": "\n".join(lines)}

    def read_entry(self, date_value: str | None) -> dict[str, Any]:
        entry_date, entries = get_entries_for_date(date_value)
        if not entries:
            return {"date": entry_date, "message": f"No entry found for {entry_date}."}
        return {"date": entry_date, "message": render_entries_for_day(entry_date, entries)}

    def read_range(self, year: int, month: int | None = None, limit: int | None = None) -> dict[str, Any]:
        store = load_entry_store()

        if month is not None:
            prefix = f"{year}-{month:02d}-"
            label = f"{year}-{month:02d}"
        else:
            prefix = f"{year}-"
            label = str(year)

        matching_dates = sorted(k for k in store if k.startswith(prefix))

        if not matching_dates:
            return {"message": f"No entries found for {label}."}

        total_count = len(matching_dates)
        if limit is not None:
            matching_dates = matching_dates[:limit]

        if limit is not None and len(matching_dates) < total_count:
            count_label = f" (showing {len(matching_dates)} of {total_count} day(s))"
        else:
            count_label = f" ({total_count} day(s))"
        lines = [f"Entries for {label}{count_label}:\n"]
        for entry_date in matching_dates:
            entries = store[entry_date]
            lines.append(render_entries_for_day(entry_date, entries))
            lines.append("")

        return {"message": "\n".join(lines).strip()}

    def list_entries(self) -> tuple[str, BrowseState]:
        import datetime as _dt
        from db import get_db
        data = get_overview_data()
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

    def browse_year(self, year: int) -> tuple[str, BrowseState]:
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

    def browse_month(self, year: int, month: int) -> tuple[str, BrowseState]:
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

    def browse_week(self, year: int, month: int, week_num: int, dates: list[str]) -> tuple[str, BrowseState]:
        import datetime as _dt
        month_label = f"{calendar.month_name[month]} {year}"
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

    def todo_list(self) -> dict[str, Any]:
        tasks = list_tasks(include_completed=True)
        return {"tasks": tasks, "message": render_tasks(tasks)}

    def todo_add(self, task_text: str) -> str:
        cleaned = str(task_text or "").strip()
        if not cleaned:
            return "No task provided."
        task = add_task(cleaned)
        return f"Added task {task['id']}: {task['task']}"

    def todo_done(self, task_id: int | None) -> str:
        if task_id is None:
            return "Task id is required."
        task = mark_done(task_id)
        if not task:
            return f"Task {task_id} not found."
        return f"Completed task {task['id']}: {task['task']}"

    def todo_delete(self, task_id: int | None) -> str:
        if task_id is None:
            return "Task id is required."
        task = delete_task(task_id)
        if not task:
            return f"Task {task_id} not found."
        return f"Deleted task {task['id']}: {task['task']}"

    def show_facts(self) -> str:
        return render_facts(load_facts())

    def summarize_period(self, year: int, month: int | None = None, label: str | None = None) -> str:
        import calendar as _cal
        if label is None:
            label = _cal.month_name[month] + f" {year}" if month else str(year)

        entries = get_entries_for_period(year, month)
        if not entries:
            return f"No entries found for {label}."

        digest, truncated = _build_entries_digest(entries)
        trunc_note = f" (showing first 50 of {len(entries)})" if truncated else ""
        date_range = f"{entries[0]['date']} to {entries[-1]['date']}"

        try:
            summary = generate_period_summary(
                entries_digest=digest,
                label=label,
                entry_count=len(entries),
                date_range=date_range + trunc_note,
                model=self.model,
            )
            return summary
        except AIError as exc:
            # Fallback: stats-only summary
            moods = [e.get("mood") for e in entries if e.get("mood")]
            all_tags: list[str] = []
            for e in entries:
                all_tags.extend(e.get("tags") or [])
            from collections import Counter
            top_tags = [t for t, _ in Counter(all_tags).most_common(5)]
            lines = [
                f"{label} Summary",
                f"",
                f"Entries: {len(entries)} ({date_range})",
                f"AI unavailable: {exc}",
            ]
            if top_tags:
                lines.append(f"Top tags: {', '.join(top_tags)}")
            return "\n".join(lines)

    def ask(self, question: str) -> str:
        try:
            return answer_with_facts(
                question,
                load_facts(),
                load_entries(),
                characters=load_characters(),
                model=self.model,
            )
        except AIError as exc:
            return f"AI unavailable: {exc}"

    def show_characters(self) -> str:
        chars = get_all_characters()
        if not chars:
            return "No characters saved yet."
        lines = [f"{c['name']} — {c.get('relationship') or 'unknown relationship'}" for c in chars]
        return "\n".join(lines)

    def show_character(self, name: str) -> str:
        name = name.strip().title()
        char = get_character(name)
        if not char:
            return f"No character found named '{name}'."
        return render_character_card(char)

    def add_character_fact_interactive(self, name: str, raw_text: str) -> str:
        name = name.strip().title()
        mode = get_setting("character_manual_entry_mode", default="interactive")

        if mode == "auto":
            try:
                results = extract_character_facts(f"{name}: {raw_text}", today_key(), model=self.model)
                for char in results:
                    if char.get("name", "").strip().lower() == name.lower():
                        upsert_character(name, char.get("facts") or {}, today_key())
                        for inc in char.get("incidents") or []:
                            add_incident(name, inc, today_key())
                return f"Updated facts for {name}."
            except AIError as exc:
                return f"AI unavailable: {exc}"

        # Interactive mode
        fields = [
            "relationship", "job", "location", "birthday",
            "personality_traits", "interests_hobbies", "family_members",
            "health_notes", "contact_info", "last_seen", "status",
        ]
        print(f"\nWhich field to update for {name}?")
        for i, f in enumerate(fields, 1):
            print(f"  {i:>2}. {f}")
        choice_raw = input("> ").strip()
        if not choice_raw.isdigit() or not (1 <= int(choice_raw) <= len(fields)):
            return "Invalid choice. Cancelled."
        field = fields[int(choice_raw) - 1]
        value = input(f"New value for {field}\n> ").strip()
        if not value:
            return "No value provided. Cancelled."
        confirm = input(f"Set {name}.{field} = {value!r}? (y/n)\n> ").strip().lower()
        if confirm not in {"y", "yes"}:
            return "Cancelled."
        upsert_character(name, {field: value}, today_key())
        return f"Updated {field} for {name}."

    def unknown(self, message: str) -> str:
        if not message:
            return "Try `help` to see what I can do."
        return chitchat(message, model=self.model)


def build_legacy_write_args(date_value: str | None, skip_ai: bool, model: str) -> argparse.Namespace:
    return argparse.Namespace(command="write", date=date_value, skip_ai=skip_ai, model=model)
