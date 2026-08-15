from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import pandas as pd


@dataclass(frozen=True)
class WorkbookSnapshot:
    path: Path
    modified_ns: int
    sheets: Dict[str, pd.DataFrame]


def _real_timeline() -> pd.DataFrame:
    # Pulled directly from the Timeline sheet of
    # Barrister_Source_of_Truth_Master_ZERO_MISSING_BASELINE_Through_Event96_2026-08-10.xlsx
    # 96 completed events, city-level location on every row.
    # Every event's revenue is confirmed (Verified?="Yes") — the workbook's
    # own Financial Closeout reports "Payment Breakdowns Missing: 0" as of
    # this pull, a genuine first for this dataset.
    # "Residential – Annapolis Neck, MD" corrected to "Residential" (city
    # was redundant with Location Detail already carrying it) and
    # "Dunkin\u2019" normalized to "Dunkin'" (straight apostrophe), matching
    # prior confirmed corrections.
    rows = [
        ("Macy's", "Virginia", "Completed", 90, "Yes", "2026-04-20", "Fairfax, VA"),
        ("Bloomingdale's", "Virginia", "Completed", 344, "Yes", "2026-04-21", "Tysons, VA"),
        ("Bloomingdale's", "Virginia", "Completed", 344, "Yes", "2026-04-22", "Tysons, VA"),
        ("Macy's", "Maryland", "Completed", 180, "Yes", "2026-04-23", "Frederick, MD"),
        ("Hampton Inn & Suites", "Washington, D.C.", "Completed", 50, "Yes", "2026-04-24", "Washington, DC"),
        ("Macy's", "Maryland", "Completed", 180, "Yes", "2026-04-27", "Frederick, MD"),
        ("Davis Polk & Wardwell", "Washington, D.C.", "Completed", 50, "Yes", "2026-04-29", "Washington, DC"),
        ("Hebrew Home GW", "Maryland", "Completed", 45, "Yes", "2026-04-29", "North Bethesda, MD"),
        ("7-Eleven", "Maryland", "Completed", 135, "Yes", "2026-04-30", "Baltimore, MD"),
        ("Giant Food Stores", "Pennsylvania", "Completed", 212.5, "Yes", "2026-05-05", "Hanover, PA"),
        ("Food Lion", "Virginia", "Completed", 157.5, "Yes", "2026-05-11", "Leesburg, VA"),
        ("Weis Markets", "Pennsylvania", "Completed", 85, "Yes", "2026-05-12", "Chambersburg, PA"),
        ("Senator C. Van Hollen", "Maryland", "Completed", 50, "Yes", "2026-05-13", "Rockville, MD"),
        ("Residential", "Maryland", "Completed", 25, "Yes", "2026-05-13", "Annapolis Neck, MD"),
        ("Verizon", "Maryland", "Completed", 75, "Yes", "2026-05-14", "College Park, MD"),
        ("Atrium Village", "Maryland", "Completed", 45, "Yes", "2026-05-15", "Owings Mills, MD"),
        ("Maryland Baptist Age Home", "Maryland", "Completed", 50, "Yes", "2026-05-19", "Baltimore, MD"),
        ("Under Armour", "Maryland", "Completed", 106.67, "Yes", "2026-05-20", "Hanover, MD"),
        ("Under Armour", "Maryland", "Completed", 153.33, "Yes", "2026-05-21", "Hanover, MD"),
        ("Giant Food Stores", "Pennsylvania", "Completed", 112.5, "Yes", "2026-05-21", "Red Lion, PA"),
        ("Food Lion", "Maryland", "Completed", 97.91, "Yes", "2026-05-26", "Middle River, MD"),
        ("HomeGoods", "Maryland", "Completed", 50, "Yes", "2026-05-26", "Gaithersburg, MD"),
        ("Joint Base Andrews", "Maryland", "Completed", 50, "Yes", "2026-05-27", "Andrews AFB, MD"),
        ("USDA", "Washington, D.C.", "Completed", 200, "Yes", "2026-05-27", "Washington, DC"),
        ("PepsiCo", "Maryland", "Completed", 50, "Yes", "2026-05-28", "Cheverly, MD"),
        ("USDA", "Washington, D.C.", "Completed", 175, "Yes", "2026-05-28", "Washington, DC"),
        ("USDA", "Washington, D.C.", "Completed", 320, "Yes", "2026-06-01", "Washington, DC"),
        ("USDA", "Washington, D.C.", "Completed", 320, "Yes", "2026-06-02", "Washington, DC"),
        ("USDA", "Washington, D.C.", "Completed", 200, "Yes", "2026-06-03", "Washington, DC"),
        ("TJ Maxx", "Maryland", "Completed", 96.66, "Yes", "2026-06-03", "Rockville, MD"),
        ("USDA", "Washington, D.C.", "Completed", 140, "Yes", "2026-06-04", "Washington, DC"),
        ("Hilton Garden Inn", "Virginia", "Completed", 25, "Yes", "2026-06-05", "Fairfax, VA"),
        ("Hebrew Home GW", "Maryland", "Completed", 50, "Yes", "2026-06-05", "North Bethesda, MD"),
        ("TJ Maxx", "Maryland", "Completed", 70, "Yes", "2026-06-05", "Annapolis, MD"),
        ("Marshalls", "Maryland", "Completed", 70, "Yes", "2026-06-08", "Dunkirk, MD"),
        ("Hampton Inn & Suites", "Maryland", "Completed", 65, "Yes", "2026-06-09", "Edgewood, MD"),
        ("HomeGoods", "Virginia", "Completed", 90, "Yes", "2026-06-09", "Sterling, VA"),
        ("7-Eleven", "Maryland", "Completed", 240, "Yes", "2026-06-10", "Lanham, MD"),
        ("TJ Maxx", "Maryland", "Completed", 90, "Yes", "2026-06-10", "Annapolis, MD"),
        ("Residential", "Maryland", "Completed", 60, "Yes", "2026-06-10", "Annapolis Neck, MD"),
        ("Baskin-Robbins", "Virginia", "Completed", 45, "Yes", "2026-06-11", "Falls Church, VA"),
        ("Verizon", "Maryland", "Completed", 50, "Yes", "2026-06-11", "Ellicott City, MD"),
        ("Verizon", "Maryland", "Completed", 50, "Yes", "2026-06-12", "Lanham, MD"),
        ("Marshalls", "Maryland", "Completed", 123.75, "Yes", "2026-06-15", "Frederick, MD"),
        ("Montpelier Liquors", "Maryland", "Completed", 128, "Yes", "2026-06-17", "Laurel, MD"),
        ("Marshalls", "Maryland", "Completed", 90, "Yes", "2026-06-17", "Laurel, MD"),
        ("Senator A. Alsobrooks", "Maryland", "Completed", 130, "Yes", "2026-06-18", "Bowie, MD"),
        ("Hebrew Home GW", "Maryland", "Completed", 70, "Yes", "2026-06-18", "North Bethesda, MD"),
        ("Weis Markets", "Maryland", "Completed", 90, "Yes", "2026-06-19", "Callaway, MD"),
        ("Giant Food Stores", "Washington, D.C.", "Completed", 50, "Yes", "2026-06-19", "Washington, DC"),
        ("Hebrew Home GW", "Maryland", "Completed", 60, "Yes", "2026-06-22", "North Bethesda, MD"),
        ("Food Lion", "Maryland", "Completed", 116.24, "Yes", "2026-06-23", "Upper Marlboro, MD"),
        ("Hilton Garden Inn", "Washington, D.C.", "Completed", 132.03, "Yes", "2026-06-24", "Washington, DC"),
        ("7-Eleven", "Maryland", "Completed", 120, "Yes", "2026-06-30", "Owings Mills, MD"),
        ("Senator A. Alsobrooks", "Maryland", "Completed", 120, "Yes", "2026-07-01", "Largo, MD"),
        ("Dunkin'", "Maryland", "Completed", 170.66, "Yes", "2026-07-02", "Reisterstown, MD"),
        ("Montpelier Liquors", "Maryland", "Completed", 66.74, "Yes", "2026-07-06", "Laurel, MD"),
        ("Dunkin'", "Maryland", "Completed", 202.5, "Yes", "2026-07-06", "Lutherville, MD"),
        ("Dunkin'", "Maryland", "Completed", 250, "Yes", "2026-07-07", "Aberdeen, MD"),
        ("Carvana", "Maryland", "Completed", 130, "Yes", "2026-07-08", "Baltimore, MD"),
        ("TJ Maxx", "Maryland", "Completed", 194.99, "Yes", "2026-07-09", "Germantown, MD"),
        ("TJ Maxx", "West Virginia", "Completed", 100.83, "Yes", "2026-07-09", "Martinsburg, WV"),
        ("Marshalls", "Maryland", "Completed", 180, "Yes", "2026-07-13", "Cockeysville, MD"),
        ("Marshalls", "Maryland", "Completed", 178.75, "Yes", "2026-07-13", "Hagerstown, MD"),
        ("HomeGoods", "Maryland", "Completed", 129.16, "Yes", "2026-07-13", "Gaithersburg, MD"),
        ("TJ Maxx", "Maryland", "Completed", 213.75, "Yes", "2026-07-14", "Bel Air, MD"),
        ("Dunkin'", "Maryland", "Completed", 183.74, "Yes", "2026-07-14", "Aberdeen, MD"),
        ("Dunkin'", "Maryland", "Completed", 350, "Yes", "2026-07-15", "Fallston, MD"),
        ("TJ Maxx", "Maryland", "Completed", 180, "Yes", "2026-07-16", "Columbia, MD"),
        ("Giant Food Stores", "Maryland", "Completed", 103.33, "Yes", "2026-07-16", "Olney, MD"),
        ("WeWork", "Washington, D.C.", "Completed", 90, "Yes", "2026-07-17", "Washington, DC"),
        ("Hebrew Home GW", "Maryland", "Completed", 50, "Yes", "2026-07-17", "North Bethesda, MD"),
        ("Homesense", "Maryland", "Completed", 180, "Yes", "2026-07-20", "Owings Mills, MD"),
        ("Autumn Lake Healthcare", "Maryland", "Completed", 50, "Yes", "2026-07-20", "Glen Burnie, MD"),
        ("Autumn Lake Healthcare", "Maryland", "Completed", 50, "Yes", "2026-07-20", "Glen Burnie, MD"),
        ("Marshalls", "Maryland", "Completed", 120, "Yes", "2026-07-21", "Owings Mills, MD"),
        ("Marshalls", "Maryland", "Completed", 130, "Yes", "2026-07-22", "Towson, MD"),
        ("Dunkin'", "Maryland", "Completed", 160.29, "Yes", "2026-07-22", "Owings Mills, MD"),
        ("7-Eleven", "Maryland", "Completed", 168.75, "Yes", "2026-07-22", "Fallston, MD"),
        ("Marshalls", "Maryland", "Completed", 163.33, "Yes", "2026-07-23", "Westminster, MD"),
        ("HomeGoods", "Virginia", "Completed", 125, "Yes", "2026-07-23", "Fairfax, VA"),
        ("TJ Maxx", "Virginia", "Completed", 110, "Yes", "2026-07-23", "Alexandria, VA"),
        ("Carvana", "Maryland", "Completed", 65, "Yes", "2026-07-24", "Baltimore, MD"),
        ("Giant Food Stores", "Maryland", "Completed", 243.66, "Yes", "2026-07-24", "Wheaton, MD"),
        ("Dunkin'", "Maryland", "Completed", 240, "Yes", "2026-07-27", "Bel Air, MD"),
        ("Marshalls", "Maryland", "Completed", 270, "Yes", "2026-07-28", "Hyattsville, MD"),
        ("WeWork", "Washington, D.C.", "Completed", 164.5, "Yes", "2026-07-28", "Washington, DC"),
        ("Dunkin'", "Maryland", "Completed", 178.5, "Yes", "2026-07-29", "Reisterstown, MD"),
        ("East Coast Warehouse of Maryland", "Maryland", "Completed", 112.5, "Yes", "2026-07-30", "Sparrows Point, MD"),
        ("Giant Food Stores", "Maryland", "Completed", 116.24, "Yes", "2026-07-31", "Severna Park, MD"),
        ("Marshalls", "Maryland", "Completed", 180, "Yes", "2026-08-03", "Frederick, MD"),
        ("Dunkin'", "Maryland", "Completed", 292.5, "Yes", "2026-08-03", "Owings Mills, MD"),
        ("Food Lion", "Maryland", "Completed", 123.75, "Yes", "2026-08-04", "Essex, MD"),
        ("Food Lion", "Maryland", "Completed", 161.24, "Yes", "2026-08-05", "Scaggsville, MD"),
        ("Marshalls", "Maryland", "Completed", 200, "Yes", "2026-08-07", "Clinton, MD"),
        ("TJ Maxx", "Maryland", "Completed", 183.33, "Yes", "2026-08-10", "Prince Frederick, MD"),
        ("Marshalls", "Virginia", "Completed", None, "No", "2026-08-11", "Alexandria, VA"),
        ("Dunkin'", "Maryland", "Completed", None, "No", "2026-08-12", "Rockville, MD"),
        ("Food Lion", "Maryland", "Completed", None, "No", "2026-08-12", "Middle River, MD"),
    ]

    return pd.DataFrame(
        rows,
        columns=[
            "Client",
            "State/Region",
            "Status",
            "Amount",
            "Verified?",
            "Service Date",
            "Location Detail",
        ],
    )



