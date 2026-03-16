from __future__ import annotations

import argparse
from typing import Any

from ai import DEFAULT_MODEL, AIError, analyze_entry, extract_tasks, generate_reflection
from diary import get_entries_for_date, load_entry_store, render_entries_for_day, render_task_candidate, upsert_entry
from prompts import mood_choices
from todo import add_task, bulk_add_tasks, delete_task, list_tasks, mark_done, render_tasks


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
                "Try:",
                "- i want to write",
                "- read today's entry",
                "- show my todos",
                "- add todo finish thesis draft",
                "- mark task 2 done",
                "- delete task 3",
                "- exit",
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

    def unknown(self, message: str) -> str:
        return f"I couldn't route that yet: {message}\nTry `help`."


def build_legacy_write_args(date_value: str | None, skip_ai: bool, model: str) -> argparse.Namespace:
    return argparse.Namespace(command="write", date=date_value, skip_ai=skip_ai, model=model)
