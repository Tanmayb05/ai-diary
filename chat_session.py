from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intent_router import RoutedIntent, route_message


@dataclass
class ChatSessionState:
    active_entry_date: str | None = None
    last_intent: str | None = None
    last_rendered_tasks: list[dict[str, Any]] = field(default_factory=list)
    pending_intent: RoutedIntent | None = None


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
            payload = self.handlers.read_range(
                year=routed.params["year"],
                month=routed.params.get("month"),
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
