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
    box_size: str = "66px",
) -> str:
    """Builds the CSS for one gross/net toggle button instance, keyed to
    whichever widget `key` is actually live this render.

    Rebuilt after the previous version rendered huge/unstyled/misplaced
    live — the button's actual text label was still the literal
    "\U0001F4B5" emoji (only ever HIDDEN via font-size:0, never removed),
    so if that CSS lost any cascade fight against Streamlit's own button
    styling, the raw native emoji showed through at whatever size/place
    the browser defaulted to — which is exactly what happened. Two
    changes make this failure mode structurally impossible now instead
    of just "hopefully covered by more CSS":
      1. The button's actual label is now a plain space, not an emoji —
         nothing left to leak through even in a worst case.
      2. Sizing is applied to BOTH the wrapper div AND the button
         (belt-and-suspenders), each with !important, instead of only
         the button.

    Single image asset (toggle-bank-color.png) — always shown in full
    color, no grayscale/desaturation ever. A CSS `filter` on a parent
    element composites its ENTIRE rendered subtree, including any
    ::before/::after pseudo-elements — so the earlier grayscale-toggle
    approach was also grayscaling the car and money bag pseudo-elements
    sitting on that same button, which should never change color at
    all. Dropping grayscale entirely sidesteps that rather than fighting
    it. On/off is now signaled purely by an outline glow
    (filter:drop-shadow, which paints color around the alpha edge
    without touching the icon's own pixels) — not a brightness pulse on
    the icon itself.

    `overflow: visible` is required — the global
    `div[data-testid="stButton"] button { overflow: hidden !important; }`
    rule (needed elsewhere for nav-label text-ellipsis truncation) would
    otherwise clip the car/moneybag the whole time they're positioned
    outside the button's own box.

    Animated (turning-on) sequence, three stages chained by delay,
    total 4.5s:
      0.0s-3.0s  car drives in from off-screen left, steady/linear speed,
                 parking just left of the bank icon (::before pseudo-el)
      3.0s-4.5s  money bag pops from the car and arcs over to the bank
                 (::after pseudo-el, animation-delay: 3s)
      4.5s       bag vanishes, outline glow appears around the bank
                 (steps(1,end) keyframe), car stays parked/visible the
                 whole time — only the OFF direction makes it disappear
    """
    bank_uri = _icon_data_uri("toggle-bank-color.png")
    # Outline glow only — filter:drop-shadow() paints a colored blur
    # along the element's alpha edge, sitting around/behind it, without
    # touching the icon's own pixel brightness/color. That's the
    # "shines on the outline, not on the icon itself" look. No
    # brightness/grayscale filter anywhere anymore — the bank stays in
    # full color always; this glow is now the ONLY on/off signal.
    glow = (
        "filter: drop-shadow(0 0 14px rgba(250,204,21,.95)) "
        "drop-shadow(0 0 28px rgba(250,204,21,.7)) drop-shadow(0 0 46px rgba(250,204,21,.4));"
    )
    css = (
        f"div.st-key-{key} {{ display: flex !important; align-items: center !important; "
        f"justify-content: center !important; width: {box_size} !important; height: {box_size} !important; "
        f"overflow: visible !important; {position_css} }}"
        f"div.st-key-{key} button {{ display: flex !important; align-items: center !important; "
        "justify-content: center !important; position: relative !important; overflow: visible !important; "
        f"width: {box_size} !important; height: {box_size} !important; "
        "background: transparent !important; border: none !important; box-shadow: none !important; "
        "border-radius: 10px !important; padding: 0 !important; min-width: 0 !important; "
        "min-height: unset !important; line-height: 1 !important; font-size: 0 !important; "
        f"background-image: url({bank_uri}) !important; "
        "background-size: contain !important; background-repeat: no-repeat !important; "
        "background-position: center !important; }"
        # No !important on filter here — CSS animations rank BELOW
        # "important author" rules in the cascade, so an !important here
        # would silently defeat the delayed-reveal animation below (it
        # would never be able to override this rule during the animated
        # render's first 4.5s). The specificity of this selector (class +
        # attribute) already beats the base button rule above without
        # needing !important.
        f"div.st-key-{key} button[data-testid='stBaseButton-primary'] {{ {glow} }}"
    )
    if play_anim:
        car_uri = _icon_data_uri("toggle-car.png")
        moneybag_uri = _icon_data_uri("toggle-moneybag.png")
        reveal_name = f"barrister-icon-reveal-{key}"
        css += (
            f"@keyframes {reveal_name} {{ "
            "0%, 99% { filter: none; } "
            f"100% {{ {glow} }} }}"
            f"div.st-key-{key} button[data-testid='stBaseButton-primary'] {{ "
            f"animation: {reveal_name} 4.5s steps(1, end) forwards; }}"
            # Car: drives in from the left, steady/linear speed, parks
            # just left of the bank icon — and STAYS visible/parked
            # (no fade-out). Own natural color throughout — it isn't
            # affected by the glow above since that only ever applies to
            # the primary-state selector, not this pseudo-element's own
            # rule (car pseudo-element carries no filter property at all).
            # Sized 250% of the original (145x83, up from 58x33) — i.e.
            # +150% on top of the current size, per request.
            f"div.st-key-{key} button::before {{ content: ''; position: absolute; right: -2px; "
            "top: 50%; width: 145px; height: 83px; pointer-events: none; "
            f"background-image: url({car_uri}); background-size: contain; background-repeat: no-repeat; "
            "animation: barrister-car-approach 5s linear forwards; }"
            # Money bag: pops from the car and tosses over to the bank in
            # an arc, timed to start the instant the car finishes parking.
            f"div.st-key-{key} button::after {{ content: ''; position: absolute; right: -2px; "
            "top: 50%; width: 26px; height: 26px; pointer-events: none; opacity: 0; "
            f"background-image: url({moneybag_uri}); background-size: contain; background-repeat: no-repeat; "
            "animation: barrister-moneybag-toss 1.5s ease-in 3s forwards; }"
        )
    return css


