from __future__ import annotations

import argparse
import json
from typing import Iterable

from ai import (
    DEFAULT_MODEL,
    AIError,
    analyze_entry,
    answer_from_entries,
    answer_with_context,
    extract_tasks,
    generate_coaching,
    generate_insight,
    generate_plan_next,
    generate_reflection,
    generate_weekly_summary,
    rewrite_entry,
)
from chat_session import ChatSession
from diary import (
    aggregate_goals,
    detect_contradictions,
    find_similar_entries,
    get_entry,
    get_entries_for_date,
    get_entry_tags,
    get_recent_entries,
    list_entry_dates,
    load_entries,
    mood_trend,
    render_entry,
    render_entries_for_day,
    render_task_candidate,
    resurface_entries,
    sentiment_trends,
    upsert_entry,
)
from handlers import ChatHandlers
from prompts import list_prompts, mood_choices
from todo import add_task, bulk_add_tasks, delete_task, list_tasks, mark_done, render_tasks
from utils import normalize_date, today_key


def prompt_input(label: str, default: str = "") -> str:
    prompt = f"{label}"
    if default:
        prompt += f" [{default}]"
    prompt += "\n> "
    value = input(prompt).strip()
    return value or default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Diary CLI")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")

    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser("chat-ui", help="Start the interactive chat interface")

    write_parser = subparsers.add_parser("write", help="Create or update a diary entry")
    write_parser.add_argument("--date", help="Entry date in YYYY-MM-DD format")
    write_parser.add_argument("--skip-ai", action="store_true", help="Skip AI reflection and metadata extraction")

    read_parser = subparsers.add_parser("read", help="Read a diary entry")
    read_parser.add_argument("--date", help="Entry date in YYYY-MM-DD format")

    history_parser = subparsers.add_parser("history", help="List recent diary dates")
    history_parser.add_argument("--limit", type=int, default=10)

    prompts_parser = subparsers.add_parser("prompts", help="Show reflection prompts")
    prompts_parser.add_argument("--with-answers", action="store_true", help="Show today's saved answers")
    prompts_parser.add_argument("--date", help="Entry date in YYYY-MM-DD format")

    mood_parser = subparsers.add_parser("mood", help="Show recent mood trend")
    mood_parser.add_argument("--days", type=int, default=7)

    ask_parser = subparsers.add_parser("ask", help="Ask your diary a question")
    ask_parser.add_argument("question")

    insight_parser = subparsers.add_parser("insight", help="Generate a short insight from recent entries")

    weekly_parser = subparsers.add_parser("weekly-review", help="Generate a weekly review from recent entries")
    weekly_parser.add_argument("--days", type=int, default=7)

    tags_parser = subparsers.add_parser("tags", help="Show entry tags")
    tags_group = tags_parser.add_mutually_exclusive_group()
    tags_group.add_argument("--date", help="Entry date in YYYY-MM-DD format")
    tags_group.add_argument("--recent", action="store_true", help="Show tags for the most recent entry")

    goals_parser = subparsers.add_parser("goals", help="Show tracked goals")
    goals_parser.add_argument("--recent", type=int, help="Limit aggregation to the last N days")

    tomorrow_parser = subparsers.add_parser("plan-tomorrow", help="Show tomorrow plan for an entry")
    tomorrow_parser.add_argument("--date", help="Entry date in YYYY-MM-DD format")

    similar_parser = subparsers.add_parser("similar", help="Find similar past diary entries")
    similar_parser.add_argument("--date", help="Entry date in YYYY-MM-DD format")

    analyze_parser = subparsers.add_parser("analyze", help="Generate structured metadata for an entry")
    analyze_parser.add_argument("--date", help="Entry date in YYYY-MM-DD format")
    analyze_parser.add_argument("--save", action="store_true", help="Persist regenerated analysis to the entry")

    trends_parser = subparsers.add_parser("trends", help="Show sentiment, stress, and habit trends")
    trends_parser.add_argument("--days", type=int, default=30)

    resurface_parser = subparsers.add_parser("resurface", help="Resurface related diary entries")
    resurface_group = resurface_parser.add_mutually_exclusive_group(required=True)
    resurface_group.add_argument("--query", help="Keyword, goal, or entity to resurface")
    resurface_group.add_argument("--similar-to", dest="similar_to", help="Find similar entries to a date")

    rewrite_parser = subparsers.add_parser("rewrite", help="Rewrite an entry")
    rewrite_parser.add_argument("--date", help="Entry date in YYYY-MM-DD format")
    rewrite_parser.add_argument("--mode", choices=["clean", "bullets"], default="clean")

    coach_parser = subparsers.add_parser("coach", help="Generate coaching guidance for an entry")
    coach_parser.add_argument("--date", help="Entry date in YYYY-MM-DD format")

    plan_next_parser = subparsers.add_parser("plan-next", help="Generate a next-day plan from an entry")
    plan_next_parser.add_argument("--date", help="Entry date in YYYY-MM-DD format")

    chat_parser = subparsers.add_parser("chat", help="Chat with your diary using bounded context")
    chat_parser.add_argument("question")

    contradictions_parser = subparsers.add_parser("contradictions", help="Show repeated priorities without follow-through")
    contradictions_parser.add_argument("--days", type=int, default=30)

    timing_parser = subparsers.add_parser("timing", help="Show LLM call timing stats by call type")
    timing_parser.add_argument("--last", type=int, default=None, help="Only show the last N calls")

    todo_parser = subparsers.add_parser("todo", help="Manage tasks")
    todo_subparsers = todo_parser.add_subparsers(dest="todo_command", required=True)

    todo_add = todo_subparsers.add_parser("add", help="Add a task")
    todo_add.add_argument("task")

    todo_list = todo_subparsers.add_parser("list", help="List tasks")
    todo_list.add_argument("--pending-only", action="store_true")

    todo_done = todo_subparsers.add_parser("done", help="Mark a task done")
    todo_done.add_argument("id", type=int)

    todo_delete = todo_subparsers.add_parser("delete", help="Delete a task")
    todo_delete.add_argument("id", type=int)

    return parser.parse_args()


