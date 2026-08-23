"""Google Sheets-backed persistence for Timeline + Pipeline.

Replaces the old `local_store.py` (a JSON file written to the app
container's local disk). That approach silently lost data whenever
Streamlit Cloud spun up a fresh container — after a redeploy, or simply
after the app went idle overnight and woke back up. A Google Sheet lives
outside the container entirely, so it survives both.

The Sheet is now the single source of truth for Timeline and Pipeline.
Every add, mark-complete, edit, and delete writes straight to it; every
page load reads straight from it. Nothing is cached in container memory
or disk across a restart.

Setup required before this works — see SETUP.md in the repo root.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

TIMELINE_SHEET = "Timeline"
PIPELINE_SHEET = "Pipeline"

TIMELINE_HEADERS = [
    "Event ID", "Client", "State/Region", "Status", "Amount",
    "Verified?", "Service Date", "Location Detail", "Billing Type",
]
PIPELINE_HEADERS = ["Event ID", "Client", "Location", "Status", "Date / Timing"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class SheetsUnavailable(RuntimeError):
    """Raised whenever secrets are missing or a live API call fails.
    Callers should catch this and fall back gracefully rather than crash
    the whole page — see data_source.load_snapshot()."""


def is_configured() -> bool:
    try:
        return "gcp_service_account" in st.secrets and "gsheets" in st.secrets
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def _client():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return gspread.authorize(creds)


def _spreadsheet():
    try:
        sheet_id = st.secrets["gsheets"]["spreadsheet_id"]
        return _client().open_by_key(sheet_id)
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI as a banner
        raise SheetsUnavailable(f"Could not open the Google Sheet: {exc}") from exc


def _worksheet(name: str, headers: list[str]):
    import gspread

    ss = _spreadsheet()
    try:
        return ss.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=1000, cols=max(len(headers), 8))
        ws.append_row(headers)
        return ws
    except Exception as exc:  # noqa: BLE001
        raise SheetsUnavailable(f"Could not open tab '{name}': {exc}") from exc


def _read(name: str, headers: list[str]) -> pd.DataFrame:
    try:
        ws = _worksheet(name, headers)
        records = ws.get_all_records()
    except SheetsUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SheetsUnavailable(f"Could not read tab '{name}': {exc}") from exc

    if not records:
        return pd.DataFrame(columns=headers)
    df = pd.DataFrame(records)
    for col in headers:
        if col not in df.columns:
            df[col] = ""
    return df[headers]


def read_timeline() -> pd.DataFrame:
    return _cached_read(TIMELINE_SHEET, tuple(TIMELINE_HEADERS))


def read_pipeline() -> pd.DataFrame:
    return _cached_read(PIPELINE_SHEET, tuple(PIPELINE_HEADERS))


@st.cache_data(ttl=8, show_spinner=False)
def _cached_read(name: str, headers: tuple) -> pd.DataFrame:
    # Streamlit reruns the whole script on every tap/click, and the free
    # Sheets API tier caps out at 60 read requests/minute/user. A few
    # seconds of caching absorbs that rerun storm without ever showing
    # stale data for more than a moment — writes below force-clear this
    # immediately, so your own edits still show up right away.
    return _read(name, list(headers))


def clear_read_cache() -> None:
    _cached_read.clear()


def is_seeded() -> bool:
    """True once the Timeline tab actually has rows in it."""
    return len(read_timeline()) > 0


def seed(timeline: pd.DataFrame, pipeline: pd.DataFrame) -> None:
    """One-time bulk write. Only ever called when the Sheet is empty, so
    this can never clobber live data — see data_source.load_snapshot()."""
    tl_ws = _worksheet(TIMELINE_SHEET, TIMELINE_HEADERS)
    pl_ws = _worksheet(PIPELINE_SHEET, PIPELINE_HEADERS)

    tl_rows = timeline.reindex(columns=TIMELINE_HEADERS).fillna("").astype(str).values.tolist()
    pl_rows = pipeline.reindex(columns=PIPELINE_HEADERS).fillna("").astype(str).values.tolist()

    tl_ws.clear()
    tl_ws.append_row(TIMELINE_HEADERS)
    if tl_rows:
        tl_ws.append_rows(tl_rows, value_input_option="USER_ENTERED")

    pl_ws.clear()
    pl_ws.append_row(PIPELINE_HEADERS)
    if pl_rows:
        pl_ws.append_rows(pl_rows, value_input_option="USER_ENTERED")

    clear_read_cache()


def _find_row(ws, event_id: str) -> int | None:
    import gspread

    try:
        cell = ws.find(str(event_id), in_column=1)
    except gspread.exceptions.CellNotFound:
        return None
    except Exception as exc:  # noqa: BLE001
        raise SheetsUnavailable(f"Lookup failed for {event_id}: {exc}") from exc
    return cell.row if cell else None


def append_row(sheet_name: str, headers: list[str], row: dict) -> None:
    ws = _worksheet(sheet_name, headers)
    ordered = [str(row.get(h, "")) for h in headers]
    ws.append_row(ordered, value_input_option="USER_ENTERED")
    clear_read_cache()


def update_row(sheet_name: str, headers: list[str], event_id: str, row: dict) -> None:
    ws = _worksheet(sheet_name, headers)
    ordered = [str(row.get(h, "")) for h in headers]
    row_idx = _find_row(ws, event_id)
    if row_idx is None:
        ws.append_row(ordered, value_input_option="USER_ENTERED")
        clear_read_cache()
        return
    end_col = chr(ord("A") + len(headers) - 1)
    ws.update(range_name=f"A{row_idx}:{end_col}{row_idx}", values=[ordered])
    clear_read_cache()


def delete_row(sheet_name: str, headers: list[str], event_id: str) -> None:
    ws = _worksheet(sheet_name, headers)
    row_idx = _find_row(ws, event_id)
    if row_idx is not None:
        ws.delete_rows(row_idx)
        clear_read_cache()


def move_row(
    from_sheet: str, from_headers: list[str],
    to_sheet: str, to_headers: list[str],
    event_id: str, new_row: dict,
) -> None:
    """A Pipeline (Scheduled) event being marked Completed: delete it out
    of Pipeline and append it into Timeline in one call."""
    delete_row(from_sheet, from_headers, event_id)
    append_row(to_sheet, to_headers, new_row)


def next_event_id(timeline: pd.DataFrame, pipeline: pd.DataFrame) -> str:
    """IDs entered through the app are prefixed 'S' (session) to stay
    visually distinct from the original 'T'/'P' baseline rows, though
    both are equally live/editable now that everything is one Sheet."""
    nums = []
    for df in (timeline, pipeline):
        if "Event ID" not in df.columns:
            continue
        for raw in df["Event ID"]:
            s = str(raw)
            if s.startswith("S") and s[1:].isdigit():
                nums.append(int(s[1:]))
    n = (max(nums) + 1) if nums else 1
    return f"S{n:04d}"


LOGOS_SHEET = "Logos"
LOGO_HEADERS = ["Key", "Filename", "Scale", "X", "Y", "ImageBase64"]


def read_logos() -> pd.DataFrame:
    return _cached_read(LOGOS_SHEET, tuple(LOGO_HEADERS))


def save_logo(key: str, filename: str, scale: float, x: int, y: int, image_base64: str) -> None:
    """Upserts one logo (calibration + the actual image bytes, base64-
    encoded as plain text) by Key -- same find-or-append mechanism as
    events, using update_row's existing column-1 lookup. A single small
    PNG (a few KB) base64-encodes to a few thousand characters, well
    under a Sheet cell's ~50,000-character limit.
    """
    update_row(
        LOGOS_SHEET, LOGO_HEADERS, key,
        {"Key": key, "Filename": filename, "Scale": scale, "X": x, "Y": y, "ImageBase64": image_base64},
    )
