"""
Persistent local history of previously checked items.

This is WasteBuddy's memory / persistent-state capability: it remembers what
a returning user has already checked, across separate visits, with no server
or account, just a small local JSON file. The UI never reads or writes this
file directly; it only calls the functions in this module, matching the
project's core architectural rule that all state access goes through the
service layer.

This is a lightweight recent-items log, not a chat history: it stores only
the real, grounded classification result for each successful lookup, never
an off-topic redirect or an error message, so it stays a trustworthy record
of what the user has actually checked so far.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HISTORY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "user_history.json"
MAX_ENTRIES = 50


def load_history() -> list[dict]:
    """Loads the stored history, or an empty list if the file is missing or unreadable."""
    if not HISTORY_PATH.exists():
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(entries: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def record_entry(item_name: str, disposal_category: str, recycled_into: Optional[str]) -> None:
    """
    Appends one real, grounded classification result to the local history file.

    Keeps only the most recent MAX_ENTRIES items so the file cannot grow
    without bound the longer the app is used.
    """
    entries = load_history()
    entries.append({
        "item_name": item_name,
        "disposal_category": disposal_category,
        "recycled_into": recycled_into,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    entries = entries[-MAX_ENTRIES:]
    _save_history(entries)


def get_recent(limit: int = 5) -> list[dict]:
    """Returns up to `limit` most recently checked items, newest first."""
    entries = load_history()
    return list(reversed(entries[-limit:]))
