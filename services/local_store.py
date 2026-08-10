from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

STORE_PATH = Path(__file__).resolve().parent.parent / "session_data.json"

_DEFAULT = {"added_events": [], "deleted_ids": [], "event_id_counter": 0}


def _read() -> dict:
    if not STORE_PATH.exists():
        return dict(_DEFAULT)
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT)
    for key, default in _DEFAULT.items():
        data.setdefault(key, default)
    return data


def _write(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STORE_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp_path.replace(STORE_PATH)


def get_added_events() -> list[dict]:
    return _read()["added_events"]


def get_deleted_ids() -> set[str]:
    return set(_read()["deleted_ids"])


def append_added_event(record: dict) -> None:
    data = _read()
    data["added_events"].append(record)
    _write(data)


def update_added_event(event_id: str, new_record: dict) -> bool:
    data = _read()
    for i, item in enumerate(data["added_events"]):
        if item.get("event_id") == event_id:
            data["added_events"][i] = new_record
            _write(data)
            return True
    return False


def remove_added_event(event_id: str) -> None:
    data = _read()
    data["added_events"] = [item for item in data["added_events"] if item.get("event_id") != event_id]
    _write(data)


def add_deleted_id(event_id: str) -> None:
    data = _read()
    if event_id not in data["deleted_ids"]:
        data["deleted_ids"].append(event_id)
    _write(data)


def next_event_id() -> str:
    data = _read()
    data["event_id_counter"] += 1
    _write(data)
    return f"S{data['event_id_counter']:04d}"
