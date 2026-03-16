from __future__ import annotations

from typing import Any

from utils import TODOS_PATH, load_json, save_json, timestamp


def load_todos() -> list[dict[str, Any]]:
    return load_json(TODOS_PATH, [])


def save_todos(todos: list[dict[str, Any]]) -> None:
    save_json(TODOS_PATH, todos)


def add_task(task: str, source: str = "manual") -> dict[str, Any]:
    todos = load_todos()
    next_id = max((item["id"] for item in todos), default=0) + 1
    payload = {
        "id": next_id,
        "task": task.strip(),
        "done": False,
        "source": source,
        "created_at": timestamp(),
        "completed_at": None,
    }
    todos.append(payload)
    save_todos(todos)
    return payload


def bulk_add_tasks(tasks: list[Any], source: str = "ai") -> list[dict[str, Any]]:
    added = []
    for task in tasks:
        if isinstance(task, dict):
            cleaned = str(task.get("task", "")).strip()
        else:
            cleaned = str(task).strip()
        if cleaned:
            added.append(add_task(cleaned, source=source))
    return added


def list_tasks(include_completed: bool = True) -> list[dict[str, Any]]:
    todos = load_todos()
    if include_completed:
        return todos
    return [item for item in todos if not item["done"]]


def mark_done(task_id: int) -> dict[str, Any] | None:
    todos = load_todos()
    for item in todos:
        if item["id"] == task_id:
            item["done"] = True
            item["completed_at"] = timestamp()
            save_todos(todos)
            return item
    return None


def delete_task(task_id: int) -> dict[str, Any] | None:
    todos = load_todos()
    for index, item in enumerate(todos):
        if item["id"] == task_id:
            removed = todos.pop(index)
            save_todos(todos)
            return removed
    return None


def render_tasks(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "No tasks found."
    lines = []
    for item in tasks:
        status = "x" if item["done"] else " "
        lines.append(f"[{status}] {item['id']}: {item['task']} ({item['source']})")
    return "\n".join(lines)
