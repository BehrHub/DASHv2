from __future__ import annotations

from datetime import date, datetime
from html import escape
from io import BytesIO

import pandas as pd
import streamlit as st

from components.journey import compact_state_code
from services.tz import eastern_today, eastern_today_naive


REAL_CLIENTS = [
    "7-Eleven", "Atrium Village", "Autumn Lake Healthcare", "Baskin-Robbins",
    "Bloomingdale's", "Carvana", "Davis Polk & Wardwell", "Dunkin'",
    "East Coast Warehouse of Maryland", "Food Lion", "Giant Food Stores",
    "Hampton Inn & Suites", "Hebrew Home GW",
    "Hilton Garden Inn", "HomeGoods", "HomeSense", "Joint Base Andrews",
    "Macy's", "Marshalls", "Maryland Baptist Age Home",
    "Montpelier Liquors", "Senator A. Alsobrooks",
    "Senator C. Van Hollen", "PepsiCo",
    "Residential", "TJ Maxx", "USDA",
    "Under Armour", "Verizon", "WeWork", "Weis Markets",
]

STATE_CODE_TO_NAME = {
    "MD": "Maryland",
    "VA": "Virginia",
    "DC": "Washington, DC",
    "PA": "Pennsylvania",
    "WV": "West Virginia",
}


def _parse_location(raw: str) -> tuple[str, str, str] | None:
    """Splits 'Columbia, MD' into ('Columbia', 'Maryland', 'MD'). None if unparseable."""
    if not raw or "," not in raw:
        return None
    city_part, _, state_part = raw.rpartition(",")
    city = city_part.strip()
    code = compact_state_code(state_part.strip())
    state_name = STATE_CODE_TO_NAME.get(code)
    if not city or not state_name:
        return None
    return city, state_name, code


def _known_locations(timeline: pd.DataFrame) -> list[str]:
    """Real 'City, ST' combos pulled from the Timeline's Location Detail
    column — same-named cities in different states (e.g. Hanover, MD vs
    Hanover, PA) are kept as separate entries.

    Normalizes any full state names (e.g. a session-added 'City, Maryland')
    down to the abbreviated code so they collapse onto the same real entry
    instead of appearing as a separate, inconsistent duplicate.
    """
    if "Location Detail" not in timeline.columns:
        return []
    values = timeline["Location Detail"].dropna().astype(str).str.strip()
    values = values[values != ""]

    normalized: set[str] = set()
    for value in values:
        parsed = _parse_location(value)
        if parsed:
            city, _state_name, code = parsed
            normalized.add(f"{city}, {code}")
        else:
            normalized.add(value)
    return sorted(normalized)


def _next_event_id(timeline: pd.DataFrame, pipeline: pd.DataFrame) -> str:
    from services import sheets_store
    return sheets_store.next_event_id(timeline, pipeline)


