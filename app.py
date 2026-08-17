from __future__ import annotations

from pathlib import Path

import streamlit as st

from components.ui import render_dashboard
from components.journey import render_barrister_journey
from components.add_event import render_add_event
from components.client_hub import render_client_standings
from components.ledger import render_ledger_summary, render_ledger_breakdowns
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
            "<style>"
            "div.st-key-gross_toggle_btn button { position: relative; left: -2px; top: 6px; }"
            # Glow only appears when the toggle is actually ON (Streamlit
            # marks the active button variant with this data attribute),
            # so it doubles as the on/off indicator this button needs —
            # placed on the button itself so it wraps the emoji glyph
            # directly rather than a container that no longer exists.
            "div.st-key-gross_toggle_btn button[data-testid='stBaseButton-primary'] "
            "{ text-shadow: 0 0 8px rgba(250,204,21,.9), 0 0 16px rgba(250,204,21,.6), "
            "0 0 28px rgba(250,204,21,.35); }"
            "</style>",
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
        render_ledger_summary(snapshot.sheets["Timeline"], gross_view)
        # Native title+toggle row — this is the exact spot the old
        # embedded "MONTHLY BREAKDOWN" title sat, between the Financial
        # Closeout panel above and the tab-grid panel below. Has to be a
        # real Streamlit row (not part of either iframe) so the toggle
        # button stays clickable — components.html output is a static
        # snapshot, nothing inside it can trigger a Python rerun.
        st.markdown(
            "<style>"
            ".ledger-breakdowns-title { font-family: 'Merriweather', Georgia, serif; "
            "font-size: clamp(1.6rem, 3.3vw, 2.6rem); font-weight: 850; line-height: .94; "
            "letter-spacing: -.028em; color: #fff; margin: 6px 0 0 -4px; }"
            # Pulls this row up against the panel above, closing the gap
            # created by that panel's own trailing margin plus Streamlit's
            # normal spacing between elements.
            "div[data-testid='stHorizontalBlock']:has(div.st-key-gross_toggle_btn_ledger) "
            "{ margin-top: -14px !important; gap: 0 !important; }"
            # Column itself gets zero right padding so its content can
            # actually reach the true right edge of the page's content
            # column — the same right edge the BREAKDOWNS panel's outer
            # border sits on below, since both the native row and the
            # iframe panel share that same column width.
            "div[data-testid='stColumn']:has(div.st-key-gross_toggle_btn_ledger) "
            "{ display: flex !important; justify-content: flex-end !important; padding-right: 0 !important; }"
            # Strip the big pill/oval button chrome — just the emoji,
            # tight and unobtrusive, nudged down ~8px to level with the
            # title text's own top margin, flush against the right edge.
            "div.st-key-gross_toggle_btn_ledger button { background: transparent !important; "
            "border: none !important; box-shadow: none !important; padding: 2px 0px 2px 2px !important; "
            "margin: 8px 0 0 !important; font-size: 22px !important; min-height: unset !important; }"
            # Same on/off glow as the header instance — text-shadow around
            # the emoji itself, since there's no container left to glow.
            "div.st-key-gross_toggle_btn_ledger button[data-testid='stBaseButton-primary'] "
            "{ text-shadow: 0 0 8px rgba(250,204,21,.9), 0 0 16px rgba(250,204,21,.6), "
            "0 0 28px rgba(250,204,21,.35); }"
            "</style>",
            unsafe_allow_html=True,
        )
        title_col, toggle_col = st.columns([10, 1])
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
        render_ledger_breakdowns(snapshot.sheets["Timeline"], gross_view)
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