def handle_write(args: argparse.Namespace) -> None:
    entry_date, _existing_entries = get_entries_for_date(args.date)
    mood_map = mood_choices()

    entry_text = prompt_input("How was your day?")
    highlight = prompt_input("Highlight of the day")

    mood_default = "🙂 Good"
    print("Mood options:", ", ".join(mood_map.values()))
    mood = prompt_input("Mood", mood_default)

    reflection = ""
    extracted_tasks = []
    tags: list[str] = []
    goals: list[str] = []
    tomorrow_plan: list[str] = []
    sentiment = ""
    stress_triggers = []
    habits = []
    mood_alignment = ""
    wins = []
    gratitude = []
    follow_up_questions = []
    advice = []
    entities = []

    if not args.skip_ai:
        try:
            reflection = generate_reflection(entry_text, mood, highlight, model=args.model)
            extracted_tasks = extract_tasks(entry_text, model=args.model)
            analysis = analyze_entry(entry_text, mood, highlight, model=args.model)
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

    print(f"\nSaved entry for {saved_date} at {payload.get('updated_at', payload.get('saved_at', ''))}.")
    if payload.get("reflection"):
        print("\nAI reflection:")
        print(payload["reflection"])

    tasks = payload.get("suggested_tasks") or []
    if tasks:
        print("\nSuggested tasks:")
        for task in tasks:
            print(f"- {render_task_candidate(task)}")
        add_now = prompt_input("Add these tasks to your todo list? (y/n)", "y").lower()
        if add_now == "y":
            added = bulk_add_tasks(tasks, source=f"entry:{saved_date}")
            print(f"Added {len(added)} task(s).")

    metadata_tags = payload.get("tags") or []
    if metadata_tags:
        print(f"\nTags: {', '.join(metadata_tags)}")

    metadata_goals = payload.get("goals") or []
    if metadata_goals:
        print("\nGoals:")
        for goal in metadata_goals:
            print(f"- {goal}")

    metadata_plan = payload.get("tomorrow_plan") or []
    if metadata_plan:
        print("\nTomorrow plan:")
        for item in metadata_plan:
            print(f"- {item}")

    if payload.get("sentiment"):
        print(f"\nSentiment: {payload['sentiment']}")

    if payload.get("wins"):
        print("\nWins:")
        for item in payload["wins"]:
            print(f"- {item}")

    if payload.get("gratitude"):
        print("\nGratitude:")
        for item in payload["gratitude"]:
            print(f"- {item}")

    if payload.get("follow_up_questions"):
        print("\nFollow-up questions:")
        for item in payload["follow_up_questions"]:
            print(f"- {item}")


def handle_read(args: argparse.Namespace) -> None:
    entry_date, entries = get_entries_for_date(args.date)
    if not entries:
        print(f"No entry found for {entry_date}.")
        return
    print(render_entries_for_day(entry_date, entries))


