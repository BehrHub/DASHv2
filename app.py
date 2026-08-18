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


@st.cache_data(show_spinner=False)
def _icon_data_uri(filename: str) -> str:
    """Base64-encodes a small icon once per session (cached) instead of
    on every single rerun — these get embedded inline in CSS since
    Streamlit doesn't serve arbitrary local files as static URLs."""
    import base64

    data = (ROOT / "assets" / "icons" / filename).read_bytes()
    return f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"


def _toggle_button_css(
    key: str,
    play_anim: bool,
    position_css: str = "",
    off_font_size: str = "30px",
    box_size: str = "44px",
) -> str:
    """Builds the CSS for one gross/net toggle button instance, keyed to
    whichever widget `key` is actually live this render. On the single
    render right after a click, `key` is the "_anim" variant and this
    also attaches the truck-approach + arrival-flash animation; every
    other render it's just the steady position + on-state icon swap.

    Both toggle instances (header + Ledger) are unified to the exact
    same bare-icon look here — no pill/oval background in any state.
    Previously only the Ledger one had its chrome stripped, so the
    header instance still showed Streamlit's own type="primary" vs
    type="secondary" default styling underneath, which looked like 3-4
    different inconsistent "stages" rather than a clean on/off toggle.

    Sized up substantially from the original 26px box — next to
    BARRISTER's now much larger Merriweather wordmark, the small version
    was reading as basically invisible.

    `overflow: visible` is required here — the global
    `div[data-testid="stButton"] button { overflow: hidden !important; }`
    rule (needed elsewhere for nav-label text-ellipsis truncation) was
    clipping the truck the entire time it was positioned outside the
    button's own box, so it only became visible once it had already
    slid most of the way in.

    ON state swaps the plain "\U0001F4B5" text label for the money-bags
    icon (background-image, since the text itself is hidden via
    font-size:0 — text-shadow has no effect on a background-image, so
    the on-state glow uses filter:drop-shadow instead).

    During the animated (post-click) render, the icon-swap itself is
    DELAYED to land at the same instant the truck arrives (2s) rather
    than switching instantly on click — a steps(1,end) keyframe holds
    the plain "before" look for the truck's whole flight, then jumps to
    the money-bags look + flash together at the very end.
    """
    moneybags_uri = _icon_data_uri("toggle-moneybags.png")
    glow = (
        "filter: drop-shadow(0 0 14px rgba(250,204,21,.95)) "
        "drop-shadow(0 0 28px rgba(250,204,21,.7)) drop-shadow(0 0 46px rgba(250,204,21,.4));"
    )
    css = (
        f"div.st-key-{key} button {{ position: relative; overflow: visible !important; "
        "background: transparent !important; border: none !important; box-shadow: none !important; "
        f"border-radius: 10px !important; width: {box_size} !important; height: {box_size} !important; "
        f"padding: 0 !important; min-width: 0 !important; line-height: 1 !important; "
        f"font-size: {off_font_size} !important; "
        f"{position_css} }}"
        # No !important on font-size/background-image/filter here — CSS
        # animations rank BELOW "important author" rules in the cascade,
        # so an !important here would silently defeat the delayed-reveal
        # animation below (it would never be able to override this rule
        # during the animated render's first 2s). The specificity of
        # this selector (class + attribute) is already enough to beat
        # Streamlit's own base button styling without needing !important.
        f"div.st-key-{key} button[data-testid='stBaseButton-primary'] {{ "
        "font-size: 0; "
        f"background-image: url({moneybags_uri}); "
        "background-size: contain; background-repeat: no-repeat; "
        "background-position: center; "
        f"{glow} }}"
    )
    if play_anim:
        truck_uri = _icon_data_uri("toggle-truck.png")
        reveal_name = f"barrister-icon-reveal-{key}"
        css += (
            f"@keyframes {reveal_name} {{ "
            f"0%, 99% {{ font-size: {off_font_size}; background-image: none; filter: none; }} "
            f"100% {{ font-size: 0; background-image: url({moneybags_uri}); "
            "background-size: contain; background-repeat: no-repeat; background-position: center; "
            f"{glow} }} }}"
            f"div.st-key-{key} button[data-testid='stBaseButton-primary'] {{ "
            f"animation: {reveal_name} 2s steps(1, end) forwards, "
            "barrister-toggle-flash .5s ease-out 2s 1; }"
            f"div.st-key-{key} button::before {{ content: ''; position: absolute; right: -2px; "
            "top: 50%; width: 34px; height: 34px; pointer-events: none; "
            f"background-image: url({truck_uri}); background-size: contain; background-repeat: no-repeat; "
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
        # One-shot deep link: read (and clear) which tab to open to, so
        # this only applies on the render immediately after navigating
        # in from elsewhere (e.g. the CITIES gauge on Main) — not on
        # every later rerun while already on this page, which would
        # otherwise keep yanking the user back to that tab even after
        # they'd manually clicked a different one.
        initial_ledger_tab = st.query_params.get("ledger_tab", "l10wk")
        if "ledger_tab" in st.query_params:
            del st.query_params["ledger_tab"]
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
            # Ledger-specific position tweak only now — sizing, chrome-
            # stripping, overflow-visible, and glow are all handled
            # centrally by _toggle_button_css() for both instances.
            + _toggle_button_css(
                ledger_toggle_key, ledger_toggle_anim,
                position_css="margin: 4px 0 0;",
                off_font_size="40px", box_size="48px",
            )
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
        render_ledger_breakdowns(snapshot.sheets["Timeline"], gross_view, initial_tab=initial_ledger_tab)
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
        # Same pattern as above — hero card's "CITIES" gauge clicks this
        # via JS to deep-link straight to the Ledger page's CITIES tab.
        if st.button("View Cities Breakdown", key="hero_nav_cities"):
            st.query_params["view"] = "ledger"
            st.query_params["ledger_tab"] = "cities"
            st.rerun()


if __name__ == "__main__":
    main()