FORM_CSS = """
<style>
*:not(.app-header-word) { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif !important; }
.event-page-wrap { max-width: 620px; margin: 0 auto; }
.event-page-title { font-size: 15px; font-weight: 900; letter-spacing: 1px; color: #fff; text-transform: uppercase; margin: 4px 0 12px; }
.event-preview, .upcoming-panel, .modify-panel {
    background: radial-gradient(circle at 100% -10%, rgba(56,189,248,.08), transparent 42%), rgba(23,27,40,.55);
    border: 1px solid rgba(56,189,248,.3);
    border-radius: 20px;
    padding: 18px 20px;
    margin-bottom: 16px;
    box-shadow: 0 15px 35px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.1);
}
.preview-row { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px solid rgba(255,255,255,.06); font-size: 12px; }
.preview-row:last-child { border-bottom: none; }
.preview-label { color: #b8c4d9; font-weight: 800; letter-spacing: .4px; text-transform: uppercase; font-size: 11.5px; }
.preview-value { color: #fff; font-weight: 800; font-size: 13px; text-align: right; }
.event-success-banner {
    background: rgba(52,211,153,.1); border: 1px solid rgba(52,211,153,.4);
    border-radius: 14px; padding: 10px 16px; margin-bottom: 12px;
    color: #34d399; font-size: 12px; font-weight: 700;
}
.upcoming-title, .modify-title { font-size: 16px; font-weight: 900; letter-spacing: .5px; color: #fff; text-transform: uppercase; margin: 4px 0 10px; }
.upcoming-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.upcoming-item { display: flex; flex-direction: column; justify-content: center; padding: 9px 11px; border-radius: 10px; font-size: 12px; text-align: left; min-height: 50px; }
.upcoming-client { color: #fff; font-weight: 800; font-size: 14.5px; }
.upcoming-meta { color: #7dd3fc; font-size: 13px; margin-top: 2px; }
.upcoming-date-cell { display: flex; align-items: center; justify-content: center; height: 44px; color: #f9a8d4; font-weight: 900; font-size: 14px; white-space: nowrap; text-shadow: 0 0 10px rgba(244,114,182,.6); }
.upcoming-empty { color: #64748b; font-size: 12px; }
div[data-testid="stButton"] button[kind="secondary"] { padding: 4px 0 !important; }
.complete-panel {
    background: rgba(52,211,153,.06); border: 1px solid rgba(52,211,153,.28);
    border-radius: 14px; padding: 12px 14px 14px; margin: -2px 0 10px;
}
.complete-preview { color: #6ee7b7; font-weight: 900; font-size: 15px; text-align: center; margin: 2px 0 10px; }
.download-title { font-size: 16px; font-weight: 900; letter-spacing: .5px; color: #fff; text-transform: uppercase; margin: 4px 0 10px; }
div[data-testid="stDownloadButton"] button {
    width: 100%; background: linear-gradient(135deg, rgba(52,211,153,.18), rgba(52,211,153,.06));
    border: 1px solid rgba(52,211,153,.5); border-radius: 12px; color: #6ee7b7;
    font-weight: 900; letter-spacing: .5px; text-transform: uppercase; font-size: 12.5px;
    padding: 10px 0;
}
</style>
"""


def _mark_complete(pipeline_row: pd.Series, amount: float) -> None:
    from services import sheets_store

    parsed = _parse_location(str(pipeline_row["Location"]))
    location_detail = str(pipeline_row["Location"])
    state_name = parsed[1] if parsed else "Maryland"
    event_id = str(pipeline_row["Event ID"])
    new_row = {
        "Event ID": event_id, "Client": pipeline_row["Client"], "State/Region": state_name,
        "Status": "Completed",
        # Rate x hours, entered right here at completion time, so the
        # real payout lands in the Timeline immediately instead of a
        # placeholder that needs a manual correction pass later.
        "Amount": round(amount, 2), "Verified?": "Yes", "Service Date": pipeline_row["Date / Timing"],
        "Location Detail": location_detail, "Billing Type": "Hourly",
    }
    sheets_store.move_row(
        sheets_store.PIPELINE_SHEET, sheets_store.PIPELINE_HEADERS,
        sheets_store.TIMELINE_SHEET, sheets_store.TIMELINE_HEADERS,
        event_id, new_row,
    )


