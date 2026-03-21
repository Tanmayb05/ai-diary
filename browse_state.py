from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BrowseState:
    level: str    # "overview" | "year" | "month" | "week"
    context: dict
    options: list
    history: list = field(default_factory=list)
