from __future__ import annotations

from pathlib import Path

import streamlit as st

from components.ui import render_dashboard
from components.stats_plus import render_stats_plus
from components.journey import render_barrister_journey
from components.add_event import render_add_event
from components.client_hub import render_client_standings
from components.ledger import render_ledger_summary, render_ledger_breakdowns
from components.rocket import render_back_to_top_rocket
from components.v2_pages import render_v2_page
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
    (http://100.70.235.51:8091/barrister-splash.html), local front door — an
    people land on and links back in here with ?entered=1&view=main.
    Kept as a redirect (not deleted) so the ?entered=1 gate in main()
    still has somewhere sane to send a bare/no-param visit.
    """
    redirect_url = "http://100.70.235.51:8091/barrister-splash.html"
    st.markdown(
        f"""
        <meta http-equiv="refresh" content="0; url={redirect_url}">
        <script>window.location.replace("{redirect_url}");</script>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


def render_header(active: str) -> None:
    """Title row (BARRISTER + the universal NET / GROSS switch in the top
    right, on every page) and the nav tabs. The switch is a plain native
    st.toggle keyed straight to session state: off = NET (default),
    on = GROSS. It is styled in assets/styles.css (div.st-key-gross_annual_view).
    """
    title_col, toggle_col = st.columns([5, 3])
    with title_col:
        st.markdown(
            '<div class="app-header-word-row"><a class="app-header-word" '
            'href="http://100.70.235.51:8091/barrister-splash.html" target="_self">BARRISTER</a></div>',
            unsafe_allow_html=True,
        )
    with toggle_col:
        st.toggle("GROSS", key="gross_annual_view")
    # Six tabs in two rows of three. CLIENTS and LEDGER are the former V2
    # designs; Main and STATS+ carry their merged V2 content.
    labels = [
        ("\U0001F3C1", "MAIN", "main"),
        ("\U0001F3CE\uFE0F", "JOURNEY", "journey"),
        ("\u2795", "EVENTS", "addevent"),
        ("\U0001F465", "CLIENTS", "clienthub"),
        ("\U0001F4D3", "LEDGER", "ledger"),
        ("\U0001F52C", "STATS+", "statsplus"),
    ]
    for row in (labels[:3], labels[3:]):
        cols = st.columns(3)
        for col, (icon, label, view) in zip(cols, row):
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

    from services.logo_studio import sync_logos_from_sheet as _sync_logos_from_sheet
    from services.logo_source import discover_logos as _discover_logos_btn, logo_data_uri as _logo_data_uri_btn
    if st.button("\U0001F504 Refresh", key="logostudio_refresh_btn"):
        # Manual, on-demand only - logos change rarely, so no reason to
        # poll on an interval. This exists for the one case Save's own
        # cache-clear doesn't cover: a logo added to the Sheet from
        # somewhere else entirely (a different device/session), which
        # would otherwise only surface here once sync_logos_from_sheet's
        # own 60s cache happened to expire on its own.
        _sync_logos_from_sheet.clear()
        _discover_logos_btn.clear()
        _logo_data_uri_btn.clear()
        st.rerun()

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
        # st.selectbox always allows typing to filter its options, even
        # without accept_new_options set - there's no way to turn that
        # off on that widget, which is what was popping the keyboard.
        # st.radio has no text entry at all - tap only, confirmed.
        raw_choice = st.radio("Raw logo file", raw_files, key="logostudio_raw")
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

    # Direct, undeniable proof of what's actually in assets/logos/ right
    # now - not a claim, not an explanation, the actual files with
    # actual thumbnails. Re-scans on every render of this page (this
    # is a low-traffic admin tool, not the main dashboard, so a fresh
    # os.listdir() here every time costs nothing worth caching against).
    st.markdown("#### Currently in `assets/logos/` right now")
    current_logo_files = sorted(
        p for p in logos_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")
    ) if logos_dir.exists() else []
    if not current_logo_files:
        st.warning("This folder is completely empty. Nothing has ever been saved here yet.")
    else:
        st.caption(f"{len(current_logo_files)} file(s), refreshed every time this page loads:")
        thumb_cols = st.columns(6)
        for i, logo_path in enumerate(current_logo_files):
            with thumb_cols[i % 6]:
                st.image(str(logo_path), width="stretch")
                st.caption(logo_path.name)

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
    # Old links to the retired V2 tabs land on the merged pages instead.
    view = {"mainv2": "main", "statsv2": "statsplus", "clientsv2": "clienthub", "ledgerv2": "ledger"}.get(view, view)
    render_header(view)
    # NET (default) / GROSS — one universal switch, read after the header drew it.
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
        render_v2_page("clienthub", snapshot.sheets["Timeline"], snapshot.sheets["Pipeline"], gross=gross_view)
        st.markdown(
            '<div style="text-align:center;margin-top:18px;font-size:10.5px;">'
            '<a href="?entered=1&view=logostudio" target="_self" style="color:#e8c94a;text-decoration:none;'
            'text-shadow:0 0 6px rgba(250,204,21,.85),0 0 14px rgba(250,204,21,.5);">'
            "Logo Studio</a></div>",
            unsafe_allow_html=True,
        )
        render_back_to_top_rocket()
    elif view == "ledger":
        # One-shot deep link (e.g. the CITIES gauge on Main): open to that tab,
        # then clear it so later reruns don't yank the user back.
        initial_ledger_tab = st.query_params.get("ledger_tab")
        if "ledger_tab" in st.query_params:
            del st.query_params["ledger_tab"]
        render_v2_page("ledger", snapshot.sheets["Timeline"], snapshot.sheets["Pipeline"],
                       gross=gross_view, tab=initial_ledger_tab)
        # Financial closeout panel, moved to the bottom of the page.
        render_ledger_summary(snapshot.sheets["Timeline"], gross_view)
        render_back_to_top_rocket()
    elif view == "statsplus":
        # Merged page: the V2 stats (key stats, distributions, cumulative
        # revenue last) on top, the original STAT+ content below, unchanged.
        render_v2_page("statsv2", snapshot.sheets["Timeline"], snapshot.sheets["Pipeline"], gross=gross_view)
        render_stats_plus(snapshot.sheets["Timeline"], gross_view)
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
        # wrapper markup again. (Now keyed to STATS+, which sits in the
        # second/bottom nav row since the V2 tabs were added — the row
        # directly above this page's iframe.)
        st.markdown(
            "<style>div[data-testid='stHorizontalBlock']:has(div.st-key-nav_statsplus) "
            "{ margin-bottom: -8px !important; }</style>",
            unsafe_allow_html=True,
        )
        render_dashboard(metrics, snapshot.sheets["Timeline"], gross_view, snapshot.sheets["Pipeline"])
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
        render_back_to_top_rocket()


if __name__ == "__main__":
    main()