def render_header(active: str, show_money_toggle: bool = False, toggle_key: str = "gross_toggle_btn") -> None:
    # 4:1 split (not the old 5:1) so toggle_col occupies exactly the same
    # rightmost 1/5 of the row width as the nav row's 5 equal columns
    # below it — meaning it lands precisely above LEDGER (the 5th nav
    # button) by construction, not by guessing a pixel offset.
    title_col, toggle_col = st.columns([4, 1])
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
                " ",
                key=toggle_key,
                type="primary" if gross_view else "secondary",
            ):
                turning_on = not gross_view
                st.session_state["gross_annual_view"] = turning_on
                # The car/moneybag/bank sequence only plays when turning
                # ON — turning off is deliberately instant/unanimated
                # ("for simplicity"), so no flag is set in that case and
                # the next render just shows the plain gray bank directly.
                if turning_on:
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
            f"<style>{_toggle_button_css(main_toggle_key, main_toggle_anim, box_size='66px')}</style>",
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
            # Pulls this row up against the panel above slightly — much
            # less aggressively than before (-14px), since that value
            # was tuned for the old 48px icon. At the current 72px size
            # the icon carries more of its own visual weight in the row,
            # so a big pull now overcorrected and shoved it toward/into
            # the panel above.
            f"div[data-testid='stHorizontalBlock']:has(div.st-key-{ledger_toggle_key}) "
            "{ margin-top: -4px !important; gap: 0 !important; }"
            # Column itself gets zero right padding so its content can
            # actually reach the true right edge of the page's content
            # column — the same right edge the BREAKDOWNS panel's outer
            # border sits on below, since both the native row and the
            # iframe panel share that same column width.
            f"div[data-testid='stColumn']:has(div.st-key-{ledger_toggle_key}) "
            "{ display: flex !important; justify-content: flex-end !important; padding-right: 0 !important; }"
            # Ledger-specific: outer column stays right-aligned within
            # the BREAKDOWNS row; sizing/chrome/glow/animation all come
            # centrally from _toggle_button_css() for both instances.
            + _toggle_button_css(
                ledger_toggle_key, ledger_toggle_anim,
                box_size="72px",
            )
            + "</style>",
            unsafe_allow_html=True,
        )
        title_col, toggle_col = st.columns([9, 1])
        with title_col:
            st.markdown('<div class="ledger-breakdowns-title">BREAKDOWNS</div>', unsafe_allow_html=True)
        with toggle_col:
            if st.button(
                " ",
                key=ledger_toggle_key,
                type="primary" if gross_view else "secondary",
            ):
                turning_on = not gross_view
                st.session_state["gross_annual_view"] = turning_on
                if turning_on:
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