def _render_upcoming(pipeline: pd.DataFrame) -> None:
    count = len(pipeline)
    st.markdown(f'<div class="upcoming-title">Upcoming Events ({count})</div>', unsafe_allow_html=True)

    if pipeline.empty:
        st.markdown('<div class="upcoming-empty">Nothing scheduled.</div>', unsafe_allow_html=True)
        return

    working = pipeline.copy()
    working["__date"] = pd.to_datetime(working["Date / Timing"], errors="coerce")
    working = working.sort_values(["__date", "Event ID"], kind="stable")
    today = eastern_today_naive()
    tomorrow = today + pd.Timedelta(days=1)

    completing_id = st.session_state.get("completing_event_id")

    for _, row in working.iterrows():
        event_id = row["Event ID"]
        date_val = row["__date"]
        if pd.notna(date_val) and date_val.normalize() == today:
            date_label = "TODAY"
        elif pd.notna(date_val) and date_val.normalize() == tomorrow:
            date_label = "TOMORROW"
        elif pd.notna(date_val) and 2 <= (date_val.normalize() - today).days <= 6:
            date_label = date_val.strftime("%A").upper()
        else:
            date_label = date_val.strftime("%b %d") if pd.notna(date_val) else str(row["Date / Timing"])

        text_col, date_col, complete_col, delete_col = st.columns([3.6, 1.5, 0.65, 0.65])
        with text_col:
            st.markdown(
                '<div class="upcoming-item">'
                f'<div class="upcoming-client">{escape(str(row["Client"]))}</div>'
                f'<div class="upcoming-meta">{escape(str(row["Location"]))}</div></div>',
                unsafe_allow_html=True,
            )
        with date_col:
            st.markdown(f'<div class="upcoming-date-cell">{escape(date_label)}</div>', unsafe_allow_html=True)
        with complete_col:
            if st.button("\u2713", key=f"complete_{event_id}", width="stretch"):
                st.session_state["completing_event_id"] = (
                    None if completing_id == event_id else event_id
                )
                st.rerun()
        with delete_col:
            if st.button("\u2715", key=f"delete_{event_id}", width="stretch"):
                from services import sheets_store
                sheets_store.delete_row(sheets_store.PIPELINE_SHEET, sheets_store.PIPELINE_HEADERS, event_id)
                st.rerun()

        if completing_id == event_id:
            st.markdown('<div class="complete-panel">', unsafe_allow_html=True)
            rate_col, hours_col = st.columns(2)
            with rate_col:
                rate = st.number_input(
                    "Rate (\uFF04/hr)", min_value=0.0, step=1.0,
                    value=float(st.session_state.get("last_hourly_rate", 40.0)),
                    key=f"rate_{event_id}",
                )
            with hours_col:
                hours = st.number_input(
                    "Hours stayed", min_value=0.0, step=0.25, value=1.0, key=f"hours_{event_id}",
                )
            payout = rate * hours
            st.markdown(
                f'<div class="complete-preview">Payout: \uFF04{payout:,.2f}</div>',
                unsafe_allow_html=True,
            )
            confirm_col, cancel_col = st.columns(2)
            with confirm_col:
                if st.button(
                    "Confirm & Complete", key=f"confirm_complete_{event_id}",
                    type="primary", width="stretch",
                ):
                    _mark_complete(row, amount=payout)
                    st.session_state["last_hourly_rate"] = rate
                    st.session_state.pop("completing_event_id", None)
                    st.rerun()
            with cancel_col:
                if st.button("Cancel", key=f"cancel_complete_{event_id}", width="stretch"):
                    st.session_state.pop("completing_event_id", None)
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)


