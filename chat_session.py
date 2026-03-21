from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from browse_state import BrowseState
from intent_router import RoutedIntent, route_message


@dataclass
class ChatSessionState:
    active_entry_date: str | None = None
    last_intent: str | None = None
    last_rendered_tasks: list[dict[str, Any]] = field(default_factory=list)
    pending_intent: RoutedIntent | None = None
    browse_state: BrowseState | None = None


class ChatSession:
    def __init__(self, handlers: Any) -> None:
        self.handlers = handlers
        self.state = ChatSessionState()

    def run(self) -> None:
        print("AI Diary chat")
        print("Type what you want to do, for example: `i want to write`, `show my todos`, `read today's entry`.")
        print("Type `help` for options or `exit` to leave.")

        while True:
            try:
                message = input("\n> ").strip()
            except EOFError:
                print()
                return

            if self.state.browse_state is not None:
                response = self._handle_browse_input(message)
                if response:
                    print(response)
                continue

            if self.state.pending_intent is not None:
                response = self._resolve_pending(message)
                if response:
                    print(response)
                continue

            routed = route_message(message)
            if routed.name == "empty":
                continue
            if routed.name == "exit":
                print("Bye.")
                return

            response = self._dispatch(routed)
            if response:
                print(response)

    def _dispatch(self, routed: RoutedIntent) -> str:
        self.state.last_intent = routed.name

        if routed.name == "help":
            return self.handlers.help_text()
        if routed.name == "clarify":
            self.state.pending_intent = routed
            return routed.follow_up
        if routed.name.startswith("confirm_"):
            self.state.pending_intent = routed
            return routed.follow_up
        if routed.name == "write":
            payload = self.handlers.run_write_flow(initial_date=routed.params.get("date"))
            self.state.active_entry_date = payload.get("date")
            self.state.last_rendered_tasks = payload.get("tasks", [])
            return payload.get("message", "")
        if routed.name == "read":
            payload = self.handlers.read_entry(date_value=routed.params.get("date"))
            self.state.active_entry_date = payload.get("date")
            return payload.get("message", "")
        if routed.name == "read_range":
            year = routed.params["year"]
            month = routed.params.get("month")
            # Year-only → hierarchical browse view
            if month is None:
                text, browse_state = self.handlers.browse_year(year)
                self.state.browse_state = browse_state
                return text
            # Specific month → flat list of entries
            payload = self.handlers.read_range(
                year=year,
                month=month,
                limit=routed.params.get("limit"),
            )
            return payload.get("message", "")
        if routed.name == "todo_list":
            payload = self.handlers.todo_list()
            self.state.last_rendered_tasks = payload.get("tasks", [])
            return payload.get("message", "")
        if routed.name == "todo_add":
            task_text = routed.params.get("task") or input("Task to add\n> ").strip()
            return self.handlers.todo_add(task_text)
        if routed.name == "todo_done":
            task_id = routed.params.get("id")
            if task_id is None:
                raw = input("Task id to mark done\n> ").strip()
                task_id = int(raw) if raw.isdigit() else None
            return self.handlers.todo_done(task_id)
        if routed.name == "todo_delete":
            task_id = routed.params.get("id")
            if task_id is None:
                raw = input("Task id to delete\n> ").strip()
                task_id = int(raw) if raw.isdigit() else None
            return self.handlers.todo_delete(task_id)
        if routed.name == "summarize":
            return self.handlers.summarize_period(
                year=routed.params["year"],
                month=routed.params.get("month"),
                label=routed.params.get("label"),
            )
        if routed.name == "list_entries":
            text, browse_state = self.handlers.list_entries()
            self.state.browse_state = browse_state
            return text
        if routed.name == "show_facts":
            return self.handlers.show_facts()
        if routed.name == "ask":
            return self.handlers.ask(routed.params.get("question", ""))
        if routed.name == "show_characters":
            return self.handlers.show_characters()
        if routed.name == "show_character":
            return self.handlers.show_character(routed.params.get("name", ""))
        if routed.name == "add_character_fact":
            return self.handlers.add_character_fact_interactive(
                name=routed.params.get("name", ""),
                raw_text=routed.params.get("raw_text", ""),
            )

        return self.handlers.unknown(message=routed.params.get("text", ""))

    def _resolve_pending(self, message: str) -> str:
        pending = self.state.pending_intent
        if pending is None:
            return ""

        text = " ".join(message.strip().lower().split())
        if not text:
            text = "yes"
        if text in {"exit", "quit", "bye"}:
            print("Bye.")
            raise SystemExit(0)
        if text in {"no", "n", "cancel", "not now"}:
            self.state.pending_intent = None
            return "Okay."

        self.state.pending_intent = None

        if pending.name == "clarify":
            routed = route_message(message)
            if routed.name in {"unknown", "clarify", "empty"}:
                return "Sorry, I still couldn't understand that. Try `help` to see what I can do."
            return self._dispatch(routed)

        if pending.name == "confirm_read":
            if text in {"yes", "y", "today"}:
                payload = self.handlers.read_entry(date_value=pending.params.get("date"))
                self.state.active_entry_date = payload.get("date")
                return payload.get("message", "")
            routed = route_message(f"read {message}")
            return self._dispatch(routed)

        if pending.name == "confirm_write":
            if text in {"yes", "y", "today"}:
                payload = self.handlers.run_write_flow(initial_date=None)
                self.state.active_entry_date = payload.get("date")
                self.state.last_rendered_tasks = payload.get("tasks", [])
                return payload.get("message", "")
            routed = route_message(f"write {message}")
            return self._dispatch(routed)

        if pending.name == "confirm_todo_list":
            if text in {"yes", "y"}:
                payload = self.handlers.todo_list()
                self.state.last_rendered_tasks = payload.get("tasks", [])
                return payload.get("message", "")
            routed = route_message(f"todo {message}")
            return self._dispatch(routed)

        if pending.name == "confirm_journal_candidate":
            if text in {"yes", "y", "journal it", "save it", "today"}:
                payload = self.handlers.run_write_flow(
                    initial_date=None,
                    initial_entry_text=pending.params.get("entry_text", ""),
                )
                self.state.active_entry_date = payload.get("date")
                self.state.last_rendered_tasks = payload.get("tasks", [])
                return payload.get("message", "")
            routed = route_message(message)
            return self._dispatch(routed)

        return self.handlers.unknown(message=message)

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
            lines = []
            for i, opt in enumerate(bs.options, 1):
                lines.append(f"{i:>3}. {opt['label']}")
            lines.append("\nType a number to open, or 'back' to exit.")
            return "\n".join(lines)
        lines = []
        for i, opt in enumerate(bs.options, 1):
            lines.append(f"{i:>3}. {opt['label']}")
        prompt = "Type a number to open, or 'back' to go up."
        if bs.level == "week":
            prompt = "Type a number to read the entry, or 'back' to go up."
        lines.append(f"\n{prompt}")
        return "\n".join(lines)
