"""
Run this from the build/ folder before your next reboot.

It shows exactly what's sitting in session_data.json (if anything),
then clears it entirely — session-added events are meant to be
transient scratch state, not a permanent record, so a clean wipe here
is safe. Anything real that was in there should already be reflected
in the latest baked-in workbook data.

    python3 diagnose_and_clear_session.py
"""
import json
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent / "session_data.json"


def main() -> None:
    if not STORE_PATH.exists():
        print("No session_data.json found on this container — nothing stale here.")
        return

    data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    added = data.get("added_events", [])
    print(f"Found {len(added)} session-added event(s) still on disk:")
    for e in added:
        row = e.get("timeline_row") or e.get("pipeline_row") or {}
        print(f"  - {e.get('status')}: {row.get('Client')} | {row.get('Service Date') or row.get('Date / Timing')}")

    if not added:
        print("Nothing to clear.")
        return

    STORE_PATH.write_text(json.dumps({"added_events": []}, indent=2), encoding="utf-8")
    print(f"\nCleared. {len(added)} stale entr{'y' if len(added)==1 else 'ies'} removed.")


if __name__ == "__main__":
    main()