def _render_form(known_locations: list[str], timeline: pd.DataFrame, pipeline: pd.DataFrame) -> None:
    if st.session_state.get("last_saved_event"):
        saved = st.session_state.pop("last_saved_event")
        st.markdown(
            f'<div class="event-success-banner">\u2713 Saved &mdash; {escape(saved["client"])} '
            f'({escape(saved["status"])}, {escape(saved["date"])})</div>',
            unsafe_allow_html=True,
        )

    with st.form("add_event_form", clear_on_submit=False):
        status = st.radio("Status", ["Scheduled", "Completed"], horizontal=True, index=0)
        client = st.selectbox(
            "Client", REAL_CLIENTS, index=None,
            placeholder="Start typing or enter a new client", accept_new_options=True,
        )
        location = st.selectbox(
            "Location", known_locations, index=None,
            placeholder="e.g. Columbia, MD", accept_new_options=True,
        )
        billing_type = st.radio("Billing Type", ["Hourly", "Per Trip"], horizontal=True, index=0)
        rate = st.number_input("Rate (\uFF04)", min_value=0.0, step=1.0, value=40.0)
        notes = st.text_area("Notes", height=92)
        event_date = st.date_input("Date", value=eastern_today())
        preview_clicked = st.form_submit_button("Preview", type="primary", width="stretch")

    if preview_clicked:
        parsed = _parse_location(location or "")
        if not client:
            st.error("Client is required.")
        elif not parsed:
            st.error('Location must be "City, ST" \u2014 e.g. "Columbia, MD".')
        else:
            city, state_name, state_code = parsed
            st.session_state["pending_event"] = {
                "client": client, "city": city, "state": state_name, "state_code": state_code,
                "status": status, "billing_type": billing_type, "rate": rate,
                "notes": notes, "event_date": event_date,
            }

    pending = st.session_state.get("pending_event")
    if pending:
        rate_label = f'\uFF04{pending["rate"]:,.0f} / {"hr" if pending["billing_type"] == "Hourly" else "trip"}'
        rows = [
            ("Client", pending["client"]),
            ("Location", f'{pending["city"]}, {pending["state"]}'),
            ("Status", pending["status"]),
            ("Rate", rate_label),
            ("Date", pending["event_date"].strftime("%Y-%m-%d")),
        ]
        if pending["notes"]:
            rows.append(("Notes", pending["notes"]))
        markup = "".join(
            f'<div class="preview-row"><div class="preview-label">{escape(label)}</div>'
            f'<div class="preview-value">{escape(str(value))}</div></div>'
            for label, value in rows
        )
        st.markdown(f'<div class="event-preview">{markup}</div>', unsafe_allow_html=True)

        save_col, cancel_col = st.columns(2)
        if save_col.button("Save Event", type="primary", width="stretch", key="save_new_event"):
            from services import sheets_store

            date_str = pending["event_date"].strftime("%Y-%m-%d")
            location_detail = f'{pending["city"]}, {pending["state_code"]}'
            event_id = _next_event_id(timeline, pipeline)
            if pending["status"] == "Completed":
                sheets_store.append_row(
                    sheets_store.TIMELINE_SHEET, sheets_store.TIMELINE_HEADERS,
                    {
                        "Event ID": event_id, "Client": pending["client"], "State/Region": pending["state"],
                        "Status": "Completed", "Amount": pending["rate"], "Verified?": "No",
                        "Service Date": date_str, "Location Detail": location_detail,
                        "Billing Type": pending["billing_type"],
                    },
                )
            else:
                sheets_store.append_row(
                    sheets_store.PIPELINE_SHEET, sheets_store.PIPELINE_HEADERS,
                    {
                        "Event ID": event_id, "Client": pending["client"], "Location": location_detail,
                        "Status": "Scheduled", "Date / Timing": date_str,
                    },
                )
            st.session_state["last_saved_event"] = {
                "client": pending["client"], "status": pending["status"], "date": date_str,
            }
            st.session_state.pop("pending_event", None)
            st.rerun()
        if cancel_col.button("Cancel", width="stretch", key="cancel_new_event"):
            st.session_state.pop("pending_event", None)
            st.rerun()


