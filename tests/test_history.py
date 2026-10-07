from src.services import history


def test_record_entry_and_get_recent_round_trip(tmp_path, monkeypatch):
    """Verify entries persist across calls and get_recent returns newest first."""
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "user_history.json")

    history.record_entry("glass jar", "Glass", "Melted down into new glass bottles and jars.")
    history.record_entry("banana peel", "Biowaste", "Composted into soil improvement products.")

    recent = history.get_recent(limit=5)

    assert len(recent) == 2
    assert recent[0]["item_name"] == "banana peel"
    assert recent[1]["item_name"] == "glass jar"
    assert "checked_at" in recent[0]


def test_get_recent_respects_limit_and_trims_oldest_entries(tmp_path, monkeypatch):
    """Verify the history file is capped at MAX_ENTRIES, dropping the oldest entries first."""
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "user_history.json")
    monkeypatch.setattr(history, "MAX_ENTRIES", 3)

    for i in range(5):
        history.record_entry(f"item-{i}", "Mixed / miscellaneous waste", None)

    stored = history.load_history()
    assert [e["item_name"] for e in stored] == ["item-2", "item-3", "item-4"]

    recent = history.get_recent(limit=2)
    assert [e["item_name"] for e in recent] == ["item-4", "item-3"]


def test_load_history_returns_empty_list_when_file_missing(tmp_path, monkeypatch):
    """Verify a missing history file is treated as an empty history rather than an error."""
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "does_not_exist.json")

    assert history.load_history() == []


def test_load_history_returns_empty_list_for_corrupted_file(tmp_path, monkeypatch):
    """Verify a corrupted or non-list JSON file never crashes the app, just resets to empty."""
    bad_file = tmp_path / "user_history.json"
    bad_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(history, "HISTORY_PATH", bad_file)

    assert history.load_history() == []
