import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ENTRIES_PATH = DATA_DIR / "entries.json"
TODOS_PATH = DATA_DIR / "todos.json"
SETTINGS_PATH = DATA_DIR / "settings.json"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    ensure_data_dir()
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError:
            return default


def save_json(path: Path, data: Any) -> None:
    ensure_data_dir()
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def today_key() -> str:
    return date.today().isoformat()


def normalize_date(value: str | None) -> str:
    if not value:
        return today_key()
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


def timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_setting(key: str, default: Any = None) -> Any:
    settings = load_json(SETTINGS_PATH, {})
    return settings.get(key, default)


def set_setting(key: str, value: Any) -> None:
    settings = load_json(SETTINGS_PATH, {})
    settings[key] = value
    save_json(SETTINGS_PATH, settings)