def _event_options(timeline: pd.DataFrame, pipeline: pd.DataFrame) -> dict[str, dict]:
    options: dict[str, dict] = {}

    pipeline_sorted = pipeline.copy()
    pipeline_sorted["__date"] = pd.to_datetime(pipeline_sorted["Date / Timing"], errors="coerce")
    pipeline_sorted = pipeline_sorted.sort_values("__date", ascending=True)

    timeline_sorted = timeline.copy()
    timeline_sorted["__date"] = pd.to_datetime(timeline_sorted["Service Date"], errors="coerce")
    timeline_sorted = timeline_sorted.sort_values("__date", ascending=False)

    for _, row in pipeline_sorted.iterrows():
        date_val = row["__date"]
        date_label = date_val.strftime("%b %d, %Y") if pd.notna(date_val) else str(row["Date / Timing"])
        label = f'{row["Client"]} \u2014 {date_label} (Scheduled)'
        options[label] = {
            "event_id": row["Event ID"], "kind": "pipeline", "client": row["Client"],
            "location": row["Location"], "state": "", "status": "Scheduled",
            "rate": 40.0, "billing_type": "Hourly", "notes": "",
            "date": date_val.date() if pd.notna(date_val) else eastern_today(),
        }

    for _, row in timeline_sorted.iterrows():
        date_val = row["__date"]
        date_label = date_val.strftime("%b %d, %Y") if pd.notna(date_val) else str(row["Service Date"])
        label = f'{row["Client"]} \u2014 {date_label} (Completed)'
        options[label] = {
            "event_id": row["Event ID"], "kind": "timeline", "client": row["Client"],
            "location": row.get("Location Detail") or row["State/Region"],
            "state": row["State/Region"], "status": "Completed",
            "rate": float(row["Amount"]) if pd.notna(row["Amount"]) else 40.0,
            "billing_type": row.get("Billing Type") or "Hourly",
            "notes": "", "date": date_val.date() if pd.notna(date_val) else eastern_today(),
        }

    return options


def _apply_save(
    original_kind: str, original_id: str, new_status: str,
    timeline_row: dict | None, pipeline_row: dict | None,
) -> None:
    from services import sheets_store

    if new_status == "Completed":
        if original_kind == "pipeline":
            sheets_store.move_row(
                sheets_store.PIPELINE_SHEET, sheets_store.PIPELINE_HEADERS,
                sheets_store.TIMELINE_SHEET, sheets_store.TIMELINE_HEADERS,
                original_id, timeline_row,
            )
        else:
            sheets_store.update_row(
                sheets_store.TIMELINE_SHEET, sheets_store.TIMELINE_HEADERS, original_id, timeline_row,
            )
    else:
        if original_kind == "timeline":
            sheets_store.move_row(
                sheets_store.TIMELINE_SHEET, sheets_store.TIMELINE_HEADERS,
                sheets_store.PIPELINE_SHEET, sheets_store.PIPELINE_HEADERS,
                original_id, pipeline_row,
            )
        else:
            sheets_store.update_row(
                sheets_store.PIPELINE_SHEET, sheets_store.PIPELINE_HEADERS, original_id, pipeline_row,
            )


def _apply_delete(kind: str, event_id: str) -> None:
    from services import sheets_store

    sheet = sheets_store.TIMELINE_SHEET if kind == "timeline" else sheets_store.PIPELINE_SHEET
    headers = sheets_store.TIMELINE_HEADERS if kind == "timeline" else sheets_store.PIPELINE_HEADERS
    sheets_store.delete_row(sheet, headers, event_id)