def handle_history(limit: int) -> None:
    dates = list_entry_dates(limit=limit)
    if not dates:
        print("No diary entries found.")
        return
    print("\n".join(dates))


def handle_prompts(args: argparse.Namespace) -> None:
    if not args.with_answers:
        print("\n".join(f"- {prompt}" for prompt in list_prompts()))
        return

    entry_date, entry = get_entry(args.date)
    if not entry:
        print(f"No entry found for {entry_date}.")
        return

    print(f"Prompt answers for {entry_date}:")
    for prompt in list_prompts():
        print(f"- {prompt} {entry.get('prompts', {}).get(prompt, '-')}")


def handle_mood(days: int) -> None:
    trend = mood_trend(days=days)
    if not trend:
        print("No mood data found.")
        return
    print("Mood trend:")
    for entry_date, mood in trend:
        print(f"{entry_date}: {mood}")


def handle_ask(question: str, model: str) -> None:
    try:
        print(answer_from_entries(question, load_entries(), model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")


def handle_insight(model: str) -> None:
    try:
        print(generate_insight(load_entries(), model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")


def handle_weekly_review(days: int, model: str) -> None:
    entries = get_recent_entries(limit=days)
    if not entries:
        print("No diary entries found.")
        return

    try:
        print(generate_weekly_summary(entries, model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")


def handle_tags(args: argparse.Namespace) -> None:
    target_date = None
    if args.recent:
        dates = list_entry_dates(limit=1)
        if not dates:
            print("No diary entries found.")
            return
        target_date = dates[0]
    elif args.date:
        target_date = args.date
    else:
        target_date = today_key()

    entry_date, tags = get_entry_tags(target_date)
    if not tags:
        print(f"No tags found for {entry_date}.")
        return
    print(f"Tags for {entry_date}: {', '.join(tags)}")


def handle_goals(days: int | None) -> None:
    goals = aggregate_goals(days=days)
    if not goals:
        print("No goals found.")
        return

    for item in goals:
        print(item["goal"])
        print(f"  first mentioned: {item['first_mentioned']}")
        print(f"  last mentioned: {item['last_mentioned']}")
        print(f"  mention count: {item['mention_count']}")
        moods = ", ".join(item["moods"]) if item["moods"] else "-"
        print(f"  related moods: {moods}")


def handle_plan_tomorrow(entry_date: str | None) -> None:
    key, entry = get_entry(entry_date)
    if not entry:
        print(f"No entry found for {key}.")
        return

    plan = entry.get("tomorrow_plan") or []
    if not plan:
        print(f"No tomorrow plan found for {key}.")
        return

    print(f"Tomorrow plan for {key}:")
    for item in plan:
        print(f"- {item}")


def handle_similar(entry_date: str | None) -> None:
    key, matches = find_similar_entries(entry_date)
    if not matches:
        entry_key, entry = get_entry(entry_date)
        if not entry:
            print(f"No entry found for {entry_key}.")
            return
        print(f"No similar entries found for {key}.")
        return

    print(f"Similar entries for {key}:")
    for match in matches:
        print(f"- {match['date']}: {'; '.join(match['reasons'])}")
        if match["highlight"]:
            print(f"  highlight: {match['highlight']}")
        if match["excerpt"]:
            print(f"  excerpt: {match['excerpt']}")


def handle_analyze(entry_date: str | None, save: bool, model: str) -> None:
    key, entry = get_entry(entry_date)
    if not entry:
        print(f"No entry found for {key}.")
        return

    try:
        tasks = extract_tasks(entry.get("entry", ""), model=model)
        analysis = analyze_entry(entry.get("entry", ""), entry.get("mood", ""), entry.get("highlight", ""), model=model)
    except AIError as exc:
        print(f"AI unavailable: {exc}")
        return

    if save:
        _saved_date, entry = upsert_entry(
            entry_date=key,
            free_text=entry.get("entry", ""),
            mood=entry.get("mood", ""),
            highlights=entry.get("highlight", ""),
            prompt_answers=entry.get("prompts", {}),
            reflection=entry.get("reflection", ""),
            extracted_tasks=tasks,
            tags=analysis["tags"],
            goals=analysis["goals"],
            sentiment=analysis["sentiment_label"],
            tomorrow_plan=analysis["tomorrow_plan"],
            stress_triggers=analysis["stress_triggers"],
            habits=analysis["habits"],
            sentiment_label=analysis["sentiment_label"],
            mood_alignment=analysis["mood_alignment"],
            wins=analysis["wins"],
            gratitude=analysis["gratitude"],
            follow_up_questions=analysis["follow_up_questions"],
            advice=analysis["advice"],
            entities=analysis["entities"],
        )
        print(f"Saved refreshed analysis for {key}.")

    print(f"Analysis for {key}:")
    print(f"Sentiment: {analysis['sentiment_label']}")
    print(f"Mood alignment: {analysis['mood_alignment']}")
    if analysis["tags"]:
        print(f"Tags: {', '.join(analysis['tags'])}")
    if analysis["goals"]:
        print("Goals:")
        for item in analysis["goals"]:
            print(f"- {item}")
    if tasks:
        print("Tasks:")
        for task in tasks:
            print(f"- {render_task_candidate(task)}")
    if analysis["stress_triggers"]:
        print("Stress triggers:")
        for item in analysis["stress_triggers"]:
            detail = item["trigger"]
            if item["evidence"]:
                detail += f" ({item['evidence']})"
            print(f"- {detail}")
    for section_name in ("habits", "wins", "gratitude", "entities", "follow_up_questions", "advice", "tomorrow_plan"):
        values = analysis[section_name]
        if values:
            print(f"{section_name.replace('_', ' ').title()}:")
            for item in values:
                print(f"- {item}")


def handle_trends(days: int) -> None:
    summary = sentiment_trends(days=days)
    if summary["entry_count"] == 0:
        print("No diary entries found.")
        return

    print(f"Trends over the last {summary['entry_count']} entries:")
    if summary["sentiments"]:
        print("Sentiment counts:")
        for label, count in summary["sentiments"].items():
            print(f"- {label}: {count}")
    if summary["mood_alignment"]:
        print("Mood alignment:")
        for label, count in summary["mood_alignment"].items():
            print(f"- {label}: {count}")
    if summary["top_habits"]:
        print("Habits:")
        for item in summary["top_habits"]:
            print(f"- {item['habit']}: {item['count']}")
    if summary["top_stress_triggers"]:
        print("Stress triggers:")
        for item in summary["top_stress_triggers"]:
            print(f"- {item['trigger']}: {item['count']}")


def handle_resurface(query: str | None, similar_to: str | None) -> None:
    if query:
        matches = resurface_entries(query)
        if not matches:
            print(f"No entries found for query: {query}")
            return
        print(f"Resurfaced entries for '{query}':")
    else:
        target_date, matches = find_similar_entries(similar_to, limit=5)
        if not matches:
            print(f"No similar entries found for {target_date}.")
            return
        print(f"Resurfaced entries similar to {target_date}:")

    for match in matches:
        print(f"- {match['date']}: {'; '.join(match['reasons'])}")
        if match["highlight"]:
            print(f"  highlight: {match['highlight']}")
        if match["excerpt"]:
            print(f"  excerpt: {match['excerpt']}")


def handle_rewrite(entry_date: str | None, mode: str, model: str) -> None:
    key, entry = get_entry(entry_date)
    if not entry:
        print(f"No entry found for {key}.")
        return

    try:
        print(rewrite_entry(entry.get("entry", ""), mode=mode, model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")


def handle_coach(entry_date: str | None, model: str) -> None:
    key, entry = get_entry(entry_date)
    if not entry:
        print(f"No entry found for {key}.")
        return

    recent_entries = [(date, item) for date, item in get_recent_entries(limit=5) if date != key]
    try:
        print(generate_coaching(entry, recent_entries, model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")


def handle_plan_next(entry_date: str | None, model: str) -> None:
    key, entry = get_entry(entry_date)
    if not entry:
        print(f"No entry found for {key}.")
        return

    recent_entries = [(date, item) for date, item in get_recent_entries(limit=5) if date != key]
    try:
        print(generate_plan_next(entry, recent_entries, model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")


def handle_chat(question: str, model: str) -> None:
    dates = list_entry_dates(limit=1)
    current_entry = None
    if dates:
        current_entry = (dates[0], get_entry(dates[0])[1])
        if current_entry[1] is None:
            current_entry = None

    recent_entries = get_recent_entries(limit=5)
    resurfaced = []
    for match in resurface_entries(question, limit=4):
        _date, entry = get_entry(match["date"])
        if entry:
            resurfaced.append((match["date"], entry))

    try:
        print(answer_with_context(question, current_entry, recent_entries, resurfaced, model=model))
    except AIError as exc:
        print(f"AI unavailable: {exc}")


def handle_timing(last: int | None) -> None:
    from collections import defaultdict
    from utils import DATA_DIR

    log_path = DATA_DIR / "llm_timing.jsonl"
    if not log_path.exists():
        print("No timing data yet. Run some queries first.")
        return

    records = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    if last:
        records = records[-last:]

    if not records:
        print("No timing records found.")
        return

    # Aggregate by call_type
    stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_s": 0.0, "min_s": float("inf"), "max_s": 0.0, "models": set()})
    for r in records:
        ct = r.get("call_type", "unknown")
        s = stats[ct]
        s["count"] += 1
        s["total_s"] += r["elapsed_s"]
        s["min_s"] = min(s["min_s"], r["elapsed_s"])
        s["max_s"] = max(s["max_s"], r["elapsed_s"])
        s["models"].add(r.get("model", "?"))

    print(f"LLM timing summary ({len(records)} calls):\n")
    print(f"{'call_type':<22} {'count':>5} {'avg(s)':>8} {'min(s)':>8} {'max(s)':>8}  model(s)")
    print("-" * 75)
    for ct, s in sorted(stats.items(), key=lambda x: -x[1]["total_s"]):
        avg = s["total_s"] / s["count"]
        models = ", ".join(sorted(s["models"]))
        print(f"{ct:<22} {s['count']:>5} {avg:>8.2f} {s['min_s']:>8.2f} {s['max_s']:>8.2f}  {models}")

    print(f"\nRaw log: {log_path}")


def handle_contradictions(days: int) -> None:
    contradictions = detect_contradictions(days=days)
    if not contradictions:
        print("No contradictions found.")
        return

    for item in contradictions:
        print(item["goal"])
        print(f"  mentions: {item['mention_count']}")
        print(f"  tasks created: {item['task_count']}")
        print(f"  follow-through signals: {item['follow_through_count']}")
        print(f"  dates: {', '.join(item['dates'])}")


def handle_todo(args: argparse.Namespace) -> None:
    if args.todo_command == "add":
        task = add_task(args.task)
        print(f"Added task {task['id']}: {task['task']}")
        return

    if args.todo_command == "list":
        print(render_tasks(list_tasks(include_completed=not args.pending_only)))
        return

    if args.todo_command == "done":
        task = mark_done(args.id)
        if not task:
            print(f"Task {args.id} not found.")
            return
        print(f"Completed task {task['id']}: {task['task']}")
        return

    if args.todo_command == "delete":
        task = delete_task(args.id)
        if not task:
            print(f"Task {args.id} not found.")
            return
        print(f"Deleted task {task['id']}: {task['task']}")


def main() -> None:
    args = parse_args()
    if args.command in {None, "chat-ui"}:
        ChatSession(ChatHandlers(model=args.model)).run()
    elif args.command == "write":
        handle_write(args)
    elif args.command == "read":
        handle_read(args)
    elif args.command == "history":
        handle_history(args.limit)
    elif args.command == "prompts":
        handle_prompts(args)
    elif args.command == "mood":
        handle_mood(args.days)
    elif args.command == "ask":
        handle_ask(args.question, args.model)
    elif args.command == "insight":
        handle_insight(args.model)
    elif args.command == "weekly-review":
        handle_weekly_review(args.days, args.model)
    elif args.command == "tags":
        handle_tags(args)
    elif args.command == "goals":
        handle_goals(args.recent)
    elif args.command == "plan-tomorrow":
        handle_plan_tomorrow(args.date)
    elif args.command == "similar":
        handle_similar(args.date)
    elif args.command == "analyze":
        handle_analyze(args.date, args.save, args.model)
    elif args.command == "trends":
        handle_trends(args.days)
    elif args.command == "resurface":
        handle_resurface(args.query, args.similar_to)
    elif args.command == "rewrite":
        handle_rewrite(args.date, args.mode, args.model)
    elif args.command == "coach":
        handle_coach(args.date, args.model)
    elif args.command == "plan-next":
        handle_plan_next(args.date, args.model)
    elif args.command == "chat":
        handle_chat(args.question, args.model)
    elif args.command == "contradictions":
        handle_contradictions(args.days)
    elif args.command == "timing":
        handle_timing(args.last)
    elif args.command == "todo":
        handle_todo(args)


if __name__ == "__main__":
    main()
