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


def _toggle_button_css(key: str, play_anim: bool, position_css: str = "") -> str:
    """Builds the CSS for one gross/net toggle button instance, keyed to
    whichever widget `key` is actually live this render. On the single
    render right after a click, `key` is the "_anim" variant and this
    also attaches the truck-approach + arrival-flash animation; every
    other render it's just the steady position + on-state glow.

    Both toggle instances (header + Ledger) are unified to the exact
    same bare-emoji look here — no pill/oval background in any state.
    Previously only the Ledger one had its chrome stripped, so the
    header instance still showed Streamlit's own type="primary" vs
    type="secondary" default styling underneath, which looked like 3-4
    different inconsistent "stages" rather than a clean on/off toggle.

    `overflow: visible` is required here — the global
    `div[data-testid="stButton"] button { overflow: hidden !important; }`
    rule (needed elsewhere for nav-label text-ellipsis truncation) was
    clipping the truck the entire time it was positioned outside the
    button's own box, so it only became visible once it had already
    slid most of the way in.
    """
    css = (
        f"div.st-key-{key} button {{ position: relative; overflow: visible !important; "
        "background: transparent !important; border: none !important; box-shadow: none !important; "
        "border-radius: 8px !important; width: 26px !important; height: 26px !important; "
        "padding: 0 !important; min-width: 0 !important; line-height: 1 !important; "
        f"{position_css} }}"
        f"div.st-key-{key} button[data-testid='stBaseButton-primary'] {{ "
        "text-shadow: 0 0 8px rgba(250,204,21,.9), 0 0 16px rgba(250,204,21,.6), "
        "0 0 28px rgba(250,204,21,.35); }"
    )
    if play_anim:
        css += (
            f"div.st-key-{key} button {{ animation: barrister-toggle-flash .5s ease-out 2s 1; }}"
            f"div.st-key-{key} button::before {{ content: '\\1F69A'; position: absolute; right: -2px; "
            "top: 50%; font-size: 16px; line-height: 1; pointer-events: none; "
            "animation: barrister-truck-approach 2s ease-in forwards; }"
        )
    return css


def render_header(active: str, show_money_toggle: bool = False, toggle_key: str = "gross_toggle_btn") -> None:
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
                key=toggle_key,
                type="primary" if gross_view else "secondary",
            ):
                st.session_state["gross_annual_view"] = not gross_view
                st.session_state["gross_toggle_anim_main"] = True
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
    main_toggle_anim = st.session_state.pop("gross_toggle_anim_main", False)
    main_toggle_key = "gross_toggle_btn_anim" if main_toggle_anim else "gross_toggle_btn"
    render_header(view, show_money_toggle, toggle_key=main_toggle_key)
    if show_money_toggle:
        st.markdown(
            f"<style>{_toggle_button_css(main_toggle_key, main_toggle_anim, position_css='left: -2px; top: 6px;')}</style>",
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
        ledger_toggle_anim = st.session_state.pop("gross_toggle_anim_ledger", False)
        ledger_toggle_key = "gross_toggle_btn_ledger_anim" if ledger_toggle_anim else "gross_toggle_btn_ledger"
        st.markdown(
            "<style>"
            ".ledger-breakdowns-title { font-family: 'Merriweather', Georgia, serif; "
            "font-size: clamp(1.6rem, 3.3vw, 2.6rem); font-weight: 850; line-height: .94; "
            "letter-spacing: -.028em; color: #fff; margin: 6px 0 0 -4px; }"
            # Pulls this row up against the panel above, closing the gap
            # created by that panel's own trailing margin plus Streamlit's
            # normal spacing between elements.
            f"div[data-testid='stHorizontalBlock']:has(div.st-key-{ledger_toggle_key}) "
            "{ margin-top: -14px !important; gap: 0 !important; }"
            # Column itself gets zero right padding so its content can
            # actually reach the true right edge of the page's content
            # column — the same right edge the BREAKDOWNS panel's outer
            # border sits on below, since both the native row and the
            # iframe panel share that same column width.
            f"div[data-testid='stColumn']:has(div.st-key-{ledger_toggle_key}) "
            "{ display: flex !important; justify-content: flex-end !important; padding-right: 0 !important; }"
            # Ledger-specific sizing/position tweaks — chrome-stripping,
            # overflow-visible, and the glow itself are now handled
            # centrally by _toggle_button_css() for both instances. This
            # block comes AFTER that shared CSS in the cascade so its
            # bigger/borderless sizing wins over the header's default
            # small-square sizing (same selector + !important on both,
            # so source order decides the winner).
            + _toggle_button_css(ledger_toggle_key, ledger_toggle_anim)
            + f"div.st-key-{ledger_toggle_key} button {{ width: auto !important; height: auto !important; "
            "border-radius: 0 !important; padding: 2px 0px 2px 2px !important; "
            "margin: 8px 0 0 !important; font-size: 22px !important; min-height: unset !important; }"
            + "</style>",
            unsafe_allow_html=True,
        )
        title_col, toggle_col = st.columns([10, 1])
        with title_col:
            st.markdown('<div class="ledger-breakdowns-title">BREAKDOWNS</div>', unsafe_allow_html=True)
        with toggle_col:
            if st.button(
                "\U0001F4B5",
                key=ledger_toggle_key,
                type="primary" if gross_view else "secondary",
            ):
                st.session_state["gross_annual_view"] = not gross_view
                st.session_state["gross_toggle_anim_ledger"] = True
                st.rerun()
        render_ledger_breakdowns(snapshot.sheets["Timeline"], gross_view)
    else:
        # render_dashboard() is one big components.html() iframe. The
        # previous attempt tried to pull the iframe itself up via
        # div[data-testid='stIFrame'] — an unverified guess at Streamlit's
        # internal testid that evidently either didn't match at all or
        # matched the wrong thing, since the gap grew instead of shrank.
        # This instead pulls up the *nav-tabs row itself* (the row right
        # above the iframe), anchored to the MAIN nav button's own proven
        # .st-key-nav_main class — a selector we're actually certain
        # exists, rather than guessing at Streamlit's internal iframe
        # wrapper markup again.
        st.markdown(
            "<style>div[data-testid='stHorizontalBlock']:has(div.st-key-nav_main) "
            "{ margin-bottom: -8px !important; }</style>",
            unsafe_allow_html=True,
        )
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
