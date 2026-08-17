from __future__ import annotations

from pathlib import Path

import streamlit as st

from components.ui import render_dashboard
from components.journey import render_barrister_journey
from components.add_event import render_add_event
from components.client_hub import render_client_standings
from components.ledger import render_ledger
from services.data_source import load_snapshot
from services.metrics import build_executive_metrics


ROOT = Path(__file__).resolve().parent


def load_css() -> str:
    return (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")


def render_header(active: str, show_money_toggle: bool = False) -> None:
    title_col, toggle_col = st.columns([5, 1])
    with title_col:
        st.markdown(
            '<div class="app-header-word-row"><a class="app-header-word" '
            'href="https://dashv2.streamlit.app" target="_self">BARRISTER</a></div>',
            unsafe_allow_html=True,
        )
    with toggle_col:
        if show_money_toggle:
            gross_view = bool(st.session_state.get("gross_annual_view", False))
            if st.button(
                "\U0001F4B5",
                key="gross_toggle_btn",
                type="primary" if gross_view else "secondary",
            ):
                st.session_state["gross_annual_view"] = not gross_view
                st.rerun()
    cols = st.columns(5)
    labels = [
        ("\U0001F3C1", "MAIN", "main"),
        ("\U0001F3CE\uFE0F", "JOURNEY", "journey"),
        ("\u2795", "EVENTS", "addevent"),
        ("\U0001F465", "CLIENTS", "clienthub"),
        ("\U0001F4D3", "LEDGER", "ledger"),
    ]
    for col, (icon, label, view) in zip(cols, labels):
        with col:
            is_active = view == active
            if st.button(
                f"{icon}\n{label}",
                key=f"nav_{view}",
                type="primary" if is_active else "secondary",
                width="stretch",
            ):
                if not is_active:
                    st.query_params["view"] = view
                    st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Barrister Preview",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(f"<style>{load_css()}</style>", unsafe_allow_html=True)

    snapshot = load_snapshot()
    metrics = build_executive_metrics(snapshot)

    sheets_error = st.session_state.get("sheets_error")
    if sheets_error:
        st.markdown(
            '<div style="background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.4);'
            'border-radius:12px;padding:10px 14px;margin:0 0 10px;color:#fca5a5;'
            'font-size:12.5px;font-weight:600;">\u26A0\uFE0F '
            f'{sheets_error}</div>',
            unsafe_allow_html=True,
        )

    view = st.query_params.get("view", "main")
    # The gross/net toggle lives in the top app header for Main and Client
    # Hub, but on Ledger it renders inline with the "BREAKDOWNS" title
    # instead (see below) — it's used constantly on that page and forcing
    # a scroll up to the header every time was the whole complaint.
    show_money_toggle = view in ("main", "clienthub")
    render_header(view, show_money_toggle)
    if show_money_toggle:
        st.markdown(
            "<style>div.st-key-gross_toggle_btn button "
            "{ position: relative; left: 13px; top: 6px; }</style>",
            unsafe_allow_html=True,
        )
    gross_view = bool(st.session_state.get("gross_annual_view", False))

    if view == "journey":
        render_barrister_journey(snapshot.sheets["Timeline"])
    elif view == "addevent":
        render_add_event(
            snapshot.sheets["Timeline"],
            snapshot.sheets["Pipeline"],
            snapshot.sheets.get("State Coverage"),
        )
    elif view == "clienthub":
        render_client_standings(metrics, snapshot.sheets["Timeline"], gross_view)
    elif view == "ledger":
        st.markdown(
            "<style>.ledger-breakdowns-title { font-size: 16px; font-weight: 900; "
            "letter-spacing: .5px; color: #fff; text-transform: uppercase; margin-top: 8px; }</style>",
            unsafe_allow_html=True,
        )
        title_col, toggle_col = st.columns([5, 1])
        with title_col:
            st.markdown('<div class="ledger-breakdowns-title">BREAKDOWNS</div>', unsafe_allow_html=True)
        with toggle_col:
            if st.button(
                "\U0001F4B5",
                key="gross_toggle_btn_ledger",
                type="primary" if gross_view else "secondary",
            ):
                st.session_state["gross_annual_view"] = not gross_view
                st.rerun()
        render_ledger(snapshot.sheets["Timeline"], gross_view)
    else:
        render_dashboard(metrics, snapshot.sheets["Timeline"], gross_view)
        # Hero card's "UPCOMING" KPI clicks this via JS (window.parent lookup by
        # button text) to trigger a real Streamlit rerun/navigation. Hidden by
        # that same script once it runs; if hiding ever fails for any reason,
        # it just degrades into an ordinary, sensible extra button.
        if st.button("View Upcoming Events", key="hero_nav_events"):
            st.query_params["view"] = "addevent"
            st.rerun()


if __name__ == "__main__":
    main()