def _render_modify(timeline: pd.DataFrame, pipeline: pd.DataFrame, known_locations: list[str]) -> None:
    st.markdown('<div class="modify-title">Edit or Remove an Event</div>', unsafe_allow_html=True)

    options = _event_options(timeline, pipeline)
    if not options:
        st.markdown('<div class="upcoming-empty">No events to edit.</div>', unsafe_allow_html=True)
        return

    selected_label = st.selectbox(
        "Select an event", list(options.keys()), index=None,
        placeholder="Choose an event to edit or remove", key="modify_select",
    )

    if selected_label:
        original = options[selected_label]

        with st.form("modify_event_form"):
            m_status = st.radio(
                "Status", ["Scheduled", "Completed"], horizontal=True,
                index=0 if original["status"] == "Scheduled" else 1,
            )
            m_client = st.selectbox(
                "Client", REAL_CLIENTS, index=REAL_CLIENTS.index(original["client"])
                if original["client"] in REAL_CLIENTS else None,
                accept_new_options=True,
            )
            location_options = sorted(set(known_locations) | {str(original["location"])})
            m_location = st.selectbox(
                "Location", location_options,
                index=location_options.index(str(original["location"])), accept_new_options=True,
            )
            m_billing = st.radio(
                "Billing Type", ["Hourly", "Per Trip"], horizontal=True,
                index=0 if original["billing_type"] == "Hourly" else 1,
            )
            m_rate = st.number_input("Rate (\uFF04)", min_value=0.0, step=1.0, value=original["rate"])
            m_notes = st.text_area("Notes", value=original["notes"], height=92)
            m_date = st.date_input("Date", value=original["date"])

            save_col, delete_col = st.columns(2)
            m_save = save_col.form_submit_button("Save Changes", type="primary", width="stretch")
            m_delete = delete_col.form_submit_button("Delete Event", width="stretch")

        if m_save:
            parsed = _parse_location(m_location or "")
            if not m_client or not parsed:
                st.error('Client and a valid "City, ST" location are required.')
            else:
                city, state_name, state_code = parsed
                location_detail = f"{city}, {state_code}"
                date_str = m_date.strftime("%Y-%m-%d")
                event_id = str(original["event_id"])
                if m_status == "Completed":
                    timeline_row = {
                        "Event ID": event_id, "Client": m_client, "State/Region": state_name,
                        "Status": "Completed", "Amount": m_rate, "Verified?": "No",
                        "Service Date": date_str, "Location Detail": location_detail,
                        "Billing Type": m_billing,
                    }
                    _apply_save(original["kind"], event_id, "Completed", timeline_row, None)
                else:
                    pipeline_row = {
                        "Event ID": event_id, "Client": m_client, "Location": location_detail,
                        "Status": "Scheduled", "Date / Timing": date_str,
                    }
                    _apply_save(original["kind"], event_id, "Scheduled", None, pipeline_row)
                st.success(f"Updated {m_client}.")
                st.rerun()

        if m_delete:
            _apply_delete(original["kind"], str(original["event_id"]))
            st.success(f'Removed {original["client"]}.')
            st.rerun()


def _build_master_workbook(
    timeline: pd.DataFrame, pipeline: pd.DataFrame, state_coverage: pd.DataFrame | None
) -> bytes:
    """Builds the current live Timeline/Pipeline/State Coverage sheets into
    a real .xlsx in memory, matching the workbook the app is otherwise
    driven by, so it can be downloaded, saved, and handed back for edits.
    """
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        timeline.to_excel(writer, sheet_name="Timeline", index=False)
        pipeline.to_excel(writer, sheet_name="Pipeline", index=False)
        if state_coverage is not None and not state_coverage.empty:
            state_coverage.to_excel(writer, sheet_name="State Coverage", index=False)
    return buffer.getvalue()


def _render_download(
    timeline: pd.DataFrame, pipeline: pd.DataFrame, state_coverage: pd.DataFrame | None
) -> None:
    st.markdown('<div class="download-title">Download Master Workbook</div>', unsafe_allow_html=True)
    workbook_bytes = _build_master_workbook(timeline, pipeline, state_coverage)
    file_name = f"Barrister_Master_{eastern_today().isoformat()}.xlsx"
    st.download_button(
        label="⬇ Download Barrister_Master.xlsx",
        data=workbook_bytes,
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )


def render_add_event(
    timeline: pd.DataFrame,
    pipeline: pd.DataFrame,
    state_coverage: pd.DataFrame | None = None,
) -> None:
    st.markdown(FORM_CSS, unsafe_allow_html=True)

    known_locations = _known_locations(timeline)

    _render_upcoming(pipeline)

    st.markdown('<div class="event-page-title">ADD SERVICE EVENT</div>', unsafe_allow_html=True)
    _render_form(known_locations, timeline, pipeline)

    _render_modify(timeline, pipeline, known_locations)

    _render_download(timeline, pipeline, state_coverage)