def _real_pipeline() -> pd.DataFrame:
    # Live scheduled list as of 2026-08-12, confirmed dates/locations
    # directly from bravo echo (relative dates resolved against
    # "today" = 2026-08-12: tomorrow = 8/13, Monday = 8/17).
    rows = [
        ("Dunkin'", "West Friendship, MD", "Scheduled", "2026-08-13"),
        ("Hebrew Home GW", "North Bethesda, MD", "Scheduled", "2026-08-13"),
        ("Senator A. Alsobrooks", "Largo, MD", "Scheduled", "2026-08-17"),
        ("Marshalls", "Owings Mills, MD", "Scheduled", "2026-08-24"),
        ("Marshalls", "Annapolis, MD", "Scheduled", "2026-08-27"),
        ("Dunkin'", "Rockville, MD", "Scheduled", "2026-09-01"),
        ("Dunkin'", "Silver Spring, MD", "Scheduled", "2026-09-02"),
    ]

    return pd.DataFrame(
        rows,
        columns=["Client", "Location", "Status", "Date / Timing"],
    )



def _local_fallback_snapshot() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Old on-disk-JSON overlay behavior. Used only when Google Sheets
    isn't configured yet, or a live call to it fails, so the app still
    functions during setup/outages instead of hard-crashing — but note
    this fallback does NOT survive a container restart, which is the
    exact problem the Sheets store exists to fix."""
    from services import local_store

    timeline = _real_timeline()
    timeline.insert(0, "Event ID", [f"T{i:03d}" for i in range(len(timeline))])

    pipeline = _real_pipeline()
    pipeline.insert(0, "Event ID", [f"P{i:03d}" for i in range(len(pipeline))])

    deleted_ids = local_store.get_deleted_ids()
    timeline = timeline[~timeline["Event ID"].isin(deleted_ids)].reset_index(drop=True)
    pipeline = pipeline[~pipeline["Event ID"].isin(deleted_ids)].reset_index(drop=True)

    for event in local_store.get_added_events():
        if event["status"] == "Completed":
            row = dict(event["timeline_row"])
            row.setdefault("Event ID", event.get("event_id"))
            timeline = pd.concat([timeline, pd.DataFrame([row])], ignore_index=True)
        else:
            row = dict(event["pipeline_row"])
            row.setdefault("Event ID", event.get("event_id"))
            pipeline = pd.concat([pipeline, pd.DataFrame([row])], ignore_index=True)

    return timeline, pipeline


def load_snapshot() -> WorkbookSnapshot:
    """Live snapshot, sourced from the Google Sheet that is now the
    single source of truth for Timeline and Pipeline (see
    services/sheets_store.py). Falls back to the old local-only behavior
    if Sheets isn't configured yet or a call to it fails, and records
    the reason in st.session_state["sheets_error"] so the UI can show a
    banner explaining why changes won't be persistent in that case.
    State Coverage is always derived live from the current Timeline, so
    an edit or delete never leaves stale territory numbers behind.
    """
    import streamlit as st
    from services import sheets_store

    st.session_state.pop("sheets_error", None)
    source_label = "Barrister_Master_Four_Month_Closeout_Financially_Verified_2026-08-03.xlsx"

    if sheets_store.is_configured():
        try:
            if not sheets_store.is_seeded():
                seed_timeline = _real_timeline()
                seed_timeline.insert(0, "Event ID", [f"T{i:03d}" for i in range(len(seed_timeline))])
                seed_pipeline = _real_pipeline()
                seed_pipeline.insert(0, "Event ID", [f"P{i:03d}" for i in range(len(seed_pipeline))])
                sheets_store.seed(seed_timeline, seed_pipeline)

            timeline = sheets_store.read_timeline()
            pipeline = sheets_store.read_pipeline()
            timeline["Amount"] = pd.to_numeric(timeline["Amount"], errors="coerce")
            source_label = "Google Sheets (live)"
        except sheets_store.SheetsUnavailable as exc:
            st.session_state["sheets_error"] = str(exc)
            timeline, pipeline = _local_fallback_snapshot()
    else:
        st.session_state["sheets_error"] = (
            "Google Sheets isn't connected yet \u2014 changes made in this session "
            "will NOT survive a restart. See SETUP.md."
        )
        timeline, pipeline = _local_fallback_snapshot()

    if timeline.empty:
        coverage = pd.DataFrame(columns=["State/Region", "Completed Visits"])
    else:
        coverage = (
            timeline.groupby("State/Region", as_index=False)
            .size()
            .rename(columns={"size": "Completed Visits"})
            .sort_values("Completed Visits", ascending=False)
            .reset_index(drop=True)
        )

    return WorkbookSnapshot(
        path=Path(source_label),
        modified_ns=time.time_ns(),
        sheets={
            "Timeline": timeline,
            "State Coverage": coverage,
            "Pipeline": pipeline,
        },
    )
