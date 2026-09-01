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


@st.cache_data(show_spinner=False)
def _splash_image_data_uri() -> str:
    import base64

    data = (ROOT / "assets" / "splash" / "barrister_splash.jpg").read_bytes()
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode('ascii')}"


def render_splash_screen() -> None:
    """Entry gate shown before the dashboard on a fresh visit.

    Previously rendered a full-bleed curtain/poster splash in-app. Now
    redirects immediately to the new cloud-hosted splash page
    (https://behrhub.github.io/SPLASH/), which is the actual front door
    people land on and links back in here with ?entered=1&view=main.
    Kept as a redirect (not deleted) so the ?entered=1 gate in main()
    still has somewhere sane to send a bare/no-param visit.
    """
    redirect_url = "https://behrhub.github.io/SPLASH/"
    st.markdown(
        f"""
        <meta http-equiv="refresh" content="0; url={redirect_url}">
        <script>window.location.replace("{redirect_url}");</script>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


def _toggle_button_css(
    key: str,
    play_anim: bool,
    position_css: str = "",
    box_w: str = "125px",
    box_h: str = "71px",
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

    Box is now a real rectangle (box_w x box_h), not a forced square —
    the current bank illustration is a wide building shot (~1.76:1),
    not the roughly-square flat emoji this replaced. Forcing it into a
    square box would letterbox it (visible blank space above/below).

    Single image asset (toggle-bank-building.png) — always shown in
    full color, no grayscale/desaturation ever. A CSS `filter` on a
    parent element composites its ENTIRE rendered subtree, including
    any ::before pseudo-element — so a grayscale-toggle approach here
    would also grayscale the car sitting on that same button, which
    should never change color at all. On/off is signaled purely by an
    outline glow (filter:drop-shadow, which paints color around the
    alpha edge without touching the icon's own pixels) — not a
    brightness pulse on the icon itself.

    `overflow: visible` is required — the global
    `div[data-testid="stButton"] button { overflow: hidden !important; }`
    rule (needed elsewhere for nav-label text-ellipsis truncation) would
    otherwise clip the car the whole time it's positioned outside the
    button's own box.

    Animated (turning-on) sequence — a single combined car+bag image
    drives straight across at constant speed, 4s total. The glow-trigger
    point is a real calculated value, and now properly accounts for the
    bank's own WIDTH, not just treating it as a zero-width point at
    translateX=0 (a fine approximation back when the icon was small and
    roughly square, but wrong now that it's a wide building graphic).
    The car has fully cleared the building once its trailing edge passes
    the building's LEFT edge (which sits at translateX = -box_w, since
    the car's own translateX is anchored to the icon's right edge) —
    i.e. PASS_X = CAR_W - box_w. That value is negative whenever the
    building is wider than the car, meaning the glow now correctly
    fires while the car is still mid-crossing the building's width, not
    only after clearing its right edge. Recalculated per-instance from
    the actual box_w passed in, since header and Ledger use different
    sizes. No "sit and disappear" timer needed either — once the drive
    reaches its endpoint the car is already off-screen by construction.
    """
    _CAR_W, _CAR_H = 90, 38
    _START_X, _END_X = -500, 300
    _box_w_num = float(box_w.replace("px", ""))
    _pass_x = _CAR_W - _box_w_num
    _pass_pct = (_pass_x - _START_X) / (_END_X - _START_X) * 100

    bank_uri = _icon_data_uri("toggle-bank-building.png")
    # Outline glow only — filter:drop-shadow() paints a colored blur
    # along the element's alpha edge, sitting around/behind it, without
    # touching the icon's own pixel brightness/color. That's the
    # "shines on the outline, not on the icon itself" look. No
    # brightness/grayscale filter anywhere anymore — the bank stays in
    # full color always; this glow is now the ONLY on/off signal.
    glow = (
        "filter: drop-shadow(0 0 14px rgba(224,251,255,.95)) "
        "drop-shadow(0 0 28px rgba(103,232,249,.7)) drop-shadow(0 0 46px rgba(34,211,238,.4));"
    )
    css = (
        f"div.st-key-{key} {{ display: flex !important; align-items: center !important; "
        f"justify-content: center !important; width: {box_w} !important; height: {box_h} !important; "
        f"overflow: visible !important; {position_css} }}"
        f"div.st-key-{key} button {{ display: flex !important; align-items: center !important; "
        "justify-content: center !important; position: relative !important; overflow: visible !important; "
        f"width: {box_w} !important; height: {box_h} !important; "
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
        # render). The specificity of this selector (class + attribute)
        # already beats the base button rule above without !important.
        f"div.st-key-{key} button[data-testid='stBaseButton-primary'] {{ {glow} }}"
    )
    if play_anim:
        car_uri = _icon_data_uri("toggle-car-bag.png")
        reveal_name = f"barrister-icon-reveal-{key}"
        hold_pct = _pass_pct - 0.1
        css += (
            f"@keyframes {reveal_name} {{ "
            f"0%, {hold_pct:.2f}% {{ filter: none; }} "
            f"{_pass_pct:.2f}% {{ {glow} }} }}"
            f"div.st-key-{key} button[data-testid='stBaseButton-primary'] {{ "
            f"animation: {reveal_name} 4s steps(1, end) forwards; }}"
            # Car+bag: one straight, constant-speed pass across the whole
            # width, right through the bank icon's own position — no
            # parking, no separate toss element, no disappear-timer.
            # Own natural color throughout, unaffected by the glow above
            # (that rule only ever targets the primary-state button
            # selector, not this pseudo-element).
            f"div.st-key-{key} button::before {{ content: ''; position: absolute; right: -2px; "
            f"top: 50%; width: {_CAR_W}px; height: {_CAR_H}px; pointer-events: none; "
            f"background-image: url({car_uri}); background-size: contain; background-repeat: no-repeat; "
            "animation: barrister-car-drive-through 4s linear forwards; }"
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
            'href="https://behrhub.github.io/SPLASH/" target="_self">BARRISTER</a></div>',
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


def render_logo_studio_page(timeline: pd.DataFrame) -> None:
    """Hidden admin tool (reachable via ?view=logostudio, not a nav-bar
    tab) closing the loop the person asked for: drop a raw logo into
    assets/logos_raw/, calibrate scale/x/y with a live preview showing
    exactly how it'll look in a real Client Hub row, save it, and
    Client Hub picks it up on its very next render — no redeploy needed
    for the current session, since it clears the same st.cache_data
    caches discover_logos()/logo_data_uri() rely on.

    Rebuilds the ORIGINAL Barrister2.0 "Logo Factory" tool's actual
    convention (scale relative to the source's own trimmed content,
    then an x/y pixel offset onto a fixed tile) rather than inventing a
    new one — its logo_profiles.json schema is reused as-is, so the 27
    already-calibrated logos and any new ones share one file.

    Honest limitation, stated up front in the UI: Streamlit Cloud's
    filesystem doesn't survive a reboot/redeploy. Save here is real and
    immediate for the current running session, but permanence requires
    downloading the result and committing it — same tradeoff as the
    Master Workbook export on the Events page, for the same reason.
    """
    from services.logo_studio import (
        list_raw_logos, load_profiles, save_profiles, render_calibrated_tile,
        preview_png_bytes, DEFAULT_PROFILE,
    )
    from services.logo_source import (
        discover_logos, resolve_client_logo, normalize_client_filename,
        CLIENT_LOGO_FILENAMES, logo_data_uri,
    )
    import base64
    import io

    raw_dir = ROOT / "assets" / "logos_raw"
    logos_dir = ROOT / "assets" / "logos"
    profiles_path = logos_dir / "logo_profiles.json"

    st.markdown(
        '<div style="font-family:\'Merriweather\',Georgia,serif;font-size:clamp(1.6rem,3.3vw,2.4rem);'
        'font-weight:850;color:#fff;margin-bottom:2px;">LOGO STUDIO</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Calibrate a raw logo and save it —  \n"
        "Client Hub picks it up immediately for this session. Download the result below to make it "
        "permanent across reboots (same as Ledger workbook)"
    )

    raw_dir.mkdir(parents=True, exist_ok=True)

    uploaded = st.file_uploader(
        "Upload raw logo(s) — straight from your phone",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="logostudio_uploader",
    )
    if uploaded:
        for f in uploaded:
            (raw_dir / f.name).write_bytes(f.getvalue())
        st.success(f"Added {len(uploaded)} file(s) to the staging folder below \u2014 pick one to calibrate.")
    st.caption("Uploads land here live for this session only")

    raw_files = list_raw_logos(raw_dir)
    if not raw_files:
        st.info(
            "No raw logos waiting yet. Upload one above (works straight from your phone's Photos), "
            "or push a file into `assets/logos_raw/` from your Mac the normal way — either works."
        )
        return

    from services.logo_studio import sync_logos_from_sheet
    sync_logos_from_sheet(str(logos_dir), str(profiles_path))
    logo_files, _dupes = discover_logos(logos_dir)
    client_names = sorted(timeline["Client"].dropna().unique()) if "Client" in timeline.columns else []
    missing = [c for c in client_names if resolve_client_logo(c, logo_files) is None]
    has_logo = [c for c in client_names if c not in missing]

    # Every client is selectable now, not just ones missing a logo —
    # picking an existing one (e.g. Dunkin') loads ITS real saved
    # scale/x/y so a bad crop can actually be fixed, not just new ones
    # added. format_func decorates the on-screen label only; the
    # underlying selectbox value stays the plain client name.
    NEW_NAME_SENTINEL = "\u2795 Type a new client name..."
    dropdown_options = [NEW_NAME_SENTINEL] + missing + has_logo

    def _format_client_option(name: str) -> str:
        if name == NEW_NAME_SENTINEL:
            return name
        return f"\u26A0\uFE0F {name} (needs a logo)" if name in missing else f"\u2705 {name} (recalibrate)"

    def _sync_manual_field() -> None:
        # Explicitly pushes the dropdown's choice into the text input's
        # own session-state entry BEFORE that widget is instantiated
        # below. This runs as Streamlit's on_change callback, which
        # fires before the script reruns from the top — a plain
        # value=... argument on an already-keyed widget is silently
        # ignored on every render after the first, which was the actual
        # bug (manual field stuck on whatever loaded initially,
        # regardless of later dropdown changes).
        choice = st.session_state.get("logostudio_client_select")
        if not choice or choice == NEW_NAME_SENTINEL:
            return
        st.session_state["logostudio_manual"] = choice

        # Also auto-select the matching raw source file, if one exists,
        # for the SAME reason — this is what actually makes "select an
        # existing client, see their logo to edit" work. Previously
        # nothing populated because assets/logos_raw/ genuinely had no
        # source images at all for the 27 already-calibrated logos, only
        # their final processed tiles — recalibrating those tiles
        # directly wouldn't work correctly (the trim-to-content step
        # would just see an opaque white square, not the real logo
        # bounds), so the true original sources were brought in
        # separately, under the same filenames as their calibrated
        # counterparts, specifically so this lookup can find them.
        expected_filename = CLIENT_LOGO_FILENAMES.get(
            choice.strip().casefold(), f"{normalize_client_filename(choice)}.png"
        )
        if expected_filename in raw_files:
            st.session_state["logostudio_raw"] = expected_filename

    col1, col2 = st.columns(2)
    with col1:
        raw_choice = st.selectbox("Raw logo file", raw_files, key="logostudio_raw")
    with col2:
        client_select = st.selectbox(
            "Client", dropdown_options, format_func=_format_client_option,
            key="logostudio_client_select", on_change=_sync_manual_field,
        )
        manual_key = st.text_input("OR type a new client name below", key="logostudio_manual")

    target_client_name = (manual_key or "").strip() or (
        client_select if client_select != NEW_NAME_SENTINEL else None
    )
    if not target_client_name:
        st.warning("Pick or type which client this logo is for.")
        return

    target_filename = CLIENT_LOGO_FILENAMES.get(
        target_client_name.strip().casefold(), f"{normalize_client_filename(target_client_name)}.png"
    )
    st.caption(f"Will save as \u2192 `assets/logos/{target_filename}`")

    profiles = load_profiles(profiles_path)
    stem = Path(target_filename).stem
    existing = profiles.get(stem, dict(profiles.get("_defaults", DEFAULT_PROFILE)))

    s1, s2, s3 = st.columns(3)
    with s1:
        scale = st.slider("Scale", 0.20, 2.00, float(existing.get("scale", 0.78)), 0.01, key="logostudio_scale")
    with s2:
        x = st.slider("X offset", -48, 48, int(existing.get("x", 0)), 1, key="logostudio_x")
    with s3:
        y = st.slider("Y offset", -48, 48, int(existing.get("y", 0)), 1, key="logostudio_y")

    raw_path = raw_dir / raw_choice
    preview_bytes = preview_png_bytes(raw_path, scale, x, y)

    st.markdown("#### Preview")
    pcol1, pcol2 = st.columns([1, 2])
    with pcol1:
        st.image(preview_bytes, width=120, caption="Isolated tile")
    with pcol2:
        b64 = base64.b64encode(preview_bytes).decode("ascii")
        st.markdown(
            f'<div style="background:rgba(15,20,32,.4);border:1px solid rgba(255,255,255,.05);'
            f'border-radius:14px;padding:12px 14px;display:flex;align-items:center;gap:12px;max-width:320px;">'
            f'<img src="data:image/png;base64,{b64}" style="width:52px;height:52px;border-radius:10px;flex-shrink:0;">'
            f'<div style="font-size:14px;font-weight:700;color:#e5edf9;">{target_client_name}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.caption("Exactly how it'll look in a real Client Hub row")

    from services import sheets_store

    save_col, dl_col = st.columns(2)
    with save_col:
        if st.button("\U0001F4BE Save", type="primary", width="stretch"):
            tile = render_calibrated_tile(raw_path, scale, x, y)
            tile_bytes_io = io.BytesIO()
            tile.save(tile_bytes_io, format="PNG")
            tile_bytes = tile_bytes_io.getvalue()

            tile.save(logos_dir / target_filename)
            profiles[stem] = {"scale": scale, "x": x, "y": y}
            save_profiles(profiles_path, profiles)
            discover_logos.clear()
            logo_data_uri.clear()

            if sheets_store.is_configured():
                try:
                    sheets_store.save_logo(
                        key=stem, filename=target_filename, scale=scale, x=x, y=y,
                        image_base64=base64.b64encode(tile_bytes).decode("ascii"),
                    )
                    sync_logos_from_sheet.clear()
                    st.success(
                        f"Saved to Google Sheets \u2014 assets/logos/{target_filename} is now permanent. "
                        "No download needed, this survives reboots. Check Client Hub now."
                    )
                except Exception as exc:
                    st.warning(
                        f"Saved locally for this session, but the Sheets write failed ({exc}) \u2014 "
                        "download the tile below and commit it manually so this survives a reboot."
                    )
            else:
                st.success(f"Saved to assets/logos/{target_filename} for this session \u2014 check Client Hub now.")
    with dl_col:
        st.download_button(
            "\u2B07\uFE0F Download this tile  \n(backup copy)",
            data=preview_bytes,
            file_name=target_filename,
            mime="image/png",
            width="stretch",
        )

    st.divider()
    if sheets_store.is_configured():
        st.caption(
            "Save writes straight to the Google Sheet backing this app \u2014 same place your event data "
            "lives \u2014 so it survives reboots/redeploys on its own. The download button above is just an "
            "optional backup copy, not a required step."
        )
    else:
        st.caption(
            "Google Sheets isn't configured for this app, so Save only writes to local disk, which does "
            "NOT survive a reboot/redeploy.  \n"
            "-  download the tile above and commit it to assets/logos (same as any other asset in this repo)  \n"
            "-  download the updated logo_profiles.json below too (so re-calibrating later starts from these "
            "values instead of defaults)"
        )
        if profiles_path.exists():
            st.download_button(
                "\u2B07\uFE0F Download logo_profiles.json",
                data=profiles_path.read_bytes(),
                file_name="logo_profiles.json",
                mime="application/json",
            )


def main() -> None:
    st.set_page_config(
        page_title="Barrister Preview",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # Splash gate — checked before anything else (including the CSS load
    # and data snapshot) so a fresh visit isn't paying the cost of
    # loading the dashboard just to hide it behind the splash. ?entered=1
    # is a hard URL gate (survives refresh/sharing), not session state —
    # matches how the original Barrister2.0 app did it with its own
    # ?page=... param.
    if st.query_params.get("entered") != "1":
        render_splash_screen()
        return

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
            f"<style>{_toggle_button_css(main_toggle_key, main_toggle_anim, box_w='94px', box_h='53px', position_css='margin-top: 1px;')}</style>",
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
        st.markdown(
            '<div style="text-align:center;margin-top:18px;font-size:10.5px;">'
            '<a href="?entered=1&view=logostudio" target="_self" style="color:#e8c94a;text-decoration:none;'
            'text-shadow:0 0 6px rgba(250,204,21,.85),0 0 14px rgba(250,204,21,.5);">'
            "Logo Studio</a></div>",
            unsafe_allow_html=True,
        )
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
            "{ margin-top: -4px !important; margin-right: 0 !important; "
            "padding-right: 0 !important; gap: 0 !important; }"
            # Column itself gets zero right padding so its content can
            # actually reach the true right edge of the page's content
            # column — the same right edge the BREAKDOWNS panel's outer
            # border sits on below, since both the native row and the
            # iframe panel share that same column width. Still overflowing
            # past that edge in practice even with both zeroed out, so a
            # direct pixel correction on the icon itself is layered on top
            # as a guaranteed backstop rather than relying on the anchor
            # alone.
            f"div[data-testid='stColumn']:has(div.st-key-{ledger_toggle_key}) "
            "{ display: flex !important; justify-content: flex-end !important; "
            "padding-right: 0 !important; margin-right: 0 !important; }"
            # Ledger-specific: outer column stays right-aligned within
            # the BREAKDOWNS row; sizing/chrome/glow/animation all come
            # centrally from _toggle_button_css() for both instances.
            # margin-right is the direct pixel backstop mentioned above —
            # was 22px, still overflowing past the panel's border below,
            # so bumped to 29px (22+7). margin-top matches the same 5px
            # downward nudge applied to the header instance.
            + _toggle_button_css(
                ledger_toggle_key, ledger_toggle_anim,
                position_css="margin-right: 29px; margin-top: 1px;",
                box_w="103px",
                box_h="58px",
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
    elif view == "logostudio":
        render_logo_studio_page(snapshot.sheets["Timeline"])
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
