"""V2 preview tabs (Main V2, Clients V2, Ledger V2, Stats+ V2).

Each V2 tab renders one view of the BehrHub preview design inside a single
components.html() iframe, fed by the same live Timeline/Pipeline the
original pages use. Read-only: nothing here writes to the Sheet, session
state, or any file, and nothing here is imported by the original pages.

Safety: the whole render is wrapped in try/except, so if anything goes
wrong only the V2 tab shows a short error card - the original pages,
the nav bar and the rest of the app are unaffected.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from services.money_view import GROSS_MARGIN
from services.logo_source import discover_logos, logo_data_uri, resolve_client_logo
from services.tz import eastern_today_naive
from services.v2_data import build_v2_data

TEMPLATE_PATH = Path(__file__).resolve().parent / "v2_template.html"
LOGOS_DIR = Path(__file__).resolve().parent.parent / "assets" / "logos"

# Streamlit view name -> view id inside the V2 template. The V2 designs now
# ARE the CLIENTS and LEDGER pages; "statsv2" is rendered at the top of the
# merged STATS+ page (Main V2's region card lives in components/region_panel.py).
V2_VIEWS = {
    "clienthub": "clients",
    "ledger": "ledger",
}
_INNER = {"statsv2": "stats", **V2_VIEWS}

# Old Ledger tab ids (deep links such as Main's CITIES gauge) -> V2 tab ids.
_LEDGER_TAB_MAP = {
    "cities": "topCities", "clients": "topClients", "days": "topDays", "weeks": "topWeeks",
    "l10wk": "l10wk", "l10d": "l10d", "career": "cycles", "calendar": "months", "eras": "events",
}

# Static fallback height used only for the instant before the iframe's
# own JS measures itself and resizes (same pattern as client_hub.py).
_FALLBACK_HEIGHT = {"main": 2600, "clients": 4200, "ledger": 3000, "stats": 2300}


def _frame_fingerprint(frame: pd.DataFrame | None) -> str:
    if frame is None or frame.empty:
        return "empty"
    raw = pd.util.hash_pandas_object(frame.astype(str), index=False).values.tobytes()
    return hashlib.sha1(raw).hexdigest()


@st.cache_data(show_spinner=False, ttl=300)
def _cached_payload(fingerprint: str, today_iso: str, gross: bool, _timeline: pd.DataFrame, _pipeline: pd.DataFrame | None) -> str:
    # fingerprint + date + gross flag are the cache key; the frames themselves
    # are passed with a leading underscore so Streamlit doesn't re-hash them.
    if gross:
        # GROSS view: same assumption as the rest of the app (net = 62% of
        # gross), so every revenue figure on the V2 pages scales uniformly.
        _timeline = _timeline.copy()
        amt_col = next((c for c in _timeline.columns if str(c).strip().casefold() == "amount"), None)
        if amt_col is not None:
            _timeline[amt_col] = pd.to_numeric(_timeline[amt_col], errors="coerce") / GROSS_MARGIN
    data = build_v2_data(_timeline, _pipeline, today_iso)
    return json.dumps(data, separators=(",", ":"))


def _logo_map(clients: list[str]) -> dict[str, str]:
    try:
        logo_files, _dupes = discover_logos(LOGOS_DIR)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for name in clients:
        try:
            path = resolve_client_logo(name, logo_files)
            if path is not None:
                out[name] = logo_data_uri(path)
        except Exception:
            continue
    return out


def render_v2_page(view: str, timeline: pd.DataFrame, pipeline: pd.DataFrame | None,
                   gross: bool = False, tab: str | None = None) -> None:
    inner_view = _INNER.get(view, "main")
    try:
        today = eastern_today_naive()
        payload = _cached_payload(
            _frame_fingerprint(timeline) + "|" + _frame_fingerprint(pipeline),
            pd.Timestamp(today).strftime("%Y-%m-%d"),
            bool(gross),
            timeline,
            pipeline,
        )
        data = json.loads(payload)
        data["view"] = inner_view
        data["embed"] = True
        data["gross"] = bool(gross)
        if tab:
            data["tab"] = _LEDGER_TAB_MAP.get(str(tab), str(tab))
        if inner_view == "clients":
            names = sorted({s["name"] for s in data.get("standings", [])} | {t["n"] for t in data.get("ticker", [])})
            data["logos"] = _logo_map(names)
        # </script> inside a JSON string would end the script tag early.
        blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
        html = TEMPLATE_PATH.read_text(encoding="utf-8").replace("__DATA__", blob, 1)
    except Exception as exc:  # never let a V2 problem break the app
        st.markdown(
            '<div style="background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.4);'
            'border-radius:12px;padding:12px 14px;color:#fecaca;font-size:14px;font-weight:600;">'
            "V2 preview couldn't load this page: "
            f"{type(exc).__name__}: {str(exc)[:200]}"
            "</div>",
            unsafe_allow_html=True,
        )
        return
    components.html(html, height=_FALLBACK_HEIGHT.get(inner_view, 2600), scrolling=False)
