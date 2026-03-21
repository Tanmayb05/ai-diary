from __future__ import annotations

import json
from typing import Any

from db import get_db
from utils import timestamp, today_key

_JSON_FIELDS = {"personality_traits", "interests_hobbies", "family_members", "incidents", "fact_history"}

_SCALAR_FIELDS = {"relationship", "job", "location", "birthday", "health_notes", "contact_info", "last_seen", "status"}


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    for field in _JSON_FIELDS:
        raw = d.get(field)
        if isinstance(raw, str):
            try:
                d[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d[field] = []
        elif d[field] is None:
            d[field] = []
    return d


def load_characters() -> dict[str, dict[str, Any]]:
    db = get_db()
    rows = db.execute("SELECT * FROM characters ORDER BY name").fetchall()
    return {row["name"]: _row_to_dict(row) for row in rows}


def get_character(name: str) -> dict[str, Any] | None:
    db = get_db()
    row = db.execute("SELECT * FROM characters WHERE name=?", (name,)).fetchone()
    return _row_to_dict(row) if row else None


def get_all_characters() -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute("SELECT name, relationship FROM characters ORDER BY name").fetchall()
    return [{"name": row["name"], "relationship": row["relationship"]} for row in rows]


def upsert_character(name: str, fields_dict: dict[str, Any], entry_date: str) -> dict[str, Any]:
    name = name.strip().title()
    db = get_db()
    existing_row = db.execute("SELECT * FROM characters WHERE name=?", (name,)).fetchone()

    if existing_row:
        existing = _row_to_dict(existing_row)
    else:
        existing = {
            "name": name,
            "relationship": None, "job": None, "location": None, "birthday": None,
            "health_notes": None, "contact_info": None, "last_seen": None, "status": None,
            "personality_traits": [], "interests_hobbies": [], "family_members": [],
            "incidents": [], "fact_history": [],
            "created_at": timestamp(), "updated_at": timestamp(),
        }

    fact_history: list[dict] = existing.get("fact_history") or []

    for key, new_val in fields_dict.items():
        if key in ("name", "incidents", "fact_history", "id", "created_at", "updated_at"):
            continue

        if key in _SCALAR_FIELDS:
            old_val = existing.get(key)
            new_val_str = str(new_val).strip() if new_val is not None else None
            if new_val_str and old_val and old_val.strip().lower() != new_val_str.lower():
                fact_history.append({
                    "field": key,
                    "old_value": old_val,
                    "new_value": new_val_str,
                    "date": entry_date,
                })
            if new_val_str:
                existing[key] = new_val_str

        elif key in _JSON_FIELDS - {"incidents", "fact_history"}:
            # Merge list: extend without duplicates
            current_list: list = existing.get(key) or []
            new_items = new_val if isinstance(new_val, list) else ([new_val] if new_val else [])
            current_lower = {str(x).lower() for x in current_list}
            for item in new_items:
                item_str = str(item).strip()
                if item_str and item_str.lower() not in current_lower:
                    current_list.append(item_str)
                    current_lower.add(item_str.lower())
            existing[key] = current_list

    existing["fact_history"] = fact_history
    existing["updated_at"] = timestamp()

    now = timestamp()
    db.execute(
        """INSERT INTO characters
               (name, relationship, job, location, birthday,
                personality_traits, interests_hobbies, family_members,
                health_notes, contact_info, last_seen, status,
                incidents, fact_history, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(name) DO UPDATE SET
             relationship=excluded.relationship,
             job=excluded.job,
             location=excluded.location,
             birthday=excluded.birthday,
             personality_traits=excluded.personality_traits,
             interests_hobbies=excluded.interests_hobbies,
             family_members=excluded.family_members,
             health_notes=excluded.health_notes,
             contact_info=excluded.contact_info,
             last_seen=excluded.last_seen,
             status=excluded.status,
             fact_history=excluded.fact_history,
             updated_at=excluded.updated_at""",
        (
            name,
            existing.get("relationship"),
            existing.get("job"),
            existing.get("location"),
            existing.get("birthday"),
            json.dumps(existing.get("personality_traits") or []),
            json.dumps(existing.get("interests_hobbies") or []),
            json.dumps(existing.get("family_members") or []),
            existing.get("health_notes"),
            existing.get("contact_info"),
            existing.get("last_seen"),
            existing.get("status"),
            json.dumps(existing.get("incidents") or []),
            json.dumps(fact_history),
            existing.get("created_at") or now,
            now,
        ),
    )
    db.commit()

    row = db.execute("SELECT * FROM characters WHERE name=?", (name,)).fetchone()
    return _row_to_dict(row)


def add_incident(name: str, summary: str, entry_date: str) -> bool:
    """Add a notable incident for a character. Returns True if added, False if duplicate."""
    from ai import detect_duplicate_incident, AIError

    name = name.strip().title()
    char = get_character(name)
    if not char:
        # Create bare record first
        upsert_character(name, {}, entry_date)
        char = get_character(name)

    existing_incidents: list[dict] = char.get("incidents") or []
    new_incident = {"date": entry_date, "summary": summary.strip()}

    # Check for duplicates via LLM
    try:
        if existing_incidents and detect_duplicate_incident(existing_incidents, new_incident):
            return False
    except AIError:
        pass  # Conservative: add anyway if LLM unavailable

    existing_incidents.append(new_incident)

    db = get_db()
    db.execute(
        "UPDATE characters SET incidents=?, updated_at=? WHERE name=?",
        (json.dumps(existing_incidents), timestamp(), name),
    )
    db.commit()
    return True


def render_character_card(char: dict[str, Any]) -> str:
    lines = []

    name = char.get("name", "Unknown")
    relationship = char.get("relationship")
    header = name
    if relationship:
        header += f"  —  {relationship}"
    lines.append(header)
    lines.append("=" * len(header))

    scalar_labels = [
        ("job", "Job"),
        ("location", "Location"),
        ("birthday", "Birthday"),
        ("status", "Status"),
        ("health_notes", "Health notes"),
        ("contact_info", "Contact"),
        ("last_seen", "Last seen"),
    ]
    for field, label in scalar_labels:
        val = char.get(field)
        if val:
            lines.append(f"{label}: {val}")

    list_labels = [
        ("personality_traits", "Personality"),
        ("interests_hobbies", "Interests / hobbies"),
        ("family_members", "Family"),
    ]
    for field, label in list_labels:
        items = char.get(field) or []
        if items:
            lines.append(f"{label}: {', '.join(items)}")

    # Fact history
    history = char.get("fact_history") or []
    if history:
        lines.append("")
        lines.append("Fact history:")
        for h in history:
            lines.append(f"  [{h.get('date', '?')}] {h.get('field', '?')}: {h.get('old_value')} → {h.get('new_value')}")

    # Incidents
    incidents = char.get("incidents") or []
    if incidents:
        lines.append("")
        lines.append("Notable incidents:")
        for inc in incidents:
            lines.append(f"  [{inc.get('date', '?')}] {inc.get('summary', '')}")
    else:
        lines.append("")
        lines.append("No incidents recorded yet.")

    return "\n".join(lines)
