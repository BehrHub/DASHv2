from __future__ import annotations

import base64

import json
from datetime import date, datetime
from html import escape
import math
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote, unquote

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

try:
    import folium
    from streamlit_folium import st_folium

    FOLIUM_AVAILABLE = True
except ModuleNotFoundError:
    folium = None
    st_folium = None
    FOLIUM_AVAILABLE = False

from workbook_source import (
    WorkbookData,
    empty_pipeline_frame,
    find_source_workbook,
    load_workbook,
    normalize_label,
    read_xlsx,
    scorecard_metric,
    workbook_version,
)
from map_source import (
    load_locations,
    match_report_table,
    match_timeline_locations,
)
from logo_source import (
    client_initials,
    discover_logos,
    logo_data_uri,
    resolve_client_logo,
)
from event_writer import (
    append_service_event,
    build_service_event_draft,
    complete_scheduled_assignment,
    delete_existing_event,
    replace_workbook_sheet_table,
    update_existing_event,
)
from pages.career_analytics_page import render_career_analytics_page


APP_NAME = "Barrister Dashboard"
COLORS = ["#2dd4bf", "#38bdf8", "#a78bfa", "#f59e0b", "#fb7185", "#94a3b8"]
JURISDICTION_COLORS = {
    "Maryland": "#2dd4bf",
    "Virginia": "#5c8ee8",
    "Washington, D.C.": "#f97316",
    "West Virginia": "#a78bfa",
    "Pennsylvania / Other": "#f5c542",
}
JURISDICTION_DONUT_STYLES = {
    "Maryland": {"color": "#d85a62", "depth": "#742932", "icon": "🦀"},
    "Washington, D.C.": {"color": "#d7a63d", "depth": "#74531d", "icon": "🏛️"},
    "Virginia": {"color": "#5c8ee8", "depth": "#274f99", "icon": "❤️"},
    "West Virginia": {"color": "#a78bfa", "depth": "#4c3f78", "icon": "🏔️"},
    "Pennsylvania": {"color": "#5dbb82", "depth": "#276942", "icon": "🔔"},
    "Pennsylvania / Other": {"color": "#5dbb82", "depth": "#276942", "icon": "🔔"},
}
USDA_TOTAL_REVENUE = 1355.0
USDA_VISIT_COUNT = 6
USDA_AVG_REVENUE = USDA_TOTAL_REVENUE / USDA_VISIT_COUNT
REVENUE_ATTRIBUTION_BREAKDOWNS = {
    "USDA": [200, 175, 320, 320, 220, 120],
    "Under Armour": [120, 140],
}
CLIENT_CARD_ALIASES = {
    "Hebrew Home of Greater Washington": "Hebrew Home of GW",
    "Maryland Baptist Age Home": "MD Baptist Age Home",
    "Office of MD Senator Chris Van Hollen": "Office of MD Van Hollen",
    "Office of MD Senator Angela Alsobrooks": "Office of MD Alsobrooks",
}
DASHBOARD_PAGES = {
    "Main": "main",
    "Client Timeline": "client-timeline",
    "Add Service Event": "add-service-event",
    "Client": "client",
    "Finance": "finance",
    "Ledger": "ledger",
    "Designer": "designer",
    "Test Tube Two": "test-tube-two",
}
NAV_DISPLAY = {
    "Main": {"label": "Main", "icon": "🏁", "accent": "#f472b6"},
    "Client Timeline": {"label": "Journey", "icon": "🏎️", "accent": "#dc2626"},
    "Add Service Event": {"label": "Add Event", "icon": "➕", "accent": "#f97316"},
    "Client": {"label": "Client", "icon": "👥", "accent": "#2dd4bf"},
    "Finance": {"label": "Finance", "icon": "💰", "accent": "#22c55e"},
    "Ledger": {"label": "Ledger", "icon": "📓", "accent": "#38bdf8"},
    "Designer": {"label": "Designer", "icon": "🎨", "accent": "#f4d054"},
    "Test Tube Two": {"label": "Test Tube 2", "icon": "🧫", "accent": "#a78bfa"},
}
HIDDEN_PAGES = {
    "Coordinate Match Report": "coordinate-match-report",
    "add-event": "Add Service Event",
    "add-service-event": "Add Service Event",
    "journey": "Journey",
    "barrister-journey": "Journey",
    "ledger": "Ledger",
}
PAGE_ROUTE_ALIASES = {
    "main": "Main",
    "executive-summary": "Main",
    "exec": "Main",
    "client-timeline": "Client Timeline",
    "journey": "Client Timeline",
    "add-event": "Add Service Event",
    "add-service-event": "Add Service Event",
    "client": "Client",
    "top-clients": "Client",
    "client-analytics": "Client",
    "career-analytics": "Client",
    "finance": "Finance",
    "financial-status": "Finance",
    "ledger": "Ledger",
    "test-tube": "Designer",
    "designer": "Designer",
    "test-tube-two": "Test Tube Two",
}
LOCATIONS_PATH = Path(__file__).parent / "data" / "locations.csv"
LOGOS_DIR = Path(__file__).parent / "assets" / "logos"
BRAND_FACTORY_APPROVED_DIR = Path(__file__).parent / "assets" / "brand_factory" / "approved"
BACKUPS_DIR = Path(__file__).parent / "data" / "backups"
SPLASH_IMAGE_PATH = Path(__file__).resolve().parent / "static" / "splash" / "barrister_splash.jpg"
SPLASH_IMAGE_URL = "data:image/jpeg;base64," + base64.b64encode(SPLASH_IMAGE_PATH.read_bytes()).decode("ascii") if SPLASH_IMAGE_PATH.exists() else ""
SPLASH_IMAGE_WIDTH = 853
SPLASH_IMAGE_HEIGHT = 1280
PIN_ICON_URLS = {
    "Maryland": "app/static/map/pin_maryland.svg",
    "Virginia": "app/static/map/pin_virginia.svg",
    "Washington, D.C.": "app/static/map/pin_dc.svg",
    "West Virginia": "app/static/map/pin_pennsylvania.svg",  # TODO: swap once a dedicated pin_west_virginia.svg (purple, #a78bfa) is added
    "Pennsylvania / Other": "app/static/map/pin_pennsylvania.svg",
}
PLOTLY_CONFIG = {
    "displayModeBar": False,
    "scrollZoom": False,
    "doubleClick": False,
    "showTips": False,
    "responsive": True,
}


@st.cache_data(show_spinner=False)
def cached_workbook(path: str, modified_ns: int, size: int) -> WorkbookData:
    _ = modified_ns, size
    return load_workbook(Path(path))


def compact(markup: str) -> str:
    """Strip indentation and drop blank lines so indented HTML never gets
    mis-parsed as a CommonMark indented code block. Safe to use on HTML
    bodies; <style> blocks don't need it (raw HTML block type-1 already
    tolerates blank lines) but it doesn't hurt them either."""
    return "\n".join(line.strip() for line in markup.splitlines() if line.strip())


def configure_page() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="EC", layout="wide", initial_sidebar_state="collapsed")
    _month_tokens = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    _current_month_token = _month_tokens[date.today().month - 1]
    st.markdown(
        compact(f"<style>:root {{ --hero-accent: var(--kith-month-{_current_month_token}); --hero-accent-rgb: var(--kith-month-{_current_month_token}-rgb); }}</style>"),
        unsafe_allow_html=True,
    )
    st.markdown(
        compact("""
<style>
        @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@500;700;900&family=Merriweather:wght@700;900&display=swap');
        .stApp { background: linear-gradient(180deg, var(--kith-genesis) 0px, var(--kith-battleship) 400px, var(--kith-battleship) 100%); font-family: "Bebas Neue", "Arial Narrow", sans-serif; }
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"] { height: 0 !important; min-height: 0 !important; background: transparent !important; border-bottom: none !important; visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }
        [data-testid="stToolbar"] *,
        [data-testid="stStatusWidget"] *,
        button[kind="header"],
        [data-testid="stMainMenu"] { visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }
        [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] { display: none !important; }
        .block-container { max-width: 1480px; padding-top: .75rem; padding-bottom: 2.5rem; }
        h1, h2, h3 { letter-spacing: -0.025em; }

        @media (max-width: 700px) {
            .hero-title-logo {
                width: min(96vw, 520px);
                max-height: 74px;
            }
        }


        .hero-title-ascii {
            color: #f8fafc;
            font-family: "Courier New", "SF Mono", Menlo, Monaco, monospace;
            font-size: clamp(2.35rem, 5.4vw, 4.45rem);
            font-weight: 900;
            line-height: .9;
            letter-spacing: -.085em;
            margin: .05rem 0 .78rem;
            text-transform: none;
            text-shadow:
                2px 0 0 rgba(15,23,42,.92),
                -2px 0 0 rgba(15,23,42,.92),
                0 2px 0 rgba(15,23,42,.92),
                0 -2px 0 rgba(15,23,42,.92),
                0 0 24px rgba(248,250,252,.12),
                0 14px 28px rgba(0,0,0,.34);
        }
        @media (max-width: 700px) {
            .hero-title-ascii {
                font-size: 2.1rem;
                letter-spacing: -.075em;
                margin: .02rem 0 .7rem;
            }
        }

        .hero-title { color: var(--kith-chalk); font-family: "Merriweather", Georgia, serif; font-size: clamp(2.45rem, 5vw, 3.95rem); font-weight: 850; margin: .08rem 0 .78rem; line-height: .94; letter-spacing: -.028em; text-shadow: 0 0 9px rgba(244,114,182,.2), 0 0 17px rgba(244,114,182,.12), 0 14px 28px rgba(0,0,0,.3); }
        .hero-title-link, .hero-title-link:visited, .hero-title-link:hover, .hero-title-link:active { color: inherit !important; text-decoration: none !important; cursor: pointer; }
        .executive-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .65rem; margin: .2rem 0 .8rem; }
        .metric-card { min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: .38rem; text-align: center; background: radial-gradient(circle at 50% 0%, rgba(255,255,255,.055), transparent 46%), linear-gradient(145deg, rgba(21,36,58,.9), rgba(8,18,32,.94)); border: 1px solid rgba(148,163,184,.18); border-radius: 12px; padding: .78rem .82rem; min-height: 94px; box-shadow: 0 14px 34px rgba(0,0,0,.2), inset 0 1px 0 rgba(255,255,255,.055); backdrop-filter: blur(10px); }
        .metric-label { width: 100%; color: #bfe9ff; font-size: .62rem; font-weight: 800; letter-spacing: .085em; line-height: 1.16; text-align: center; text-transform: uppercase; text-shadow: 0 0 8px rgba(125,211,252,.28), 0 5px 12px rgba(0,0,0,.24); }
        .metric-value { position: relative; z-index: 0; width: 100%; display: flex; align-items: center; justify-content: center; color: #ffffff; font-size: 2.72rem; font-weight: 900; margin: 0; line-height: .86; text-shadow: 0 0 24px rgba(255,255,255,.52), 0 0 44px rgba(255,255,255,.2), 0 10px 22px rgba(0,0,0,.3); }
        .metric-value::before { content: ""; position: absolute; inset: 2% 10%; z-index: -1; border-radius: 999px; background: radial-gradient(circle, rgba(255,255,255,.24), rgba(255,255,255,.08) 42%, transparent 70%); filter: blur(10px); }
        .upcoming-assignments { margin: .1rem 0 .85rem; padding: .72rem .85rem; border: 1px solid #243751; border-radius: 13px; background: rgba(13,25,43,.78); }
        .upcoming-title { color: #f1f5fa; font-size: .86rem; font-weight: 780; margin-bottom: .36rem; }
        .upcoming-list { display: grid; gap: .24rem; margin: 0; padding: 0; list-style: none; }
        .upcoming-list li { color: #cbd8e9; font-size: .78rem; line-height: 1.25; }
        .upcoming-list strong { color: #f8fafc; font-weight: 720; }
        .top-nav { display: flex; gap: .42rem; overflow-x: auto; overscroll-behavior-inline: contain; padding: .08rem 0 .48rem; margin: .08rem 0 .34rem; scrollbar-width: thin; scrollbar-color: #38506f transparent; scroll-snap-type: inline proximity; }
        .top-nav::-webkit-scrollbar { height: 5px; }
        .top-nav::-webkit-scrollbar-thumb { background: #38506f; border-radius: 999px; }
        .top-nav-link { position: relative; display: flex; flex: 0 0 74px; width: 74px; min-height: 58px; flex-direction: column; align-items: center; justify-content: center; gap: .18rem; padding: .42rem .38rem .58rem; border: 1px solid color-mix(in srgb, var(--nav-accent, #2dd4bf) 26%, rgba(80,103,133,.34)); border-radius: 13px; background: radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--nav-accent, #2dd4bf) 10%, transparent), transparent 54%), linear-gradient(180deg, rgba(20,34,55,.42), rgba(8,17,31,.7)); color: #aebdd1 !important; font-size: .57rem; font-weight: 880; letter-spacing: .045em; line-height: 1; text-transform: uppercase; text-align: center; text-decoration: none !important; scroll-snap-align: start; box-shadow: inset 0 1px 0 rgba(255,255,255,.035); opacity: .86; }
        .top-nav-link::after { content: ""; position: absolute; left: 50%; bottom: .24rem; width: 42px; height: 3px; border-radius: 999px; background: var(--nav-accent, #2dd4bf); opacity: .34; transform: translateX(-50%) scaleX(.62); transition: opacity .16s ease, transform .16s ease, box-shadow .16s ease; }
        .top-nav-link:hover { border-color: color-mix(in srgb, var(--nav-accent, #2dd4bf) 38%, rgba(148,163,184,.36)); background: radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--nav-accent, #2dd4bf) 14%, transparent), transparent 56%), linear-gradient(180deg, rgba(20,34,55,.58), rgba(8,17,31,.78)); color: #d8e3f1 !important; opacity: .96; }
        .top-nav-link.active { border-color: color-mix(in srgb, var(--nav-accent, #2dd4bf) 68%, rgba(226,232,240,.22)); background: radial-gradient(circle at 50% -8%, color-mix(in srgb, var(--nav-accent, #2dd4bf) 24%, transparent), transparent 58%), linear-gradient(180deg, rgba(30,45,68,.76), rgba(9,19,34,.92)); color: #f8fafc !important; opacity: 1; box-shadow: 0 0 0 1px color-mix(in srgb, var(--nav-accent, #2dd4bf) 34%, transparent), 0 10px 20px rgba(0,0,0,.2), 0 0 16px color-mix(in srgb, var(--nav-accent, #2dd4bf) 18%, transparent), inset 0 1px 0 rgba(255,255,255,.07); }
        .top-nav-link.active::after { opacity: 1; transform: translateX(-50%) scaleX(1); box-shadow: 0 0 12px color-mix(in srgb, var(--nav-accent, #2dd4bf) 68%, transparent); }
        .nav-icon { color: var(--nav-accent, #2dd4bf); font-size: 1rem; line-height: 1; filter: saturate(.92); opacity: .78; }
        .top-nav-link.active .nav-icon { opacity: 1; filter: saturate(1.12) drop-shadow(0 0 8px color-mix(in srgb, var(--nav-accent, #2dd4bf) 46%, transparent)); }
        .nav-label { display: block; width: 100%; white-space: normal; overflow-wrap: normal; text-align: center; }
        .client-link, .client-link:visited { color: inherit !important; text-decoration: none !important; }
        .client-link:hover { color: #70ddd1 !important; }
        .section-kicker { color: #8fa1bb; font-size: .64rem; font-weight: 820; letter-spacing: .13em; text-transform: uppercase; margin: .1rem 0 .1rem; }
        .section-title { color: #f8fafc; font-family: "Space Grotesk", "SF Pro Display", "Aptos Display", "Segoe UI", Arial, sans-serif; font-size: clamp(1.32rem, 3vw, 1.9rem); font-weight: 820; letter-spacing: -.04em; text-transform: none; margin: 0 0 .58rem; text-shadow: 0 0 18px rgba(255,255,255,.08), 0 10px 24px rgba(0,0,0,.24); }
        .standings-board { display: grid; gap: .42rem; margin: .1rem 0 .95rem; }
        .standing-row { display: grid; grid-template-columns: minmax(96px, 132px) minmax(0, 1fr) auto; gap: .72rem; align-items: center; padding: .58rem .72rem; border: 1px solid #243751; border-radius: 12px; background: linear-gradient(135deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); box-shadow: 0 9px 22px rgba(0,0,0,.14); overflow: hidden; }
        .standing-row.podium { border-color: rgba(245,197,66,.34); background: linear-gradient(135deg, rgba(41,38,32,.98), rgba(13,25,43,.96)); }
        .standing-rank { color: #f6d892; font-size: .68rem; font-weight: 850; letter-spacing: .055em; text-transform: uppercase; white-space: nowrap; }
        .standing-main { min-width: 0; display: grid; gap: .28rem; }
        .standing-client { min-width: 0; color: #f8fafc; font-size: .94rem; font-weight: 800; line-height: 1.12; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .standing-track { width: 100%; height: 7px; overflow: hidden; border-radius: 999px; background: rgba(148,163,184,.14); }
        .standing-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #d85a62, #f5c542 48%, #2dd4bf); box-shadow: 0 0 14px rgba(45,212,191,.18); }
        .standing-visits { color: #f8fafc; font-size: .76rem; font-weight: 850; text-align: right; white-space: nowrap; }
        .standing-client-line { min-width: 0; display: flex; align-items: center; gap: .48rem; }
        .client-logo-badge { flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; width: 42px; height: 42px; border: 1px solid rgba(148,163,184,.18); border-radius: 12px; background: radial-gradient(circle at 28% 18%, rgba(255,255,255,.1), rgba(15,33,54,.8) 42%, rgba(8,17,31,.92)); box-shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 8px 18px rgba(0,0,0,.18); overflow: hidden; color: #bfe9ff; font-size: .76rem; font-weight: 880; letter-spacing: .04em; text-align: center; }
        .client-logo-badge img { width: 118%; height: 118%; object-fit: contain; box-sizing: border-box; padding: 0; background: rgba(248,250,252,.94); border: 1px solid rgba(191,233,255,.28); box-shadow: 0 0 16px rgba(56,189,248,.18); filter: none; transition: filter .16s ease, transform .16s ease; }
        .client-link:hover .client-logo-badge img, .portfolio-logo-card:hover .client-logo-badge img { filter: grayscale(0) contrast(1); transform: scale(1.04); }
        .client-logo-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
        .client-portfolio { margin: .15rem 0 .85rem; padding: .86rem; border: 1px solid #243751; border-radius: 18px; background: radial-gradient(circle at 16% 0%, rgba(56,189,248,.1), transparent 34%), linear-gradient(145deg, rgba(14,27,46,.88), rgba(8,17,31,.94)); box-shadow: 0 16px 34px rgba(0,0,0,.18), inset 0 1px 0 rgba(255,255,255,.045); }
        .portfolio-heading { color: #bfe9ff; font-size: .66rem; font-weight: 880; letter-spacing: .16em; text-transform: uppercase; margin: 0 0 .7rem; text-shadow: 0 0 10px rgba(34,197,94,.34); }
        .portfolio-logo-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: .48rem; }
        .portfolio-logo-card { min-width: 0; min-height: 104px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: .34rem; padding: .18rem; border: 1px solid rgba(34,197,94,.34); border-radius: 12px; background: rgba(8,17,31,.45); text-decoration: none !important; color: #e7eef8 !important; box-shadow: 0 0 0 1px rgba(34,197,94,.34), 0 0 18px rgba(56,189,248,.24), 0 0 34px rgba(56,189,248,.12); transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }
        .portfolio-logo-card:hover, .portfolio-logo-card:active { border-color: rgba(125,211,252,.55); box-shadow: 0 0 22px rgba(56,189,248,.22); transform: translateY(-1px) scale(1.015); }
        .portfolio-logo-card .client-logo-badge { width: 88px; height: 88px; border-radius: 16px; }
        .portfolio-logo-name {
    display: none;
}
        .records-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .62rem; margin: .1rem 0 1rem; }
        .record-card { min-width: 0; padding: .72rem .78rem; border: 1px solid #243751; border-radius: 15px; background: radial-gradient(circle at 20% 10%, rgba(45,212,191,.13), transparent 34%), linear-gradient(145deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); box-shadow: 0 9px 22px rgba(0,0,0,.14); }
        .record-label { color: #9eb0c8; font-size: .64rem; font-weight: 820; letter-spacing: .08em; line-height: 1.1; text-transform: uppercase; margin-bottom: .44rem; }
        .record-client { color: #f8fafc; font-size: .95rem; font-weight: 820; line-height: 1.12; min-height: 2.1em; }
        .record-value { color: #70ddd1; font-size: .76rem; font-weight: 780; margin-top: .36rem; }
        .client-profile { margin: .12rem 0 1rem; padding: .82rem; border: 1px solid #243751; border-radius: 18px; background: radial-gradient(circle at 20% 10%, rgba(45,212,191,.1), transparent 34%), linear-gradient(145deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); box-shadow: 0 12px 28px rgba(0,0,0,.16); }
        .profile-top { display: flex; justify-content: space-between; align-items: flex-start; gap: .8rem; margin-bottom: .7rem; }
        .profile-title { color: #f8fafc; font-size: clamp(1.25rem, 4vw, 1.8rem); font-weight: 860; line-height: 1.05; }
        .profile-back { color: #70ddd1 !important; font-size: .76rem; font-weight: 760; text-decoration: none !important; white-space: nowrap; }
        .profile-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .48rem; margin-bottom: .78rem; }
        .profile-metric { padding: .56rem .6rem; border: 1px solid rgba(148,163,184,.15); border-radius: 12px; background: rgba(8,17,31,.5); text-align: center; }
        .profile-metric-value { color: #f8fafc; font-size: .96rem; font-weight: 850; line-height: 1; }
        .profile-metric-label { color: #9fb1c8; font-size: .52rem; font-weight: 760; letter-spacing: .06em; margin-top: .22rem; text-transform: uppercase; }
        .profile-detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .44rem; margin-bottom: .78rem; }
        .profile-detail { padding: .5rem .58rem; border-radius: 11px; background: rgba(8,17,31,.38); }
        .profile-detail-label { color: #8fa1bb; font-size: .54rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; }
        .profile-detail-value { color: #f1f5fa; font-size: .76rem; font-weight: 720; margin-top: .16rem; }
        .profile-visit-list { display: grid; gap: .36rem; }
        .profile-visit { display: grid; grid-template-columns: 54px minmax(0, 1fr) auto; gap: .55rem; align-items: center; padding: .52rem .58rem; border: 1px solid rgba(148,163,184,.14); border-radius: 12px; background: rgba(8,17,31,.42); }
        .profile-visit-number { color: #77e1d5; font-size: .7rem; font-weight: 850; }
        .profile-visit-main { min-width: 0; display: grid; gap: .14rem; }
        .profile-visit-location { color: #f8fafc; font-size: .76rem; font-weight: 780; }
        .profile-visit-notes { color: #aebdd1; font-size: .64rem; line-height: 1.18; }
        .profile-visit-money { color: #70ddd1; font-size: .72rem; font-weight: 850; text-align: right; white-space: nowrap; }
        .financial-section { margin: .1rem 0 1rem; }
        .financial-board { display: grid; gap: .38rem; margin: .15rem 0 .9rem; }
        .financial-row { display: grid; grid-template-columns: 56px minmax(0, 1fr) 74px minmax(96px, auto) minmax(86px, auto); gap: .5rem; align-items: center; padding: .5rem .62rem; border: 1px solid #243751; border-radius: 13px; background: linear-gradient(135deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); box-shadow: 0 7px 18px rgba(0,0,0,.12); }
        .financial-row.avg-row { grid-template-columns: 56px minmax(0, 1fr) 74px minmax(98px, auto); }
        .financial-row.compact { grid-template-columns: minmax(0, 1fr) minmax(96px, auto) minmax(78px, auto); }
        .financial-row.state-row { grid-template-columns: minmax(0, 1fr) minmax(92px, auto) minmax(64px, auto) minmax(86px, auto); }
        .financial-card-row { display: grid; gap: .34rem; padding: .62rem .7rem; border: 1px solid #243751; border-radius: 12px; background: linear-gradient(135deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); box-shadow: 0 7px 18px rgba(0,0,0,.12); }
        .financial-card-top { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .55rem; align-items: center; }
        .financial-card-title { min-width: 0; color: #f8fafc; font-size: .82rem; font-weight: 820; line-height: 1.1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .financial-card-value { color: #70ddd1; font-size: .8rem; font-weight: 850; text-align: right; white-space: nowrap; }
        .financial-card-track { height: 7px; overflow: hidden; border-radius: 999px; background: rgba(148,163,184,.14); }
        .financial-card-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #d85a62, #f5c542 50%, #2dd4bf); box-shadow: 0 0 14px rgba(45,212,191,.18); }
        .financial-card-meta { display: flex; justify-content: space-between; gap: .7rem; color: #c2cddd; font-size: .65rem; font-weight: 720; line-height: 1.15; }
        .financial-rank { color: #f6d892; font-size: .7rem; font-weight: 850; text-transform: uppercase; }
        .financial-client, .financial-state, .financial-month { min-width: 0; color: #f8fafc; font-size: .82rem; font-weight: 780; line-height: 1.12; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .financial-meta { color: #c2cddd; font-size: .68rem; font-weight: 720; text-align: right; white-space: nowrap; }
        .financial-money { color: #70ddd1; font-size: .76rem; font-weight: 820; text-align: right; white-space: nowrap; }
        .integrity-card { margin: .15rem 0 .8rem; padding: .72rem .8rem; border: 1px solid #243751; border-radius: 12px; background: rgba(13,25,43,.76); }
        .integrity-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .48rem; }
        .integrity-stat { padding: .48rem .5rem; border-radius: 11px; background: rgba(8,17,31,.54); text-align: center; }
        .integrity-value { color: #f8fafc; font-size: 1rem; font-weight: 850; line-height: 1; }
        .integrity-label { color: #aebdd1; font-size: .56rem; font-weight: 760; letter-spacing: .05em; margin-top: .22rem; text-transform: uppercase; }
        .ledger-path { color: #c2cddd; font-size: .72rem; line-height: 1.25; overflow-wrap: anywhere; }
        .ledger-kpi-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .55rem; margin: .25rem 0 .75rem; }
        .ledger-kpi-card { min-width: 0; padding: .68rem .72rem; border: 1px solid rgba(148,163,184,.16); border-radius: 12px; background: radial-gradient(circle at 50% 0%, rgba(255,255,255,.045), transparent 48%), linear-gradient(145deg, rgba(20,34,55,.92), rgba(8,18,32,.94)); box-shadow: 0 12px 26px rgba(0,0,0,.18), inset 0 1px 0 rgba(255,255,255,.05); text-align: center; }
        .ledger-kpi-value { color: #fff; font-size: clamp(1.25rem, 3vw, 1.9rem); font-weight: 880; line-height: 1; text-shadow: 0 0 14px rgba(255,255,255,.18), 0 8px 18px rgba(0,0,0,.24); }
        .ledger-kpi-label { margin-top: .28rem; color: #aebdd1; font-size: .58rem; font-weight: 820; letter-spacing: .06em; line-height: 1.05; text-transform: uppercase; }
        .change-summary { margin: .2rem 0 .7rem; padding: .62rem .72rem; border: 1px solid rgba(245,197,66,.34); border-radius: 12px; background: rgba(42,36,27,.76); color: #ffe8a3; font-size: .76rem; font-weight: 730; }
        .chart-lab-note { color: #aebdd1; font-size: .74rem; line-height: 1.35; margin: -.18rem 0 .72rem; }
        .chart-lab-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .72rem; margin: .15rem 0 1rem; align-items: stretch; }
        .chart-style-card { min-width: 0; min-height: 300px; padding: .84rem .88rem; border: 1px solid #243751; border-radius: 17px; background: radial-gradient(circle at 18% 12%, rgba(45,212,191,.1), transparent 34%), linear-gradient(145deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); box-shadow: 0 11px 26px rgba(0,0,0,.16); overflow: hidden; }
        .chart-style-label { color: #f6d892; font-size: .62rem; font-weight: 850; letter-spacing: .1em; text-transform: uppercase; margin-bottom: .24rem; }
        .chart-style-title { color: #f8fafc; font-size: .98rem; font-weight: 840; margin-bottom: .18rem; line-height: 1.1; }
        .chart-style-story { color: #9fb1c8; font-size: .66rem; font-weight: 680; line-height: 1.24; margin-bottom: .65rem; }
        .lab-columns { height: 185px; display: flex; align-items: stretch; gap: .7rem; padding: .35rem .1rem .2rem; border-bottom: 1px solid rgba(148,163,184,.18); }
        .lab-column-item { min-width: 0; height: 100%; flex: 1; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: .35rem; align-items: end; text-align: center; }
        .lab-column-value { color: #70ddd1; font-size: .62rem; font-weight: 820; white-space: nowrap; }
        .lab-column-bar { width: 100%; min-height: 10px; border-radius: 8px 8px 2px 2px; background: linear-gradient(180deg, #70ddd1, #2dd4bf 58%, #1f8f87); box-shadow: 0 8px 18px rgba(45,212,191,.16); }
        .lab-column-label { color: #c2cddd; font-size: .56rem; font-weight: 740; line-height: 1.05; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .premium-columns .lab-column-bar { border-radius: 999px 999px 10px 10px; background: linear-gradient(180deg, #fff4bf 0%, #f5c542 26%, #d85a62 100%); box-shadow: inset 0 1px 0 rgba(255,255,255,.38), 0 12px 20px rgba(245,197,66,.16); }
        .pseudo3d-columns .lab-column-bar { position: relative; border-radius: 6px 6px 2px 2px; background: linear-gradient(135deg, #5c8ee8 0%, #2dd4bf 72%); transform: skewX(-5deg); box-shadow: 9px 9px 0 rgba(10,21,36,.8), 0 10px 22px rgba(92,142,232,.18); }
        .pseudo3d-columns .lab-column-bar::before { content: ""; position: absolute; top: 0; right: -9px; width: 9px; height: 100%; transform: skewY(42deg); transform-origin: left top; background: linear-gradient(180deg, rgba(112,221,209,.7), rgba(39,79,153,.78)); border-radius: 0 5px 2px 0; }
        .executive-columns .lab-column-bar { border-radius: 5px 5px 0 0; background: linear-gradient(180deg, #dce5f1, #5c8ee8 44%, #274f99); box-shadow: 0 12px 20px rgba(92,142,232,.15); }
        .premium3d-columns .lab-column-bar { position: relative; border-radius: 7px 7px 2px 2px; background: linear-gradient(160deg, #f8fafc 0%, #f5c542 32%, #d85a62 100%); box-shadow: 10px 10px 0 rgba(68,34,20,.78), 0 14px 24px rgba(245,197,66,.16); transform: perspective(160px) rotateX(1deg) skewX(-4deg); }
        .premium3d-columns .lab-column-bar::after { content: ""; position: absolute; inset: 0 0 auto auto; width: 28%; height: 100%; background: linear-gradient(180deg, rgba(255,255,255,.28), rgba(92,47,20,.3)); border-radius: 0 7px 2px 0; transform: skewY(18deg); transform-origin: top right; }
        .tower-grid, .chip-grid, .radial-grid, .fuel-grid, .skyline-grid, .trophy-grid, .vault-grid, .container-grid, .power-grid, .wildcard-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .5rem; align-items: end; }
        .tower-item, .chip-item, .radial-item, .fuel-item, .skyline-item, .trophy-item, .vault-item, .container-item, .power-item, .wildcard-item { min-width: 0; display: grid; justify-items: center; gap: .32rem; text-align: center; }
        .money-tower { min-height: 138px; display: flex; flex-direction: column-reverse; gap: 3px; justify-content: flex-start; }
        .money-block { width: 42px; height: 12px; border-radius: 3px; background: linear-gradient(90deg, #1f8f87, #70ddd1); box-shadow: inset 0 1px 0 rgba(255,255,255,.28); }
        .chip-stack { min-height: 138px; display: flex; flex-direction: column-reverse; gap: 0; justify-content: flex-start; }
        .casino-chip { width: 48px; height: 11px; margin-top: -2px; border-radius: 999px; background: radial-gradient(circle at 50% 35%, #fff7d6 0 18%, #d85a62 19% 42%, #f5c542 43% 58%, #8a2f38 59% 100%); border: 1px solid rgba(255,255,255,.16); box-shadow: 0 3px 5px rgba(0,0,0,.18); }
        .tower-unit { color: #8fa1bb; font-size: .58rem; font-weight: 740; text-align: right; margin-top: .45rem; }
        .garage-board { display: grid; gap: .44rem; }
        .garage-row { display: grid; grid-template-columns: minmax(70px, 112px) minmax(0, 1fr) auto; gap: .52rem; align-items: center; padding: .44rem .5rem; border-radius: 12px; background: linear-gradient(90deg, rgba(8,17,31,.72), rgba(20,34,55,.5)); border-left: 3px solid #d85a62; }
        .garage-team { min-width: 0; color: #f8fafc; font-size: .7rem; font-weight: 820; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .garage-track { height: 14px; overflow: hidden; border-radius: 3px; background: repeating-linear-gradient(90deg, rgba(148,163,184,.18) 0 8px, rgba(148,163,184,.08) 8px 16px); }
        .garage-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, #d85a62, #f5c542 55%, #2dd4bf); box-shadow: 0 0 14px rgba(245,197,66,.15); }
        .garage-value { color: #70ddd1; font-size: .64rem; font-weight: 850; white-space: nowrap; }
        .champ-podium { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .55rem; align-items: end; min-height: 180px; }
        .champ-step { display: grid; gap: .35rem; align-content: end; justify-items: center; text-align: center; }
        .champ-medal { font-size: 1.35rem; }
        .champ-name { max-width: 100%; color: #f8fafc; font-size: .7rem; font-weight: 830; line-height: 1.08; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .champ-value { color: #70ddd1; font-size: .66rem; font-weight: 820; }
        .champ-block { width: 100%; border-radius: 10px 10px 3px 3px; background: linear-gradient(180deg, rgba(245,197,66,.92), rgba(216,90,98,.72)); box-shadow: inset 0 1px 0 rgba(255,255,255,.25); }
        .radial-medal { width: 82px; height: 82px; display: grid; place-items: center; border-radius: 999px; background: conic-gradient(#2dd4bf var(--pct), rgba(148,163,184,.16) 0); box-shadow: inset 0 0 0 10px rgba(8,17,31,.88), 0 8px 18px rgba(0,0,0,.16); color: #f8fafc; font-size: .72rem; font-weight: 850; }
        .fuel-tank { position: relative; width: 46px; height: 138px; display: flex; align-items: flex-end; overflow: hidden; border: 1px solid rgba(148,163,184,.28); border-radius: 16px 16px 8px 8px; background: linear-gradient(180deg, rgba(8,17,31,.84), rgba(13,25,43,.96)); box-shadow: inset 0 0 0 4px rgba(148,163,184,.07); }
        .fuel-fill { width: 100%; min-height: 5%; background: linear-gradient(180deg, #f5c542, #f97316 54%, #d85a62); box-shadow: 0 0 16px rgba(249,115,22,.2); }
        .fuel-tank::before { content: ""; position: absolute; inset: 12px 8px auto; height: 2px; background: repeating-linear-gradient(90deg, rgba(255,255,255,.3) 0 5px, transparent 5px 10px); box-shadow: 0 26px 0 rgba(255,255,255,.16), 0 52px 0 rgba(255,255,255,.16), 0 78px 0 rgba(255,255,255,.16); }
        .skyline-building { width: 100%; min-height: 10px; position: relative; border-radius: 5px 5px 0 0; background: linear-gradient(180deg, #5c8ee8, #14243a 72%); box-shadow: 8px 8px 0 rgba(8,17,31,.72); overflow: hidden; }
        .skyline-building::after { content: ""; position: absolute; inset: 8px 7px; background: repeating-linear-gradient(180deg, rgba(245,197,66,.62) 0 3px, transparent 3px 12px), repeating-linear-gradient(90deg, transparent 0 8px, rgba(245,197,66,.45) 8px 10px, transparent 10px 18px); opacity: .7; }
        .pit-lane { display: grid; gap: .5rem; }
        .pit-row { display: grid; grid-template-columns: minmax(74px, 112px) minmax(0, 1fr) auto; gap: .5rem; align-items: center; }
        .pit-track { position: relative; height: 18px; overflow: hidden; border-radius: 999px; background: repeating-linear-gradient(90deg, rgba(148,163,184,.18) 0 16px, rgba(148,163,184,.08) 16px 32px); }
        .pit-progress { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #d85a62, #f5c542 55%, #2dd4bf); box-shadow: 0 0 16px rgba(45,212,191,.16); }
        .pit-track::after { content: ""; position: absolute; right: 0; top: 0; width: 18px; height: 100%; background: repeating-linear-gradient(45deg, #f8fafc 0 4px, #07101c 4px 8px); opacity: .72; }
        .trophy-shape { width: 54px; height: 54px; display: grid; place-items: center; color: #07101c; font-size: 1.35rem; border-radius: 50% 50% 42% 42%; background: linear-gradient(180deg, #fff2ad, #f5c542 52%, #a66a18); box-shadow: 0 12px 22px rgba(245,197,66,.16); transform-origin: bottom center; }
        .gold-stack, .container-stack, .power-stack { min-height: 138px; display: flex; flex-direction: column-reverse; justify-content: flex-start; gap: 3px; }
        .gold-bar { width: 52px; height: 12px; clip-path: polygon(8% 0, 92% 0, 100% 100%, 0 100%); background: linear-gradient(90deg, #9f6417, #f5c542 48%, #fff0a8); box-shadow: inset 0 1px 0 rgba(255,255,255,.4); }
        .container-box { width: 52px; height: 13px; border-radius: 2px; background: linear-gradient(90deg, #274f99, #5c8ee8); border: 1px solid rgba(255,255,255,.12); box-shadow: inset 8px 0 0 rgba(255,255,255,.08), inset -8px 0 0 rgba(0,0,0,.12); }
        .power-cell { width: 48px; height: 13px; border-radius: 4px; background: linear-gradient(90deg, #112139, #2dd4bf); border: 1px solid rgba(112,221,209,.35); box-shadow: 0 0 12px rgba(45,212,191,.18); }
        .wildcard-orbit { position: relative; width: 92px; height: 92px; border-radius: 999px; border: 1px dashed rgba(148,163,184,.28); display: grid; place-items: center; }
        .wildcard-core { border-radius: 999px; background: radial-gradient(circle at 35% 28%, #fff7d6, #f5c542 34%, #d85a62 72%); box-shadow: 0 0 22px rgba(245,197,66,.18); }
        .mini-podium { display: grid; gap: .38rem; }
        .mini-podium-row { display: grid; grid-template-columns: 40px minmax(0, 1fr) auto; gap: .45rem; align-items: center; padding: .42rem .5rem; border-radius: 11px; background: rgba(8,17,31,.52); }
        .mini-rank { color: #f6d892; font-size: .68rem; font-weight: 850; }
        .mini-name { min-width: 0; color: #f8fafc; font-size: .76rem; font-weight: 770; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .mini-value { color: #70ddd1; font-size: .72rem; font-weight: 820; white-space: nowrap; }
        .directory-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .62rem; margin: .15rem 0 1rem; align-items: stretch; }
        .directory-card { width: 100%; min-width: 0; height: 104px; display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: .58rem; align-items: center; padding: .62rem; border: 1px solid #243751; border-radius: 12px; background: linear-gradient(145deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); box-shadow: 0 8px 20px rgba(0,0,0,.12); }
        .directory-logo { width: 42px; height: 42px; object-fit: contain; border-radius: 9px; background: #f8fafc; padding: .18rem; }
        .directory-logo-badge { width: 42px; height: 42px; border-radius: 9px; }
        .directory-placeholder { width: 42px; height: 42px; display: flex; align-items: center; justify-content: center; border: 1px solid #35506f; border-radius: 10px; background: radial-gradient(circle at 28% 22%, #294666 0%, #192c46 48%, #112139 100%); color: #8ce7dc; font-size: .82rem; font-weight: 850; }
        .directory-name { color: #f8fafc; font-size: .82rem; font-weight: 800; line-height: 1.12; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
        .directory-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .28rem; margin-top: .38rem; }
        .directory-stat { min-width: 0; padding: .28rem .32rem; border-radius: 9px; background: rgba(8,17,31,.52); text-align: center; }
        .directory-stat-value { color: #f8fafc; font-size: .76rem; font-weight: 850; line-height: 1; }
        .directory-stat-label { color: #aebdd1; font-size: .52rem; font-weight: 720; line-height: 1.05; margin-top: .16rem; text-transform: uppercase; }
        .premium-donut-card { margin: .2rem 0 .85rem; padding: 1rem; border: 1px solid #243751; border-radius: 18px; background: radial-gradient(circle at 30% 18%, rgba(43,65,96,.56), rgba(11,23,39,.95) 58%, rgba(7,16,28,.98)); box-shadow: 0 18px 42px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.05); }
        .premium-donut-title { color: #f4f8fd; font-family: "Space Grotesk", "SF Pro Display", "Aptos Display", "Segoe UI", Arial, sans-serif; font-size: clamp(1.38rem, 3vw, 1.95rem); font-weight: 840; letter-spacing: -.045em; margin: 0 0 .72rem; text-shadow: 0 0 20px rgba(255,255,255,.08), 0 10px 24px rgba(0,0,0,.26); }
        .premium-donut-layout { display: grid; grid-template-columns: minmax(260px, 400px) minmax(230px, 1fr); gap: 1rem; align-items: center; }
        .donut-stage { position: relative; width: min(100%, 400px); aspect-ratio: 1 / 1; margin: 0 auto 0 0; }
        .donut-svg { width: 100%; height: 100%; overflow: visible; filter: drop-shadow(0 22px 18px rgba(0,0,0,.28)); }
        .donut-segment-depth { opacity: .82; stroke-linecap: round; }
        .donut-segment-top { stroke-linecap: round; filter: drop-shadow(0 0 8px rgba(255,255,255,.08)); transition: opacity .15s ease; }
        .donut-segment-major { stroke-width: 41; filter: drop-shadow(0 0 12px rgba(216,90,98,.38)); }
        .donut-center { position: absolute; inset: 34%; display: flex; flex-direction: column; align-items: center; justify-content: center; border-radius: 999px; background: radial-gradient(circle at 40% 25%, rgba(35,55,82,.98), rgba(8,17,31,.98)); border: 1px solid rgba(203,213,225,.14); box-shadow: inset 0 8px 24px rgba(0,0,0,.28), 0 0 22px rgba(45,212,191,.08); }
        .donut-center-label { color: #8fa1bb; font-size: .62rem; font-weight: 800; letter-spacing: .09em; text-transform: uppercase; }
        .donut-center-value { color: #ffffff; font-size: clamp(1.65rem, 5vw, 2.5rem); font-weight: 820; line-height: 1; margin-top: .16rem; }
        .donut-label { position: absolute; transform: translate(-50%, -50%); display: flex; align-items: center; gap: .25rem; padding: .2rem .42rem; border: 1px solid rgba(226,232,240,.14); border-radius: 999px; background: rgba(8,17,31,.76); color: #f8fafc; font-size: .72rem; font-weight: 780; line-height: 1; white-space: nowrap; box-shadow: 0 8px 18px rgba(0,0,0,.22); }
        .donut-legend { display: grid; gap: .52rem; }
        .donut-legend-row { display: block; padding: 0; border: 1px solid rgba(148,163,184,.16); border-radius: 13px; background: rgba(13,25,43,.72); overflow: hidden; }
        .donut-legend-row[open] { border-color: rgba(244,167,189,.34); box-shadow: 0 0 18px rgba(244,167,189,.08); }
        .donut-legend-summary { display: grid; grid-template-columns: 28px 1fr auto; gap: .6rem; align-items: center; padding: .62rem .7rem; cursor: pointer; list-style: none; }
        .donut-legend-summary::-webkit-details-marker { display: none; }
        .legend-icon { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 999px; background: rgba(255,255,255,.08); font-size: .9rem; }
        .legend-name { color: #f8fafc; font-size: 1.02rem; font-weight: 860; line-height: 1.04; letter-spacing: -.025em; text-shadow: 0 0 12px rgba(255,255,255,.08); }
        .legend-percent { color: #f8fafc; font-size: .95rem; font-weight: 800; }
        .legend-drawer { width: fit-content; margin: 0 .7rem .62rem calc(28px + 1.3rem); padding: .38rem .62rem; border: 1px solid rgba(191,233,255,.24); border-radius: 999px; background: linear-gradient(135deg, rgba(15,33,54,.82), rgba(8,17,31,.72)); color: #d9f3ff; font-size: .72rem; font-weight: 860; letter-spacing: .06em; text-transform: uppercase; box-shadow: 0 0 14px rgba(125,211,252,.12), inset 0 1px 0 rgba(255,255,255,.06); }
        .donut-legend-row:not([open]) .legend-drawer { display: none; }
        .donut-callout { margin-top: .35rem; padding: .72rem .85rem; border: 1px solid rgba(216,90,98,.34); border-radius: 13px; background: linear-gradient(90deg, rgba(216,90,98,.18), rgba(13,25,43,.7)); color: #f6d7da; font-size: .86rem; font-weight: 700; }
        .timeline-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .62rem; margin: .35rem 0 .8rem; align-items: stretch; }
        .timeline-tile { min-width: 0; height: 154px; display: flex; flex-direction: column; padding: .72rem .78rem; border: 1px solid #243751; border-radius: 12px; background: linear-gradient(145deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); box-shadow: 0 7px 18px rgba(0,0,0,.12); }
        .timeline-topline { display: flex; align-items: flex-start; justify-content: space-between; gap: .5rem; margin-bottom: .35rem; }
        .timeline-visit { color: #77e1d5; font-size: .68rem; font-weight: 780; letter-spacing: .055em; text-transform: uppercase; }
        .timeline-meta { display: flex; flex-direction: column; align-items: center; gap: .18rem; min-width: 0; }
        .timeline-status { flex: 0 0 auto; padding: .16rem .4rem; border: 1px solid #35516f; border-radius: 999px; color: #b9c9dc; background: #14243a; font-size: .59rem; font-weight: 700; text-transform: uppercase; }
        .timeline-status.scheduled, .timeline-status.upcoming, .timeline-status.awarded { border-color: #7b6340; color: #e7c98b; background: #2a241b; }
        .timeline-main { flex: 1; display: flex; align-items: center; justify-content: center; min-height: 0; text-align: center; padding: .08rem 0 .2rem; }
        .timeline-client { max-height: 2.18em; color: #f8fafc; font-size: 1.18rem; font-weight: 780; line-height: 1.09; overflow: hidden; text-align: center; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
        .timeline-location { margin-top: auto; min-height: 1.05rem; color: #c2cddd; font-size: .74rem; line-height: 1.2; text-align: center; }
        .timeline-event-date { color: #c2cddd; font-size: .64rem; font-weight: 650; line-height: 1; text-align: center; opacity: .84; }
        .journey-fuel-button { border: 1px solid rgba(45,212,191,.28); border-radius: 999px; background: linear-gradient(135deg, rgba(20,34,55,.94), rgba(13,25,43,.96)); color: #e9f4ff; box-shadow: 0 8px 18px rgba(0,0,0,.16), inset 0 1px 0 rgba(255,255,255,.05); font-weight: 800; cursor: pointer; appearance: none; -webkit-appearance: none; -webkit-tap-highlight-color: transparent; }
        .journey-fuel-button { width: 34px; height: 34px; display: inline-flex; align-items: center; justify-content: center; padding: 0; font-size: 1rem; }
        .journey-fuel-button:hover { border-color: rgba(45,212,191,.52); background: linear-gradient(135deg, rgba(24,63,70,.92), rgba(13,25,43,.96)); }
        .journey-track { position: relative; display: grid; gap: .72rem; margin: .2rem 0 1rem; padding: .4rem 0 .6rem 1.2rem; }
        .journey-track::before { content: ""; position: absolute; top: 2.8rem; bottom: 2.8rem; left: .68rem; width: 4px; border-radius: 999px; background: repeating-linear-gradient(to bottom, #d9e1ec 0 12px, #0b1627 12px 22px); box-shadow: 0 0 16px rgba(45,212,191,.18); opacity: .82; }
        .journey-replay-car { position: absolute; left: -.12rem; top: .9rem; z-index: 5; width: 26px; height: 26px; display: flex; align-items: center; justify-content: center; padding: 0; appearance: none; -webkit-appearance: none; border-radius: 999px; background: #02050a; border: 1px solid rgba(248,250,252,.2); box-shadow: 0 0 0 2px rgba(244,167,189,.16), 0 0 13px rgba(244,167,189,.34), 0 7px 15px rgba(0,0,0,.34); color: #fff; font-size: 1rem; line-height: 1; opacity: 0; pointer-events: none; cursor: pointer; transform: translateY(-50%); transition-property: top, opacity; transition-timing-function: cubic-bezier(.2,.72,.22,1); }
        .journey-car-icon { display: block; transform: scaleX(-1); transform-origin: center center; line-height: 1; }
        .journey-track.replay-active .journey-replay-car { opacity: 1; }
        .journey-track.replay-active .journey-replay-car { pointer-events: auto; }
        .journey-stop.new-client-celebration { animation: journeyClientGlow 1.45s ease-out both; }
        @keyframes journeyClientGlow { 0% { transform: scale(1); border-color: #243751; box-shadow: 0 9px 22px rgba(0,0,0,.16); } 22% { transform: scale(1.03); border-color: rgba(244,167,189,.74); box-shadow: 0 0 0 1px rgba(244,167,189,.36), 0 0 24px rgba(244,167,189,.3), 0 12px 28px rgba(0,0,0,.22); } 100% { transform: scale(1); border-color: #243751; box-shadow: 0 9px 22px rgba(0,0,0,.16); } }
        .journey-achievement-badge { position: absolute; left: 1.42rem; top: 50%; z-index: 6; padding: .18rem .38rem; border: 1px solid rgba(244,167,189,.38); border-radius: 999px; background: rgba(8,17,31,.9); color: #f8c8d7; font-size: .55rem; font-weight: 900; letter-spacing: .06em; text-transform: uppercase; box-shadow: 0 0 14px rgba(244,167,189,.22); opacity: 0; pointer-events: none; transform: translateY(-50%) translateX(-3px); transition: opacity .18s ease, transform .18s ease; white-space: nowrap; }
        .journey-achievement-badge.is-visible { opacity: 1; transform: translateY(-50%) translateX(0); }
        .journey-finish-line { position: relative; z-index: 1; margin-left: .2rem; padding: .55rem .75rem; display: flex; align-items: center; justify-content: space-between; gap: .75rem; border: 1px dashed rgba(248,250,252,.42); border-radius: 12px; background: repeating-linear-gradient(45deg, rgba(248,250,252,.16) 0 8px, rgba(8,17,31,.82) 8px 16px); color: #f8fafc; font-size: .72rem; font-weight: 850; letter-spacing: .08em; text-transform: uppercase; opacity: 0; transform: translateY(4px); transition: opacity .25s ease, transform .25s ease; }
        .journey-finish-line.is-visible { opacity: 1; transform: translateY(0); }

        .journey-top-button {
            margin-left: auto;
            border: 0;
            background: rgba(248,250,252,.10);
            border-radius: 999px;
            padding: .25rem .42rem;
            cursor: pointer;
            text-decoration: none !important;
            color: #f8fafc !important;
            font-size: 1.05rem;
            line-height: 1;
            filter: drop-shadow(0 0 8px rgba(248,250,252,.38));
        }
        .journey-top-button:hover {
            transform: translateY(-1px);
            filter: drop-shadow(0 0 12px rgba(248,250,252,.58));
        }
        .journey-replay-car.is-boosting::after,
        #journeyReplayCar.is-boosting::after,
        .journey-car.is-boosting::after,
        #journeyCar.is-boosting::after {
            content: "💨";
            position: absolute;
            right: 100%;
            top: 50%;
            transform: translateY(-50%) scaleX(-1);
            margin-right: .18rem;
            font-size: 1.05em;
            opacity: .92;
            filter: drop-shadow(0 0 8px rgba(248,250,252,.35));
            animation: journeySmokePulse .42s ease-in-out infinite alternate;
        }
        @keyframes journeySmokePulse {
            from { opacity: .55; transform: translateY(-50%) scaleX(-1) translateX(0); }
            to { opacity: .95; transform: translateY(-50%) scaleX(-1) translateX(-3px); }
        }

        .journey-replay-summary { position: fixed; left: 50%; right: auto; bottom: max(1rem, env(safe-area-inset-bottom)); z-index: 50; width: min(310px, calc(100vw - 2rem)); padding: .9rem; border: 1px solid rgba(244,167,189,.3); border-radius: 16px; background: linear-gradient(145deg, rgba(20,34,55,.98), rgba(8,17,31,.98)); box-shadow: 0 18px 44px rgba(0,0,0,.42), 0 0 24px rgba(244,167,189,.08), inset 0 1px 0 rgba(255,255,255,.06); color: #eef6ff; pointer-events: auto; opacity: 0; transform: translate(-50%, 10px) scale(.98); transition: opacity .24s ease, transform .24s ease; }
        .journey-replay-summary.is-visible { transform: translate(-50%, 0) scale(1); }
        .journey-summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .42rem; margin-top: .65rem; }
        .journey-summary-stat { padding: .52rem; border: 1px solid rgba(148,163,184,.16); border-radius: 12px; background: rgba(13,25,43,.82); }
        .journey-summary-value { color: #fff; font-size: .98rem; font-weight: 860; line-height: 1; }
        .journey-summary-label { margin-top: .18rem; color: #9fb1c8; font-size: .56rem; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; }
        .journey-start { position: relative; z-index: 1; margin-left: .2rem; padding: .7rem .85rem; border: 1px solid rgba(45,212,191,.34); border-radius: 12px; background: linear-gradient(135deg, rgba(24,63,70,.78), rgba(13,25,43,.9)); color: #f8fafc; font-size: .82rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
        .journey-start { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
        .journey-checkpoint { position: relative; z-index: 1; margin-left: .2rem; padding: .48rem .7rem; border: 1px solid rgba(245,158,11,.36); border-radius: 999px; background: rgba(42,36,27,.9); color: #f7d38d; font-size: .72rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; width: fit-content; max-width: 100%; }
        .journey-milestone { position: relative; z-index: 1; margin-left: .2rem; padding: .56rem .78rem; border: 1px solid rgba(245, 197, 66, .46); border-radius: 12px; background: linear-gradient(135deg, rgba(91,64,16,.92), rgba(27,37,56,.9)); color: #ffe8a3; font-size: .74rem; font-weight: 850; letter-spacing: .07em; text-transform: uppercase; width: fit-content; max-width: 100%; box-shadow: 0 10px 22px rgba(0,0,0,.16), inset 0 1px 0 rgba(255,255,255,.06); }
        .journey-stop { position: relative; z-index: 1; display: grid; grid-template-columns: 54px 1fr; gap: .72rem; align-items: stretch; margin-left: .2rem; padding: .62rem .72rem; border: 1px solid rgba(var(--month-accent-rgb, 36,55,81), .65); border-radius: 16px; background: linear-gradient(145deg, rgba(var(--month-accent-rgb, 20,34,55), .38), rgba(13,25,43,.97)); box-shadow: 0 9px 22px rgba(0,0,0,.16), inset 0 0 0 1px rgba(var(--month-accent-rgb, 36,55,81), .2); }
        .journey-stop::before { content: ""; position: absolute; left: -1.02rem; top: 50%; width: 13px; height: 13px; transform: translateY(-50%); border: 2px solid #07101c; border-radius: 999px; background: #2dd4bf; box-shadow: 0 0 0 3px rgba(45,212,191,.18); }
        .journey-number { display: flex; align-items: center; justify-content: center; border-radius: 12px; background: linear-gradient(180deg, #101d31, #0b1627); border: 1px solid #2a405d; color: #77e1d5; font-size: .72rem; font-weight: 850; text-transform: uppercase; text-align: center; line-height: 1.05; }
        .journey-content { position: relative; min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) max-content; gap: .9rem; align-items: start; }
        .journey-left-stack { min-width: 0; display: grid; gap: .3rem; padding-right: .15rem; }
        .journey-client { min-width: 0; color: #f8fafc; font-size: 1rem; font-weight: 800; line-height: 1.12; }
        .journey-location { color: #c2cddd; font-size: .72rem; line-height: 1.2; }
        .journey-right-meta { width: max-content; min-width: 84px; display: flex; flex-direction: column; align-items: flex-end; justify-content: flex-start; justify-self: end; gap: .24rem; white-space: nowrap; text-align: right; }
        .journey-status { padding: .12rem .38rem; border: 1px solid #35516f; border-radius: 999px; background: #14243a; color: #b9c9dc; font-size: .58rem; font-weight: 800; text-transform: uppercase; }
        .journey-date { color: #c2cddd; font-size: .68rem; font-weight: 650; line-height: 1.2; text-align: right; opacity: .86; white-space: nowrap; }
        .logo-ribbon { display: flex; gap: .65rem; overflow-x: auto; overscroll-behavior-inline: contain; padding: .2rem .05rem .75rem; margin: .25rem 0 .55rem; scrollbar-width: thin; scrollbar-color: #38506f transparent; scroll-snap-type: inline proximity; }
        .logo-ribbon::-webkit-scrollbar { height: 6px; }
        .logo-ribbon::-webkit-scrollbar-thumb { background: #38506f; border-radius: 999px; }
        .logo-card { position: relative; display: flex; flex: 0 0 92px; min-width: 92px; flex-direction: column; align-items: center; gap: .38rem; padding: .55rem .4rem .5rem; border: 1px solid #243751; border-radius: 13px; background: linear-gradient(145deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); color: #e6edf7 !important; text-decoration: none !important; scroll-snap-align: start; transition: border-color .15s ease, background .15s ease; }
        .logo-card:hover { border-color: #2dd4bf; background: #14233a; }
        .logo-card.selected { border-color: #2dd4bf; box-shadow: 0 0 0 1px rgba(45,212,191,.32); }
        .logo-image { width: 68px; height: 68px; object-fit: contain; border-radius: 10px; background: #f8fafc; padding: .28rem; }
        .logo-placeholder { width: 68px; height: 68px; display: flex; align-items: center; justify-content: center; border: 1px solid #35506f; border-radius: 12px; background: radial-gradient(circle at 28% 22%, #294666 0%, #192c46 48%, #112139 100%); box-shadow: inset 0 1px 0 rgba(255,255,255,.08); color: #8ce7dc; font-size: 1.2rem; font-weight: 800; letter-spacing: .035em; }
        .logo-client { width: 100%; min-height: 2.25em; max-height: 2.25em; overflow: hidden; color: #f1f5fa; font-size: .68rem; font-weight: 680; line-height: 1.12; text-align: center; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
        .logo-counts { min-height: 2.2em; color: #c2cddd; font-size: .61rem; line-height: 1.1; text-align: center; }
        .visit-badge { position: absolute; top: .3rem; right: .3rem; min-width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; padding: 0 .3rem; border: 2px solid #102039; border-radius: 999px; background: #2dd4bf; color: #07101c; font-size: .66rem; font-weight: 800; }
        .clients-heading-row { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin: .12rem 0 .22rem; }
        .clients-heading-title { color: #f4f8fd; font-size: 1.15rem; font-weight: 760; letter-spacing: -.02em; }
        .active-client { display: flex; align-items: center; justify-content: flex-end; min-height: 24px; color: #c9d6e7; font-size: .84rem; white-space: nowrap; }
        .active-client strong { color: #2dd4bf; margin-left: .3rem; }
        .ribbon-heading { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-top: .9rem; }
        .ribbon-title { color: #e7eef8; font-size: .82rem; font-weight: 760; letter-spacing: .045em; text-transform: uppercase; }
        .ribbon-show-all { color: #70ddd1 !important; font-size: .72rem; font-weight: 700; text-decoration: none !important; }
        .ribbon-empty { color: #c2cddd; font-size: .78rem; padding: .6rem .1rem .9rem; }
        .st-key-interactive_map_chart { margin-bottom: 1.55rem; }
        .st-key-interactive_map_chart .maplibregl-ctrl-attrib { max-width: min(72vw, 260px) !important; max-height: 22px !important; overflow: hidden !important; font-size: 9px !important; line-height: 14px !important; opacity: .72; }
        .st-key-interactive_map_chart .maplibregl-ctrl-attrib:hover, .st-key-interactive_map_chart .maplibregl-ctrl-attrib:focus-within { max-height: 52px !important; opacity: .95; }
        .st-key-interactive_map_chart .maplibregl-ctrl-attrib button { width: 20px !important; height: 20px !important; }
        .st-key-interactive_map_chart .mapboxgl-ctrl-bottom-left,
        .st-key-interactive_map_chart .mapboxgl-ctrl-bottom-right,
        .st-key-interactive_map_chart .maplibregl-ctrl-bottom-left,
        .st-key-interactive_map_chart .maplibregl-ctrl-bottom-right,
        .st-key-interactive_map_chart .mapboxgl-ctrl,
        .st-key-interactive_map_chart .maplibregl-ctrl { display: none !important; visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }
        .event-form-shell { max-width: 680px; }
        .event-preview { max-width: 680px; margin: .8rem 0; padding: .9rem; border: 1px solid #263a55; border-radius: 12px; background: linear-gradient(145deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); }
        .preview-row { display: grid; grid-template-columns: 120px 1fr; gap: .6rem; padding: .42rem 0; border-bottom: 1px solid rgba(148,163,184,.14); }
        .preview-row:last-child { border-bottom: none; }
        .preview-label { color: #91a3bd; font-size: .72rem; font-weight: 750; letter-spacing: .055em; text-transform: uppercase; }
        .preview-value { color: #f4f8fd; font-size: .95rem; font-weight: 650; }
        .scheduled-ticket-list { display: grid; gap: .26rem; max-width: 780px; margin: .08rem 0 .7rem; }
        .scheduled-ticket-card { min-height: 46px; display: grid; align-items: center; padding: .42rem .56rem; border: 1px solid #2b405d; border-radius: 11px; background: linear-gradient(145deg, rgba(20,34,55,.96), rgba(13,25,43,.96)); box-shadow: 0 7px 17px rgba(0,0,0,.11); }
        .scheduled-ticket-client { color: #f8fafc; font-size: .8rem; font-weight: 820; line-height: 1.1; }
        .scheduled-ticket-meta { color: #c2cddd; font-size: .66rem; line-height: 1.22; margin-top: .16rem; }
        .scheduled-ticket-notes { color: #9fb1c8; font-size: .61rem; line-height: 1.15; margin-top: .14rem; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
        div[data-testid="stDataFrame"] { border: 1px solid #20314a; border-radius: 12px; overflow: hidden; }
        @media (max-width: 1050px) and (min-width: 701px) {
            .timeline-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .premium-donut-layout { grid-template-columns: 1fr; }
            .donut-stage { margin: 0 auto; }
        }
        @media (max-width: 700px) {
            [data-testid="stHeader"] { height: 0 !important; min-height: 0 !important; }
            .block-container { padding: .55rem .55rem 1.35rem; }
            .hero-title { font-size: 2.04rem; margin: .02rem 0 .72rem; letter-spacing: -.06em; }
            .executive-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .28rem; margin: .18rem 0 .48rem; }
            .metric-card { min-height: 66px; padding: .46rem .3rem; border-radius: 11px; gap: .26rem; }
            .metric-label { font-size: .48rem; letter-spacing: .052em; }
            .metric-value { font-size: 1.94rem; }
            .upcoming-assignments { padding: .62rem .68rem; margin-bottom: .65rem; }
            .top-nav { margin-left: -.55rem; margin-right: -.55rem; margin-bottom: .24rem; padding-left: .55rem; padding-right: .55rem; padding-bottom: .42rem; }
            .top-nav-link { flex-basis: 64px; width: 64px; min-height: 54px; padding: .36rem .28rem .54rem; font-size: .49rem; border-radius: 11px; gap: .16rem; }
            .top-nav-link::after { bottom: .2rem; width: 36px; height: 2px; }
            .nav-icon { font-size: .88rem; }
            .section-title { font-size: 1.04rem; margin-bottom: .42rem; }
            .standings-board { gap: .34rem; margin-bottom: .78rem; }
            .standing-row { grid-template-columns: 82px minmax(0, 1fr) auto; gap: .42rem; padding: .48rem .52rem; border-radius: 12px; }
            .standing-rank { font-size: .55rem; letter-spacing: .035em; }
            .standing-client { font-size: .78rem; }
            .standing-visits { font-size: .64rem; }
            .standing-track { height: 6px; }
            .standing-client-line { gap: .34rem; }
            .client-logo-badge { width: 34px; height: 34px; border-radius: 10px; font-size: .64rem; }
            .client-portfolio { padding: .62rem; margin-bottom: .68rem; border-radius: 15px; }
            .portfolio-heading { font-size: .56rem; margin-bottom: .52rem; }
            .portfolio-logo-grid { grid-template-columns: repeat(5, 1fr); gap: .34rem; }
            .portfolio-logo-card { min-height: 66px; padding: .38rem .24rem; border-radius: 12px; gap: .28rem; }
            .portfolio-logo-card .client-logo-badge { width: 72px; height: 72px; border-radius: 16px; }
            .portfolio-logo-name { font-size: .5rem; }
            .records-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .42rem; margin-bottom: .82rem; }
            .record-card { padding: .58rem .62rem; border-radius: 13px; }
            .record-label { font-size: .54rem; }
            .record-client { font-size: .8rem; }
            .record-value { font-size: .66rem; }
            .profile-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .36rem; }
            .profile-detail-grid { grid-template-columns: 1fr; gap: .34rem; }
            .profile-visit { grid-template-columns: 42px minmax(0, 1fr); gap: .4rem; }
            .profile-visit-money { grid-column: 2; text-align: left; }
            .financial-row { grid-template-columns: 36px minmax(0, 1fr) 46px minmax(76px, auto) minmax(64px, auto); gap: .32rem; padding: .44rem .46rem; border-radius: 11px; }
            .financial-row.avg-row { grid-template-columns: 36px minmax(0, 1fr) 46px minmax(68px, auto); }
            .financial-row.compact { grid-template-columns: minmax(0, 1fr) minmax(72px, auto) minmax(54px, auto); }
            .financial-row.state-row { grid-template-columns: minmax(0, 1fr) minmax(64px, auto) minmax(42px, auto) minmax(58px, auto); }
            .financial-card-row { padding: .5rem .54rem; border-radius: 12px; }
            .financial-card-title { font-size: .7rem; }
            .financial-card-value { font-size: .66rem; }
            .financial-card-meta { font-size: .54rem; }
            .financial-rank { font-size: .58rem; }
            .financial-client, .financial-state, .financial-month { font-size: .68rem; }
            .financial-meta { font-size: .56rem; }
            .financial-money { font-size: .62rem; }
            .integrity-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .36rem; }
            .chart-lab-grid { grid-template-columns: 1fr; gap: .52rem; }
            .chart-style-card { min-height: 0; padding: .68rem .62rem; border-radius: 13px; }
            .chart-style-title { font-size: .78rem; }
            .lab-columns { height: 150px; gap: .42rem; }
            .lab-column-value { font-size: .52rem; }
            .lab-column-label { font-size: .49rem; }
            .tower-grid, .chip-grid, .radial-grid, .fuel-grid, .skyline-grid, .trophy-grid, .vault-grid, .container-grid, .power-grid, .wildcard-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .42rem; }
            .money-block { width: 34px; height: 10px; }
            .casino-chip { width: 38px; height: 10px; }
            .fuel-tank { width: 38px; height: 118px; }
            .gold-stack, .container-stack, .power-stack, .money-tower, .chip-stack { min-height: 118px; }
            .gold-bar, .container-box { width: 40px; height: 10px; }
            .power-cell { width: 38px; height: 11px; }
            .pit-row { grid-template-columns: minmax(62px, 90px) minmax(0, 1fr) auto; gap: .36rem; }
            .pit-track { height: 16px; }
            .trophy-shape { width: 44px; height: 44px; font-size: 1.1rem; }
            .wildcard-orbit { width: 72px; height: 72px; }
            .garage-row { grid-template-columns: minmax(62px, 92px) minmax(0, 1fr) auto; gap: .36rem; padding: .38rem .42rem; }
            .garage-team { font-size: .62rem; }
            .garage-value { font-size: .56rem; }
            .champ-podium { gap: .38rem; min-height: 160px; }
            .champ-name { font-size: .58rem; }
            .champ-value { font-size: .56rem; }
            .radial-medal { width: 66px; height: 66px; font-size: .62rem; box-shadow: inset 0 0 0 8px rgba(8,17,31,.88), 0 8px 18px rgba(0,0,0,.16); }
            .mini-podium-row { grid-template-columns: 34px minmax(0, 1fr) auto; padding: .38rem .44rem; }
            .mini-name { font-size: .68rem; }
            .mini-value { font-size: .64rem; }
            .directory-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .42rem; }
            .directory-card { height: 98px; grid-template-columns: 34px minmax(0, 1fr); gap: .42rem; padding: .48rem; border-radius: 12px; }
            .directory-logo, .directory-placeholder, .directory-logo-badge { width: 34px; height: 34px; border-radius: 8px; }
            .directory-name { font-size: .7rem; }
            .directory-stats { gap: .18rem; margin-top: .32rem; }
            .directory-stat { padding: .22rem .18rem; border-radius: 8px; }
            .directory-stat-value { font-size: .66rem; }
            .directory-stat-label { font-size: .45rem; }
            .premium-donut-card { padding: .72rem; border-radius: 15px; }
            .premium-donut-layout { grid-template-columns: 1fr; gap: .72rem; }
            .donut-stage { width: min(100%, 330px); margin: 0 auto; }
            .donut-label { font-size: .61rem; padding: .17rem .34rem; }
            .donut-legend-row { grid-template-columns: 24px 1fr auto; padding: .5rem .55rem; gap: .45rem; }
            .legend-icon { width: 24px; height: 24px; font-size: .78rem; }
            .legend-name { font-size: .75rem; }
            .legend-percent { font-size: .82rem; }
            .timeline-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .42rem; }
            .timeline-tile { height: 142px; padding: .55rem .58rem; }
            .timeline-topline { align-items: flex-start; gap: .25rem; margin-bottom: .32rem; }
            .timeline-visit { font-size: .61rem; }
            .timeline-status { padding: .13rem .3rem; font-size: .51rem; }
            .timeline-event-date { font-size: .56rem; }
            .timeline-client { max-height: 2.16em; font-size: 1.02rem; }
            .timeline-location { font-size: .66rem; }
            .journey-track { padding-left: .85rem; gap: .52rem; }
            .journey-track::before { left: .42rem; }
            .journey-fuel-button { width: 32px; height: 32px; font-size: .95rem; }
            .journey-replay-car { left: -.24rem; width: 24px; height: 24px; font-size: .92rem; }
            .journey-achievement-badge { left: 1.18rem; font-size: .5rem; padding: .15rem .32rem; }
            .journey-replay-summary { width: min(300px, calc(100vw - 1.4rem)); padding: .78rem; }
            .journey-summary-grid { gap: .34rem; }
            .journey-stop { grid-template-columns: 42px 1fr; gap: .52rem; padding: .54rem .58rem; border-radius: 13px; }
            .journey-stop::before { left: -.76rem; width: 10px; height: 10px; }
            .journey-number { font-size: .58rem; border-radius: 10px; }
            .journey-client { font-size: .9rem; }
            .journey-content { grid-template-columns: minmax(0, 1fr) max-content; gap: .48rem; }
            .journey-left-stack { gap: .24rem; }
            .journey-right-meta { min-width: 72px; gap: .18rem; }
            .journey-location { font-size: .64rem; }
            .journey-date { font-size: .6rem; }
            .journey-checkpoint { font-size: .6rem; padding: .38rem .55rem; }
            .journey-milestone { font-size: .61rem; padding: .42rem .58rem; }
            .clients-heading-row { margin-top: .02rem; margin-bottom: .12rem; }
            .clients-heading-title { font-size: 1rem; }
            .active-client { font-size: .72rem; min-height: 20px; }
            .logo-ribbon { margin-left: -.55rem; margin-right: -.55rem; padding-left: .55rem; padding-right: .55rem; }
            .logo-card { flex-basis: 88px; min-width: 88px; }
            .scheduled-ticket-list { gap: .24rem; }
            .scheduled-ticket-card { min-height: 44px; padding: .38rem .48rem; }
            .ledger-kpi-row { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .28rem; margin-bottom: .52rem; }
            .ledger-kpi-card { padding: .48rem .28rem; border-radius: 11px; }
            .ledger-kpi-value { font-size: 1.02rem; }
            .ledger-kpi-label { font-size: .45rem; letter-spacing: .035em; }
            .preview-row { grid-template-columns: 1fr; gap: .12rem; }
        }
        
.record-icon-line {
    display: flex;
    align-items: center;
    gap: .55rem;
}
.record-icon-line .record-client-text {
    color: #f8fafc;
    font-size: .95rem;
    font-weight: 850;
    line-height: 1.14;
}

/* === REDESIGN PASS: Executive Summary KPIs + Journey polish (additive, CSS-only where possible) === */
@keyframes dashFadeUp {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}
.metric-card {
    position: relative;
    opacity: 0;
    animation: dashFadeUp .5s ease forwards;
    transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.metric-card:nth-child(1) { animation-delay: .02s; }
.metric-card:nth-child(2) { animation-delay: .08s; }
.metric-card:nth-child(3) { animation-delay: .14s; }
.metric-card:nth-child(4) { animation-delay: .20s; }
.metric-card::before {
    content: "";
    position: absolute;
    top: 0;
    left: 14%;
    right: 14%;
    height: 3px;
    border-radius: 0 0 6px 6px;
    background: linear-gradient(90deg, transparent, var(--metric-accent, #2dd4bf), transparent);
    opacity: .85;
}
.metric-card:hover {
    transform: translateY(-3px);
    border-color: color-mix(in srgb, var(--metric-accent, #2dd4bf) 46%, rgba(148,163,184,.28));
    box-shadow: 0 18px 34px rgba(0,0,0,.26), 0 0 22px color-mix(in srgb, var(--metric-accent, #2dd4bf) 20%, transparent), inset 0 1px 0 rgba(255,255,255,.06);
}
.metric-icon {
    font-size: .92rem;
    line-height: 1;
    opacity: .82;
    margin-bottom: .05rem;
}
.metric-detail {
    margin-top: .3rem;
    color: #8fa1bb;
    font-size: .56rem;
    font-weight: 680;
    letter-spacing: .03em;
    line-height: 1.15;
    text-align: center;
}
@media (max-width: 700px) {
    .metric-icon, .metric-detail { display: none; }
}
.live-pulse-dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    margin-right: .42rem;
    border-radius: 999px;
    background: #34d399;
    vertical-align: middle;
    animation: livePulse 2.1s ease-in-out infinite;
}
@keyframes livePulse {
    0% { box-shadow: 0 0 0 0 rgba(52,211,153,.55); }
    70% { box-shadow: 0 0 0 7px rgba(52,211,153,0); }
    100% { box-shadow: 0 0 0 0 rgba(52,211,153,0); }
}
.upcoming-list li {
    display: flex;
    align-items: center;
    gap: .5rem;
    padding: .18rem .22rem;
    border-radius: 8px;
    opacity: 0;
    animation: dashFadeUp .4s ease forwards;
    transition: background .15s ease;
}
.upcoming-list li:hover { background: rgba(255,255,255,.035); }
.upcoming-dot {
    flex: 0 0 auto;
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: #38bdf8;
    box-shadow: 0 0 8px rgba(56,189,248,.55);
}
.upcoming-main { flex: 1; min-width: 0; }
.upcoming-date {
    flex: 0 0 auto;
    color: #8fa1bb;
    font-size: .64rem;
    font-weight: 700;
    white-space: nowrap;
}
.premium-donut-card {
    opacity: 0;
    animation: dashFadeUp .6s ease forwards;
}
.donut-legend-row {
    opacity: 0;
    animation: dashFadeUp .5s ease forwards;
    transition: border-color .15s ease;
}
.donut-legend-summary:hover .legend-name { color: #eaf6ff; }
.journey-fuel-button {
    animation: fuelIdlePulse 2.6s ease-in-out infinite;
}
@keyframes fuelIdlePulse {
    0%, 100% { box-shadow: 0 8px 18px rgba(0,0,0,.16), inset 0 1px 0 rgba(255,255,255,.05), 0 0 0 0 rgba(45,212,191,0); }
    50% { box-shadow: 0 8px 18px rgba(0,0,0,.16), inset 0 1px 0 rgba(255,255,255,.05), 0 0 14px 2px rgba(45,212,191,.3); }
}
.journey-track:not(.replay-active)::before {
    animation: journeyTrackShimmer 3.2s linear infinite;
}
@keyframes journeyTrackShimmer {
    from { background-position: 0 0; }
    to { background-position: 0 44px; }
}

.journey-finish-line.is-visible {
    animation: finishGlowPulse 1.6s ease-in-out 2;
}
@keyframes finishGlowPulse {
    0%, 100% { box-shadow: none; }
    50% { box-shadow: 0 0 22px rgba(248,250,252,.35); }
}
.journey-stop {
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
.journey-stop:hover {
    transform: translateY(-2px);
    border-color: color-mix(in srgb, var(--stop-accent, #2dd4bf) 42%, rgba(148,163,184,.26));
    box-shadow: 0 12px 26px rgba(0,0,0,.2), 0 0 16px color-mix(in srgb, var(--stop-accent, #2dd4bf) 16%, transparent);
}
.journey-stop::before {
    background: var(--stop-accent, #2dd4bf) !important;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--stop-accent, #2dd4bf) 30%, transparent) !important;
}
.journey-checkpoint, .journey-milestone {
    opacity: 0;
    animation: dashFadeUp .45s ease forwards;
}
.client-marquee-viewport {
    position: relative;
    overflow: hidden;
    border-radius: 14px;
    padding: .85rem 0;
    background: linear-gradient(180deg, rgba(3,10,20,.55), rgba(3,10,20,.82));
    mask-image: linear-gradient(90deg, transparent, black 6%, black 94%, transparent);
    -webkit-mask-image: linear-gradient(90deg, transparent, black 6%, black 94%, transparent);
}
.client-marquee-viewport::before {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    bottom: 6px;
    height: 2px;
    background: repeating-linear-gradient(90deg, rgba(248,250,252,.32) 0 14px, transparent 14px 28px);
}
.client-marquee-track {
    display: flex;
    width: max-content;
    gap: .65rem;
    animation: clientMarqueeScroll 38s linear infinite;
}
.client-marquee:hover .client-marquee-track {
    animation-play-state: paused;
}
@keyframes clientMarqueeScroll {
    from { transform: translateX(-50%); }
    to { transform: translateX(0%); }
}
.client-marquee-item {
    flex: 0 0 auto;
    width: 88px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: .32rem;
}
.marquee-logo-badge {
    width: 64px;
    height: 64px;
    border-radius: 14px;
}
.marquee-client-name {
    width: 100%;
    color: #c2cddd;
    font-size: .58rem;
    font-weight: 700;
    line-height: 1.15;
    text-align: center;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
@media (max-width: 700px) {
    .client-marquee-item { width: 68px; }
    .marquee-logo-badge { width: 50px; height: 50px; border-radius: 12px; }
    .marquee-client-name { font-size: .52rem; }
}
/* === END REDESIGN PASS === */

/* === CLIENT ANALYTICS REDESIGN PASS === */
.champ-logo-badge {
    width: 44px;
    height: 44px;
    border-radius: 11px;
}
.champ-step {
    opacity: 0;
    animation: dashFadeUp .5s ease forwards;
    transition: transform .16s ease;
}
.champ-step:nth-child(1) { animation-delay: .06s; }
.champ-step:nth-child(2) { animation-delay: 0s; }
.champ-step:nth-child(3) { animation-delay: .12s; }
.champ-step:hover { transform: translateY(-3px); }
.record-card {
    position: relative;
    opacity: 0;
    animation: dashFadeUp .5s ease forwards;
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
.record-card::before {
    content: "";
    position: absolute;
    top: 0;
    left: 14%;
    right: 14%;
    height: 3px;
    border-radius: 0 0 6px 6px;
    background: linear-gradient(90deg, transparent, var(--record-accent, #2dd4bf), transparent);
    opacity: .85;
}
.record-card:hover {
    transform: translateY(-3px);
    border-color: color-mix(in srgb, var(--record-accent, #2dd4bf) 42%, rgba(148,163,184,.26));
    box-shadow: 0 16px 30px rgba(0,0,0,.22), 0 0 18px color-mix(in srgb, var(--record-accent, #2dd4bf) 16%, transparent);
}
.record-card:nth-child(1) { animation-delay: .02s; }
.record-card:nth-child(2) { animation-delay: .08s; }
.record-card:nth-child(3) { animation-delay: .14s; }
.record-card:nth-child(4) { animation-delay: .2s; }
.standing-row {
    opacity: 0;
    animation: dashFadeUp .45s ease forwards;
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
.standing-row:hover {
    transform: translateY(-2px);
    border-color: rgba(45,212,191,.4);
    box-shadow: 0 14px 28px rgba(0,0,0,.2), 0 0 16px rgba(45,212,191,.14);
}
.directory-card {
    position: relative;
    opacity: 0;
    animation: dashFadeUp .45s ease forwards;
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
.directory-card::after {
    content: "";
    position: absolute;
    left: 0;
    bottom: 0;
    height: 3px;
    width: var(--activity-pct, 20%);
    border-radius: 0 4px 4px 12px;
    background: linear-gradient(90deg, #2dd4bf, #38bdf8);
    box-shadow: 0 0 10px rgba(45,212,191,.3);
}
.directory-card:hover {
    transform: translateY(-2px);
    border-color: rgba(56,189,248,.4);
    box-shadow: 0 14px 26px rgba(0,0,0,.18), 0 0 14px rgba(56,189,248,.12);
}
.record-icon-badge {
    width: 54px !important;
    height: 54px !important;
    min-width: 54px !important;
    border-radius: 13px !important;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.55rem;
    line-height: 1;
}
.financial-rank-chip {
    flex: 0 0 auto;
    min-width: 20px;
    color: #f6d892;
    font-size: .72rem;
    font-weight: 850;
}
.financial-card-value-link {
    color: #70ddd1 !important;
    font-size: .8rem;
    font-weight: 850;
    text-align: right;
    white-space: nowrap;
    text-decoration: none !important;
}
.financial-card-value-link:hover {
    color: #9ff0e6 !important;
}
/* === END CLIENT ANALYTICS REDESIGN PASS === */
.client-champ-podium {
    margin: .1rem 0 1.1rem;
}

.mini-tile-icon {
    width: 58px !important;
    height: 58px !important;
    min-width: 58px !important;
    border-radius: 14px !important;
    overflow: hidden !important;
}
.mini-tile-icon img {
    width: 100% !important;
    height: 100% !important;
    object-fit: cover !important;
    padding: 0 !important;
    background: transparent !important;
}
.accolade-logo-center {
    display: flex;
    justify-content: center;
    align-items: center;
    margin: .35rem auto .3rem auto;
}
.accolade-logo-center .mini-tile-icon {
    width: 72px !important;
    height: 72px !important;
    min-width: 72px !important;
}
.transition-icons-clean {
    filter: grayscale(1) brightness(1.25) contrast(.9) drop-shadow(0 0 6px rgba(226,232,240,.22)) !important;
}
        .journey-start-actions {
            display: inline-flex;
            align-items: center;
            justify-content: flex-end;
        }
        .journey-teddy-button {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            text-decoration: none !important;
            color: inherit !important;
            line-height: 1 !important;
            flex: 0 0 auto;}
        .journey-two-space-gap {
            display: inline-block;
            width: 3px;
            min-width: 3px;
            flex: 0 0 3px;
        }

/* === MAIN PAGE - KITH-inspired palette === */
:root {
    --kith-sand: #d9c7a8;
    --kith-sand-deep: #b89f79;
    --kith-blue: #7c93b3;
    --kith-blue-deep: #536280;
    --kith-mauve: #a893ab;
    --kith-mauve-deep: #7e6884;
    --kith-blush: #d3a3a8;
    --kith-blush-deep: #a9767c;
    --kith-sage: #94997d;
    --kith-sage-deep: #6c715a;
    --kith-charcoal: #17161a;
    --kith-charcoal-soft: #211f26;
    --kith-warm-gray: #a9a29a;
    --kith-battleship: #434A54;
    --kith-battleship-rgb: 67,74,84;
    --kith-dusty-quartz: #A37B85;
    --kith-dusty-quartz-rgb: 163,123,133;
    --kith-anchor: #2B3E50;
    --kith-anchor-rgb: 43,62,80;
    --kith-saddle: #D7CCC8;
    --kith-genesis: #22252A;
    --kith-chalk: #E6E9ED;
    --kith-mantle: #656D78;
    --kith-current: #736075;
    --kith-aster-mauve: #8E7C85;
    --kith-elevated-navy: #1C2430;
    --kith-voyage: #A3B8C4;
    --kith-voyage-rgb: 163,184,196;
    --kith-sakura: #D4B2BA;
    --kith-sakura-rgb: 212,178,186;
    --kith-plume: #7D9480;
    --kith-plume-rgb: 125,148,128;
    --kith-campus-maroon: #7A1C2C;
    --kith-campus-maroon-rgb: 122,28,44;
    --kith-pink-accent: #f472b6;
    --kith-pink-accent-rgb: 244,114,182;
    --kith-wave: #4A6572;
    --kith-wave-rgb: 74,101,114;
    --kith-rococo-red: #B22234;
    --kith-rococo-red-rgb: 178,34,52;
    --kith-leaf-green: #4D6451;
    --kith-leaf-green-rgb: 77,100,81;
    --kith-month-jan: var(--kith-voyage);
    --kith-month-feb: var(--kith-campus-maroon);
    --kith-month-mar: var(--kith-sakura);
    --kith-month-apr: var(--kith-wave);
    --kith-month-may: var(--kith-plume);
    --kith-month-jun: var(--kith-blue);
    --kith-month-jul: var(--kith-pink-accent);
    --kith-month-aug: var(--kith-dusty-quartz);
    --kith-month-sep: var(--kith-sand-deep);
    --kith-month-oct: var(--kith-blue-deep);
    --kith-month-nov: var(--kith-mauve-deep);
    --kith-month-dec: var(--kith-leaf-green);
    --kith-month-jan-rgb: 163,184,196;
    --kith-month-feb-rgb: 122,28,44;
    --kith-month-mar-rgb: 212,178,186;
    --kith-month-apr-rgb: 74,101,114;
    --kith-month-may-rgb: 125,148,128;
    --kith-month-jun-rgb: 124,147,179;
    --kith-month-jul-rgb: 244,114,182;
    --kith-month-aug-rgb: 163,123,133;
    --kith-month-sep-rgb: 184,159,121;
    --kith-month-oct-rgb: 83,98,128;
    --kith-month-nov-rgb: 126,104,132;
    --kith-month-dec-rgb: 77,100,81;
}
.page-nav { display: flex; gap: .5rem; margin-bottom: .8rem; }
.page-nav a { color: var(--text-muted) !important; text-decoration: none !important; font-size: .68rem; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; padding: .4rem .8rem; border-radius: 999px; border: 1px solid rgba(var(--slate-border-rgb),.28); }
.page-nav a.active { color: var(--kith-blush) !important; border-color: rgba(211,163,168,.5); }
@keyframes mainRiseIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@keyframes mainGlowPulse { 0%, 100% { opacity: .55; } 50% { opacity: .95; } }
@keyframes mainTickerScroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@keyframes mainAccentPulse { 0%, 100% { opacity: .55; transform: scale(1); } 50% { opacity: 1; transform: scale(1.25); } }
.main-hero { position: relative; overflow: hidden; border-radius: 24px; margin: 0 0 .9rem; padding: 1.5rem 1.3rem 1.4rem; background: linear-gradient(155deg, #0c1118 0%, #080b11 85%); border: 1px solid rgba(var(--hero-accent-rgb),.35); box-shadow: 0 30px 64px rgba(0,0,0,.55), 0 0 42px rgba(var(--hero-accent-rgb),.12); animation: mainRiseIn .55s var(--ease-emphasized) both; }
.main-hero-inner { position: relative; z-index: 2; }
.main-hero-radio { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.main-hero-label-row { display: flex; align-items: center; justify-content: space-between; gap: .8rem; margin-bottom: .15rem; }
.main-hero-eyebrow { display: inline-flex; align-items: center; gap: .45rem; font-size: .64rem; font-weight: 800; letter-spacing: .18em; text-transform: uppercase; color: #8fa3b8; font-family: "Bebas Neue", "Arial Narrow", sans-serif; }
.main-hero-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--hero-accent); box-shadow: 0 0 12px 2px rgba(var(--hero-accent-rgb),.9); animation: mainAccentPulse 1.8s ease-in-out infinite; }
.main-hero-toprow { display: flex; align-items: flex-start; justify-content: space-between; gap: .8rem; margin-bottom: 1rem; }
.main-hero-seg { display: flex; gap: .4rem; flex: 1 1 auto; }
.main-hero-seg-btn { padding: .42rem .78rem; border-radius: 999px; cursor: pointer; -webkit-tap-highlight-color: transparent; font-size: .7rem; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; color: #8fa3b8; border: 1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.03); transition: background .22s ease, color .22s ease, border-color .22s ease, box-shadow .22s ease; white-space: nowrap; }
#mainEvents:checked ~ .main-hero-toprow label[for="mainEvents"], #mainRevenue:checked ~ .main-hero-toprow label[for="mainRevenue"], #mainClients:checked ~ .main-hero-toprow label[for="mainClients"] { background: rgba(var(--hero-accent-rgb),.22); color: #fff; border-color: rgba(var(--hero-accent-rgb),.75); box-shadow: 0 0 16px rgba(var(--hero-accent-rgb),.35); }
.main-hero-next { flex: 0 0 auto; max-width: 58%; text-align: right; }
.main-hero-next-label { font-size: .775rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: #8fa3b8; font-family: "Bebas Neue", "Arial Narrow", sans-serif; transform: translateY(4px); }
.main-hero-next-name { font-size: 1.55rem; font-weight: 800; color: #f4f7fb; line-height: 1.2; overflow-wrap: break-word; font-family: "Bebas Neue", "Arial Narrow", sans-serif; margin-top: 3px; }
.main-hero-next-when { font-size: .775rem; font-weight: 800; letter-spacing: .03em; text-transform: uppercase; color: var(--hero-accent); margin-top: calc(.18rem + 3px); text-shadow: 0 0 12px rgba(var(--hero-accent-rgb),.5); font-family: "Bebas Neue", "Arial Narrow", sans-serif; transform: translateY(-1px); }
.main-hero-body { position: relative; }
.main-hero-figure { display: none; align-items: baseline; gap: .6rem; flex-wrap: wrap; }
#mainFigEvents { display: flex; }
#mainEvents:checked ~ .main-hero-body #mainFigEvents { display: flex; }
#mainRevenue:checked ~ .main-hero-body #mainFigRevenue { display: flex; }
#mainClients:checked ~ .main-hero-body #mainFigClients { display: flex; }
#mainRevenue:checked ~ .main-hero-body #mainFigEvents, #mainClients:checked ~ .main-hero-body #mainFigEvents { display: none; }
.main-hero-number { display: block; font-family: "Space Grotesk", "SF Pro Display", "Segoe UI", Arial, sans-serif; font-size: clamp(7rem, 25vw, 8rem); font-weight: 900; line-height: .82; letter-spacing: -.045em; color: #fff; text-shadow: 0 0 24px rgba(var(--hero-accent-rgb),.6), 0 0 50px rgba(var(--hero-accent-rgb),.2), 0 10px 20px rgba(0,0,0,.5); }
.main-hero-tag { font-size: 1.55rem; font-weight: 800; letter-spacing: .01em; text-transform: uppercase; color: var(--hero-accent); text-shadow: 0 0 18px rgba(var(--hero-accent-rgb),.5); font-family: "Bebas Neue", "Arial Narrow", sans-serif; }
.main-hero-mini-row { display: flex; align-items: flex-end; margin-top: 1.1rem; padding-top: .9rem; border-top: 1px solid rgba(var(--hero-accent-rgb),.3); }
.main-hero-mini { text-align: center; display: flex; flex-direction: column; flex: 1 1 0; min-width: 0; }
.main-hero-mini-val { order: 1; }
.main-hero-mini-lab { order: 2; }
.main-hero-mini-val { font-size: 1.55rem; font-weight: 900; color: #fff; font-family: "Space Grotesk", "SF Pro Display", Arial, sans-serif; }
.main-hero-mini-val.is-month { font-size: 1.3rem; font-family: "Bebas Neue", "Arial Narrow", sans-serif; color: var(--hero-accent); }
.main-hero-mini-lab { font-size: .66rem; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; color: #8fa3b8; margin-top: .14rem; font-family: "Bebas Neue", "Arial Narrow", sans-serif; }
.main-hero-upcoming-empty { font-size: .68rem; color: var(--kith-warm-gray); }
@media (max-width: 480px) { .main-hero-next-name { font-size: 1.3rem; } .main-hero-next-when { font-size: .7rem; } .main-hero-tag { font-size: 1.3rem; } }
.main-ticker { position: relative; overflow: hidden; height: 38px; display: flex; align-items: center; margin: 0 0 1rem; border-radius: 12px; border: 1px solid rgba(169,162,154,.2); background: linear-gradient(90deg, var(--kith-charcoal), var(--kith-charcoal-soft)); }
.main-ticker::before, .main-ticker::after { content: ""; position: absolute; top: 0; bottom: 0; width: 26px; z-index: 1; pointer-events: none; }
.main-ticker::before { left: 0; background: linear-gradient(90deg, var(--kith-charcoal), transparent); }
.main-ticker::after { right: 0; background: linear-gradient(270deg, var(--kith-charcoal), transparent); }
.main-ticker-track { display: flex; align-items: center; gap: 1.9rem; width: max-content; padding: 0 1.1rem; animation: mainTickerScroll 24s linear infinite; }
.main-ticker-item { flex: 0 0 auto; display: flex; align-items: center; gap: .32rem; white-space: nowrap; font-size: .62rem; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; color: var(--kith-warm-gray); }
.main-ticker-item strong { font-family: "Space Grotesk", "SF Pro Display", Arial, sans-serif; }
.main-ticker-item strong.is-word { font-family: "Bebas Neue", "Arial Narrow", sans-serif; }
.main-ticker-item strong { color: var(--kith-saddle); font-weight: 900; }
.main-kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .4rem; margin: 0 0 .7rem; }
@media (max-width: 700px) { .main-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.main-flip { position: relative; height: 52px; perspective: 900px; -webkit-tap-highlight-color: transparent; animation: mainRiseIn .5s var(--ease-emphasized) both; }
.main-flip-toggle { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.main-flip-label { display: block; width: 100%; height: 100%; cursor: pointer; }
.main-flip-inner { position: relative; width: 100%; height: 100%; transform-style: preserve-3d; transform: rotateY(0deg); transition: transform .5s cubic-bezier(.4,.2,.2,1); }
.main-flip-toggle:checked ~ .main-flip-label .main-flip-inner { transform: rotateY(180deg); }
.main-flip-face { position: absolute; inset: 0; overflow: hidden; backface-visibility: hidden; -webkit-backface-visibility: hidden; display: flex; flex-direction: row; align-items: center; justify-content: center; gap: .3rem; text-align: center; border-radius: 10px; padding: .3rem .35rem; }
.main-flip-front { border: 1px solid rgba(var(--hero-accent-rgb),.3); background: linear-gradient(155deg, #0c1118 0%, #080b11 85%); box-shadow: 0 0 22px rgba(var(--hero-accent-rgb),.1); }
.main-flip-face.suit-spade .main-flip-front, .main-flip-front.suit-spade { border-color: rgba(124,147,179,.4); }
.main-flip-back { transform: rotateY(180deg); border: 1px solid rgba(211,163,168,.35); background: linear-gradient(150deg, #2a2230, var(--kith-charcoal)); }
.main-kpi-label { font-size: .6rem; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; color: var(--kith-warm-gray); line-height: 1.1; }
.main-kpi-value { font-size: 1.35rem; font-weight: 900; line-height: 1; color: #fff; font-family: "Space Grotesk", "SF Pro Display", Arial, sans-serif; text-shadow: 0 0 20px rgba(var(--hero-accent-rgb),.4); }
.main-kpi-value.is-text { font-size: .93rem; font-family: "Bebas Neue", "Arial Narrow", sans-serif; }
.main-kpi-back-title { font-size: .4rem; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; color: var(--kith-blush); }
.main-kpi-back-row { font-size: .58rem; font-weight: 800; color: var(--kith-saddle); }
.main-kpi-back-row span { display: block; font-size: .4rem; font-weight: 600; color: var(--kith-warm-gray); }
.main-suit-hint { position: static; width: 15px; height: 15px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: .55rem; line-height: 1; color: var(--kith-sand); background: rgba(169,162,154,.14); border: 1px solid rgba(169,162,154,.2); flex: 0 0 auto; }
.main-flip.is-month-oct .main-flip-front { border-color: rgba(var(--kith-month-oct-rgb),.4); background: linear-gradient(150deg, rgba(var(--kith-month-oct-rgb),.22), var(--kith-charcoal)); }
.main-section.is-month-jun { border-color: rgba(var(--kith-month-jun-rgb),.4); background: linear-gradient(150deg, rgba(var(--kith-month-jun-rgb),.16), var(--kith-charcoal)); }
.main-section { position: relative; overflow: hidden; border-radius: 18px; border: 1px solid rgba(var(--hero-accent-rgb),.28); background: linear-gradient(155deg, #0c1118 0%, #080b11 85%); box-shadow: 0 0 24px rgba(var(--hero-accent-rgb),.1); margin-bottom: .65rem; animation: mainRiseIn .5s var(--ease-emphasized) both; }
.main-section-toggle { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.main-section-head-row { display: flex; align-items: center; justify-content: space-between; gap: .5rem; padding: .8rem .95rem; }
.main-section-head { display: flex; align-items: center; gap: .6rem; cursor: pointer; -webkit-tap-highlight-color: transparent; min-width: 0; }
.main-section-title-group { display: flex; flex-direction: column; gap: .12rem; min-width: 0; }
.main-section-name { color: #fff; font-size: 1.05rem; font-weight: 800; white-space: nowrap; text-shadow: 0 0 16px rgba(var(--hero-accent-rgb),.3); text-transform: uppercase; font-family: "Bebas Neue", "Arial Narrow", sans-serif; letter-spacing: .02em; }
.main-section-teaser { color: var(--kith-warm-gray); font-size: .63rem; }
.main-section-chevron { flex: 0 0 auto; color: var(--kith-blush); font-size: .78rem; transform: rotate(0deg); transition: transform .3s var(--ease-standard); }
.main-section-toggle:checked ~ .main-section-head-row .main-section-chevron { transform: rotate(180deg); }
.main-section-body-wrap { display: grid; grid-template-rows: 0fr; max-height: 0; overflow: hidden; transition: grid-template-rows .42s cubic-bezier(.3,.7,.3,1), max-height .42s cubic-bezier(.3,.7,.3,1); }
.main-section-toggle:checked ~ .main-section-body-wrap { grid-template-rows: 1fr; max-height: 3000px; }
.main-section-body { min-height: 0; overflow: hidden; padding: 0 .95rem .95rem; }
.main-trend-header-toggle { display: flex; gap: .3rem; flex: 0 0 auto; }
.main-trend-header-toggle .main-lever-label { }
.main-lever-toggle { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.main-lever-row { display: flex; flex-wrap: wrap; gap: .35rem; margin-bottom: .4rem; }
.main-lever-row.is-metric { margin-bottom: .85rem; }
.main-lever-label { display: inline-block; padding: .42rem .78rem; border-radius: 999px; cursor: pointer; -webkit-tap-highlight-color: transparent; border: 1px solid rgba(169,162,154,.25); background: rgba(23,22,26,.5); color: var(--kith-warm-gray); font-size: .65rem; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; font-family: "Bebas Neue", "Arial Narrow", sans-serif; }
#mainTrendWeekly:checked ~ .main-section-head-row label[for="mainTrendWeekly"], #mainTrendMonthly:checked ~ .main-section-head-row label[for="mainTrendMonthly"], #mainTrendWeekday:checked ~ .main-section-head-row label[for="mainTrendWeekday"] { background: rgba(var(--hero-accent-rgb),.22); color: #fff; border-color: rgba(var(--hero-accent-rgb),.75); box-shadow: 0 0 16px rgba(var(--hero-accent-rgb),.35); }
#mainMetEvents:checked ~ .main-section-body-wrap .main-lever-row label[for="mainMetEvents"], #mainMetRevenue:checked ~ .main-section-body-wrap .main-lever-row label[for="mainMetRevenue"] { background: rgba(var(--hero-accent-rgb),.22); color: #fff; border-color: rgba(var(--hero-accent-rgb),.75); box-shadow: 0 0 16px rgba(var(--hero-accent-rgb),.35); }
.main-trend-view { display: none; }
#mainViewWeeklyEvents { display: block; }
#mainTrendMonthly:checked ~ .main-section-body-wrap .main-trend-views #mainViewWeeklyEvents, #mainTrendWeekday:checked ~ .main-section-body-wrap .main-trend-views #mainViewWeeklyEvents, #mainMetRevenue:checked ~ .main-section-body-wrap .main-trend-views #mainViewWeeklyEvents { display: none; }
#mainTrendWeekly:checked ~ #mainMetEvents:checked ~ .main-section-body-wrap .main-trend-views #mainViewWeeklyEvents, #mainTrendWeekly:checked ~ #mainMetRevenue:checked ~ .main-section-body-wrap .main-trend-views #mainViewWeeklyRevenue, #mainTrendMonthly:checked ~ #mainMetEvents:checked ~ .main-section-body-wrap .main-trend-views #mainViewMonthlyEvents, #mainTrendMonthly:checked ~ #mainMetRevenue:checked ~ .main-section-body-wrap .main-trend-views #mainViewMonthlyRevenue, #mainTrendWeekday:checked ~ #mainMetEvents:checked ~ .main-section-body-wrap .main-trend-views #mainViewWeekdayEvents, #mainTrendWeekday:checked ~ #mainMetRevenue:checked ~ .main-section-body-wrap .main-trend-views #mainViewWeekdayRevenue { display: block; }
.main-plot { position: relative; height: 128px; padding-left: 32px; }
.main-grid-line { position: absolute; left: 32px; right: 0; height: 1px; background: rgba(169,162,154,.14); }
.main-grid-line.is-base { background: rgba(169,162,154,.32); }
.main-grid-tag { position: absolute; left: 0; width: 28px; text-align: right; transform: translateY(-50%); font-size: .45rem; font-weight: 800; color: var(--kith-warm-gray); font-family: "Space Grotesk", "SF Pro Display", Arial, sans-serif; }
.main-bar-row { position: absolute; left: 32px; right: 0; top: 0; bottom: 0; display: flex; align-items: flex-end; gap: .38rem; }
.main-bar-col { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: .2rem; }
.main-bar-value { font-size: .5rem; font-weight: 900; white-space: nowrap; color: var(--kith-warm-gray); font-family: "Space Grotesk", "SF Pro Display", Arial, sans-serif; }
.main-bar-col.is-record .main-bar-value { color: var(--kith-blush); }
.main-bar-shape { width: 100%; max-width: 28px; border-radius: 6px 6px 2px 2px; background: linear-gradient(180deg, var(--kith-blue), var(--kith-blue-deep)); }
.main-bar-shape.is-record { background: linear-gradient(180deg, var(--kith-blush), var(--kith-blush-deep)); box-shadow: 0 0 14px rgba(211,163,168,.35); }
.main-axis { display: flex; gap: .38rem; margin-top: .4rem; padding-left: 32px; }
.main-axis span { flex: 1 1 0; min-width: 0; text-align: center; font-size: .52rem; font-weight: 800; color: var(--kith-warm-gray); }
.main-trend-foot { display: flex; flex-wrap: wrap; gap: .3rem .9rem; margin-top: .7rem; padding-top: .6rem; border-top: 1px solid rgba(169,162,154,.16); font-size: .57rem; color: var(--kith-warm-gray); }
.main-trend-foot strong { color: var(--kith-saddle); font-weight: 800; }
.main-empty { padding: 1.2rem 0; text-align: center; color: var(--kith-warm-gray); font-size: .68rem; }
.main-podium { display: flex; align-items: flex-end; gap: .45rem; margin-bottom: .85rem; }
.main-podium-slot { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: .22rem; padding: .55rem .3rem .5rem; border-radius: 12px 12px 0 0; border: 1px solid rgba(169,162,154,.22); background: linear-gradient(180deg, rgba(38,34,42,.7), var(--kith-charcoal)); }
.main-podium-slot.rank-1 { border-color: rgba(211,163,168,.4); box-shadow: 0 0 26px rgba(211,163,168,.14); }
.main-podium-medal { font-size: 1.2rem; }
.main-podium-name { font-size: .6rem; font-weight: 800; color: var(--kith-saddle); text-align: center; line-height: 1.2; }
.main-podium-stat { font-size: .55rem; color: var(--kith-warm-gray); }
.main-rank-row { display: grid; grid-template-columns: 1.15rem 1fr auto; align-items: center; gap: .55rem; padding: .48rem 0; border-top: 1px solid rgba(169,162,154,.14); }
.main-rank-main { display: flex; align-items: center; gap: .6rem; min-width: 0; }
.main-rank-track { flex: 1 1 auto; min-width: 40px; }
.main-rank-num { font-size: .66rem; font-weight: 800; color: var(--kith-warm-gray); }
.main-rank-name { font-size: .7rem; font-weight: 700; color: var(--kith-saddle); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: "Bebas Neue", "Arial Narrow", sans-serif; }
.main-rank-track { height: 4px; border-radius: 999px; overflow: hidden; background: rgba(169,162,154,.16); }
.main-rank-fill { height: 4px; border-radius: 999px; background: linear-gradient(90deg, var(--kith-blue), var(--kith-mauve)); }
.main-rank-stat { font-size: .64rem; font-weight: 800; color: var(--kith-blush); white-space: nowrap; font-family: "Space Grotesk", "SF Pro Display", Arial, sans-serif; }
.main-donut-wrap { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.main-donut { position: relative; width: 128px; height: 128px; border-radius: 50%; flex: 0 0 auto; }
.main-donut::after { content: ""; position: absolute; inset: 20px; border-radius: 50%; background: var(--kith-charcoal); }
.main-donut-core { position: absolute; inset: 0; z-index: 2; display: flex; flex-direction: row; align-items: baseline; justify-content: center; gap: .3rem; }
.main-donut-core-val { font-size: 1.1rem; font-weight: 900; color: var(--kith-saddle); }
.main-donut-core-lab { font-size: .45rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: var(--kith-warm-gray); }
.main-legend { display: flex; flex-direction: column; gap: .34rem; flex: 1 1 150px; min-width: 150px; }
.main-legend-row { display: flex; align-items: center; gap: .45rem; font-size: .66rem; color: var(--kith-warm-gray); font-family: "Bebas Neue", "Arial Narrow", sans-serif; }
.main-legend-dot { width: 8px; height: 8px; border-radius: 2px; flex: 0 0 auto; }
.main-legend-row strong { margin-left: auto; color: var(--kith-saddle); font-weight: 800; }
.main-milestone { margin-bottom: .8rem; }
.main-milestone:last-child { margin-bottom: 0; }
.main-milestone-head { display: flex; align-items: center; justify-content: space-between; gap: .6rem; margin-bottom: .3rem; }
.main-milestone-name { font-size: .69rem; font-weight: 800; color: var(--kith-saddle); }
.main-milestone-name.is-done { color: var(--kith-sage); }
.main-milestone-detail { font-size: .57rem; color: var(--kith-warm-gray); white-space: nowrap; }
.main-progress-track { height: 7px; border-radius: 999px; overflow: hidden; background: rgba(169,162,154,.16); }
.main-progress-fill { height: 7px; border-radius: 999px; background: linear-gradient(90deg, var(--kith-blue), var(--kith-mauve)); }
.main-progress-fill.is-done { background: linear-gradient(90deg, var(--kith-sage), var(--kith-sage-deep)); }
.hero-header-row { display: flex; align-items: center; justify-content: space-between; gap: .5rem; flex-wrap: nowrap; width: 100%; max-width: 100%; box-sizing: border-box; overflow: hidden; }
.hero-title-link { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.hero-header-links { display: flex; align-items: center; gap: .3rem; flex: 0 0 auto; transform: translateX(-17px) translateY(-4px); }
.hero-header-links .journey-fuel-button { width: 45px; height: 45px; font-size: 1.28rem; border-radius: 12px; animation: none; background: var(--kith-battleship); }
</style>
        """),

        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        f'<div class="hero-header-row"><a class="hero-title-link" href="./" target="_self"><div class="hero-title hero-title-ascii">BARRISTER</div></a>'
        '<div class="hero-header-links">'
        '<a href="http://100.70.235.51:8000/" target="_self" class="journey-fuel-button journey-teddy-button" aria-label="Open Bronx Bombers Daily">\u26be\ufe0f</a>'
        '<a href="http://100.70.235.51:8011" target="_self" class="journey-fuel-button journey-teddy-button" aria-label="Open Heroes and Muses">\U0001F4DA</a>'
        '<a href="http://100.70.235.51:9000" target="_self" class="journey-fuel-button journey-teddy-button" aria-label="Open Showcase">\U0001F9F8</a>'
        '</div></div>',
        unsafe_allow_html=True,
    )


NEW_SPLASH_URL = "https://behrhub.github.io/SPLASH/"

def render_splash_screen() -> None:
    st.markdown(
        compact(f"""
<meta http-equiv="refresh" content="0; url={NEW_SPLASH_URL}">
<script>window.location.replace("{NEW_SPLASH_URL}");</script>
"""),
        unsafe_allow_html=True,
    )
    st.stop()
    return

    # --- old poster-image splash, kept below but unreachable, in case we ever want it back ---
    enter_url = "?page=executive-summary"
    st.markdown(
        compact(f"""
<style>
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stExpandSidebarButton"] {{
            display: none !important;
        }}
        html,
        body,
        [data-testid="stAppViewContainer"],
        [data-testid="stApp"],
        .main,
        .stApp {{
            overflow: hidden !important;
            height: 100vh !important;
            max-height: 100vh !important;
            overscroll-behavior: none !important;
            touch-action: none;
        }}
        .stApp {{
            background: #05070b !important;
        }}
        .block-container {{
            max-width: none !important;
            width: 100vw !important;
            height: 100vh !important;
            padding: 0 !important;
            margin: 0 !important;
        }}
        .splash-gateway {{
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            overflow: hidden;
            background: var(--kith-sand);
        }}
        .splash-enter-link {{
            position: absolute;
            inset: 0;
            z-index: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            box-sizing: border-box;
            width: 100vw;
            height: 100vh;
            padding: 0 0 clamp(1.2rem, 4.5vh, 4rem);
            cursor: pointer;
            text-decoration: none !important;
            -webkit-tap-highlight-color: transparent;
        }}

        .splash-gateway::before,
        .splash-gateway::after {{
            content: "";
            position: fixed;
            top: 0;
            bottom: 0;
            width: 51vw;
            z-index: 9999;
            pointer-events: none;
            background:
                radial-gradient(circle at 50% 18%, rgba(56,189,248,.12), transparent 35%),
                linear-gradient(135deg, rgba(8,17,31,.98), rgba(3,7,18,.995));
            box-shadow: inset 0 0 42px rgba(56,189,248,.14);
            transition: transform .58s cubic-bezier(.78,.02,.22,1);
        }}
        .splash-gateway::before {{
            left: 0;
            transform: translateX(-101%);
            border-right: 1px solid rgba(148,163,184,.18);
        }}
        .splash-gateway::after {{
            right: 0;
            transform: translateX(101%);
            border-left: 1px solid rgba(148,163,184,.18);
        }}
        .splash-gateway.curtain-close::before,
        .splash-gateway.curtain-close::after {{
            transform: translateX(0);
        }}

        .splash-poster {{
            filter: saturate(1.03) contrast(1.02);
            display: block;
        }}
        .splash-image-frame {{
            display: flex;
            align-items: center;
            justify-content: center;
            transform-origin: center center;
        }}
        .splash-poster-official {{
            width: auto;
            height: auto;
            max-width: min(97vw, 1180px);
            max-height: calc(97vh - clamp(1.2rem, 4.5vh, 4rem));
            object-fit: contain;
            object-position: center center;
        }}
        @media (max-width: 700px) {{
            .splash-enter-link {{
                padding-bottom: 0;
            }}
            .splash-image-frame {{
                margin-top: -92px;
            }}
            .splash-poster-official {{
                width: min(107vw, 68vh) !important;
                height: auto !important;
                max-width: none !important;
                max-height: calc(100vh - .75rem) !important;
                object-fit: contain !important;
                object-position: center center !important;
            }}
        }}
        </style>
        <div class="splash-gateway" aria-label="Barrister Dashboard splash screen">
            <a class="splash-enter-link" href="{enter_url}" target="_self" aria-label="Enter dashboard" onclick="event.preventDefault(); const gate=this.closest('.splash-gateway'); if(gate){{gate.classList.add('curtain-close');}} setTimeout(()=>{{window.location.href=this.href;}},620);">
                <div class="splash-image-frame">
                    <img class="splash-poster splash-poster-official" src="{SPLASH_IMAGE_URL}" alt="" aria-hidden="true" width="{SPLASH_IMAGE_WIDTH}" height="{SPLASH_IMAGE_HEIGHT}" loading="eager" decoding="async" fetchpriority="high">
                </div>
            </a>
        </div>
        """),
        unsafe_allow_html=True,
    )

def metric_card(label: str, value: object, detail: str = "", icon: str = "", accent: str = "") -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    display = f"{value:,}" if isinstance(value, int) else str(value if value not in (None, "") else "N/A")
    icon_markup = f'<div class="metric-icon">{escape(icon)}</div>' if icon else ""
    detail_markup = f'<div class="metric-detail">{escape(detail)}</div>' if detail else ""
    accent_style = f' style="--metric-accent: {escape(accent, quote=True)}"' if accent else ""
    return (
        f'<div class="metric-card"{accent_style}>{icon_markup}'
        f'<div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value">{escape(display)}</div>{detail_markup}</div>'
    )


@st.cache_data(show_spinner=False)
def _cached_logo_data_uri(path_str: str, mtime: float) -> str:
    """Cache logo base64 so Client Analytics does not reread/re-encode logos repeatedly."""
    import base64
    path = Path(path_str)
    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("utf-8")


def _logo_key(value: object) -> str:
    return (
        str(value or "")
        .lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("&", "and")
        .replace("'", "")
        .replace(".", "")
    )


def client_logo_markup(client: object, logo_files: dict[str, Path], class_name: str = "client-logo-badge") -> str:
    """Fast mini-logo renderer for Client Analytics.

    Uses prebuilt 92x92 mini icons first to avoid large logo loads.
    """
    client_name = str(getattr(client, "client", "") or getattr(client, "name", "") or client or "")

    def norm(value: object) -> str:
        raw = str(value or "").lower()
        return (
            raw.replace(" ", "")
            .replace("-", "")
            .replace("_", "")
            .replace("&", "and")
            .replace("'", "")
            .replace(".", "")
            .replace(",", "")
        )

    aliases = {
        "hebrewhomeofgreaterwashington": "hebrewhomegw",
        "hebrewhome": "hebrewhomegw",
        "officeofmdsenatorangelaalsobrooks": "alsobrooks",
        "angelaalsobrooks": "alsobrooks",
        "officeofmdsenatorchrisvanhollen": "vanhollen",
        "chrisvanhollen": "vanhollen",
        "macy": "macys",
        "macys": "macys",
        "giantfoodstores": "giant",
        "weismarkets": "weis",
        "hamptoninnandsuites": "hamptoninn",
        "bloomingdale": "bloomingdales",
        "bloomingdales": "bloomingdales",
        "7eleven": "711",
        "seveneleven": "711",
        "pepsico": "pepsi",
        "montpellier": "montpelier",
        "montpellierliquors": "montpelier",
        "montpelierliquors": "montpelier",
        "marylandbaptisthome": "marylandbaptistagehome",
        "mdbaptistagehome": "marylandbaptistagehome",
    }

    wanted = aliases.get(norm(client_name), norm(client_name))

    mini_path = BRAND_FACTORY_APPROVED_DIR / "_client_mini_icons" / f"{wanted}.png"
    if mini_path.exists():
        src = _cached_logo_data_uri(str(mini_path), mini_path.stat().st_mtime)
        return (
            f'<span class="{class_name}">'
            f'<img src="{src}" alt="{escape(client_name)} logo" loading="lazy" />'
            f'</span>'
        )

    return (
        f'<span class="{class_name}">'
        f'<span class="client-logo-placeholder">{escape(client_initials(client_name))}</span>'
        f'</span>'
    )


def completed_client_portfolio(data: WorkbookData) -> pd.DataFrame:
    chronology = completed_chronology(data)
    if chronology.empty or "client" not in chronology:
        return pd.DataFrame(columns=["Client", "first_visit", "visits"])
    portfolio = (
        chronology.assign(client=chronology["client"].fillna("").astype(str).str.strip())
        .loc[lambda frame: frame["client"].ne("")]
        .groupby("client", as_index=False)
        .agg(first_visit=("visit_number", "min"), visits=("visit_number", "count"))
        .sort_values(["first_visit", "client"], ascending=[True, True])
        .rename(columns={"client": "Client"})
    )
    return portfolio


def render_client_logo_marquee(data: WorkbookData) -> None:
    """F1-style scrolling sponsor board of every client served — pure CSS, pauses on hover."""
    portfolio = completed_client_portfolio(data)
    if portfolio.empty:
        return
    logo_files, _ = discover_logos(LOGOS_DIR)
    clients = portfolio["Client"].tolist()

    def tile(client: str) -> str:
        return (
            '<div class="client-marquee-item">'
            f'{client_logo_markup(client, logo_files, "client-logo-badge marquee-logo-badge")}'
            f'<div class="marquee-client-name">{escape(client_card_display_name(client))}</div>'
            '</div>'
        )

    tiles = "".join(tile(client) for client in clients)
    st.markdown(
        '<div class="client-portfolio client-marquee">'
        f'<div class="portfolio-heading">CLIENTS SERVED · {len(clients)}</div>'
        '<div class="client-marquee-viewport">'
        f'<div class="client-marquee-track">{tiles}{tiles}</div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

def style_figure(figure: go.Figure, height: int = 390) -> go.Figure:
    figure.update_layout(
        height=height,
        margin=dict(l=20, r=20, t=55, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#dce5f1", family="Arial"),
        title_font=dict(size=17, color="#f4f8fd"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        colorway=COLORS,
        dragmode=False,
    )
    figure.update_xaxes(gridcolor="#1c2d45", zerolinecolor="#1c2d45", fixedrange=True)
    figure.update_yaxes(gridcolor="#1c2d45", zerolinecolor="#1c2d45", fixedrange=True)
    return figure


def count_value(value: object, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def completed_timeline(data: WorkbookData) -> pd.DataFrame:
    timeline = data.timeline
    if "status" not in timeline:
        return timeline.iloc[0:0]
    return timeline[timeline["status"].eq("Completed")].copy()


def completed_chronology(data: WorkbookData) -> pd.DataFrame:
    completed = completed_timeline(data)
    if completed.empty:
        return completed
    completed = completed.copy()
    completed["_sort_number"] = pd.to_numeric(completed.get("event_number", pd.Series(dtype=float)), errors="coerce")
    completed = completed.sort_values(["_sort_number", "client"], na_position="last").reset_index(drop=True)
    completed["visit_number"] = range(1, len(completed) + 1)
    return completed.drop(columns=["_sort_number"])


def _pipeline_location_parts(location: object) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", str(location or "").strip())
    if "," in text:
        city, state = [part.strip() for part in text.rsplit(",", 1)]
        return city, state
    return text, ""


def compact_state_code(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z]+", " ", str(value or "")).strip().upper()
    if not normalized:
        return ""
    if normalized.startswith("DC") or "DISTRICT OF COLUMBIA" in normalized or normalized == "WASHINGTON D C":
        return "DC"
    if normalized.startswith("MD") or normalized == "MARYLAND":
        return "MD"
    if normalized.startswith("VA") or normalized == "VIRGINIA":
        return "VA"
    if normalized.startswith("PA") or normalized == "PENNSYLVANIA":
        return "PA"
    if normalized.startswith("WV") or normalized == "WEST VIRGINIA":
        return "WV"
    if normalized.startswith("DE") or normalized == "DELAWARE":
        return "DE"
    return str(value or "").strip()


def add_known_location(locations: set[str], city: object, state: object) -> None:
    city_label = str(city or "").strip()
    state_label = compact_state_code(state)
    if city_label and state_label:
        locations.add(f"{city_label}, {state_label}")


def pipeline_frame(data: WorkbookData) -> pd.DataFrame:
    pipeline = getattr(data, "pipeline", None)
    if pipeline is None or not isinstance(pipeline, pd.DataFrame):
        pipeline = empty_pipeline_frame()
    if pipeline.empty and not len(pipeline.columns):
        pipeline = empty_pipeline_frame()
    normalized = pipeline.copy()
    for column in empty_pipeline_frame().columns:
        if column not in normalized:
            normalized[column] = ""
    normalized["_source_path"] = str(data.path)
    return normalized


def has_usable_scheduled_assignments(frame: pd.DataFrame) -> bool:
    if frame.empty or not {"client", "location", "status"}.issubset(frame.columns):
        return False
    scheduled = frame[frame["status"].fillna("").astype(str).str.title().eq("Scheduled")].copy()
    if scheduled.empty:
        return False
    return bool(
        (
            scheduled["client"].fillna("").astype(str).str.strip().ne("")
            & scheduled["location"].fillna("").astype(str).str.strip().ne("")
        ).any()
    )


def upcoming_assignments(data: WorkbookData) -> pd.DataFrame:
    rows = []
    seen = set()
    pipeline = pipeline_frame(data)
    if not pipeline.empty and {"client", "status"}.issubset(pipeline.columns):
        scheduled = pipeline[pipeline["status"].fillna("").astype(str).str.title().eq("Scheduled")]
        for row in scheduled.to_dict("records"):
            city, state = _pipeline_location_parts(row.get("location", ""))
            key = (
                str(row.get("client", "")).casefold(),
                city.casefold(),
                state.casefold(),
                str(row.get("event_date", "")).casefold(),
                str(row.get("status", "")).casefold(),
                str(row.get("notes", "")).casefold(),
            )
            if not row.get("client"):
                continue
            seen.add(key)
            rows.append({
                "client": row.get("client", ""),
                "city": city,
                "state": state,
                "notes": row.get("notes", ""),
                "event_date": row.get("event_date", ""),
            })

    if "status" in data.timeline:
        scheduled_timeline = data.timeline[data.timeline["status"].eq("Scheduled")]
        for row in scheduled_timeline.to_dict("records"):
            city = str(row.get("city", "") or "").strip()
            state = str(row.get("region_code", "") or "").strip()
            key = (
                str(row.get("client", "")).casefold(),
                city.casefold(),
                state.casefold(),
                str(row.get("event_date", "")).casefold(),
                str(row.get("status", "")).casefold(),
                str(row.get("notes", "")).casefold(),
            )
            if not row.get("client") or key in seen:
                continue
            seen.add(key)
            rows.append({
                "client": row.get("client", ""),
                "city": city,
                "state": state,
                "notes": row.get("notes", ""),
                "event_date": row.get("event_date", ""),
            })
    upcoming = pd.DataFrame(rows)
    if upcoming.empty:
        return upcoming
    upcoming["_sort_date"] = pd.to_datetime(upcoming["event_date"], errors="coerce")
    upcoming = upcoming.sort_values(
        ["_sort_date", "client", "city"],
        ascending=[True, True, True],
        na_position="last",
        key=lambda values: values.str.casefold() if values.dtype == object else values,
    )
    return upcoming.drop(columns=["_sort_date"]).reset_index(drop=True)


def known_location_options(data: WorkbookData) -> list[str]:
    locations = set()
    if {"city", "region_code"}.issubset(data.timeline.columns):
        for row in data.timeline[["city", "region_code"]].fillna("").astype(str).to_dict("records"):
            add_known_location(locations, row["city"], row["region_code"])

    pipeline = pipeline_frame(data)
    if "location" in pipeline:
        for value in pipeline["location"].fillna("").astype(str):
            city, state = _pipeline_location_parts(value)
            add_known_location(locations, city, state)

    try:
        coordinate_locations = load_locations(LOCATIONS_PATH)
    except (OSError, ValueError):
        coordinate_locations = pd.DataFrame()
    if {"city", "state"}.issubset(coordinate_locations.columns):
        for row in coordinate_locations[["city", "state"]].fillna("").astype(str).to_dict("records"):
            add_known_location(locations, row["city"], row["state"])

    return sorted(locations, key=str.casefold)


def render_upcoming_assignments(data: WorkbookData) -> None:
    upcoming = upcoming_assignments(data)
    items = []
    for index, row in enumerate(upcoming.to_dict("records")):
        location = ", ".join(value for value in [str(row.get("city", "")).strip(), str(row.get("state", "")).strip()] if value)
        date_label = scheduled_date_label(row.get("event_date", ""))
        date_markup = f'<span class="upcoming-date">{escape(date_label)}</span>' if date_label not in ("", "No Date") else ""
        delay = min(index * 0.045, 0.4)
        items.append(
            f'<li style="animation-delay:{delay:.3f}s"><span class="upcoming-dot"></span>'
            '<div class="upcoming-main"><strong>'
            f'{escape(str(row.get("client", "")))}</strong>'
            + (f' — {escape(location)}' if location else "")
            + f'</div>{date_markup}</li>'
        )
    st.markdown(
        '<div class="upcoming-assignments"><div class="upcoming-title">'
        f'<span class="live-pulse-dot"></span>Upcoming Assignments ({len(upcoming)})</div>'
        f'<ul class="upcoming-list">{"".join(items) if items else "<li>None scheduled</li>"}</ul></div>',
        unsafe_allow_html=True,
    )


def repeat_client_count(data: WorkbookData) -> int:
    completed = completed_timeline(data)
    if "client" in completed and not completed.empty:
        return int(completed["client"].replace("", pd.NA).dropna().value_counts().gt(1).sum())
    return 0


def render_premium_jurisdiction_donut(activity: pd.DataFrame) -> None:
    total = int(activity["events"].sum())
    if total <= 0:
        st.info("Completed jurisdiction activity is unavailable in the Timeline sheet.")
        return

    activity = activity.copy()
    activity["percentage"] = activity["events"].div(total).mul(100)
    circumference = 2 * math.pi * 96
    gap = 3.8
    offset = 0.0
    depth_segments = []
    top_segments = []
    labels = []
    legend_rows = []
    largest = activity.iloc[0]

    for legend_index, row in enumerate(activity.to_dict("records")):
        name = str(row["state_region"])
        events = int(row["events"])
        percentage = float(row["percentage"])
        style = JURISDICTION_DONUT_STYLES.get(name, JURISDICTION_DONUT_STYLES["Pennsylvania / Other"])
        dash = max(circumference * events / total - gap, 1)
        stroke_width = 41 if name == largest["state_region"] else 35
        title = f"{name}\n{percentage:.1f}%\n{events} of {total} completed visits"
        common = (
            f'cx="150" cy="150" r="96" fill="none" stroke-dasharray="{dash:.3f} {circumference:.3f}" '
            f'stroke-dashoffset="{-offset:.3f}" transform="rotate(-90 150 150)"'
        )
        depth_segments.append(
            f'<circle class="donut-segment-depth" {common} stroke="{style["depth"]}" stroke-width="{stroke_width}">'
            f"<title>{escape(title)}</title></circle>"
        )
        top_class = "donut-segment-top donut-segment-major" if name == largest["state_region"] else "donut-segment-top"
        top_segments.append(
            f'<circle class="{top_class}" {common} stroke="{style["color"]}" stroke-width="{stroke_width}">'
            f"<title>{escape(title)}</title></circle>"
        )

        mid_angle = math.radians(-90 + ((offset + (circumference * events / total) / 2) / circumference) * 360)
        label_radius = 38 if name == largest["state_region"] else 37
        label_left = 50 + math.cos(mid_angle) * label_radius
        label_top = 50 + math.sin(mid_angle) * label_radius
        labels.append(
            f'<div class="donut-label" style="left:{label_left:.1f}%; top:{label_top:.1f}%;">'
            f'<span>{style["icon"]}</span><span>{percentage:.1f}%</span></div>'
        )
        legend_delay = min(legend_index * 0.06, 0.3)
        legend_rows.append(
            f'<details class="donut-legend-row" style="border-left:4px solid {style["color"]}; animation-delay:{legend_delay:.3f}s;">'
            f'<summary class="donut-legend-summary">'
            f'<div class="legend-icon">{style["icon"]}</div>'
            f'<div class="legend-name">{escape(name)}</div>'
            f'<div class="legend-percent">{percentage:.1f}%</div>'
            f'</summary>'
            f'<div class="legend-drawer">{events} Visits</div>'
            f'</details>'
        )
        offset += circumference * events / total

    callout = f'{largest["state_region"]} represents {float(largest["percentage"]):.1f}% of completed service activity.'
    svg = (
        '<svg class="donut-svg" viewBox="0 0 300 300" role="img" '
        f'aria-label="Service Activity by Jurisdiction, {total} total completed visits">'
        '<defs><radialGradient id="donutPlate" cx="50%" cy="43%" r="56%">'
        '<stop offset="0%" stop-color="#263b59"/><stop offset="62%" stop-color="#102039"/>'
        '<stop offset="100%" stop-color="#07101c"/></radialGradient></defs>'
        '<ellipse cx="150" cy="178" rx="118" ry="34" fill="rgba(0,0,0,.34)"/>'
        '<circle cx="150" cy="150" r="122" fill="url(#donutPlate)" opacity=".72"/>'
        '<circle cx="150" cy="164" r="96" fill="none" stroke="rgba(0,0,0,.28)" stroke-width="39"/>'
        f'<g transform="translate(0 14)">{"".join(depth_segments)}</g>'
        f'<g>{"".join(top_segments)}</g>'
        '<circle cx="150" cy="150" r="60" fill="#07101c" opacity=".96"/>'
        '</svg>'
    )
    st.markdown(
        f"""
        <div class="premium-donut-card">
            <div class="premium-donut-title">Service Activity by Jurisdiction</div>
            <div class="premium-donut-layout">
                <div class="donut-stage">
                    {svg}
                    <div class="donut-center">
                        <div class="donut-center-label">TOTAL VISITS</div>
                        <div class="donut-center-value">{total}</div>
                    </div>
                    {''.join(labels)}
                </div>
                <div class="donut-legend">{''.join(legend_rows)}</div>
            </div>
            <div class="donut-callout">{escape(callout)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_summary(data: WorkbookData, filtered_timeline: pd.DataFrame) -> None:
    completed = completed_timeline(data)
    unique_fallback = int(completed["client"].replace("", pd.NA).dropna().nunique()) if "client" in completed else 0
    regions_fallback = completed["state_region"].replace("", pd.NA).nunique() if "state_region" in completed else 0
    metrics = [
        (
            "Service Events",
            scorecard_metric(data.scorecard, "Completed Service Events", fallback=len(completed)),
            "Scorecard completed events",
            "🏁",
            "#2dd4bf",
        ),
        (
            "Unique Clients",
            unique_fallback,
            "Completed client authority",
            "🤝",
            "#38bdf8",
        ),
        (
            "Repeat Clients",
            repeat_client_count(data),
            "Client List completed visits > 1",
            "🔁",
            "#a78bfa",
        ),
        (
            "Jurisdictions",
            scorecard_metric(data.scorecard, "Jurisdictions Covered", "States Worked", fallback=regions_fallback),
            "Verified coverage",
            "🗺️",
            "#f59e0b",
        ),
    ]
    metric_markup = "".join(
        metric_card(label, value, detail, icon=icon, accent=accent)
        for label, value, detail, icon, accent in metrics
    )
    st.markdown(f'<div class="executive-metrics">{metric_markup}</div>', unsafe_allow_html=True)
    render_client_logo_marquee(data)

    completed_activity = filtered_timeline
    if "status" in completed_activity:
        completed_activity = completed_activity[completed_activity["status"].eq("Completed")]
    if "state_region" in completed_activity and not completed_activity.empty:
        activity = (
            completed_activity.groupby("state_region").size().sort_values(ascending=False)
            .rename("events").reset_index()
        )
        render_premium_jurisdiction_donut(activity)
    else:
        st.info("Completed jurisdiction activity is unavailable in the Timeline sheet.")
    render_upcoming_assignments(data)


def state_debut_label(row: dict) -> str:
    state = str(row.get("state_region", "") or row.get("region_code", "") or "").strip()
    normalized = jurisdiction_group(state)
    if normalized == "Washington, D.C.":
        return "DISTRICT OF COLUMBIA DEBUT"
    if normalized == "Pennsylvania / Other":
        state_code = compact_state_code(row.get("region_code", "")) or "NEW TERRITORY"
        if state_code == "PA":
            return "PENNSYLVANIA DEBUT"
        return f"{state_code.upper()} DEBUT"
    return f"{normalized.upper()} DEBUT"


def career_milestones_for_row(row: dict) -> list[str]:
    client = str(row.get("client", "") or "").lower()
    notes = str(row.get("notes", "") or "").lower()
    visit_number = int(row.get("visit_number", row.get("event_number", 0)) or 0)
    milestones = []

    if "senator" in client or "van hollen" in client or "alsobrooks" in client:
        milestones.append("FIRST SENATE OFFICE")
    if "joint base andrews" in client:
        milestones.append("FIRST MILITARY INSTALLATION")
    if client == "usda":
        milestones.append("USDA MAJOR PROJECT")
    if client in {"tj maxx", "marshalls", "homegoods"} and (
        "tjx" in notes or "trifecta" in notes or visit_number >= 35
    ):
        milestones.append("TJX CONTRACT AWARDED")
    if "baskin robbins" in client or "dunkin" in notes:
        milestones.append("DUNKIN’ CONTRACT AWARDED")

    return milestones


def career_milestones_after_row(row: dict) -> list[str]:
    client = str(row.get("client", "") or "").lower()
    notes = str(row.get("notes", "") or "").lower()
    milestones = []
    if "montpelier liquors" in client or "catalina" in notes:
        milestones.append("CATALINA CONTRACT AWARDED")
    if "alsobrooks" in client:
        milestones.append("BOTH MARYLAND SENATORS' OFFICES COMPLETED")
    return milestones


def render_main_page(data: WorkbookData, filtered_timeline: pd.DataFrame) -> None:
    completed = completed_timeline(data)
    financial = financial_frame(data)
    directory = client_directory_frame(data)

    def esc(value) -> str:
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    def money(value) -> str:
        value = float(value or 0)
        if abs(value) >= 1000:
            text = f"＄{value / 1000:.1f}k"
            return text.replace(".0k", "k")
        return f"＄{value:,.0f}"

    def fmt(value, metric: str) -> str:
        return money(value) if metric == "revenue" else f"{value:,.0f}"

    def axis_ceiling(peak: float):
        if peak <= 0:
            return 1, 4
        for step in (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 75,
                     100, 125, 150, 200, 250, 300, 400, 500, 600, 750,
                     1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000, 7500, 10000):
            if step * 4 >= peak:
                return step, step * 4
        return 25000, 100000

    def compact(markup: str) -> str:
        return "\n".join(line.strip() for line in markup.splitlines() if line.strip())

    dated = financial.dropna(subset=["event_date"]) if "event_date" in financial else financial.iloc[0:0]

    career_events = len(completed)
    career_revenue = float(pd.to_numeric(financial.get("revenue_amount", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    unique_clients = int(completed["client"].replace("", pd.NA).dropna().nunique()) if "client" in completed else 0
    repeat_clients = repeat_client_count(data)
    repeat_rate = round(repeat_clients / max(1, unique_clients) * 100)
    avg_per_event = round(career_revenue / max(1, career_events))

    jurisdiction_series = (
        completed["state_region"].replace("", pd.NA).dropna()
        if "state_region" in completed else pd.Series(dtype=str)
    )
    jurisdiction_counts = jurisdiction_series.value_counts()
    jurisdictions = int(jurisdiction_counts.shape[0])

    work_days = sorted(dated["event_date"].dt.date.unique()) if not dated.empty else []

    def _streak_continues(prev, curr) -> bool:
        gap = (curr - prev).days
        if gap == 1:
            return True
        if gap == 3 and prev.weekday() == 4:  # Friday -> Monday, not a real break
            return True
        return False

    current_streak, best_streak = 0, 0
    if work_days:
        run = 1
        best_streak = 1
        for i in range(1, len(work_days)):
            if _streak_continues(work_days[i - 1], work_days[i]):
                run += 1
            else:
                run = 1
            best_streak = max(best_streak, run)
        current_streak = 1
        for i in range(len(work_days) - 1, 0, -1):
            if _streak_continues(work_days[i - 1], work_days[i]):
                current_streak += 1
            else:
                break

    def build_series(rows: list[dict]) -> list[dict]:
        if not rows:
            return []
        peak_events = max(r["events"] for r in rows)
        peak_revenue = max(r["revenue"] for r in rows)
        for r in rows:
            r["is_record"] = r["events"] == peak_events or r["revenue"] == peak_revenue
        return rows

    weekly, monthly, weekday = [], [], []
    if not dated.empty:
        wk = dated.copy()
        iso = wk["event_date"].dt.isocalendar()
        wk["iso_year"], wk["iso_week"] = iso["year"], iso["week"]
        wk["week_index"] = wk["iso_year"] * 52 + wk["iso_week"]
        career_start_index = int(wk["week_index"].min())
        grouped = wk.groupby("week_index").agg(
            events=("client", "count"),
            revenue=("revenue_amount", lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
        ).reset_index().sort_values("week_index").tail(6)
        weekly = build_series([
            {"label": f"W{int(row['week_index']) - career_start_index + 1}", "events": int(row["events"]), "revenue": round(row["revenue"])}
            for _, row in grouped.iterrows()
        ])

        if "month_label" in dated and "month_order" in dated:
            mo = dated.dropna(subset=["month_label"]).copy()
            grouped_m = mo.groupby(["month_order", "month_label"]).agg(
                events=("client", "count"),
                revenue=("revenue_amount", lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
            ).reset_index().sort_values("month_order").tail(6)
            monthly = build_series([
                {"label": str(row["month_label"])[:3].upper(), "events": int(row["events"]), "revenue": round(row["revenue"])}
                for _, row in grouped_m.iterrows()
            ])

        wd = dated.copy()
        wd["weekday_name"] = wd["event_date"].dt.day_name()
        order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        grouped_wd = wd.groupby("weekday_name").agg(
            events=("client", "count"),
            revenue=("revenue_amount", lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0).sum())),
        ).reindex(order).dropna(how="all").fillna(0).reset_index()
        weekday = build_series([
            {"label": str(row["weekday_name"])[:3].upper(), "events": int(row["events"]), "revenue": round(row["revenue"])}
            for _, row in grouped_wd.iterrows()
        ])

    client_revenue = pd.Series(dtype=float)
    if not financial.empty and "client" in financial:
        client_revenue = financial.groupby("client")["revenue_amount"].apply(
            lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0).sum())
        )
    clients: list[dict] = []
    if not directory.empty and "Client" in directory:
        all_clients = [
            {
                "name": str(row["Client"]),
                "events": int(row["# of Visits"]),
                "revenue": round(float(client_revenue.get(str(row["Client"]), 0.0))),
            }
            for _, row in directory.iterrows()
        ]
        clients = sorted(all_clients, key=lambda c: (-c["events"], -c["revenue"]))[:10]

    jur_palette = ["var(--kith-blush)", "var(--kith-blue)", "var(--kith-sand)", "var(--kith-mauve)", "var(--kith-sage)"]
    territory: list[dict] = []
    if jurisdiction_counts.shape[0] > 0:
        total_jur = int(jurisdiction_counts.sum())
        for index, (name, count) in enumerate(jurisdiction_counts.items()):
            territory.append({
                "name": str(name),
                "pct": round(count / max(1, total_jur) * 100),
                "color": jur_palette[index % len(jur_palette)],
            })

    next_tier = ((int(career_revenue) // 5000) + 1) * 5000 if career_revenue > 0 else 5000
    milestones = [
        {"name": "50 Career Events", "detail": "Achieved" if career_events >= 50 else f"{career_events} of 50",
         "pct": 100 if career_events >= 50 else round(career_events / 50 * 100), "done": career_events >= 50},
        {"name": "5+ Jurisdictions", "detail": "Achieved" if jurisdictions >= 5 else f"{jurisdictions} of 5",
         "pct": 100 if jurisdictions >= 5 else round(jurisdictions / 5 * 100), "done": jurisdictions >= 5},
        {"name": f"{best_streak}-Day Streak", "detail": "Longest run on record", "pct": 100, "done": True},
        {"name": f"{money(next_tier)} Career Revenue", "detail": f"{money(career_revenue)} of {money(next_tier)}",
         "pct": max(3, min(100, round(career_revenue / next_tier * 100))), "done": False},
    ]
    milestones.sort(key=lambda m: m["done"])
    achieved = sum(1 for m in milestones if m["done"])
    in_progress = len(milestones) - achieved

    stops, running = [], 0
    for sector in territory:
        stops.append(f'{sector["color"]} {running}% {running + sector["pct"]}%')
        running += sector["pct"]
    donut = f"conic-gradient(from -90deg, {', '.join(stops)})" if stops else "conic-gradient(rgba(169,162,154,.25) 0% 100%)"

    top_client = clients[0] if clients else {"name": "\u2014", "events": 0, "revenue": 0}

    pipeline = data.pipeline.copy() if getattr(data, "pipeline", None) is not None else pd.DataFrame()
    upcoming_count = len(pipeline)
    upcoming_rows: list[dict] = []
    if not pipeline.empty and "client" in pipeline:
        display_pipeline = pipeline.copy()
        if "event_date" in display_pipeline:
            display_pipeline = display_pipeline.sort_values("event_date", na_position="last")
        today = date.today()
        for record in display_pipeline.head(5).to_dict("records"):
            name = str(record.get("client", "") or "").strip() or "Unnamed"
            raw_date = record.get("event_date")
            when = ""
            if pd.notna(raw_date):
                event_day = pd.Timestamp(raw_date).date()
                delta = (event_day - today).days
                if delta == 0:
                    when = "TODAY"
                elif delta == 1:
                    when = "TOM"
                else:
                    when = f"{event_day.month}/{event_day.day}"
            upcoming_rows.append({"name": name, "when": when})
    best_month = max(monthly, key=lambda row: row["events"]) if monthly else {"label": "\u2014", "events": 0, "revenue": 0}

    plot_h, bar_max, bar_min = 128, 108, 5

    def chart(series, metric: str, view_id: str) -> str:
        if not series:
            return f'<div class="main-trend-view" id="{view_id}"><div class="main-empty">Not enough dated history yet.</div></div>'
        values = [row[metric] for row in series]
        peak = max(values) if values else 0
        step, top = axis_ceiling(peak)
        grid = []
        for level_index in range(4, -1, -1):
            level = step * level_index
            y = min(plot_h - 1, plot_h - round((level / top) * bar_max))
            css_class = "main-grid-line is-base" if level_index == 0 else "main-grid-line"
            grid.append(f'<div class="{css_class}" style="top:{y}px"></div>')
            if level_index in (0, 2, 4):
                grid.append(f'<span class="main-grid-tag" style="top:{y}px">{esc(fmt(level, metric))}</span>')
        bars, axis = [], []
        for row in series:
            value = row[metric]
            height = max(bar_min, round(value / top * bar_max)) if value > 0 else 3
            record = " is-record" if row["is_record"] else ""
            bars.append(
                f'<div class="main-bar-col{record}">'
                f'<div class="main-bar-value">{esc(fmt(value, metric))}</div>'
                f'<div class="main-bar-shape{record}" style="height:{height}px"></div>'
                f"</div>"
            )
            axis.append(f'<span>{esc(row["label"])}</span>')
        best = max(series, key=lambda row: row[metric]) if series else None
        foot = ""
        if best is not None:
            total = sum(values)
            average = total / len(values)
            foot = (
                '<div class="main-trend-foot">'
                f'<span>Peak <strong>{esc(best["label"])}</strong> &middot; {esc(fmt(best[metric], metric))}</span>'
                f'<span>Average <strong>{esc(fmt(round(average), metric))}</strong></span>'
                f'<span>Total <strong>{esc(fmt(total, metric))}</strong></span>'
                "</div>"
            )
        return (
            f'<div class="main-trend-view" id="{view_id}">'
            f'<div class="main-plot">{"".join(grid)}<div class="main-bar-row">{"".join(bars)}</div></div>'
            f'<div class="main-axis">{"".join(axis)}</div>{foot}</div>'
        )

    ticker_items = [
        f'&#127937; <strong>{career_events}</strong> career events',
        f'&#128176; career <strong>{money(career_revenue)}</strong>',
        f'&#129309; <strong>{unique_clients}</strong> clients &middot; {repeat_rate}% repeat',
        f'&#128293; <strong>{current_streak}</strong>-day streak',
        f'&#127942; best month <strong class="is-word">{esc(best_month["label"])}</strong> &middot; {best_month["events"]} events',
    ]
    ticker = "".join(f'<span class="main-ticker-item">{item}</span>' for item in ticker_items * 2)

    _month_tokens = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    current_month_token = _month_tokens[date.today().month - 1]

    next_up_name = esc(upcoming_rows[0]["name"]) if upcoming_rows else "Nothing scheduled"
    next_up_when = esc(upcoming_rows[0]["when"]) if upcoming_rows else ""

    hero = (
        f'<div class="main-hero" style="--hero-accent:var(--kith-month-{current_month_token});--hero-accent-rgb:var(--kith-month-{current_month_token}-rgb);">'
        '<div class="main-hero-inner">'
        '<input type="radio" name="mainMetric" id="mainEvents" class="main-hero-radio" checked>'
        '<input type="radio" name="mainMetric" id="mainRevenue" class="main-hero-radio">'
        '<input type="radio" name="mainMetric" id="mainClients" class="main-hero-radio">'
        '<div class="main-hero-label-row">'
        '<div class="main-hero-eyebrow"><span class="main-hero-dot"></span>Career to date</div>'
        '<div class="main-hero-next-label">Next up</div>'
        '</div>'
        '<div class="main-hero-toprow">'
        '<div class="main-hero-seg">'
        '<label for="mainEvents" class="main-hero-seg-btn">Events</label>'
        '<label for="mainClients" class="main-hero-seg-btn">Clients</label>'
        '<label for="mainRevenue" class="main-hero-seg-btn">Revenue</label></div>'
        '<div class="main-hero-next">'
        f'<div class="main-hero-next-name">{next_up_name}</div>'
        f'<div class="main-hero-next-when">{next_up_when}</div>'
        '</div></div>'
        '<div class="main-hero-body">'
        f'<div class="main-hero-figure" id="mainFigEvents"><span class="main-hero-number">{career_events}</span><span class="main-hero-tag">Events</span></div>'
        f'<div class="main-hero-figure" id="mainFigRevenue"><span class="main-hero-number">{money(career_revenue)}</span><span class="main-hero-tag">Revenue</span></div>'
        f'<div class="main-hero-figure" id="mainFigClients"><span class="main-hero-number">{unique_clients}</span><span class="main-hero-tag">Clients</span></div>'
        '</div>'
        '<div class="main-hero-mini-row">'
        f'<div class="main-hero-mini"><div class="main-hero-mini-val">{best_streak}</div><div class="main-hero-mini-lab">Streak</div></div>'
        f'<div class="main-hero-mini"><div class="main-hero-mini-val">{jurisdictions}</div><div class="main-hero-mini-lab">Jurisd.</div></div>'
        f'<div class="main-hero-mini"><div class="main-hero-mini-val">{upcoming_count}</div><div class="main-hero-mini-lab">Upcoming</div></div>'
        f'<div class="main-hero-mini"><div class="main-hero-mini-val is-month">{esc(best_month["label"])}</div><div class="main-hero-mini-lab">Best Mo.</div></div>'
        '</div>'
        "</div></div>"
    )

    suits = ["\u2660", "\u2666", "\u2665", "\u2663"]
    kpis = [
        ("mk1", suits[0], "Repeat Rate", f"{repeat_rate}%", "Loyalty",
         f'{repeat_clients}', f'of {unique_clients} clients returned'),
        ("mk2", suits[1], "Jurisdictions", f'{jurisdictions}', "Widest",
         esc(territory[0]["name"]) if territory else "\u2014", f'{territory[0]["pct"]}% of all events' if territory else "no data yet"),
        ("mk3", suits[2], "Best Streak", f'{best_streak}', "Current",
         f'{current_streak} days', "consecutive working days"),
        ("mk4", suits[3], "Top Client", esc(top_client["name"]), "Booked",
         f'{top_client["events"]}', f'events &middot; {money(top_client["revenue"])}'),
    ]
    kpi_html = "".join(
        f'<div class="main-flip is-month-oct">'
        f'<input type="checkbox" id="{cid}" class="main-flip-toggle">'
        f'<label for="{cid}" class="main-flip-label"><div class="main-flip-inner">'
        f'<div class="main-flip-face main-flip-front">'
        f'<div><div class="main-kpi-label">{label}</div>'
        f'<div class="main-kpi-value{" is-text" if not str(value)[:1].isdigit() and not str(value).startswith("＄") else ""}">{value}</div></div></div>'
        f'<div class="main-flip-face main-flip-back">'
        f'<div><div class="main-kpi-back-title">{back_title}</div>'
        f'<div class="main-kpi-back-row">{back_value}<span>{back_sub}</span></div></div></div></div></label></div>'
        for cid, suit, label, value, back_title, back_value, back_sub in kpis
    )

    charts = "".join([
        chart(weekly, "events", "mainViewWeeklyEvents"),
        chart(weekly, "revenue", "mainViewWeeklyRevenue"),
        chart(monthly, "events", "mainViewMonthlyEvents"),
        chart(monthly, "revenue", "mainViewMonthlyRevenue"),
        chart(weekday, "events", "mainViewWeekdayEvents"),
        chart(weekday, "revenue", "mainViewWeekdayRevenue"),
    ])
    trends = (
        '<div class="main-section is-month-jun">'
        '<input type="checkbox" id="mainSecTrend" class="main-section-toggle" checked>'
        '<input type="radio" name="mainTrendView" id="mainTrendWeekly" class="main-lever-toggle" checked>'
        '<input type="radio" name="mainTrendView" id="mainTrendMonthly" class="main-lever-toggle">'
        '<input type="radio" name="mainTrendView" id="mainTrendWeekday" class="main-lever-toggle">'
        '<input type="radio" name="mainTrendMetric" id="mainMetEvents" class="main-lever-toggle" checked>'
        '<input type="radio" name="mainTrendMetric" id="mainMetRevenue" class="main-lever-toggle">'
        '<div class="main-section-head-row">'
        '<label for="mainSecTrend" class="main-section-head"><div class="main-section-title-group">'
        '<div class="main-section-name">Performance Trends</div></div>'
        '</label>'
        '<div class="main-trend-header-toggle">'
        '<label for="mainTrendWeekly" class="main-lever-label">Weekly</label>'
        '<label for="mainTrendMonthly" class="main-lever-label">Monthly</label>'
        '<label for="mainTrendWeekday" class="main-lever-label">Weekday</label></div>'
        '</div>'
        '<div class="main-section-body-wrap"><div class="main-section-body"><div class="main-trend-panel">'
        '<div class="main-lever-row is-metric">'
        '<label for="mainMetEvents" class="main-lever-label">Events</label>'
        '<label for="mainMetRevenue" class="main-lever-label">Revenue</label></div>'
        f'<div class="main-trend-views">{charts}</div>'
        "</div></div></div></div>"
    )

    peak_client_events = max((row["events"] for row in clients), default=0) or 1
    rank_rows = "".join(
        f'<div class="main-rank-row"><span class="main-rank-num">{index + 1}</span>'
        f'<div class="main-rank-main"><div class="main-rank-name">{esc(row["name"])}</div>'
        f'<div class="main-rank-track"><div class="main-rank-fill" style="width:{max(4, round(row["events"] / peak_client_events * 100))}%"></div></div></div>'
        f'<span class="main-rank-stat">{row["events"]}</span></div>'
        for index, row in enumerate(clients)
    )
    leaderboard = (
        '<div class="main-section">'
        '<input type="checkbox" id="mainSecClients" class="main-section-toggle">'
        '<div class="main-section-head-row"><label for="mainSecClients" class="main-section-head"><div class="main-section-title-group">'
        '<div class="main-section-name">Client Leaderboard</div>'
        f'<div class="main-section-teaser">{esc(top_client["name"])} leads at {top_client["events"]} events</div></div>'
        '</label></div>'
        '<div class="main-section-body-wrap"><div class="main-section-body">'
        f'{rank_rows}</div></div></div>'
    )

    legend = "".join(
        f'<div class="main-legend-row"><span class="main-legend-dot" style="background:{sector["color"]}"></span>'
        f'{esc(sector["name"])}<strong>{sector["pct"]}%</strong></div>'
        for sector in territory
    )
    territory_html = (
        '<div class="main-section">'
        '<input type="checkbox" id="mainSecTerritory" class="main-section-toggle">'
        '<div class="main-section-head-row"><label for="mainSecTerritory" class="main-section-head"><div class="main-section-title-group">'
        '<div class="main-section-name">Territory &amp; Jurisdictions</div>'
        f'<div class="main-section-teaser">{jurisdictions} jurisdictions'
        + (f' &middot; {esc(territory[0]["name"])} leads at {territory[0]["pct"]}%' if territory else '')
        + '</div></div>'
        '</label></div>'
        '<div class="main-section-body-wrap"><div class="main-section-body"><div class="main-donut-wrap">'
        f'<div class="main-donut" style="background:{donut}">'
        f'<div class="main-donut-core"><div class="main-donut-core-val">{career_events}</div>'
        '<div class="main-donut-core-lab">Events</div></div></div>'
        f'<div class="main-legend">{legend}</div></div></div></div></div>'
    )

    milestone_rows = "".join(
        f'<div class="main-milestone"><div class="main-milestone-head">'
        f'<span class="main-milestone-name{" is-done" if row["done"] else ""}">{esc(row["name"])}</span>'
        f'<span class="main-milestone-detail">{esc(row["detail"])}</span></div>'
        f'<div class="main-progress-track"><div class="main-progress-fill{" is-done" if row["done"] else ""}" '
        f'style="width:{max(3, min(100, row["pct"]))}%"></div></div></div>'
        for row in milestones
    )
    fame = (
        '<div class="main-section">'
        '<input type="checkbox" id="mainSecFame" class="main-section-toggle">'
        '<div class="main-section-head-row"><label for="mainSecFame" class="main-section-head"><div class="main-section-title-group">'
        '<div class="main-section-name">Hall of Fame</div>'
        f'<div class="main-section-teaser">{achieved} achieved &middot; {in_progress} in progress</div></div>'
        '</label></div>'
        f'<div class="main-section-body-wrap"><div class="main-section-body">{milestone_rows}</div></div></div>'
    )

    st.markdown(
        compact(
            f'<div class="main-ticker"><div class="main-ticker-track">{ticker}</div></div>'
            + hero
        ),
        unsafe_allow_html=True,
    )
    st.markdown(compact(trends), unsafe_allow_html=True)
    st.markdown(compact(leaderboard), unsafe_allow_html=True)
    st.markdown(compact(territory_html), unsafe_allow_html=True)
    st.markdown(compact(fame), unsafe_allow_html=True)

def render_barrister_journey(data: WorkbookData, timeline: pd.DataFrame) -> None:
    st.markdown('<div id="journeyTopAnchor"></div>', unsafe_allow_html=True)
    if timeline.empty:
        st.info("No completed service events are available for the Barrister Journey.")
        return

    chronological = timeline.sort_values("visit_number" if "visit_number" in timeline else "event_number").copy()
    completed_visits = len(chronological)
    unique_clients = chronological.get("client", pd.Series(dtype=object)).dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
    jurisdictions = (
        chronological.get("state_region", chronological.get("region_code", pd.Series("", index=chronological.index)))
        .map(jurisdiction_group)
        .replace("", pd.NA)
        .dropna()
        .nunique()
    )
    financial = financial_frame(data)
    known_revenue = 0.0
    if not financial.empty and "has_revenue" in financial and "revenue_amount" in financial:
        known_revenue = float(pd.to_numeric(financial.loc[financial["has_revenue"], "revenue_amount"], errors="coerce").fillna(0).sum())

    seen_states = set()
    seen_clients = set()
    seen_milestones = set()
    pieces = [
        f'<div id="journeyTrack" class="journey-track" data-completed-visits="{escape(str(completed_visits))}" '
        f'data-unique-clients="{escape(str(unique_clients))}" data-jurisdictions="{escape(str(jurisdictions))}" '
        f'data-known-revenue="{escape(format_currency(known_revenue))}">'
        '<button id="journeyReplayCar" class="journey-replay-car" type="button" aria-label="Pause or resume career replay"><span class="journey-car-icon">🏎️</span><span id="journeyAchievementBadge" class="journey-achievement-badge">+CLIENT</span></button>'
        '<div id="journeyReplaySummary" class="journey-replay-summary" aria-live="polite"></div>'
        '<div class="journey-start"><span>START \U0001F3C1</span><div class="journey-start-actions"><button id="journeyFuelButton" class="journey-fuel-button" type="button" aria-label="Start or restart career replay" title="Start or restart career replay">\u26fd</button></div></div>' 
    ]
    for row in chronological.to_dict("records"):
        state_key = jurisdiction_group(row.get("state_region", row.get("region_code", "")))
        if state_key not in seen_states:
            seen_states.add(state_key)
            pieces.append(f'<div class="journey-checkpoint">🏁 {escape(state_debut_label(row))}</div>')

        for milestone in career_milestones_for_row(row):
            if milestone not in seen_milestones:
                seen_milestones.add(milestone)
                pieces.append(f'<div class="journey-milestone">🏆 {escape(milestone)}</div>')

        number = row.get("visit_number", row.get("event_number", ""))
        number = int(number) if isinstance(number, float) and number.is_integer() else number
        status = str(row.get("status", "") or "Completed").strip()
        client = str(row.get("client", "Unnamed client") or "Unnamed client").strip()
        client_key = client.casefold()
        is_new_client = client_key not in seen_clients
        location = ", ".join(str(value) for value in [row.get("city", ""), row.get("region_code", "")] if str(value).strip())
        event_date = row.get("event_date")
        date_label = pd.Timestamp(event_date).strftime("%b %d, %Y") if pd.notna(event_date) else ""
        date_markup = f'<div class="journey-date">{escape(date_label)}</div>' if date_label else ""
        month_var_map = {1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun", 7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec"}
        month_token = month_var_map.get(pd.Timestamp(event_date).month, "apr") if pd.notna(event_date) else "apr"
        month_accent = f"var(--kith-month-{month_token})"
        month_accent_rgb = f"var(--kith-month-{month_token}-rgb)"
        stop_accent = JURISDICTION_COLORS.get(state_key, JURISDICTION_COLORS["Pennsylvania / Other"])
        pieces.append(
            '<div class="journey-stop" '
            f'style="--stop-accent:{escape(stop_accent, quote=True)};--month-accent:{escape(month_accent, quote=True)};--month-accent-rgb:{escape(month_accent_rgb, quote=True)}" '
            f'data-visit="{escape(str(number))}" data-client="{escape(client, quote=True)}" '
            f'data-location="{escape(location or "Location not provided", quote=True)}" '
            f'data-new-client="{"1" if is_new_client else "0"}">'
            f'<div class="journey-number">#{escape(str(number))}</div>'
            '<div class="journey-content">'
            '<div class="journey-left-stack">'
            f'<div class="journey-client">{escape(client)}</div>'
            f'<div class="journey-location">{escape(location or "Location not provided")}</div>'
            '</div>'
            f'<div class="journey-right-meta"><span class="journey-status">{escape(status)}</span>{date_markup}</div>'
            '</div></div>'
        )
        seen_clients.add(client_key)
        for milestone in career_milestones_after_row(row):
            if milestone not in seen_milestones:
                seen_milestones.add(milestone)
                pieces.append(f'<div class="journey-milestone">🏆 {escape(milestone)}</div>')

    pieces.append(
        '<div id="journeyFinishLine" class="journey-finish-line"><span>🏁 FINISH LINE</span><button id="journeyTopButton" class="journey-top-button" type="button" title="Back to top">🏆</button></div></div>'
    )
    st.markdown("".join(pieces), unsafe_allow_html=True)
    render_journey_replay_script()


def render_journey_replay_script() -> None:
    components.html(
        """
        <script>
        (function () {
            const doc = window.parent.document;
            const win = window.parent;

            function initReplay() {
                const replayVersion = "continuous-follow-v3";
                let fuel = doc.getElementById("journeyFuelButton");
                const track = doc.getElementById("journeyTrack");
                let car = doc.getElementById("journeyReplayCar");
                let badge = doc.getElementById("journeyAchievementBadge");
                const summary = doc.getElementById("journeyReplaySummary");
                const finishLine = doc.getElementById("journeyFinishLine");

                function bindDirectNavigation(selector, destination) {
                    const element = doc.querySelector(selector);
                    if (!element) {
                        return;
                    }
                    if (element.dataset.directNavigationBound === "1") {
                        return;
                    }
                    element.dataset.directNavigationBound = "1";
                    element.addEventListener("click", function(event) {
                        event.preventDefault();
                        event.stopPropagation();
                        try {
                            window.top.location.assign(destination);
                        } catch (error) {
                            win.location.assign(destination);
                        }
                    }, true);
                }

                bindDirectNavigation(
                    '[aria-label="Open Bronx Bombers Daily"]',
                    "http://100.70.235.51:8000/"
                );
                bindDirectNavigation(
                    '[aria-label="Open Heroes and Muses"]',
                    "http://100.70.235.51:8011"
                );
                bindDirectNavigation(
                    '[aria-label="Open Showcase"]',
                    "http://100.70.235.51:9000"
                );

                const journeyTopButton = doc.getElementById("journeyTopButton");
                if (journeyTopButton) {
                    journeyTopButton.addEventListener("click", function(event) {
                        event.preventDefault();
                        try {
                            window.parent.scrollTo({top: 0, behavior: "smooth"});
                        } catch (e) {
                            window.scrollTo({top: 0, behavior: "smooth"});
                        }
                    });
                }


                const topButton = doc.querySelector(".journey-top-button");
                if (topButton) {
                    topButton.addEventListener("click", function(event) {
                        event.preventDefault();
                        try {
                            window.parent.scrollTo({top: 0, behavior: "smooth"});
                        } catch (e) {
                            window.scrollTo({top: 0, behavior: "smooth"});
                        }
                    });
                }

                if (!fuel || !track || !car || !badge) {
                    return;
                }
                if (fuel.dataset.replayBound === replayVersion) {
                    return;
                }
                if (fuel.dataset.replayBound) {
                    const freshFuel = fuel.cloneNode(true);
                    const freshCar = car.cloneNode(true);
                    fuel.replaceWith(freshFuel);
                    car.replaceWith(freshCar);
                    fuel = freshFuel;
                    car = freshCar;
                    badge = doc.getElementById("journeyAchievementBadge");
                    if (!badge) {
                        return;
                    }
                }
                fuel.dataset.replayBound = replayVersion;

                let running = false;
                let paused = false;
                let sequenceId = 0;
                let speedIndex = 0;
                let replayY = 0;
                let lastFrame = 0;
                let nextStopIndex = 0;
                let animationFrame = null;
                let activeScroller = null;
                let previousScrollerOverflow = "";
                const speedLevels = [1.00, 1.70, 2.50, 0.00];
                const basePixelsPerSecond = 145;

                function stops() {
                    return Array.from(doc.querySelectorAll(".journey-stop[data-visit]"));
                }

                function clearCelebrations() {
                    stops().forEach((stop) => stop.classList.remove("new-client-celebration"));
                    badge.classList.remove("is-visible");
                }

                function yFor(element) {
                    return element.offsetTop + element.offsetHeight / 2;
                }

                function replayScroller() {
                    if (activeScroller && doc.contains(activeScroller)) {
                        return activeScroller;
                    }
                    activeScroller = doc.querySelector('[data-testid="stMain"]') || doc.scrollingElement || doc.documentElement;
                    return activeScroller;
                }

                function scrollerTop(scroller) {
                    return scroller === doc.scrollingElement || scroller === doc.documentElement || scroller === doc.body
                        ? (win.scrollY || doc.documentElement.scrollTop || doc.body.scrollTop || 0)
                        : scroller.scrollTop;
                }

                function setScrollerTop(scroller, top) {
                    if (scroller === doc.scrollingElement || scroller === doc.documentElement || scroller === doc.body) {
                        win.scrollTo({ top, behavior: "auto" });
                    } else {
                        scroller.scrollTo({ top, behavior: "auto" });
                    }
                }

                function celebrateNewClient(stop, id) {
                    stop.classList.remove("new-client-celebration");
                    void stop.offsetWidth;
                    stop.classList.add("new-client-celebration");
                    badge.textContent = `+CLIENT #${stop.dataset.visit || ""}`.trim();
                    badge.classList.add("is-visible");
                    win.setTimeout(() => {
                        if (id === sequenceId) {
                            badge.classList.remove("is-visible");
                        }
                    }, 1050);
                }

                function showSummary() {
                    summary.innerHTML = `
                        <div class="journey-summary-grid">
                            <div class="journey-summary-stat"><div class="journey-summary-value">${track.dataset.completedVisits || "0"}</div><div class="journey-summary-label">Completed Visits</div></div>
                            <div class="journey-summary-stat"><div class="journey-summary-value">${track.dataset.uniqueClients || "0"}</div><div class="journey-summary-label">Unique Clients</div></div>
                            <div class="journey-summary-stat"><div class="journey-summary-value">${track.dataset.jurisdictions || "0"}</div><div class="journey-summary-label">Jurisdictions</div></div>
                            <div class="journey-summary-stat"><div class="journey-summary-value">${track.dataset.knownRevenue || "$0"}</div><div class="journey-summary-label">Known Revenue</div></div>
                        </div>
                    `;
                    summary.classList.add("is-visible");
                }

                function scrollWithCar() {
                    const scroller = replayScroller();
                    const trackRect = track.getBoundingClientRect();
                    const scrollerRect = scroller.getBoundingClientRect ? scroller.getBoundingClientRect() : { top: 0, height: win.innerHeight };
                    const current = scrollerTop(scroller);
                    const absoluteCarY = current + (trackRect.top - scrollerRect.top) + replayY;
                    const viewportHeight = scroller.clientHeight || win.innerHeight;
                    const desired = absoluteCarY - viewportHeight * 0.5;
                    const maxScroll = Math.max(0, scroller.scrollHeight - viewportHeight);
                    const target = Math.max(0, Math.min(desired, maxScroll));
                    const next = current + (target - current) * 0.55;
                    setScrollerTop(scroller, next);
                }

                function renderCar() {
                    car.style.top = replayY + "px";
                    scrollWithCar();
                }

                function hideOverlays() {
                    summary.classList.remove("is-visible");
                    if (finishLine) {
                        finishLine.classList.remove("is-visible");
                    }
                    clearCelebrations();
                }

                function resetReplay() {
                    sequenceId += 1;
                    running = false;
                    paused = false;
                    doc.body.style.overflow = "";
                    doc.documentElement.style.overflow = "";
                    if (activeScroller) {
                        activeScroller.style.overflowY = previousScrollerOverflow;
                    }
                    track.classList.remove("replay-active");
                    car.style.transitionDuration = "0ms";
                    car.style.opacity = "0";
                    if (animationFrame) {
                        win.clearTimeout(animationFrame);
                        animationFrame = null;
                    }
                    hideOverlays();
                }


                function setJourneyBoostSmoke(active) {
                    const candidates = [
                        doc.getElementById("journeyReplayCar"),
                        doc.getElementById("journeyCar"),
                        doc.querySelector(".journey-replay-car"),
                        doc.querySelector(".journey-car")
                    ].filter(Boolean);
                    candidates.forEach((el) => el.classList.toggle("is-boosting", !!active));
                }

                function animateReplay(now, id, replayStops, finishY) {
                    if (!running || id !== sequenceId) {
                        return;
                    }
                    if (!lastFrame) {
                        lastFrame = now;
                    }
                    const elapsed = Math.min(48, now - lastFrame);
                    lastFrame = now;
                    if (!paused) {
                        setJourneyBoostSmoke(speedLevels[speedIndex] >= 2.50);
                        replayY = Math.min(finishY, replayY + (basePixelsPerSecond * speedLevels[speedIndex] * elapsed / 1000));
                        renderCar();
                        while (nextStopIndex < replayStops.length && replayY >= yFor(replayStops[nextStopIndex])) {
                            const stop = replayStops[nextStopIndex];
                            if (stop.dataset.newClient === "1") {
                                celebrateNewClient(stop, id);
                            }
                            nextStopIndex += 1;
                        }
                        if (replayY >= finishY) {
                            setJourneyBoostSmoke(false);
                            if (finishLine) {
                                finishLine.classList.add("is-visible");
                            }
                            showSummary();
                            running = false;
                            animationFrame = null;
                            return;
                        }
                    }
                    animationFrame = win.setTimeout(() => animateReplay(Date.now(), id, replayStops, finishY), 16);
                }

                function startReplay() {
                    const replayStops = stops();
                    if (!replayStops.length) {
                        return;
                    }
                    resetReplay();
                    const id = sequenceId + 1;
                    sequenceId = id;
                    running = true;
                    paused = false;
                    doc.body.style.overflow = "";
                    doc.documentElement.style.overflow = "";
                    activeScroller = replayScroller();
                    previousScrollerOverflow = activeScroller.style.overflowY || "";
                    activeScroller.style.overflowY = previousScrollerOverflow;
                    hideOverlays();
                    track.classList.add("replay-active");

                    const start = doc.querySelector(".journey-start") || replayStops[0];
                    const finishTarget = finishLine || replayStops[replayStops.length - 1];
                    car.style.transitionDuration = "0ms";
                    car.style.opacity = "1";
                    speedIndex = 0;
                    nextStopIndex = 0;
                    replayY = yFor(start);
                    lastFrame = 0;
                    renderCar();
                    animationFrame = win.setTimeout(() => animateReplay(Date.now(), id, replayStops, yFor(finishTarget)), 16);
                }

                function cycleReplaySpeed() {
                    if (!running) {
                        return;
                    }
                    speedIndex = (speedIndex + 1) % speedLevels.length;
                }

                function togglePause() {
                    if (!running) return;
                    paused = !paused;
                    doc.body.style.overflow = paused ? "hidden" : "";
                    doc.documentElement.style.overflow = paused ? "hidden" : "";
                    const scroller = replayScroller();
                    scroller.style.overflowY = paused ? "hidden" : previousScrollerOverflow;
                }

                fuel.addEventListener("click", startReplay);
                let holdTimer = null;
                let holdTriggered = false;
                car.addEventListener("pointerdown", () => {
                    holdTriggered = false;
                    holdTimer = win.setTimeout(() => {
                        holdTriggered = true;
                        togglePause();
                    }, 420);
                });
                car.addEventListener("pointerup", () => {
                    if (holdTimer) {
                        win.clearTimeout(holdTimer);
                        holdTimer = null;
                    }
                });
                car.addEventListener("pointerleave", () => {
                    if (holdTimer) {
                        win.clearTimeout(holdTimer);
                        holdTimer = null;
                    }
                });
                car.addEventListener("click", () => {
                    if (holdTriggered) {
                        holdTriggered = false;
                        return;
                    }
                    cycleReplaySpeed();
                });
            }

            if (doc.readyState === "loading") {
                doc.addEventListener("DOMContentLoaded", initReplay, { once: true });
            } else {
                setTimeout(initReplay, 150);
            }
        })();
        </script>
        """,
        height=0,
    )


def client_directory_frame(data: WorkbookData) -> pd.DataFrame:
    clients = data.clients.copy()
    chronology = completed_chronology(data)
    if chronology.empty:
        base = clients[["client"]].copy() if "client" in clients else pd.DataFrame(columns=["client"])
        base["# of Visits"] = 0
        base["# of Locations"] = 0
        base["1st Visit"] = ""
        base["Latest Visit"] = ""
        return base.rename(columns={"client": "Client"})

    chronology = chronology.copy()
    chronology["location_key"] = (
        chronology.get("city", pd.Series("", index=chronology.index)).fillna("").astype(str).str.strip()
        + "|"
        + chronology.get("region_code", pd.Series("", index=chronology.index)).fillna("").astype(str).str.strip()
    )
    activity = (
        chronology.groupby("client")
        .agg(
            visits=("visit_number", "count"),
            locations=("location_key", lambda values: values.replace("", pd.NA).dropna().nunique()),
            first_visit=("visit_number", "min"),
            latest_visit=("visit_number", "max"),
        )
        .reset_index()
    )

    if "client" in clients:
        directory = clients[["client"]].drop_duplicates().merge(activity, on="client", how="left")
    else:
        directory = activity
    directory[["visits", "locations", "first_visit", "latest_visit"]] = directory[
        ["visits", "locations", "first_visit", "latest_visit"]
    ].fillna(0)
    directory = directory.sort_values(["visits", "first_visit", "client"], ascending=[False, True, True])
    directory = directory.rename(
        columns={
            "client": "Client",
            "visits": "# of Visits",
            "locations": "# of Locations",
            "first_visit": "1st Visit",
            "latest_visit": "Latest Visit",
        }
    )
    for column in ["# of Visits", "# of Locations", "1st Visit", "Latest Visit"]:
        directory[column] = directory[column].astype(int)
    return directory[["Client", "# of Visits", "# of Locations", "1st Visit", "Latest Visit"]]


def place_label(rank: int) -> str:
    if rank == 1:
        return "🥇 First Place"
    if rank == 2:
        return "🥈 Second Place"
    if rank == 3:
        return "🥉 Third Place"
    suffix = "th"
    if rank % 100 not in {11, 12, 13}:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"P{rank} · {rank}{suffix} Place"


def pluralize(count: int, singular: str) -> str:
    return f"{count:,} {singular}" if count == 1 else f"{count:,} {singular}s"


def page_url(page_slug: str, **params: str) -> str:
    query = [f"page={quote(page_slug)}"]
    for key, value in params.items():
        if value not in (None, ""):
            query.append(f"{quote(key)}={quote(str(value))}")
    return "?" + "&".join(query)


def selected_client_query() -> str:
    value = st.query_params.get("client", "")
    return unquote(str(value)).strip()


def client_profile_url(page_slug: str, client: str) -> str:
    return page_url(page_slug, client=client)


def client_location_label(row: pd.Series | dict) -> str:
    city = str(row.get("city", "") or "").strip()
    region = str(row.get("region_code", "") or "").strip()
    return f"{city}, {region}".strip(", ") if city or region else "Location unavailable"


def client_profile_frame(data: WorkbookData, client: str) -> pd.DataFrame:
    chronology = completed_chronology(data)
    if chronology.empty:
        return chronology
    return chronology[chronology["client"].fillna("").astype(str).str.casefold().eq(client.casefold())].copy()


def client_revenue_rollup(data: WorkbookData, client: str) -> tuple[float | None, float | None]:
    rollup = financial_client_rollup(financial_frame(data))
    if rollup.empty:
        return None, None
    match = rollup[rollup["client"].fillna("").astype(str).str.casefold().eq(client.casefold())]
    if match.empty:
        return None, None
    row = match.iloc[0]
    return float(row["total_revenue"]), float(row["avg_revenue"])


def client_visit_revenue_values(data: WorkbookData, client: str, visits: pd.DataFrame) -> list[float | None]:
    attribution = REVENUE_ATTRIBUTION_BREAKDOWNS.get(client)
    if attribution and len(attribution) == len(visits):
        return [float(value) for value in attribution]
    financial = financial_frame(data)
    if financial.empty:
        return [None] * len(visits)
    matching = financial[financial["client"].fillna("").astype(str).str.casefold().eq(client.casefold())].sort_values("visit_number")
    values = pd.to_numeric(matching.get("revenue_amount", pd.Series(dtype=float)), errors="coerce").tolist()
    result: list[float | None] = []
    for value in values[: len(visits)]:
        result.append(float(value) if pd.notna(value) else None)
    result.extend([None] * (len(visits) - len(result)))
    return result


def render_client_profile(data: WorkbookData, client: str, back_slug: str) -> None:
    visits = client_profile_frame(data, client)
    if visits.empty:
        st.warning(f"No completed visits were found for {client}.")
        return

    visits = visits.sort_values("visit_number").reset_index(drop=True)
    canonical_client = str(visits.iloc[0]["client"])
    total_revenue, avg_revenue = client_revenue_rollup(data, canonical_client)
    locations = sorted({client_location_label(row) for _, row in visits.iterrows() if client_location_label(row) != "Location unavailable"})
    states = sorted({str(value).strip() for value in visits.get("state_region", pd.Series(dtype=str)).dropna() if str(value).strip()})
    numbers = pd.to_numeric(visits["visit_number"], errors="coerce").dropna().astype(int)
    first_visit = int(numbers.min()) if not numbers.empty else 0
    latest_visit = int(numbers.max()) if not numbers.empty else 0
    dates = visits.get("event_date", pd.Series(pd.NaT, index=visits.index)).map(scheduled_date_label)
    available_dates = [value for value in dates.tolist() if value and value != "No Date"]
    revenue_values = client_visit_revenue_values(data, canonical_client, visits)

    profile_metrics = [
        ("Completed Visits", len(visits)),
        ("Total Revenue", format_currency(total_revenue) if total_revenue is not None else "Incomplete"),
        ("Avg / Visit", format_currency_precise(avg_revenue) if avg_revenue is not None else "Incomplete"),
        ("Locations", len(locations)),
    ]
    metric_markup = "".join(
        '<div class="profile-metric">'
        f'<div class="profile-metric-value">{escape(str(value))}</div>'
        f'<div class="profile-metric-label">{escape(label)}</div>'
        '</div>'
        for label, value in profile_metrics
    )
    details = [
        ("States / Jurisdictions", ", ".join(states) if states else "Unavailable"),
        ("First Visit", f"#{first_visit}" if first_visit else "Unavailable"),
        ("Most Recent Visit", f"#{latest_visit}" if latest_visit else "Unavailable"),
        ("Date Range", f"{available_dates[0]} → {available_dates[-1]}" if available_dates else "Date unavailable"),
    ]
    detail_markup = "".join(
        '<div class="profile-detail">'
        f'<div class="profile-detail-label">{escape(label)}</div>'
        f'<div class="profile-detail-value">{escape(value)}</div>'
        '</div>'
        for label, value in details
    )
    visit_cards = []
    for index, (_, row) in enumerate(visits.iterrows()):
        visit_number = int(row.get("visit_number", 0) or 0)
        location = client_location_label(row)
        notes = str(row.get("notes", "") or "").strip()
        amount = revenue_values[index] if index < len(revenue_values) else None
        visit_cards.append(
            '<div class="profile-visit">'
            f'<div class="profile-visit-number">#{visit_number}</div>'
            '<div class="profile-visit-main">'
            f'<div class="profile-visit-location">{escape(location)}</div>'
            f'<div class="profile-visit-notes">{escape(notes or "No notes available")}</div>'
            '</div>'
            f'<div class="profile-visit-money">{escape(format_currency(amount) if amount is not None else "Revenue pending")}</div>'
            '</div>'
        )

    st.markdown(
        '<div class="client-profile">'
        '<div class="profile-top">'
        f'<div class="profile-title">{escape(canonical_client)}</div>'
        f'<a class="profile-back" href="?page={escape(back_slug)}" target="_self">Close profile</a>'
        '</div>'
        f'<div class="profile-metrics">{metric_markup}</div>'
        f'<div class="profile-detail-grid">{detail_markup}</div>'
        '<div class="section-title">COMPLETED VISITS</div>'
        f'<div class="profile-visit-list">{"".join(visit_cards)}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_client_standings(directory: pd.DataFrame) -> None:
    standings = directory[directory["# of Visits"].gt(0)].copy()
    if standings.empty:
        st.info("No completed client visits are available for standings.")
        return

    logo_files, _ = discover_logos(LOGOS_DIR)
    max_visits = max(int(standings["# of Visits"].max()), 1)
    rows = []
    for rank, row in enumerate(standings.to_dict("records"), start=1):
        client = str(row["Client"])
        visits = int(row["# of Visits"])
        width = max(8, round(visits / max_visits * 100, 1))
        podium_class = " podium" if rank <= 3 else ""
        rows.append(
            f'<a class="client-link standing-row{podium_class}" href="{client_profile_url("client-analytics", client)}" target="_self">'
            f'<div class="standing-rank">{escape(place_label(rank))}</div>'
            '<div class="standing-main">'
            '<div class="standing-client-line">'
            f'{client_logo_markup(client, logo_files)}'
            f'<div class="standing-client">{escape(client)}</div>'
            '</div>'
            f'<div class="standing-track"><div class="standing-fill" style="width: {width}%"></div></div>'
            '</div>'
            f'<div class="standing-visits">{visits} VISITS</div>'
            '</a>'
        )

    st.markdown(
        '<div class="section-kicker">2026 SEASON STANDINGS</div>'
        '<div class="section-title">CLIENT STANDINGS</div>'
        f'<div class="standings-board">{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


def career_record_cards(data: WorkbookData, directory: pd.DataFrame) -> list[dict[str, str]]:
    active = directory[directory["# of Visits"].gt(0)].copy()
    if active.empty:
        return []

    most_visits = active.sort_values(["# of Visits", "1st Visit", "Client"], ascending=[False, True, True]).iloc[0]
    most_locations = active.sort_values(["# of Locations", "# of Visits", "Client"], ascending=[False, False, True]).iloc[0]

    chronology = completed_chronology(data)
    fastest_client = "N/A"
    fastest_value = "No recent activity"
    if not chronology.empty:
        recent_count = min(10, len(chronology))
        recent = chronology.sort_values("visit_number").tail(recent_count)
        recent_activity = (
            recent.groupby("client")
            .agg(recent_visits=("visit_number", "count"), latest_visit=("visit_number", "max"))
            .reset_index()
            .sort_values(["recent_visits", "latest_visit", "client"], ascending=[False, False, True])
        )
        if not recent_activity.empty:
            fastest = recent_activity.iloc[0]
            fastest_client = str(fastest["client"])
            fastest_value = f'{int(fastest["recent_visits"])} of last {recent_count} visits'

    newest = active.sort_values(["1st Visit", "Latest Visit", "Client"], ascending=[False, False, True]).iloc[0]
    records = [
        {
            "label": "🏆 Most Visits",
            "client": str(most_visits["Client"]),
            "value": pluralize(int(most_visits["# of Visits"]), "Visit"),
        },
        {
            "label": "🌎 Most Locations",
            "client": str(most_locations["Client"]),
            "value": pluralize(int(most_locations["# of Locations"]), "Location"),
        },
        {
            "label": "🚀 Fastest Growing Client",
            "client": fastest_client,
            "value": fastest_value,
        },
        {
            "label": "📍 Most Recent New Client",
            "client": str(newest["Client"]),
            "value": f'First appeared at Visit #{int(newest["1st Visit"])}',
        },
    ]
    return records


def render_client_podium(directory: pd.DataFrame) -> None:
    standings = directory[directory["# of Visits"].gt(0)].sort_values(
        ["# of Visits", "1st Visit", "Client"], ascending=[False, True, True]
    ).reset_index(drop=True)
    if standings.empty:
        return
    logo_files, _ = discover_logos(LOGOS_DIR)
    medals = ["🥇", "🥈", "🥉"]
    order = [1, 0, 2]
    top = standings.head(3).to_dict("records")
    if len(top) < 3:
        order = list(range(len(top)))
    blocks = []
    for position in order:
        row = top[position]
        client = str(row["Client"])
        visits = int(row["# of Visits"])
        height = 78 + (3 - position) * 30
        blocks.append(
            '<div class="champ-step">'
            f'<div class="champ-medal">{medals[position]}</div>'
            f'{client_logo_markup(client, logo_files, "client-logo-badge champ-logo-badge")}'
            f'<div class="champ-name" title="{escape(client, quote=True)}">{escape(client_card_display_name(client))}</div>'
            f'<div class="champ-value">{escape(pluralize(visits, "Visit"))}</div>'
            f'<div class="champ-block" style="height:{height}px"></div>'
            '</div>'
        )
    st.markdown(
        '<div class="section-kicker">TOP OF THE LEADERBOARD</div>'
        '<div class="section-title">PODIUM</div>'
        f'<div class="champ-podium client-champ-podium">{"".join(blocks)}</div>',
        unsafe_allow_html=True,
    )


def render_career_records(data: WorkbookData, directory: pd.DataFrame) -> None:
    records = career_record_cards(data, directory)
    if not records:
        return
    logo_files, _ = discover_logos(LOGOS_DIR)
    accents = ["#2dd4bf", "#f5c542", "#fb7185", "#5c8ee8"]
    cards = []
    for index, record in enumerate(records):
        accent = accents[index % len(accents)]
        icon_markup = client_logo_markup(record["client"], logo_files, "client-logo-badge mini-tile-icon")
        cards.append(
            f'<div class="record-card" style="--record-accent:{accent}">'
            f'<div class="record-label">{escape(record["label"])}</div>'
            '<div class="record-icon-line">'
            f'{icon_markup}'
            f'<div class="record-client-text">{escape(record["client"])}</div>'
            '</div>'
            f'<div class="record-value">{escape(record["value"])}</div>'
            '</div>'
        )
    st.markdown(
        '<div class="section-title">CAREER RECORDS</div>'
        f'<div class="records-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def revenue_series(values: pd.Series) -> pd.Series:
    if values.empty:
        return pd.Series(dtype=float)
    if pd.api.types.is_numeric_dtype(values):
        return pd.to_numeric(values, errors="coerce")
    cleaned = (
        values.fillna("")
        .astype(str)
        .str.strip()
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        .str.replace(r"[\$,]", "", regex=True)
        .str.replace(r"[^0-9.\-]", "", regex=True)
    )
    cleaned = cleaned.mask(cleaned.eq(""))
    return pd.to_numeric(cleaned, errors="coerce")


def format_currency(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "Incomplete"
    if math.isnan(amount):
        return "Incomplete"
    return f"＄{amount:,.0f}"


def format_currency_precise(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "Incomplete"
    if math.isnan(amount):
        return "Incomplete"
    return f"＄{amount:,.2f}"


def format_percent(value: float) -> str:
    return f"{value:.1f}%"


def authoritative_month_label(visit_number: object, event_date: object = None) -> str:
    timestamp = pd.to_datetime(event_date, errors="coerce")
    if pd.notna(timestamp):
        return timestamp.strftime("%b %Y")
    try:
        number = int(float(visit_number))
    except (TypeError, ValueError):
        return "Unknown"
    if 1 <= number <= 9:
        return "Apr 2026"
    if 10 <= number <= 26:
        return "May 2026"
    if number >= 27:
        return "Jun 2026"
    return "Unknown"


def authoritative_month_order(label: str) -> int:
    try:
        parsed = pd.to_datetime(str(label), format="%b %Y")
        return parsed.year * 12 + parsed.month
    except (ValueError, TypeError):
        return 99


def financial_frame(data: WorkbookData) -> pd.DataFrame:
    """Build Finance from current_master.xlsx Service Events."""
    source = Path(__file__).resolve().parent / "data" / "current_master.xlsx"
    output_columns = [
        "visit_number", "event_date", "client", "revenue",
        "revenue_amount", "has_revenue", "city", "region_code",
        "state_region", "status", "location", "date_label",
        "month_label", "month_order",
    ]
    if not source.is_file():
        return pd.DataFrame(columns=output_columns)
    try:
        service_events = pd.read_excel(source, sheet_name="Service Events")
    except (OSError, ValueError, ImportError):
        return pd.DataFrame(columns=output_columns)
    if service_events.empty:
        return pd.DataFrame(columns=output_columns)

    def normalize(value: object) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value).casefold())

    lookup = {normalize(column): column for column in service_events.columns}

    def find_column(*aliases: str) -> str | None:
        for alias in aliases:
            column = lookup.get(normalize(alias))
            if column is not None:
                return column
        return None

    event_col = find_column("Event #", "Event Number", "Visit #", "event_number")
    date_col = find_column("Service Date", "Event Date", "Visit Date", "Date")
    client_col = find_column("Client", "Client Name")
    revenue_col = find_column("Confirmed Revenue", "Revenue", "Confirmed Amount", "Amount")
    city_col = find_column("City")
    state_col = find_column("Jurisdiction", "State", "State/Region", "Region Code")
    status_col = find_column("Status")

    if event_col is None or client_col is None or revenue_col is None:
        return pd.DataFrame(columns=output_columns)

    frame = pd.DataFrame(index=service_events.index)
    frame["visit_number"] = pd.to_numeric(service_events[event_col], errors="coerce")
    frame["event_date"] = (
        pd.to_datetime(service_events[date_col], errors="coerce")
        if date_col is not None else pd.NaT
    )
    frame["client"] = service_events[client_col].fillna("").astype(str).str.strip()
    frame["revenue_amount"] = revenue_series(service_events[revenue_col])
    frame["revenue"] = frame["revenue_amount"]
    frame["city"] = (
        service_events[city_col].fillna("").astype(str).str.strip()
        if city_col is not None else ""
    )
    frame["region_code"] = (
        service_events[state_col].fillna("").astype(str).str.strip()
        if state_col is not None else ""
    )
    frame["state_region"] = frame["region_code"]
    frame["status"] = (
        service_events[status_col].fillna("Completed").astype(str).str.strip()
        if status_col is not None else "Completed"
    )
    frame = frame[frame["status"].str.casefold().eq("completed")].copy()
    frame["has_revenue"] = pd.to_numeric(frame["revenue_amount"], errors="coerce").notna()
    frame["location"] = (
        frame["city"].fillna("").astype(str).str.strip()
        + ", "
        + frame["region_code"].fillna("").astype(str).str.strip()
    ).str.strip(", ")
    frame["date_label"] = frame["event_date"].map(scheduled_date_label)
    frame["month_label"] = frame.apply(
        lambda row: authoritative_month_label(row.get("visit_number"), row.get("event_date")),
        axis=1,
    )
    frame["month_order"] = frame["month_label"].map(authoritative_month_order)
    return frame.reset_index(drop=True)


def financial_client_rollup(financial: pd.DataFrame) -> pd.DataFrame:
    if financial.empty:
        return pd.DataFrame(columns=["client", "visits", "total_revenue", "avg_revenue"])
    revenue_rows = financial[financial["has_revenue"]].copy()
    if revenue_rows.empty:
        return pd.DataFrame(columns=["client", "visits", "total_revenue", "avg_revenue"])
    visits = financial.groupby("client").size().rename("visits")
    totals = revenue_rows.groupby("client")["revenue_amount"].sum().rename("total_revenue")
    rollup = pd.concat([visits, totals], axis=1).dropna(subset=["total_revenue"]).reset_index()
    rollup["visits"] = rollup["visits"].astype(int)
    rollup["avg_revenue"] = rollup["total_revenue"].astype(float).div(rollup["visits"].replace(0, pd.NA))
    return rollup


def financial_state_summary(financial: pd.DataFrame) -> pd.DataFrame:
    columns = ["state_region", "total_revenue", "completed_visits", "percent", "avg_revenue"]
    if financial.empty or "has_revenue" not in financial:
        return pd.DataFrame(columns=columns)
    known_revenue = financial[financial["has_revenue"]].copy()
    if known_revenue.empty:
        return pd.DataFrame(columns=columns)
    state_totals = (
        known_revenue.groupby("state_region", dropna=False)["revenue_amount"].sum()
        .rename("total_revenue")
        .reset_index()
        .sort_values("total_revenue", ascending=False)
    )
    state_visits = financial.groupby("state_region", dropna=False).size().rename("completed_visits")
    revenue_total = float(state_totals["total_revenue"].sum())
    state_totals["completed_visits"] = state_totals["state_region"].map(state_visits).fillna(0).astype(int)
    state_totals["percent"] = state_totals["total_revenue"].astype(float).div(revenue_total).mul(100) if revenue_total else 0.0
    state_totals["avg_revenue"] = state_totals["total_revenue"].astype(float).div(state_totals["completed_visits"].replace(0, pd.NA))
    return state_totals[columns]


def financial_month_summary(financial: pd.DataFrame) -> pd.DataFrame:
    columns = ["month_label", "month_order", "total_revenue", "percent", "rank"]
    if financial.empty or "has_revenue" not in financial:
        return pd.DataFrame(columns=columns)
    known_revenue = financial[financial["has_revenue"]].copy()
    dated_revenue = known_revenue[known_revenue["month_label"].ne("Unknown")].copy() if "month_label" in known_revenue else pd.DataFrame()
    if dated_revenue.empty:
        return pd.DataFrame(columns=columns)
    monthly = (
        dated_revenue.groupby(["month_label", "month_order"])["revenue_amount"].sum()
        .rename("total_revenue")
        .reset_index()
    )
    month_total = float(monthly["total_revenue"].sum())
    monthly["percent"] = monthly["total_revenue"].astype(float).div(month_total).mul(100) if month_total else 0.0
    monthly = monthly.sort_values("total_revenue", ascending=False).reset_index(drop=True)
    monthly["rank"] = range(1, len(monthly) + 1)
    return monthly[columns]


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def road_warrior_record(data: WorkbookData) -> tuple[str, str]:
    try:
        locations = load_locations(LOCATIONS_PATH)
        matches = match_timeline_locations(completed_chronology(data), locations).successful_matches
    except (OSError, ValueError):
        return "Future metric", "Distance data pending"
    if matches.empty or not {"client", "latitude", "longitude"}.issubset(matches.columns):
        return "Future metric", "Distance data pending"

    origin_lat, origin_lon = 38.9072, -77.0369
    mapped = matches.copy()
    mapped["distance_miles"] = mapped.apply(
        lambda row: haversine_miles(origin_lat, origin_lon, float(row["latitude"]), float(row["longitude"])),
        axis=1,
    )
    averages = (
        mapped.groupby("client")["distance_miles"]
        .mean()
        .rename("avg_distance")
        .reset_index()
        .sort_values(["avg_distance", "client"], ascending=[False, True])
    )
    if averages.empty:
        return "Future metric", "Distance data pending"
    winner = averages.iloc[0]
    return str(winner["client"]), f'{float(winner["avg_distance"]):.1f} avg mi'


def render_financial_records(financial: pd.DataFrame, rollup: pd.DataFrame, data: WorkbookData) -> None:
    completed_events = len(financial)
    events_with_revenue = int(financial["has_revenue"].sum()) if not financial.empty else 0
    completion = (events_with_revenue / completed_events * 100) if completed_events else 0.0
    total_revenue = financial.loc[financial["has_revenue"], "revenue_amount"].sum() if events_with_revenue else math.nan

    highest_client = "No revenue data"
    highest_client_value = "Incomplete"
    highest_average_client = "No revenue data"
    highest_average_value = "Incomplete"
    revenue_king_client = ""
    highest_average_key = ""
    if not rollup.empty:
        top_total = rollup.sort_values(["total_revenue", "client"], ascending=[False, True]).iloc[0]
        highest_client = str(top_total["client"])
        revenue_king_client = highest_client.casefold()
        highest_client_value = format_currency(top_total["total_revenue"])
        top_avg = rollup.sort_values(["avg_revenue", "client"], ascending=[False, True]).iloc[0]
        highest_average_client = str(top_avg["client"])
        highest_average_key = highest_average_client.casefold()
        highest_average_value = f'{format_currency_precise(top_avg["avg_revenue"])} / visit'

    best_state = "No revenue data"
    best_state_value = "Incomplete"
    state_efficiency = financial_state_summary(financial)
    if not state_efficiency.empty:
        top_state = state_efficiency.sort_values(["avg_revenue", "state_region"], ascending=[False, True]).iloc[0]
        best_state = str(top_state["state_region"] or "Unknown")
        best_state_value = f'{format_currency(top_state["avg_revenue"])}/visit'

    highest_month = "No revenue data"
    highest_month_value = "Incomplete"
    month_summary = financial_month_summary(financial)
    if not month_summary.empty:
        top_month = month_summary.sort_values(["total_revenue", "month_order"], ascending=[False, True]).iloc[0]
        highest_month = str(top_month["month_label"])
        highest_month_value = format_currency(top_month["total_revenue"])

    repeat_client = "No repeat revenue"
    repeat_value = "Incomplete"
    if not rollup.empty:
        repeat_candidates = rollup[rollup["visits"].gt(1)].copy()
        alternate = repeat_candidates[
            ~repeat_candidates["client"].astype(str).str.casefold().isin({revenue_king_client, highest_average_key})
        ]
        if not alternate.empty:
            repeat_candidates = alternate
        if not repeat_candidates.empty:
            top_repeat = repeat_candidates.sort_values(["total_revenue", "client"], ascending=[False, True]).iloc[0]
            repeat_client = str(top_repeat["client"])
            repeat_value = format_currency(top_repeat["total_revenue"])

    road_client, road_value = road_warrior_record(data)

    records = [
        {"icon": "💰", "label": "Total Career Revenue", "client": format_currency(total_revenue), "value": "Known revenue only", "use_logo": False},
        {"icon": "👑", "label": "Revenue King", "client": highest_client, "value": highest_client_value, "use_logo": True},
        {"icon": "⚡", "label": "Highest Avg / Visit", "client": highest_average_client, "value": highest_average_value, "use_logo": True},
        {"icon": "🎯", "label": "Best State Efficiency", "client": best_state, "value": best_state_value, "use_logo": False},
        {"icon": "📅", "label": "Highest Revenue Month", "client": highest_month, "value": highest_month_value, "use_logo": False},
        {"icon": "✅", "label": "Revenue Completion", "client": format_percent(completion), "value": f"{events_with_revenue} of {completed_events} completed visits", "use_logo": False},
        {"icon": "🔁", "label": "Most Valuable Repeat Client", "client": repeat_client, "value": repeat_value, "use_logo": True},
        {"icon": "🛣️", "label": "Road Warrior", "client": road_client, "value": road_value, "use_logo": True},
    ]
    empty_state_values = {"No revenue data", "No repeat revenue", "Future metric"}
    logo_files, _ = discover_logos(LOGOS_DIR)
    accents = ["#2dd4bf", "#f5c542", "#fb7185", "#5c8ee8", "#a78bfa", "#f97316", "#34d399", "#38bdf8"]
    cards = []
    for index, record in enumerate(records):
        accent = accents[index % len(accents)]
        if record["use_logo"] and record["client"] not in empty_state_values:
            icon_markup = client_logo_markup(record["client"], logo_files, "client-logo-badge mini-tile-icon")
        else:
            icon_markup = f'<div class="client-logo-badge record-icon-badge">{escape(record["icon"])}</div>'
        cards.append(
            f'<div class="record-card" style="--record-accent:{accent}">'
            f'<div class="record-label">{escape(record["icon"])} {escape(record["label"])}</div>'
            '<div class="record-icon-line">'
            f'{icon_markup}'
            f'<div class="record-client-text">{escape(record["client"])}</div>'
            '</div>'
            f'<div class="record-value">{escape(record["value"])}</div>'
            '</div>'
        )
    st.markdown(f'<div class="records-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_financial_ranking(title: str, rows: list[str], empty_message: str) -> None:
    st.markdown(f'<div class="section-title">{escape(title)}</div>', unsafe_allow_html=True)
    if rows:
        st.markdown(f'<div class="financial-board">{"".join(rows)}</div>', unsafe_allow_html=True)
    else:
        st.info(empty_message)


def render_financial_standings(data: WorkbookData) -> None:
    financial = financial_frame(data)
    st.markdown('<div class="financial-section"><div class="section-title">FINANCIAL STANDINGS</div>', unsafe_allow_html=True)
    if financial.empty:
        st.info("No completed service events are available for financial standings.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    rollup = financial_client_rollup(financial)
    render_financial_records(financial, rollup, data)

    logo_files, _ = discover_logos(LOGOS_DIR)
    top_by_total = rollup.sort_values(["total_revenue", "client"], ascending=[False, True]).head(10)
    max_total = float(top_by_total["total_revenue"].max()) if not top_by_total.empty else 0.0
    total_rows = []
    for rank, row in enumerate(top_by_total.to_dict("records"), start=1):
        client = str(row["client"])
        pct = max(4, min(float(row["total_revenue"]) / max_total * 100, 100)) if max_total else 4
        total_rows.append(
            '<div class="financial-card-row">'
            '<div class="financial-card-top">'
            '<div class="standing-client-line">'
            f'<div class="financial-rank-chip">#{rank}</div>'
            f'{client_logo_markup(client, logo_files, "client-logo-badge mini-tile-icon")}'
            f'<div class="standing-client">{escape(client)}</div>'
            '</div>'
            f'<a class="financial-card-value-link" href="{client_profile_url("financial-analytics", client)}" target="_self">{escape(format_currency(row["total_revenue"]))}</a>'
            '</div>'
            f'<div class="financial-card-track"><div class="financial-card-fill" style="width:{pct:.1f}%"></div></div>'
            f'<div class="financial-card-meta"><span>{int(row["visits"])} visits</span><span>Total revenue</span></div>'
            '</div>'
        )
    render_financial_ranking("TOP REVENUE CLIENTS", total_rows, "No revenue-bearing completed visits are available yet.")

    top_by_avg = rollup.sort_values(["avg_revenue", "client"], ascending=[False, True]).head(10)
    max_avg = float(top_by_avg["avg_revenue"].max()) if not top_by_avg.empty else 0.0
    average_rows = []
    for rank, row in enumerate(top_by_avg.to_dict("records"), start=1):
        client = str(row["client"])
        pct = max(4, min(float(row["avg_revenue"]) / max_avg * 100, 100)) if max_avg else 4
        average_rows.append(
            '<div class="financial-card-row">'
            '<div class="financial-card-top">'
            '<div class="standing-client-line">'
            f'<div class="financial-rank-chip">#{rank}</div>'
            f'{client_logo_markup(client, logo_files, "client-logo-badge mini-tile-icon")}'
            f'<div class="standing-client">{escape(client)}</div>'
            '</div>'
            f'<a class="financial-card-value-link" href="{client_profile_url("financial-analytics", client)}" target="_self">{escape(format_currency_precise(row["avg_revenue"]))}</a>'
            '</div>'
            f'<div class="financial-card-track"><div class="financial-card-fill" style="width:{pct:.1f}%"></div></div>'
            f'<div class="financial-card-meta"><span>{int(row["visits"])} visits</span><span>Per visit</span></div>'
            '</div>'
        )
    render_financial_ranking("TOP AVERAGE REVENUE / VISIT", average_rows, "No average revenue ranking is available yet.")

    state_rows = []
    state_totals = financial_state_summary(financial)
    if not state_totals.empty:
        for row in state_totals.to_dict("records"):
            state_name = str(row["state_region"] or "Unknown")
            percent = float(row["percent"])
            state_rows.append(
                '<div class="financial-card-row">'
                '<div class="financial-card-top">'
                f'<div class="financial-card-title">{escape(state_name)}</div>'
                f'<div class="financial-card-value">{escape(format_currency(row["total_revenue"]))}</div>'
                '</div>'
                '<div class="financial-card-track">'
                f'<div class="financial-card-fill" style="width:{max(3, min(percent, 100)):.1f}%"></div>'
                '</div>'
                '<div class="financial-card-meta">'
                f'<span>{format_percent(percent)} of revenue</span>'
                f'<span>{escape(format_currency(row["avg_revenue"]))}/visit</span>'
                '</div>'
                '</div>'
            )
    render_financial_ranking("REVENUE BY STATE", state_rows, "No state revenue totals are available yet.")

    month_rows = []
    monthly = financial_month_summary(financial)
    if not monthly.empty:
        for row in monthly.sort_values("rank").to_dict("records"):
            percent = float(row["percent"])
            month_rows.append(
                '<div class="financial-card-row">'
                '<div class="financial-card-top">'
                f'<div class="financial-card-title">#{int(row["rank"])} · {escape(str(row["month_label"]))}</div>'
                f'<div class="financial-card-value">{escape(format_currency(row["total_revenue"]))}</div>'
                '</div>'
                '<div class="financial-card-track">'
                f'<div class="financial-card-fill" style="width:{max(3, min(percent, 100)):.1f}%"></div>'
                '</div>'
                '<div class="financial-card-meta">'
                f'<span>{format_percent(percent)} of revenue</span>'
                f'<span>Month order {int(row["month_order"])}</span>'
                '</div>'
                '</div>'
            )
    render_financial_ranking("REVENUE BY MONTH", month_rows, "No dated revenue totals are available yet.")

    completed_events = len(financial)
    events_with_revenue = int(financial["has_revenue"].sum())
    missing = financial[~financial["has_revenue"]].copy()
    completion = (events_with_revenue / completed_events * 100) if completed_events else 0.0
    st.markdown(
        '<div class="section-title">FINANCIAL INTEGRITY</div>'
        '<div class="integrity-card"><div class="integrity-grid">'
        f'<div class="integrity-stat"><div class="integrity-value">{completed_events}</div><div class="integrity-label">Completed Events</div></div>'
        f'<div class="integrity-stat"><div class="integrity-value">{events_with_revenue}</div><div class="integrity-label">With Revenue</div></div>'
        f'<div class="integrity-stat"><div class="integrity-value">{len(missing)}</div><div class="integrity-label">Missing Revenue</div></div>'
        f'<div class="integrity-stat"><div class="integrity-value">{format_percent(completion)}</div><div class="integrity-label">Completion</div></div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    if missing.empty:
        st.success("No completed events are missing revenue.")
    else:
        missing_display = missing[["visit_number", "client", "date_label", "location"]].copy()
        missing_display.columns = ["Visit #", "Client", "Date", "Location"]
        st.dataframe(missing_display, hide_index=True, width="stretch")
    st.markdown("</div>", unsafe_allow_html=True)


def render_financial_analytics(data: WorkbookData) -> None:
    selected_client = selected_client_query()
    if selected_client:
        render_client_profile(data, selected_client, "financial-analytics")
        return
    render_financial_standings(data)


def chart_lab_empty(message: str) -> None:
    st.info(message)


def plotly_horizontal_bar(frame: pd.DataFrame, label_column: str, value_column: str, title: str, color: str) -> go.Figure:
    ordered = frame.sort_values(value_column, ascending=True)
    figure = go.Figure(
        go.Bar(
            x=ordered[value_column],
            y=ordered[label_column].fillna("Unknown").astype(str),
            orientation="h",
            marker=dict(color=color, line=dict(color="rgba(255,255,255,.18)", width=1)),
            text=[format_currency(value) for value in ordered[value_column]],
            textposition="auto",
            hovertemplate="%{y}<br>%{text}<extra></extra>",
        )
    )
    figure.update_layout(title=title, height=310, margin=dict(l=12, r=16, t=44, b=18))
    return style_figure(figure, height=310)


def plotly_donut(frame: pd.DataFrame, label_column: str, value_column: str, title: str) -> go.Figure:
    figure = go.Figure(
        go.Pie(
            labels=frame[label_column].fillna("Unknown").astype(str),
            values=frame[value_column],
            hole=.58,
            textinfo="percent",
            hovertemplate="%{label}<br>%{percent}<br>%{value:$,.0f}<extra></extra>",
            marker=dict(colors=["#2dd4bf", "#f97316", "#5c8ee8", "#f5c542", "#a78bfa"]),
        )
    )
    figure.update_layout(title=title, height=310, margin=dict(l=14, r=14, t=44, b=14), showlegend=True)
    return style_figure(figure, height=310)


def mini_podium_rows(frame: pd.DataFrame, label_column: str, value_column: str) -> str:
    rows = []
    for rank, row in enumerate(frame.sort_values(value_column, ascending=False).to_dict("records"), start=1):
        rows.append(
            '<div class="mini-podium-row">'
            f'<div class="mini-rank">#{rank}</div>'
            f'<div class="mini-name">{escape(str(row[label_column] or "Unknown"))}</div>'
            f'<div class="mini-value">{escape(format_currency(row[value_column]))}</div>'
            '</div>'
        )
    return '<div class="mini-podium">' + "".join(rows) + "</div>"


def progress_card_rows(frame: pd.DataFrame, label_column: str, value_column: str, percent_column: str) -> str:
    rows = []
    for row in frame.sort_values(value_column, ascending=False).to_dict("records"):
        percent = float(row.get(percent_column, 0) or 0)
        meta = f"{format_percent(percent)}"
        if "avg_revenue" in row:
            meta += f" · {format_currency(row['avg_revenue'])}/visit"
        rows.append(
            '<div class="financial-card-row">'
            '<div class="financial-card-top">'
            f'<div class="financial-card-title">{escape(str(row[label_column] or "Unknown"))}</div>'
            f'<div class="financial-card-value">{escape(format_currency(row[value_column]))}</div>'
            '</div>'
            '<div class="financial-card-track">'
            f'<div class="financial-card-fill" style="width:{max(3, min(percent, 100)):.1f}%"></div>'
            '</div>'
            f'<div class="financial-card-meta"><span>{escape(meta)}</span><span>Revenue share</span></div>'
            '</div>'
        )
    return "".join(rows)


def render_chart_lab_style(label: str, title: str, body_html: str) -> None:
    st.markdown(
        '<div class="chart-style-card">'
        f'<div class="chart-style-label">{escape(label)}</div>'
        f'<div class="chart-style-title">{escape(title)}</div>'
        f'{body_html}'
        '</div>',
        unsafe_allow_html=True,
    )


def compact_currency(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if math.isnan(amount):
        return "N/A"
    if abs(amount) >= 1000:
        return f"＄{amount / 1000:.1f}K"
    return f"＄{amount:,.0f}"


def chart_lab_dataset_options(data: WorkbookData) -> dict[str, pd.DataFrame]:
    financial = financial_frame(data)
    state_summary = financial_state_summary(financial)
    month_summary = financial_month_summary(financial)
    client_rollup = financial_client_rollup(financial)
    options: dict[str, pd.DataFrame] = {}

    if not month_summary.empty:
        month = month_summary.copy()
        month["label"] = month["month_label"].astype(str)
        month["story"] = month["rank"].map(lambda rank: f"Rank #{int(rank)}")
        options["Revenue by Month"] = month[["label", "total_revenue", "percent", "story"]]

    if not state_summary.empty:
        state = state_summary.copy()
        state["label"] = state["state_region"].fillna("Unknown").astype(str)
        state["story"] = state["avg_revenue"].map(lambda value: f"{format_currency(value)}/visit")
        options["Revenue by State"] = state[["label", "total_revenue", "percent", "story"]]

    if not client_rollup.empty:
        clients = client_rollup.sort_values(["total_revenue", "client"], ascending=[False, True]).head(8).copy()
        total = float(clients["total_revenue"].sum())
        clients["label"] = clients["client"].astype(str)
        clients["percent"] = clients["total_revenue"].astype(float).div(total).mul(100) if total else 0.0
        clients["story"] = clients["visits"].map(lambda visits: f"{int(visits)} visits")
        options["Top Revenue Clients"] = clients[["label", "total_revenue", "percent", "story"]]

    return options


def chart_lab_frame(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.copy()
    prepared["total_revenue"] = pd.to_numeric(prepared["total_revenue"], errors="coerce").fillna(0.0)
    prepared = prepared.sort_values("total_revenue", ascending=False).reset_index(drop=True)
    prepared["rank"] = range(1, len(prepared) + 1)
    max_value = float(prepared["total_revenue"].max()) if not prepared.empty else 0.0
    prepared["leader_share"] = prepared["total_revenue"].div(max_value).mul(100) if max_value else 0.0
    return prepared


def chart_lab_unit(max_value: float) -> int:
    raw = max_value / 8 if max_value else 25
    for unit in (25, 50, 75, 100, 150, 200, 250, 500, 750, 1000):
        if raw <= unit:
            return unit
    return int(math.ceil(raw / 500) * 500)


def chart_lab_columns(frame: pd.DataFrame, class_name: str = "") -> str:
    items = []
    for row in frame.head(6).to_dict("records"):
        height = max(4, float(row["leader_share"]))
        items.append(
            '<div class="lab-column-item">'
            f'<div class="lab-column-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            f'<div class="lab-column-bar" style="height:{height:.1f}%"></div>'
            f'<div class="lab-column-label" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            '</div>'
        )
    return f'<div class="lab-columns {escape(class_name)}">{"".join(items)}</div>'


def chart_lab_money_towers(frame: pd.DataFrame) -> str:
    unit = chart_lab_unit(float(frame["total_revenue"].max()) if not frame.empty else 0.0)
    items = []
    for row in frame.head(6).to_dict("records"):
        blocks = max(1, int(round(float(row["total_revenue"]) / unit)))
        items.append(
            '<div class="tower-item">'
            '<div class="money-tower">'
            + "".join('<div class="money-block"></div>' for _ in range(blocks))
            + '</div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="tower-grid">{"".join(items)}</div><div class="tower-unit">1 block ≈ {format_currency(unit)}</div>'


def chart_lab_chip_stacks(frame: pd.DataFrame) -> str:
    unit = chart_lab_unit(float(frame["total_revenue"].max()) if not frame.empty else 0.0)
    items = []
    for row in frame.head(6).to_dict("records"):
        chips = max(1, int(round(float(row["total_revenue"]) / unit)))
        items.append(
            '<div class="chip-item">'
            '<div class="chip-stack">'
            + "".join('<div class="casino-chip"></div>' for _ in range(chips))
            + '</div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="chip-grid">{"".join(items)}</div><div class="tower-unit">1 chip ≈ {format_currency(unit)}</div>'


def chart_lab_garage(frame: pd.DataFrame) -> str:
    rows = []
    for row in frame.head(8).to_dict("records"):
        width = max(4, float(row["leader_share"]))
        rows.append(
            '<div class="garage-row">'
            f'<div class="garage-team" title="{escape(str(row["label"]), quote=True)}">#{int(row["rank"])} {escape(str(row["label"]))}</div>'
            f'<div class="garage-track"><div class="garage-fill" style="width:{width:.1f}%"></div></div>'
            f'<div class="garage-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="garage-board">{"".join(rows)}</div>'


def chart_lab_podium(frame: pd.DataFrame) -> str:
    medals = ["🥇", "🥈", "🥉"]
    order = [1, 0, 2]
    top = frame.head(3).to_dict("records")
    if len(top) < 3:
        order = list(range(len(top)))
    blocks = []
    for position in order:
        row = top[position]
        height = 62 + (3 - position) * 28
        blocks.append(
            '<div class="champ-step">'
            f'<div class="champ-medal">{medals[position]}</div>'
            f'<div class="champ-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="champ-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            f'<div class="champ-block" style="height:{height}px"></div>'
            '</div>'
        )
    return f'<div class="champ-podium">{"".join(blocks)}</div>'


def chart_lab_radial(frame: pd.DataFrame) -> str:
    items = []
    for row in frame.head(6).to_dict("records"):
        percent = max(2, min(float(row["leader_share"]), 100))
        items.append(
            '<div class="radial-item">'
            f'<div class="radial-medal" style="--pct:{percent:.1f}%">{escape(compact_currency(row["total_revenue"]))}</div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(str(row.get("story", "")))}</div>'
            '</div>'
        )
    return f'<div class="radial-grid">{"".join(items)}</div>'


def chart_lab_fuel_tanks(frame: pd.DataFrame) -> str:
    items = []
    for row in frame.head(6).to_dict("records"):
        height = max(5, float(row["leader_share"]))
        items.append(
            '<div class="fuel-item">'
            f'<div class="fuel-tank"><div class="fuel-fill" style="height:{height:.1f}%"></div></div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="fuel-grid">{"".join(items)}</div>'


def chart_lab_skyline(frame: pd.DataFrame) -> str:
    items = []
    for row in frame.head(6).to_dict("records"):
        height = max(8, float(row["leader_share"]))
        items.append(
            '<div class="lab-column-item skyline-item">'
            f'<div class="skyline-building" style="height:{height:.1f}%"></div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="lab-columns skyline-columns">{"".join(items)}</div>'


def chart_lab_pit_lane(frame: pd.DataFrame) -> str:
    rows = []
    for row in frame.head(8).to_dict("records"):
        width = max(4, float(row["leader_share"]))
        rows.append(
            '<div class="pit-row">'
            f'<div class="garage-team" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="pit-track"><div class="pit-progress" style="width:{width:.1f}%"></div></div>'
            f'<div class="garage-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="pit-lane">{"".join(rows)}</div>'


def chart_lab_trophy_cabinet(frame: pd.DataFrame) -> str:
    items = []
    for row in frame.head(6).to_dict("records"):
        scale = .55 + (float(row["leader_share"]) / 100 * .6)
        items.append(
            '<div class="trophy-item">'
            f'<div class="trophy-shape" style="transform:scale({scale:.2f})">🏆</div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">#{int(row["rank"])} {escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="trophy-grid">{"".join(items)}</div>'


def chart_lab_vault_stacks(frame: pd.DataFrame) -> str:
    unit = chart_lab_unit(float(frame["total_revenue"].max()) if not frame.empty else 0.0)
    items = []
    for row in frame.head(6).to_dict("records"):
        bars = max(1, int(round(float(row["total_revenue"]) / unit)))
        items.append(
            '<div class="vault-item">'
            '<div class="gold-stack">'
            + "".join('<div class="gold-bar"></div>' for _ in range(bars))
            + '</div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="vault-grid">{"".join(items)}</div><div class="tower-unit">1 gold bar ≈ {format_currency(unit)}</div>'


def chart_lab_container_yard(frame: pd.DataFrame) -> str:
    unit = chart_lab_unit(float(frame["total_revenue"].max()) if not frame.empty else 0.0)
    items = []
    for row in frame.head(6).to_dict("records"):
        containers = max(1, int(round(float(row["total_revenue"]) / unit)))
        items.append(
            '<div class="container-item">'
            '<div class="container-stack">'
            + "".join('<div class="container-box"></div>' for _ in range(containers))
            + '</div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="container-grid">{"".join(items)}</div><div class="tower-unit">1 container ≈ {format_currency(unit)}</div>'


def chart_lab_power_grid(frame: pd.DataFrame) -> str:
    unit = chart_lab_unit(float(frame["total_revenue"].max()) if not frame.empty else 0.0)
    items = []
    for row in frame.head(6).to_dict("records"):
        cells = max(1, int(round(float(row["total_revenue"]) / unit)))
        items.append(
            '<div class="power-item">'
            '<div class="power-stack">'
            + "".join('<div class="power-cell"></div>' for _ in range(cells))
            + '</div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="power-grid">{"".join(items)}</div><div class="tower-unit">1 power cell ≈ {format_currency(unit)}</div>'


def chart_lab_wildcard(frame: pd.DataFrame) -> str:
    items = []
    for row in frame.head(6).to_dict("records"):
        scale = max(.08, float(row["leader_share"]) / 100)
        size = 30 + scale * 42
        items.append(
            '<div class="wildcard-item">'
            f'<div class="wildcard-orbit"><div class="wildcard-core" style="width:{size:.1f}px;height:{size:.1f}px"></div></div>'
            f'<div class="mini-name" title="{escape(str(row["label"]), quote=True)}">{escape(str(row["label"]))}</div>'
            f'<div class="mini-value">{escape(compact_currency(row["total_revenue"]))}</div>'
            '</div>'
        )
    return f'<div class="wildcard-grid">{"".join(items)}</div>'


def chart_lab_card(label: str, title: str, story: str, body: str) -> str:
    return (
        '<div class="chart-style-card">'
        f'<div class="chart-style-label">{escape(label)}</div>'
        f'<div class="chart-style-title">{escape(title)}</div>'
        f'<div class="chart-style-story">{escape(story)}</div>'
        f'{body}'
        '</div>'
    )


def render_chart_lab(data: WorkbookData) -> None:
    st.markdown('<div class="section-title">LABORATORY</div>', unsafe_allow_html=True)

    demo_path = (
        Path(__file__).resolve().parent
        / "laboratory_demos"
        / "three-transitions-demo.html"
    )

    if not demo_path.exists():
        st.error(
            "Laboratory demo is missing: "
            "laboratory_demos/three-transitions-demo.html"
        )
        return

    components.html(
        demo_path.read_text(encoding="utf-8"),
        height=650,
        scrolling=False,
    )


def render_client_directory_cards(directory: pd.DataFrame) -> None:
    logo_files, _ = discover_logos(LOGOS_DIR)
    display_directory = directory.copy()
    display_directory = display_directory[display_directory["Client"].fillna("").astype(str).str.strip().ne("")].copy()
    display_directory["display_name"] = display_directory["Client"].astype(str).map(client_card_display_name)
    display_directory = display_directory.sort_values("display_name", key=lambda values: values.str.casefold()).reset_index(drop=True)
    max_visits = max(int(display_directory["# of Visits"].max()), 1) if not display_directory.empty else 1
    split_at = math.ceil(len(display_directory) / 2)
    first_column = display_directory.iloc[:split_at].to_dict("records")
    second_column = display_directory.iloc[split_at:].to_dict("records")
    visual_rows = []
    for index in range(split_at):
        visual_rows.append(first_column[index])
        if index < len(second_column):
            visual_rows.append(second_column[index])

    cards = []
    for row in visual_rows:
        client = str(row["Client"])
        display_client = str(row["display_name"])
        visual = client_logo_markup(client, logo_files, "client-logo-badge directory-logo-badge")
        visits = int(row["# of Visits"])
        locations = int(row["# of Locations"])
        first_visit = int(row["1st Visit"])
        first_visit_display = f"#{first_visit}" if first_visit else "N/A"
        activity_pct = max(6, round(visits / max_visits * 100, 1))
        cards.append(
            f'<a class="client-link directory-card" style="--activity-pct:{activity_pct}%" '
            f'href="{client_profile_url("client-analytics", client)}" target="_self">'
            f'{visual}'
            '<div>'
            f'<div class="directory-name" title="{escape(client, quote=True)}">{escape(display_client)}</div>'
            '<div class="directory-stats">'
            f'<div class="directory-stat"><div class="directory-stat-value">{visits}</div><div class="directory-stat-label">Visits</div></div>'
            f'<div class="directory-stat"><div class="directory-stat-value">{locations}</div><div class="directory-stat-label">Locations</div></div>'
            f'<div class="directory-stat"><div class="directory-stat-value">{escape(first_visit_display)}</div><div class="directory-stat-label">1st Visit</div></div>'
            '</div>'
            '</div>'
            '</a>'
        )
    st.markdown(
        '<div class="section-title">CLIENT DIRECTORY</div>'
        f'<div class="directory-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def render_client_analytics(data: WorkbookData) -> None:
    clients = data.clients.copy()
    if clients.empty or "client" not in clients:
        st.info("No client records are available in the Client List sheet.")
        return

    selected_client = selected_client_query()
    if selected_client:
        render_client_profile(data, selected_client, "client-analytics")
        return

    directory = client_directory_frame(data)
    render_client_podium(directory)
    render_career_records(data, directory)
    render_client_standings(directory)
    render_client_directory_cards(directory)


def authoritative_clients(data: WorkbookData) -> list[str]:
    workbook_clients = set(
        value for value in data.clients.get("client", pd.Series(dtype=str)).dropna().astype(str) if value.strip()
    )
    workbook_clients.update(
        value for value in data.timeline.get("client", pd.Series(dtype=str)).dropna().astype(str) if value.strip()
    )
    return sorted(workbook_clients, key=str.casefold)


def client_card_display_name(client: str) -> str:
    return CLIENT_CARD_ALIASES.get(client, client)


def jurisdiction_group(state: object) -> str:
    normalized = re.sub(r"[^a-z]", "", str(state or "").lower())
    if normalized in {"md", "maryland"}:
        return "Maryland"
    if normalized in {"va", "virginia"}:
        return "Virginia"
    if normalized in {"dc", "washingtondc", "districtofcolumbia"}:
        return "Washington, D.C."
    if normalized in {"wv", "westvirginia"}:
        return "West Virginia"
    return "Pennsylvania / Other"


def color_to_rgba(hex_color: str, alpha: int = 215) -> list[int]:
    color = hex_color.lstrip("#")
    if len(color) != 6:
        return [45, 212, 191, alpha]
    return [int(color[index:index + 2], 16) for index in (0, 2, 4)] + [alpha]


def map_zoom_for(events: pd.DataFrame) -> float:
    if events.empty:
        return 5.2
    if events["location_key"].nunique() == 1:
        return 11.0
    span = max(
        float(events["latitude"].max() - events["latitude"].min()),
        float(events["longitude"].max() - events["longitude"].min()),
    )
    if span < .15:
        return 10.0
    if span < .5:
        return 8.5
    if span < 1.5:
        return 7.0
    return 5.2


def clustered_map_frame(map_frame: pd.DataFrame) -> pd.DataFrame:
    if map_frame.empty:
        return map_frame

    cluster_keys = [
        "location_key",
        "latitude",
        "longitude",
        "Location",
        "State",
        "Jurisdiction",
    ]
    clustered = (
        map_frame.groupby(cluster_keys, dropna=False)
        .agg(
            event_count=("client", "size"),
            clients=("client", lambda values: ", ".join(sorted(set(str(value) for value in values if str(value).strip())))),
            visit_numbers=("Visit number", lambda values: ", ".join(str(int(value)) if isinstance(value, float) and value.is_integer() else str(value) for value in values)),
            statuses=("Status", lambda values: ", ".join(sorted(set(str(value) for value in values if str(value).strip())))),
        )
        .reset_index()
    )
    clustered["pin_icon"] = clustered["Jurisdiction"].map(
        lambda value: {
            "url": PIN_ICON_URLS.get(value, PIN_ICON_URLS["Pennsylvania / Other"]),
            "width": 64,
            "height": 64,
            "anchorY": 64,
        }
    )
    clustered["cluster_label"] = clustered["event_count"].map(lambda value: str(int(value)) if int(value) > 1 else "")
    clustered["TooltipTitle"] = clustered.apply(
        lambda row: row["clients"] if int(row["event_count"]) == 1 else f'{int(row["event_count"])} completed visits',
        axis=1,
    )
    clustered["TooltipSummary"] = clustered.apply(
        lambda row: (
            f'Visit {row["visit_numbers"]}<br/>{row["statuses"]}'
            if int(row["event_count"]) == 1
            else f'Visits {row["visit_numbers"]}<br/>{row["clients"]}'
        ),
        axis=1,
    )
    return clustered


def completed_mapped_events(data: WorkbookData):
    locations = load_locations(LOCATIONS_PATH)
    source = match_timeline_locations(data.timeline, locations)
    completed_mapped = source.mapped_events[source.mapped_events["status"].eq("Completed")].copy()
    return source, completed_mapped


def map_display_frame(current: pd.DataFrame) -> pd.DataFrame:
    map_frame = current.copy()
    map_frame["Date"] = map_frame["event_date"].dt.strftime("%Y-%m-%d").fillna("Not provided")
    map_frame["Visit number"] = map_frame["event_number"]
    map_frame["Client"] = map_frame["client"]
    map_frame["Location"] = map_frame["location_address"].where(
        map_frame["location_address"].ne(""), map_frame["location_city"]
    )
    map_frame["State"] = map_frame["location_state"]
    map_frame["Jurisdiction"] = map_frame["location_state"].map(jurisdiction_group)
    map_frame["Status"] = map_frame["status"]
    map_frame["Notes"] = map_frame["notes"].replace("", "Not provided")
    return map_frame


def render_clustered_folium_map(current: pd.DataFrame, height: int = 430, empty_message: str | None = None) -> bool:
    if not FOLIUM_AVAILABLE:
        return render_pydeck_events_map(current, height=height, empty_message=empty_message, use_territory_viewport=True)

    if current.empty:
        st.warning(empty_message or "No map pins are available for the current filters. Exact workbook coordinates are required.")
        return False

    map_frame = map_display_frame(current)
    territory_map = folium.Map(
        location=[
            float((map_frame["latitude"].min() + map_frame["latitude"].max()) / 2),
            float((map_frame["longitude"].min() + map_frame["longitude"].max()) / 2),
        ],
        zoom_start=9.3,
        tiles="CartoDB dark_matter",
        zoom_control=False,
        control_scale=False,
        prefer_canvas=True,
        zoom_snap=0.1,
        zoom_delta=0.5,
    )
    territory_map.get_root().html.add_child(
        folium.Element(
            """
            <style>
            .territory-pin {
                position: relative;
                width: 24px;
                height: 24px;
                border: 2px solid rgba(248,250,252,.9);
                border-radius: 50% 50% 50% 0;
                box-shadow: 0 7px 14px rgba(0,0,0,.38), 0 0 0 3px rgba(8,17,31,.35);
                transform: rotate(-45deg);
            }
            .territory-pin::after {
                content: "";
                position: absolute;
                top: 6px;
                left: 6px;
                width: 8px;
                height: 8px;
                border-radius: 999px;
                background: rgba(8,17,31,.92);
                box-shadow: inset 0 0 0 2px rgba(248,250,252,.78);
            }
            .leaflet-popup-content-wrapper,
            .leaflet-popup-tip {
                background: rgba(7,16,28,.96);
                color: #f8fafc;
                border: 1px solid rgba(148,163,184,.28);
                box-shadow: 0 12px 26px rgba(0,0,0,.36);
            }
            .leaflet-popup-content {
                margin: 10px 12px;
                font: 12px/1.35 Arial, sans-serif;
            }
            </style>
            """
        )
    )

    for row in map_frame.to_dict("records"):
        jurisdiction = str(row.get("Jurisdiction", "Pennsylvania / Other"))
        color = JURISDICTION_COLORS.get(jurisdiction, JURISDICTION_COLORS["Pennsylvania / Other"])
        notes = str(row.get("Notes", "") or "Not provided")
        popup = folium.Popup(
            "<br/>".join(
                [
                    f"<strong>{escape(str(row.get('Client', 'Unknown client')))}</strong>",
                    f"Visit {escape(str(row.get('Visit number', '')))}",
                    f"{escape(str(row.get('Location', '')))}, {escape(str(row.get('State', '')))}",
                    f"{escape(str(row.get('Status', '')))}",
                    f"Notes: {escape(notes)}",
                ]
            ),
            max_width=280,
        )
        icon = folium.DivIcon(
            html=f'<div class="territory-pin" style="background:{escape(color, quote=True)}"></div>',
            class_name="",
            icon_size=(28, 36),
            icon_anchor=(14, 36),
        )
        folium.Marker(
            location=[float(row["latitude"]), float(row["longitude"])],
            popup=popup,
            tooltip=f"{row.get('Client', '')} · {row.get('Location', '')}, {row.get('State', '')}",
            icon=icon,
        ).add_to(territory_map)

    territory_map.fit_bounds(
        [
            [float(map_frame["latitude"].min()), float(map_frame["longitude"].min())],
            [float(map_frame["latitude"].max()), float(map_frame["longitude"].max())],
        ],
        padding=(14, 14),
        max_zoom=9,
    )

    with st.container(key="interactive_map_chart"):
        st_folium(territory_map, height=height, width="stretch", returned_objects=[])
    return True


def render_pydeck_events_map(
    current: pd.DataFrame,
    height: int = 480,
    empty_message: str | None = None,
    use_territory_viewport: bool = False,
) -> bool:
    if current.empty:
        st.warning(empty_message or "No map pins are available for the current filters. Exact workbook coordinates are required.")
        return False

    map_frame = map_display_frame(current)
    pin_frame = map_frame.copy()
    pin_frame["pin_icon"] = pin_frame["Jurisdiction"].map(
        lambda value: {
            "url": PIN_ICON_URLS.get(value, PIN_ICON_URLS["Pennsylvania / Other"]),
            "width": 64,
            "height": 64,
            "anchorY": 64,
        }
    )
    pin_frame["TooltipTitle"] = pin_frame["Client"]
    pin_frame["TooltipSummary"] = pin_frame.apply(
        lambda row: f'Visit {row["Visit number"]}<br/>{row["Status"]}<br/>{row["Notes"]}',
        axis=1,
    )
    if use_territory_viewport:
        map_center = {
            "lat": float((map_frame["latitude"].min() + map_frame["latitude"].max()) / 2),
            "lon": float((map_frame["longitude"].min() + map_frame["longitude"].max()) / 2),
        }
        zoom = 8.65
    else:
        map_center = {
            "lat": float(map_frame["latitude"].mean()),
            "lon": float(map_frame["longitude"].mean()),
        }
        zoom = map_zoom_for(map_frame)

    pin_layer = pdk.Layer(
        "IconLayer",
        data=pin_frame,
        get_icon="pin_icon",
        get_position="[longitude, latitude]",
        get_size=42,
        size_units="pixels",
        pickable=True,
        billboard=True,
    )
    deck = pdk.Deck(
        layers=[pin_layer],
        initial_view_state=pdk.ViewState(
            latitude=map_center["lat"],
            longitude=map_center["lon"],
            zoom=zoom,
            pitch=0,
            bearing=0,
        ),
        map_style=pdk.map_styles.CARTO_DARK,
        tooltip={
            "html": (
                "<b>{TooltipTitle}</b><br/>"
                "{Location}, {State}<br/>"
                "{TooltipSummary}"
            ),
            "style": {
                "backgroundColor": "rgba(7, 16, 28, 0.94)",
                "color": "#f8fafc",
                "fontFamily": "Arial, sans-serif",
                "fontSize": "12px",
                "border": "1px solid rgba(148, 163, 184, 0.28)",
                "borderRadius": "10px",
                "padding": "8px 10px",
            },
        },
    )
    with st.container(key="interactive_map_chart"):
        st.pydeck_chart(deck, width="stretch", height=height)
    return True


def render_maps_page(data: WorkbookData) -> None:
    st.markdown('<div class="section-title">Service Location Map</div>', unsafe_allow_html=True)
    try:
        source, completed_mapped = completed_mapped_events(data)
    except (OSError, ValueError) as error:
        st.error(f"Unable to load coordinate enrichment: {error}")
        return
    render_clustered_folium_map(
        completed_mapped,
        height=780,
        empty_message="No completed service locations are available for the map.",
    )
    completed_total = len(completed_timeline(data))
    mapped_total = len(completed_mapped)
    unmapped_total = max(completed_total - mapped_total, 0)
    if unmapped_total:
        st.caption(f"{unmapped_total} completed service event{'s' if unmapped_total != 1 else ''} do not currently have usable coordinates.")


def render_coordinate_match_report(data: WorkbookData) -> None:
    st.subheader("Coordinate Match Report")
    try:
        locations = load_locations(LOCATIONS_PATH)
    except (OSError, ValueError) as error:
        st.error(f"Unable to load coordinate enrichment: {error}")
        return
    source = match_timeline_locations(data.timeline, locations)
    ambiguous_events = source.ambiguous_matches["event_number"].nunique() if not source.ambiguous_matches.empty else 0
    metrics = st.columns(4)
    metrics[0].metric("Successful Matches", len(source.successful_matches))
    metrics[1].metric("Failed Matches", len(source.failed_matches))
    metrics[2].metric("Duplicate Matches", len(source.duplicate_matches))
    metrics[3].metric("Ambiguous Matches", ambiguous_events)

    report_sections = [
        ("Successful Matches", source.successful_matches),
        ("Failed Matches", source.failed_matches),
        ("Duplicate Matches", source.duplicate_matches),
        ("Ambiguous Matches", source.ambiguous_matches),
    ]
    for label, frame in report_sections:
        st.subheader(label)
        if frame.empty:
            st.success(f"No {label.lower()} detected.")
        else:
            st.dataframe(match_report_table(frame), hide_index=True, width="stretch")


def render_scorecard(data: WorkbookData) -> None:
    st.subheader("Scorecard Metrics")

    required = {"metric", "value"}
    if data.scorecard.empty or not required.issubset(data.scorecard.columns):
        st.info("No usable Scorecard metrics were detected.")
        return

    scorecard = data.scorecard.copy()
    headline = scorecard.head(5)
    normal_rows = []
    legend_rows = []

    for row in headline.to_dict("records"):
        if str(row["metric"]).strip().casefold() == "financial status legend":
            legend_rows.append(row)
        else:
            normal_rows.append(row)

    if normal_rows:
        columns = st.columns(len(normal_rows))
        for column, row in zip(columns, normal_rows):
            column.markdown(
                metric_card(str(row["metric"]), row["value"], "Workbook scorecard"),
                unsafe_allow_html=True,
            )

    for row in legend_rows:
        value = str(row["value"]).replace("|", " · ").replace(
            "Closed/updated", "Closed / Updated"
        )
        st.markdown(
            '<div style="margin:.35rem 0 .65rem;padding:.42rem .68rem;'
            'border:1px solid rgba(45,212,191,.45);border-radius:10px;'
            'background:rgba(15,31,50,.72);font-size:.76rem;font-weight:700;'
            'line-height:1.2;color:#dbe7f5;">'
            '<span style="font-size:.6rem;letter-spacing:.07em;'
            'text-transform:uppercase;color:#9fb1c8;margin-right:.5rem;">'
            'Financial Status</span>' + value + '</div>',
            unsafe_allow_html=True,
        )

    display_columns = [column for column in ("metric", "value", "source") if column in scorecard]
    display = scorecard[display_columns].copy().fillna("").astype(str)
    display.columns = [column.title() for column in display.columns]
    st.dataframe(display, hide_index=True, width="stretch")


def editable_ledger_sheet(sheet_name: str) -> bool:
    normalized = normalize_label(sheet_name)
    if normalized in {"timeline", "pipeline", "client list"}:
        return True
    return "financial" in normalized or "ledger" in normalized


def disabled_ledger_columns(sheet_name: str, columns: list[str]) -> list[str]:
    normalized_sheet = normalize_label(sheet_name)
    disabled: list[str] = []
    visit_columns = {"visit", "visit number", "visit no", "event", "event number", "service event number", "timeline position"}
    for column in columns:
        normalized_column = normalize_label(column)
        if normalized_sheet == "timeline" and normalized_column in visit_columns:
            disabled.append(column)
    return disabled


def ledger_display_client(value: object) -> str:
    text = str(value or "").strip()
    return "Hebrew Home of GW" if text == "Hebrew Home of Greater Washington" else text


def ledger_source_client(value: object) -> str:
    text = str(value or "").strip()
    return "Hebrew Home of Greater Washington" if text == "Hebrew Home of GW" else text


def ledger_visible_columns(columns: list[str]) -> list[str]:
    by_normalized = {normalize_label(column): column for column in columns}
    ordered_labels = [
        "visit #",
        "visit",
        "visit number",
        "event number",
        "date",
        "event date",
        "client",
        "amount",
        "revenue",
        "verified?",
        "verified",
        "city",
        "wo #",
        "wo",
        "work order",
    ]
    visible: list[str] = []
    for label in ordered_labels:
        column = by_normalized.get(label)
        if column and column not in visible:
            visible.append(column)
    return visible


def ledger_display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.fillna("").astype(str)
    columns = ledger_visible_columns(list(display.columns))
    display = display[columns].copy() if columns else display.iloc[:, 0:0].copy()
    for column in display.columns:
        if normalize_label(column) == "client":
            display[column] = display[column].map(ledger_display_client)
    return display


def merge_ledger_display_edits(original: pd.DataFrame, edited: pd.DataFrame) -> pd.DataFrame:
    merged = original.fillna("").astype(str).copy()
    edited_source = edited.fillna("").astype(str).copy()
    for column in edited_source.columns:
        if normalize_label(column) == "client":
            edited_source[column] = edited_source[column].map(ledger_source_client)
        if column in merged.columns:
            merged[column] = edited_source[column]
    return merged


def ledger_backup_path(workbook_path: Path) -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = BACKUPS_DIR / f"LedgerDelta_backup_{timestamp}.xlsx"
    suffix = 2
    while candidate.exists():
        candidate = BACKUPS_DIR / f"LedgerDelta_backup_{timestamp}_{suffix}.xlsx"
        suffix += 1
    shutil.copy2(workbook_path, candidate)
    return candidate


def changed_rows_preview(original: pd.DataFrame, edited: pd.DataFrame) -> tuple[int, pd.DataFrame]:
    edited_aligned = edited.reindex(columns=original.columns).fillna("").astype(str)
    original_aligned = original.fillna("").astype(str)
    changes = original_aligned.ne(edited_aligned)
    change_count = int(changes.to_numpy().sum()) if not changes.empty else 0
    if not change_count:
        return 0, pd.DataFrame()
    rows = edited_aligned.loc[changes.any(axis=1)].copy()
    rows.insert(0, "Workbook Row", [index + 2 for index in rows.index])
    return change_count, rows.head(25)


def _matches_any_keyword(column: object, keywords: tuple[str, ...]) -> bool:
    normalized = normalize_label(column)
    return any(keyword in normalized for keyword in keywords)


def _confirmed_text_series(values: pd.Series) -> pd.Series:
    text = values.fillna("").astype(str).str.strip().str.casefold()
    positive_tokens = ("☑", "✓", "yes", "true", "paid", "verified", "confirmed", "complete", "received", "deposited", "ach")
    negative_tokens = ("", "nan", "none", "no", "false", "missing", "pending", "unconfirmed", "⚠")
    positive = text.apply(lambda value: any(token in value for token in positive_tokens))
    negative = text.isin(negative_tokens) | text.apply(lambda value: any(token in value for token in ("missing", "pending", "unconfirmed")))
    return positive & ~negative


def _any_confirmed(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    if not columns:
        return pd.Series(False, index=frame.index)
    confirmed = pd.Series(False, index=frame.index)
    for column in columns:
        confirmed = confirmed | _confirmed_text_series(frame[column])
    return confirmed


def ledger_completeness_metrics(data: WorkbookData) -> dict[str, object]:
    completed = completed_timeline(data).copy()
    total_events = len(completed)
    if completed.empty:
        return {
            "total_events": 0,
            "ach_missing": 0,
            "breakdown_missing": 0,
            "revenue_completion": 0.0,
        }

    payment_columns = [
        column for column in completed.columns
        if _matches_any_keyword(column, ("ach", "deposit", "payment", "paid", "verified", "confirmation"))
    ]
    if not payment_columns and "verified" in completed:
        payment_columns = ["verified"]
    ach_confirmed = _any_confirmed(completed, payment_columns)

    breakdown_columns = [
        column for column in completed.columns
        if _matches_any_keyword(column, ("breakdown", "allocation", "detail", "ledger", "revenue", "amount"))
    ]
    if "revenue" in completed:
        revenue_confirmed = revenue_series(completed["revenue"]).notna()
        breakdown_confirmed = revenue_confirmed
        extra_breakdown_columns = [column for column in breakdown_columns if normalize_label(column) != "revenue"]
        if extra_breakdown_columns:
            breakdown_confirmed = breakdown_confirmed | _any_confirmed(completed, extra_breakdown_columns)
    else:
        breakdown_confirmed = _any_confirmed(completed, breakdown_columns)

    fully_confirmed = ach_confirmed & breakdown_confirmed
    return {
        "total_events": total_events,
        "ach_missing": int((~ach_confirmed).sum()),
        "breakdown_missing": int((~breakdown_confirmed).sum()),
        "revenue_completion": (float(fully_confirmed.sum()) / total_events * 100) if total_events else 0.0,
    }


def render_ledger_kpi_row(data: WorkbookData) -> None:
    metrics = ledger_completeness_metrics(data)
    cards = [
        ("Total Events", str(metrics["total_events"])),
        ("ACH Missing", str(metrics["ach_missing"])),
        ("Breakdown Missing", str(metrics["breakdown_missing"])),
        ("Revenue Completion", f'{float(metrics["revenue_completion"]):.1f}%'),
    ]
    markup = "".join(
        '<div class="ledger-kpi-card">'
        f'<div class="ledger-kpi-value">{escape(value)}</div>'
        f'<div class="ledger-kpi-label">{escape(label)}</div>'
        '</div>'
        for label, value in cards
    )
    st.markdown(f'<div class="ledger-kpi-row">{markup}</div>', unsafe_allow_html=True)


def render_canonical_project_registry() -> None:
    st.markdown(
        """
        <div style="
            margin:.45rem 0 .9rem;
            padding:.8rem .9rem;
            border:1px solid rgba(56,189,248,.22);
            border-radius:12px;
            background:rgba(8,18,32,.72);
        ">
            <div style="
                margin-bottom:.55rem;
                color:#e2e8f0;
                font-size:.78rem;
                font-weight:850;
                letter-spacing:.08em;
                text-transform:uppercase;
            ">
                Canonical Project Registry
            </div>
            <div class="ledger-path"><strong>8088 · Production:</strong> ~/Documents/BarristerCloud</div>
            <div class="ledger-path"><strong>8501 · Development/Test:</strong> ~/Documents/CareerDashboard</div>
            <div class="ledger-path"><strong>8020 · Transition Lab:</strong> ~/Documents/Bronx-3D-Transition</div>
            <div class="ledger-path"><strong>8011 · Heroes &amp; Muses:</strong> ~/Documents/Heroes-Muses-Library</div>
            <div class="ledger-path"><strong>9000 · Family Showcase:</strong> ~/Documents/Family-Legacy-Archive</div>
            <div class="ledger-path"><strong>8000 · Bronx Daily:</strong> active server; project folder still requires verification</div>
            <div style="margin-top:.65rem;color:#94a3b8;font-size:.68rem;line-height:1.45;">
                BarristerCloud is the Git-backed production source. CareerDashboard is the isolated development clone.
                BarristerEngine, ticket_processor_test, bronx, and Codex are not assigned active dashboard ports;
                inspect them before use and never infer their purpose from their names.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_ledger_editor(data: WorkbookData) -> None:
    st.subheader("Ledger Editor")

    with st.container(border=True):
        st.markdown("**\U0001F4E5 Backup the live workbook**")
        st.caption("Download this before pushing any code change — a redeploy rebuilds from GitHub and will discard anything added here since the last commit.")
        col_a, col_b = st.columns(2)
        try:
            master_bytes = data.path.read_bytes()
            col_a.download_button(
                "Download Barrister_Master.xlsx",
                data=master_bytes,
                file_name="Barrister_Master.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except OSError as error:
            col_a.error(f"Could not read Barrister_Master.xlsx: {error}")
        current_master_path = data.path.parent / "current_master.xlsx"
        if current_master_path.exists():
            try:
                current_bytes = current_master_path.read_bytes()
                col_b.download_button(
                    "Download current_master.xlsx",
                    data=current_bytes,
                    file_name="current_master.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            except OSError as error:
                col_b.error(f"Could not read current_master.xlsx: {error}")
        else:
            col_b.caption("current_master.xlsx not found alongside the active workbook.")

    last_save_message = st.session_state.pop("ledger_editor_last_save", None)

    try:
        sheets = read_xlsx(data.path)
    except (OSError, ValueError) as error:
        st.error(f"Unable to read the active workbook: {error}")
        return

    if not sheets:
        st.info("No readable sheets were found in the active workbook.")
        return

    selected_sheet = "Timeline"
    if selected_sheet not in sheets:
        st.error("The active workbook does not contain a Timeline sheet.")
        return

    frame = sheets[selected_sheet].copy()
    if frame.empty:
        st.info("This sheet is empty.")
        st.caption(f"Active workbook: {data.path.name}")
        st.caption(str(data.path))
        return

    source_display = frame.fillna("").astype(str)
    display = ledger_display_frame(frame)
    can_edit = editable_ledger_sheet(selected_sheet)
    edit_mode = st.toggle("Edit Mode", value=False, disabled=not can_edit)
    render_ledger_kpi_row(data)

    if not edit_mode:
        st.dataframe(display, hide_index=True, width="stretch", height=620)
        st.caption(f"{len(frame)} timeline rows · {len(display.columns)} visible columns")
        st.caption(f"Active workbook: {data.path.name}")
        st.caption(str(data.path))
        render_canonical_project_registry()
        if last_save_message:
            st.success(last_save_message)
        return

    disabled_columns = disabled_ledger_columns(selected_sheet, list(display.columns))
    edited = st.data_editor(
        display,
        hide_index=True,
        width="stretch",
        height=620,
        num_rows="fixed",
        disabled=disabled_columns,
        key=f"ledger_editor_{normalize_label(selected_sheet)}",
    )
    st.caption(f"{len(frame)} timeline rows · {len(display.columns)} visible columns")
    st.caption(f"Active workbook: {data.path.name}")
    st.caption(str(data.path))
    render_canonical_project_registry()
    if disabled_columns:
        st.caption("Read-only columns: " + ", ".join(disabled_columns))
    if last_save_message:
        st.success(last_save_message)
    change_count, changed_rows = changed_rows_preview(display, edited)
    if change_count:
        st.markdown(
            f'<div class="change-summary">{change_count} cell change{"s" if change_count != 1 else ""} detected. Review changed rows before saving.</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(changed_rows, hide_index=True, width="stretch")
    else:
        st.info("No changes detected.")

    st.warning("Saving creates a timestamped backup first, then writes the edited sheet back to the active LedgerDelta workbook.")
    confirm_save = st.checkbox("I understand this will update the active LedgerDelta workbook.")
    save_column, cancel_column = st.columns(2)
    if save_column.button("Save Changes", type="primary", disabled=not (change_count and confirm_save), width="stretch"):
        try:
            backup_path = ledger_backup_path(data.path)
            merged = merge_ledger_display_edits(source_display, edited)
            replace_workbook_sheet_table(data.path, selected_sheet, merged)
        except (OSError, ValueError) as error:
            st.error(f"Save failed: {error}")
        else:
            st.cache_data.clear()
            st.session_state["ledger_editor_last_save"] = f"Saved {selected_sheet}. Backup created: {backup_path.name}"
            st.query_params["page"] = "ledger-editor"
            st.rerun()
    if cancel_column.button("Cancel / Revert", width="stretch"):
        st.query_params["page"] = "ledger-editor"
        st.rerun()


def render_event_preview(draft: dict) -> None:
    rows = [
        ("Client", draft["client"]),
        ("Location", f'{draft["city"]}, {draft["region_code"]}'),
        ("Status", draft["status"]),
        ("Date", draft["event_date"].strftime("%Y-%m-%d")),
    ]
    if draft.get("event_number") is not None:
        rows.insert(3, ("Visit Number", draft["event_number"]))
    markup = "".join(
        f'<div class="preview-row"><div class="preview-label">{escape(label)}</div>'
        f'<div class="preview-value">{escape(str(value))}</div></div>'
        for label, value in rows
    )
    if draft.get("notes"):
        markup += (
            '<div class="preview-row"><div class="preview-label">Notes</div>'
            f'<div class="preview-value">{escape(str(draft["notes"]))}</div></div>'
        )
    st.markdown(f'<div class="event-preview">{markup}</div>', unsafe_allow_html=True)


def scheduled_date_label(value: object) -> str:
    if value in ("", None):
        return "No Date"
    raw = str(value).strip()
    if raw.lower() in {"", "nan", "nat", "none"}:
        return "No Date"
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.notna(timestamp):
        return timestamp.strftime("%b %d, %Y")
    return raw or "No Date"


def scheduled_tickets(data: WorkbookData) -> pd.DataFrame:
    pipeline = pipeline_frame(data)
    if pipeline.empty or not {"client", "location", "status"}.issubset(pipeline.columns):
        return pd.DataFrame()
    scheduled = pipeline[pipeline["status"].fillna("").astype(str).str.title().eq("Scheduled")].copy()
    if scheduled.empty:
        return scheduled
    scheduled["pipeline_index"] = scheduled.index
    scheduled["client"] = scheduled["client"].fillna("").astype(str).str.strip()
    scheduled["location"] = scheduled["location"].fillna("").astype(str).str.strip()
    scheduled["notes"] = scheduled.get("notes", pd.Series("", index=scheduled.index)).fillna("").astype(str).str.strip()
    if "_source_path" not in scheduled:
        scheduled["_source_path"] = str(data.path)
    scheduled = scheduled[scheduled["client"].ne("") | scheduled["location"].ne("")].copy()
    scheduled["_sort_date"] = pd.to_datetime(scheduled.get("event_date", pd.Series("", index=scheduled.index)), errors="coerce")
    scheduled = scheduled.sort_values(
        ["_sort_date", "client", "location"],
        ascending=[True, True, True],
        na_position="last",
        key=lambda values: values.str.casefold() if values.dtype == object else values,
    )
    return scheduled.drop(columns=["_sort_date"]).reset_index(drop=True)


def existing_event_options(data: WorkbookData) -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    completed = completed_chronology(data)
    if not completed.empty:
        completed = completed.sort_values("visit_number" if "visit_number" in completed else "event_number", ascending=False)
    for row in completed.to_dict("records"):
        visit_number = row.get("visit_number", row.get("event_number", ""))
        client = str(row.get("client", "") or "").strip()
        city = str(row.get("city", "") or "").strip()
        state = str(row.get("region_code", "") or "").strip()
        location = ", ".join(part for part in [city, state] if part)
        date_label = scheduled_date_label(row.get("event_date", ""))
        label = f"#{int(visit_number)} — {client}"
        if location:
            label += f" — {location}"
        if date_label not in {"No Date", "Date Unavailable"}:
            label += f" — {date_label}"
        options.append(
            {
                "ref": f"timeline:{int(row.get('event_number', visit_number))}",
                "label": label,
                "client": client,
                "location": location,
                "event_date": row.get("event_date", pd.NaT),
                "status": "Completed",
                "notes": str(row.get("notes", "") or "").strip(),
                "visit_number": int(visit_number),
            }
        )

    for row in scheduled_tickets(data).to_dict("records"):
        if Path(str(row.get("_source_path") or data.path)).resolve() != data.path.resolve():
            continue
        client = str(row.get("client", "") or "").strip()
        location = str(row.get("location", "") or "").strip()
        date_label = scheduled_date_label(row.get("event_date", ""))
        label = f"Scheduled — {client or 'Unnamed client'}"
        if location:
            label += f" — {location}"
        if date_label not in {"No Date", "Date Unavailable"}:
            label += f" — {date_label}"
        options.append(
            {
                "ref": f"pipeline:{int(row['pipeline_index'])}",
                "label": label,
                "client": client,
                "location": location,
                "event_date": row.get("event_date", pd.NaT),
                "status": "Scheduled",
                "notes": str(row.get("notes", "") or "").strip(),
                "visit_number": None,
            }
        )
    return options


def complete_scheduled_ticket(data: WorkbookData, row: dict) -> object:
    pipeline_index = int(row["pipeline_index"])
    return complete_scheduled_assignment(data.path, pipeline_index, date.today())


def _event_date_default(value: object) -> date:
    timestamp = pd.to_datetime(value, errors="coerce")
    return timestamp.date() if pd.notna(timestamp) else date.today()


def render_manage_existing_event(data: WorkbookData) -> None:
    st.subheader("Manage Existing Event")
    options = existing_event_options(data)
    if not options:
        st.caption("No completed or scheduled events are available to manage.")
        return

    by_ref = {str(option["ref"]): option for option in options}
    selected_ref = st.selectbox(
        "Select Existing Event",
        list(by_ref),
        index=None,
        placeholder="Choose an event",
        format_func=lambda ref: str(by_ref[ref]["label"]),
        key="manage_existing_event_select",
    )
    if not selected_ref:
        return

    selected = by_ref[selected_ref]
    action = st.radio("Action", ["Edit", "Delete"], horizontal=True, index=0, key=f"manage_action_{selected_ref}")

    if action == "Edit":
        client_options = authoritative_clients(data)
        selected_client = str(selected["client"])
        client_index = client_options.index(selected_client) if selected_client in client_options else None
        location_options = known_location_options(data)
        selected_location = str(selected["location"])
        if selected_location and selected_location not in location_options:
            location_options = [selected_location, *location_options]
        location_index = location_options.index(selected_location) if selected_location in location_options else None
        with st.form(f"edit_existing_event_form_{selected_ref}", clear_on_submit=False):
            edit_client = st.selectbox(
                "Client",
                client_options,
                index=client_index,
                placeholder="Start typing or enter a new client",
                accept_new_options=True,
                key=f"edit_client_{selected_ref}",
            )
            if not edit_client:
                edit_client = selected_client
            edit_location = st.selectbox(
                "Location",
                location_options,
                index=location_index,
                placeholder=selected_location or "Type or select a location",
                accept_new_options=True,
                key=f"edit_location_{selected_ref}",
            )
            if not edit_location:
                edit_location = selected_location
            edit_date = st.date_input("Date", value=_event_date_default(selected["event_date"]), key=f"edit_date_{selected_ref}")
            status_options = ["Scheduled", "Completed"]
            current_status = str(selected["status"])
            edit_status = st.radio(
                "Status",
                status_options,
                horizontal=True,
                index=status_options.index(current_status) if current_status in status_options else 0,
                key=f"edit_status_{selected_ref}",
            )
            edit_notes = st.text_area("Notes", value=str(selected["notes"]), height=88, key=f"edit_notes_{selected_ref}")
            save_clicked = st.form_submit_button("Save Changes", type="primary", width="stretch")

        cancel_column, _ = st.columns([1, 2])
        if cancel_column.button("Cancel", key=f"cancel_edit_{selected_ref}", width="stretch"):
            st.session_state.pop("manage_existing_event_select", None)
            st.rerun()

        if save_clicked:
            try:
                saved = update_existing_event(
                    data.path,
                    selected_ref,
                    edit_client,
                    edit_location,
                    edit_date,
                    edit_status,
                    edit_notes,
                )
            except (OSError, ValueError) as error:
                st.error(f"Save failed: {error}")
            else:
                st.cache_data.clear()
                st.session_state["last_saved_event"] = {
                    "event_number": saved.event_number,
                    "client": saved.client,
                    "managed_update": True,
                }
                st.query_params["page"] = "add-service-event"
                st.rerun()
        return

    st.warning(
        f"Delete this event?\n\n{selected['label']}\n\nThis action cannot be undone."
    )
    delete_column, cancel_column = st.columns(2)
    if delete_column.button("Delete Event", type="primary", key=f"delete_event_{selected_ref}", width="stretch"):
        try:
            delete_existing_event(data.path, selected_ref)
        except (OSError, ValueError) as error:
            st.error(f"Delete failed: {error}")
        else:
            st.cache_data.clear()
            st.session_state["last_saved_event"] = {
                "event_number": None,
                "client": str(selected["client"]),
                "deleted_event": True,
            }
            st.query_params["page"] = "add-service-event"
            st.rerun()
    if cancel_column.button("Cancel", key=f"cancel_delete_{selected_ref}", width="stretch"):
        st.session_state.pop("manage_existing_event_select", None)
        st.rerun()


def render_scheduled_ticket_management(data: WorkbookData) -> None:
    st.subheader("Scheduled Assignments")
    tickets = scheduled_tickets(data)
    if tickets.empty:
        st.caption("No scheduled assignments.")
        return

    st.markdown('<div class="scheduled-ticket-list">', unsafe_allow_html=True)
    for row in tickets.to_dict("records"):
        pipeline_index = int(row["pipeline_index"])
        client = str(row.get("client", "") or "").strip()
        location = str(row.get("location", "") or "").strip()
        date_label = scheduled_date_label(row.get("event_date", ""))
        notes = str(row.get("notes", "") or "").strip()
        meta_parts = [part for part in [location, date_label] if part]
        details_column, action_column = st.columns([4.2, 1.35], vertical_alignment="center")
        with details_column:
            st.markdown(
                '<div class="scheduled-ticket-card">'
                f'<div class="scheduled-ticket-client">{escape(client or "Unnamed client")}</div>'
                f'<div class="scheduled-ticket-meta">{escape(" · ".join(meta_parts) if meta_parts else "Location/date not provided")}</div>'
                + (f'<div class="scheduled-ticket-notes">{escape(notes)}</div>' if notes else "")
                + '</div>',
                unsafe_allow_html=True,
            )
        with action_column:
            if st.button("✓ Mark Completed", key=f"complete_scheduled_{pipeline_index}", type="primary", width="stretch"):
                try:
                    saved = complete_scheduled_ticket(data, row)
                except (OSError, ValueError) as error:
                    st.error(f"Could not complete scheduled assignment: {error}")
                else:
                    st.cache_data.clear()
                    st.session_state.pop("pending_service_event", None)
                    st.session_state["last_saved_event"] = {
                        "event_number": saved.event_number,
                        "client": saved.client,
                        "converted_scheduled": True,
                    }
                    st.query_params["page"] = "add-service-event"
                    st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)




def render_logo_factory_page() -> None:
    """Main-dashboard Logo Factory controls."""
    import json
    import subprocess
    import sys
    from PIL import Image

    profile_file = Path(__file__).parent / "assets" / "brand_factory" / "logo_profiles.json"
    approved_dir = BRAND_FACTORY_APPROVED_DIR
    tile_dir = approved_dir / "_client_portfolio_tiles"
    tile_builder = Path(__file__).parent / "tools" / "build_client_portfolio_tiles.py"
    sheet_builder = Path(__file__).parent / "tools" / "build_client_portfolio_sheet.py"

    logo_store_title, logo_factory_link = st.columns([4, 1])

    with logo_store_title:
        st.markdown(
            '<div class="section-title">LOGO STORE</div>',
            unsafe_allow_html=True,
        )

    with logo_factory_link:
        st.markdown(
            """
            <a href="http://100.70.235.51:8090"
               target="_blank"
               style="
                   display:flex;
                   align-items:center;
                   justify-content:center;
                   width:100%;
                   min-height:48px;
                   margin-top:4px;
                   padding:10px 14px;
                   border:1px solid rgba(168,85,247,.65);
                   border-radius:14px;
                   background:rgba(30,20,50,.88);
                   color:#ffffff;
                   font-weight:800;
                   text-decoration:none;
                   white-space:nowrap;
               ">🎨 Logo Lab</a>
            """,
            unsafe_allow_html=True,
        )

    if not profile_file.exists():
        st.error("Missing logo profile file: assets/brand_factory/logo_profiles.json")
        return

    profiles = json.loads(profile_file.read_text())
    defaults = profiles.get("_defaults", {"scale": 0.78, "x": 0, "y": 0})

    logo_keys = sorted([k for k in profiles.keys() if not k.startswith("_")])
    if not logo_keys:
        st.warning("No logo profiles found.")
        return

    selected = st.selectbox("Select logo", logo_keys, key="logo_factory_selected_logo")

    current = profiles.setdefault(
        selected,
        {
            "scale": float(defaults.get("scale", 0.78)),
            "x": int(defaults.get("x", 0)),
            "y": int(defaults.get("y", 0)),
        },
    )

    left, right = st.columns([1, 2], gap="large")

    def save_profile(scale_value, x_value, y_value):
        profiles[selected] = {
            "scale": float(scale_value),
            "x": int(x_value),
            "y": int(y_value),
        }
        profile_file.write_text(json.dumps(profiles, indent=2) + "\\n")

    def rebuild_assets():
        if tile_builder.exists():
            subprocess.run([sys.executable, str(tile_builder)], cwd=Path(__file__).parent)
        if sheet_builder.exists():
            subprocess.run([sys.executable, str(sheet_builder)], cwd=Path(__file__).parent)

    with left:
        st.markdown("### Controls")

        scale = st.slider(
            "Scale",
            0.20,
            2.00,
            float(current.get("scale", defaults.get("scale", 0.78))),
            0.01,
            key=f"logo_factory_scale_{selected}",
        )

        x = st.slider(
            "X offset",
            -160,
            160,
            int(current.get("x", defaults.get("x", 0))),
            1,
            key=f"logo_factory_x_{selected}",
        )

        y = st.slider(
            "Y offset",
            -160,
            160,
            int(current.get("y", defaults.get("y", 0))),
            1,
            key=f"logo_factory_y_{selected}",
        )

        b1, b2, b3 = st.columns(3)

        with b1:
            if st.button("👁️ Preview", width="stretch"):
                save_profile(scale, x, y)
                rebuild_assets()
                st.success("Preview rebuilt.")

        with b2:
            if st.button("💾 Save", width="stretch"):
                save_profile(scale, x, y)
                rebuild_assets()
                st.success("Saved and rebuilt.")

        with b3:
            if st.button("↩️ Reset", width="stretch"):
                profiles[selected] = {
                    "scale": float(defaults.get("scale", 0.78)),
                    "x": int(defaults.get("x", 0)),
                    "y": int(defaults.get("y", 0)),
                }
                profile_file.write_text(json.dumps(profiles, indent=2) + "\\n")
                rebuild_assets()
                st.success("Reset and rebuilt.")

        st.divider()
        st.code("assets/brand_factory/logo_profiles.json")

    with right:
        st.markdown("### Selected Tile")

        selected_tile = tile_dir / f"{selected}.png"
        if selected_tile.exists():
            st.image(Image.open(selected_tile), width=260)
        else:
            st.warning("No generated tile found. Click Preview or Save to rebuild.")

        st.markdown("### Executive Wall Tiles")

        wall_order = [
            "usda", "hilton", "hamptoninn", "bloomingdales", "verizon", "davispolk",
            "macys", "tjmaxx", "marshalls", "homegoods", "homesense", "underarmour",
            "dunkin", "baskinrobbins", "711", "pepsi", "montpelier", "residential",
            "foodlion", "giant", "weis", "atriumvillage", "marylandbaptistagehome", "hebrewhomegw",
            "vanhollen", "jointbaseandrews", "alsobrooks",
        ]

        cols = st.columns(6, gap="small")
        for i, key in enumerate(wall_order):
            tile_path = tile_dir / f"{key}.png"
            with cols[i % 6]:
                if tile_path.exists():
                    st.image(Image.open(tile_path), width="stretch")
                    st.caption(key)
                else:
                    st.caption(f"{key} missing")

def render_add_service_event(data: WorkbookData) -> None:
    st.subheader("Add Service Event")
    if data is None:
        st.warning("No active workbook is available. Use the hidden admin import utility before adding events.")
        return

    if "last_saved_event" in st.session_state:
        saved = st.session_state.pop("last_saved_event")
        if saved.get("deleted_event"):
            st.success("Deleted event and refreshed dashboard calculations.")
        elif saved.get("managed_update"):
            st.success(f'Updated event for {saved["client"]}.')
        elif saved.get("event_number") is None:
            st.success(f'Saved scheduled assignment for {saved["client"]}.')
        elif saved.get("converted_scheduled"):
            st.success(f'Completed scheduled assignment as Visit #{saved["event_number"]} for {saved["client"]}.')
        else:
            st.success(f'Saved Visit #{saved["event_number"]} for {saved["client"]}.')

    clients = authoritative_clients(data)
    location_options = known_location_options(data)
    with st.form("add_service_event_form", clear_on_submit=False):
        st.markdown('<div class="event-form-shell">', unsafe_allow_html=True)
        status = st.radio("Status", ["Scheduled", "Completed"], horizontal=True, index=0)
        client = st.selectbox(
            "Client",
            clients,
            index=None,
            placeholder="Start typing or enter a new client",
            accept_new_options=True,
        )
        location = st.selectbox(
            "Location",
            location_options,
            index=None,
            placeholder="Type or select a location",
            accept_new_options=True,
        )
        notes = st.text_area("Notes", height=92)
        event_date = st.date_input("Date", value=date.today())
        preview_clicked = st.form_submit_button("Preview", type="primary", width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)

    if preview_clicked:
        try:
            draft = build_service_event_draft(data, client or "", location, event_date, notes, status)
        except ValueError as error:
            st.session_state.pop("pending_service_event", None)
            st.error(str(error))
        else:
            st.session_state["pending_service_event"] = {
                "client": draft.client,
                "city": draft.city,
                "region_code": draft.region_code,
                "state_region": draft.state_region,
                "event_date": draft.event_date,
                "notes": draft.notes,
                "status": draft.status,
                "event_number": draft.event_number,
                "existing_client": draft.existing_client,
            }

    pending = st.session_state.get("pending_service_event")
    if pending:
        st.subheader("Preview")
        render_event_preview(pending)
        save_column, cancel_column = st.columns(2)
        if save_column.button("Save Event", type="primary", width="stretch"):
            try:
                draft = build_service_event_draft(
                    data,
                    pending["client"],
                    f'{pending["city"]}, {pending["region_code"]}',
                    pending["event_date"],
                    pending["notes"],
                    pending["status"],
                )
                saved = append_service_event(data.path, draft)
            except (OSError, ValueError) as error:
                st.error(f"Save failed: {error}")
            else:
                st.cache_data.clear()
                st.session_state.pop("pending_service_event", None)
                st.session_state["last_saved_event"] = {
                    "event_number": saved.event_number,
                    "client": saved.client,
                }
                st.query_params["page"] = "add-service-event"
                st.rerun()
        if cancel_column.button("Cancel", width="stretch"):
            st.session_state.pop("pending_service_event", None)
            st.rerun()

    render_manage_existing_event(data)
    render_scheduled_ticket_management(data)



def _engine_log_event_first_text(raw: str) -> str:
    """Return an event-first display: Events first, batch/output metadata last."""
    if not raw:
        return "No Barrister output found yet."

    lines = raw.splitlines()
    event_start = None
    for i, line in enumerate(lines):
        if line.strip() == "Events":
            event_start = i + 2
            break

    if event_start is None:
        return raw.strip()

    # Stop events at Decision Summary.
    decision_start = None
    for i in range(event_start, len(lines)):
        if lines[i].strip() == "Decision Summary":
            decision_start = i
            break

    events = lines[event_start:decision_start] if decision_start else lines[event_start:]

    rest = lines[decision_start:] if decision_start else []
    batch_lines = [line for line in lines if line.strip().startswith("Batch:")]
    workbook_lines = [line for line in lines if line.strip().startswith("Workbook:")]

    display = []
    display.append("EVENTS")
    display.append("------")
    display.extend(events)

    if rest:
        display.append("")
        display.extend(rest)

    if batch_lines or workbook_lines:
        display.append("")
        display.append("Run Metadata")
        display.append("------------")
        display.extend(batch_lines)
        display.extend(workbook_lines)

    return "\n".join(display).strip()


def render_engine_log_page() -> None:
    st.header("EVENTS")

    local_engine_root = Path.home() / "Documents" / "BarristerEngine" / "BarristerEngine"
    cloud_engine_root = Path(__file__).parent / "BarristerEngine"

    engine_root = (
        local_engine_root
        if local_engine_root.exists()
        else cloud_engine_root
    )
    report_path = engine_root / "logs" / "latest_barrister_output.txt"
    log_dir = engine_root / "logs"

    run_col, status_col = st.columns([1, 3])
    with run_col:
        run_clicked = st.button("Run BarristerEngine", type="primary", width="stretch")
    with status_col:
        status_box = st.empty()

    if run_clicked:
        with st.spinner("Running BarristerEngine..."):
            try:
                result = subprocess.run(
                    ["./run.sh"],
                    cwd=str(engine_root),
                    text=True,
                    capture_output=True,
                    timeout=180,
                )
                if result.returncode == 0:
                    status_box.success("BarristerEngine run complete.")
                else:
                    status_box.error("BarristerEngine run failed.")
                    st.code((result.stderr or result.stdout or "No output")[-4000:], language="text")
            except Exception as e:
                status_box.error(f"Failed to run BarristerEngine: {e}")

    if report_path.exists():
        raw = report_path.read_text(errors="ignore")
        source = report_path
    elif log_dir.exists():
        candidates = sorted(
            list(log_dir.glob("morning_report*.txt")) +
            list(log_dir.glob("engine_v*.txt")) +
            list(log_dir.glob("*.txt")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        source = candidates[0] if candidates else None
        raw = source.read_text(errors="ignore") if source else "No Barrister output found yet."
    else:
        source = None
        raw = f"BarristerEngine logs folder not found:\n{log_dir}"

    text = _engine_log_event_first_text(raw)
    st.text_area("Engine Log", text, height=900, label_visibility="collapsed")
    st.caption(f"Source: {source if source else 'None'}")



def render_navigation(active_page: str) -> None:
    links = []
    for label, slug in DASHBOARD_PAGES.items():
        active_class = " active" if label == active_page else ""
        nav_meta = NAV_DISPLAY.get(label, {"label": label, "icon": "", "accent": "#2dd4bf"})
        links.append(
            f'<a class="top-nav-link{active_class}" href="?page={slug}" target="_self" '
            f'style="--nav-accent: {escape(nav_meta["accent"], quote=True)}" aria-label="{escape(label, quote=True)}">'
            f'<span class="nav-icon">{escape(nav_meta["icon"])}</span>'
            f'<span class="nav-label">{escape(nav_meta["label"])}</span>'
            '</a>'
        )
    st.markdown(
        '<nav class="top-nav" aria-label="Dashboard pages">' + "".join(links) + '</nav>',
        unsafe_allow_html=True,
    )


def main() -> None:
    configure_page()

    has_route_context = bool(dict(st.query_params))
    if not has_route_context:
        render_splash_screen()
        return

    source = find_source_workbook()
    data = cached_workbook(*workbook_version(source)) if source else None

    slug_to_page = {slug: label for label, slug in {**DASHBOARD_PAGES, **HIDDEN_PAGES}.items()}
    slug_to_page.update(PAGE_ROUTE_ALIASES)
    requested_page = slug_to_page.get(st.query_params.get("page", ""))
    if data is None:
        section = requested_page or "Add Service Event"
    else:
        section = requested_page or "Main"
    render_header()
    render_navigation(section)

    if data is None:
        st.warning("No Barrister Source of Truth workbook is available. Place an .xlsx workbook in the data folder.")
        return

    missing = data.validation["missing_required_tabs"] or data.validation["missing_required_columns"]
    if missing:
        st.error("The active workbook has validation issues.")

    timeline = data.timeline.copy()

    if section == "Main":
        render_main_page(data, timeline)
    elif section == "Client Timeline":
        render_barrister_journey(data, completed_chronology(data))
    elif section == "Add Service Event":
        render_add_service_event(data)
    elif section == "Client":
        render_client_analytics(data)
    elif section == "Finance":
        render_financial_analytics(data)
    elif section == "Ledger":
        render_ledger_editor(data)
    elif section == "Designer":
        render_test_tube_page()
    elif section == "Test Tube Two":
        render_test_tube_two_page()

def render_test_tube_two_page() -> None:
    st.markdown("### Test Tube 2 \U0001F52C \u2014 Hero Card Directions")
    st.caption("Four different directions, dummy data, real toggles. Pick one, mix two, or none of them.")

    css = """
<style>
.tt2-wrap { display: flex; flex-direction: column; gap: 1.8rem; margin-top: .5rem; }
.tt2-label { font-size: .58rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; color: var(--kith-warm-gray); margin-bottom: .5rem; }

/* === Design 1: Kinetic Minimal === */
.tt2a-card { border-radius: 20px; border: 1px solid rgba(169,162,154,.2); background: var(--kith-anchor); padding: 1.1rem 1.2rem 1rem; }
.tt2a-seg { display: flex; gap: .3rem; margin-bottom: .7rem; }
.tt2a-seg-btn { padding: .28rem .65rem; border-radius: 999px; font-size: .5rem; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; color: var(--kith-warm-gray); border: 1px solid rgba(169,162,154,.25); cursor: pointer; -webkit-tap-highlight-color: transparent; }
.tt2a-toggle { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.tt2a-fig { display: none; align-items: baseline; gap: .5rem; }
#tt2aFigEvents { display: flex; }
#tt2aEvents:checked ~ .tt2a-body #tt2aFigEvents { display: flex; }
#tt2aClients:checked ~ .tt2a-body #tt2aFigClients { display: flex; }
#tt2aRevenue:checked ~ .tt2a-body #tt2aFigRevenue { display: flex; }
#tt2aClients:checked ~ .tt2a-body #tt2aFigEvents, #tt2aRevenue:checked ~ .tt2a-body #tt2aFigEvents { display: none; }
#tt2aEvents:checked ~ .tt2a-seg label[for="tt2aEvents"], #tt2aClients:checked ~ .tt2a-seg label[for="tt2aClients"], #tt2aRevenue:checked ~ .tt2a-seg label[for="tt2aRevenue"] { background: linear-gradient(135deg, rgba(211,163,168,.32), rgba(124,147,179,.2)); color: var(--kith-chalk); border-color: rgba(211,163,168,.5); }
.tt2a-num { font-size: 3.6rem; font-weight: 900; line-height: .85; letter-spacing: -.04em; color: var(--kith-chalk); }
.tt2a-tag { font-size: 1.1rem; font-weight: 800; letter-spacing: .02em; text-transform: uppercase; color: var(--kith-blush); }
.tt2a-strip { display: flex; gap: 1.1rem; margin-top: .9rem; padding-top: .7rem; border-top: 1px solid rgba(169,162,154,.16); }
.tt2a-strip-item { font-size: .62rem; font-weight: 700; color: var(--kith-warm-gray); }
.tt2a-strip-item strong { color: var(--kith-chalk); font-weight: 900; }

/* === Design 2: Dual Focus === */
.tt2b-card { border-radius: 20px; border: 1px solid rgba(169,162,154,.2); background: var(--kith-elevated-navy); padding: 1.1rem 1.2rem; display: flex; gap: 1rem; align-items: flex-start; justify-content: space-between; }
.tt2b-left { min-width: 0; flex: 1 1 auto; }
.tt2b-tabs { display: flex; gap: 1rem; margin-bottom: .6rem; border-bottom: 1px solid rgba(169,162,154,.18); }
.tt2b-tab { font-size: .56rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--kith-warm-gray); padding-bottom: .4rem; border-bottom: 2px solid transparent; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.tt2b-toggle { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.tt2b-fig { display: none; }
#tt2bFigEvents { display: block; }
#tt2bEvents:checked ~ .tt2b-left #tt2bFigEvents { display: block; }
#tt2bClients:checked ~ .tt2b-left #tt2bFigClients { display: block; }
#tt2bRevenue:checked ~ .tt2b-left #tt2bFigRevenue { display: block; }
#tt2bClients:checked ~ .tt2b-left #tt2bFigEvents, #tt2bRevenue:checked ~ .tt2b-left #tt2bFigEvents { display: none; }
#tt2bEvents:checked ~ .tt2b-tabs label[for="tt2bEvents"], #tt2bClients:checked ~ .tt2b-tabs label[for="tt2bClients"], #tt2bRevenue:checked ~ .tt2b-tabs label[for="tt2bRevenue"] { color: var(--kith-chalk); border-bottom-color: var(--kith-blush); }
.tt2b-num { font-size: 2.6rem; font-weight: 900; line-height: .9; color: var(--kith-chalk); }
.tt2b-unit { font-size: .68rem; font-weight: 700; color: var(--kith-sand); margin-top: .15rem; }
.tt2b-right { flex: 0 0 auto; width: 118px; text-align: right; }
.tt2b-next-label { font-size: .5rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--kith-warm-gray); }
.tt2b-next-name { font-size: .74rem; font-weight: 800; color: var(--kith-chalk); margin-top: .3rem; line-height: 1.2; }
.tt2b-next-when { font-size: .6rem; font-weight: 700; color: var(--kith-blush); margin-top: .15rem; }
.tt2b-streak { margin-top: .7rem; font-size: .58rem; font-weight: 700; color: var(--kith-warm-gray); }
.tt2b-streak strong { color: var(--kith-chalk); }

/* === Design 3: Editorial Stack === */
.tt2c-card { border-radius: 20px; border: 1px solid rgba(169,162,154,.2); background: linear-gradient(160deg, var(--kith-dusty-quartz), var(--kith-anchor) 130%); padding: 1.1rem 1.2rem 1rem; }
.tt2c-eyebrow { font-size: .55rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; color: var(--kith-genesis); margin-bottom: .6rem; }
.tt2c-badge { display: inline-flex; align-items: baseline; gap: .5rem; background: rgba(23,22,26,.35); border-radius: 14px; padding: .6rem 1rem; }
.tt2c-toggle { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.tt2c-fig { display: none; align-items: baseline; gap: .5rem; }
#tt2cFigEvents { display: flex; }
#tt2cEvents:checked ~ .tt2c-badge #tt2cFigEvents { display: flex; }
#tt2cClients:checked ~ .tt2c-badge #tt2cFigClients { display: flex; }
#tt2cRevenue:checked ~ .tt2c-badge #tt2cFigRevenue { display: flex; }
#tt2cClients:checked ~ .tt2c-badge #tt2cFigEvents, #tt2cRevenue:checked ~ .tt2c-badge #tt2cFigEvents { display: none; }
.tt2c-num { font-size: 2.4rem; font-weight: 900; line-height: .85; color: var(--kith-genesis); }
.tt2c-tag { font-size: .7rem; font-weight: 800; text-transform: uppercase; color: var(--kith-genesis); opacity: .7; }
.tt2c-pills { display: flex; gap: .3rem; margin-top: .7rem; }
.tt2c-pill { font-size: .5rem; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; padding: .26rem .55rem; border-radius: 999px; color: var(--kith-genesis); background: rgba(23,22,26,.18); cursor: pointer; -webkit-tap-highlight-color: transparent; }
#tt2cEvents:checked ~ .tt2c-pills label[for="tt2cEvents"], #tt2cClients:checked ~ .tt2c-pills label[for="tt2cClients"], #tt2cRevenue:checked ~ .tt2c-pills label[for="tt2cRevenue"] { background: var(--kith-genesis); color: var(--kith-chalk); }
.tt2c-mini-row { display: flex; justify-content: space-between; margin-top: .9rem; padding-top: .7rem; border-top: 1px solid rgba(23,22,26,.2); }
.tt2c-mini { text-align: center; }
.tt2c-mini-val { font-size: .82rem; font-weight: 900; color: var(--kith-genesis); }
.tt2c-mini-lab { font-size: .46rem; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; color: var(--kith-genesis); opacity: .65; }

/* === Design 4: Glass Gradient (converted from user mockup) === */
.tt2d-card { background: radial-gradient(circle at 102% -15%, rgba(244,114,182,.16), transparent 42%), linear-gradient(135deg, rgba(255,255,255,.055) 0%, rgba(255,255,255,.012) 100%); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,.12); border-radius: 24px; padding: 1.35rem; position: relative; overflow: hidden; box-shadow: 0 20px 44px rgba(0,0,0,.52), inset 0 1px 0 rgba(255,255,255,.15); }
.tt2d-svg-bg { position: absolute; top: 18px; right: -10px; width: 70%; height: 100px; pointer-events: none; z-index: 0; }
.tt2d-svg-bg path { stroke-dasharray: 420; stroke-dashoffset: 420; animation: tt2dDraw 1.4s .2s ease forwards; }
@keyframes tt2dDraw { to { stroke-dashoffset: 0; } }
.tt2d-toprow { display: flex; justify-content: space-between; align-items: flex-start; gap: .75rem; margin-bottom: 1rem; position: relative; z-index: 2; }
.tt2d-section-tag { color: #ec4899; font-size: .56rem; font-weight: 800; letter-spacing: .09em; margin-bottom: .56rem; display: flex; align-items: center; gap: .4rem; white-space: nowrap; }
.tt2d-section-tag::before { content: ""; width: 6px; height: 6px; background: #ec4899; border-radius: 50%; box-shadow: 0 0 8px #ec4899; }
.tt2d-toggle { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.tt2d-pill-group { display: flex; gap: .38rem; }
.tt2d-pill { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); border-radius: 20px; padding: .38rem .8rem; font-size: .6rem; font-weight: 700; color: #64748b; letter-spacing: .03em; white-space: nowrap; cursor: pointer; -webkit-tap-highlight-color: transparent; transition: all .25s ease; }
#tt2dEvents:checked ~ .tt2d-toprow label[for="tt2dEvents"], #tt2dClients:checked ~ .tt2d-toprow label[for="tt2dClients"], #tt2dRevenue:checked ~ .tt2d-toprow label[for="tt2dRevenue"] { background: rgba(244,114,182,.1); border-color: #f472b6; color: #f472b6; box-shadow: 0 0 12px rgba(244,114,182,.3); }
.tt2d-next-box { background: rgba(15,20,32,.68); border: 1px solid rgba(244,114,182,.25); border-radius: 14px; padding: .55rem .85rem; text-align: right; box-shadow: 0 4px 20px rgba(0,0,0,.4); min-width: 128px; max-width: 48%; flex: 0 0 auto; }
.tt2d-next-title { color: #64748b; font-size: .48rem; font-weight: 800; letter-spacing: .06em; }
.tt2d-next-val { overflow: hidden; font-size: .9rem; font-weight: 900; letter-spacing: .01em; color: #fff; text-overflow: ellipsis; white-space: nowrap; margin: .12rem 0; }
.tt2d-next-sub { color: #ec4899; font-size: .6rem; font-weight: 700; }
.tt2d-metric-section { position: relative; z-index: 2; margin: .5rem 0 1.2rem; display: flex; align-items: baseline; min-height: 4.2rem; }
.tt2d-fig { display: none; align-items: baseline; }
#tt2dFigEvents { display: flex; }
#tt2dEvents:checked ~ .tt2d-metric-section #tt2dFigEvents { display: flex; }
#tt2dClients:checked ~ .tt2d-metric-section #tt2dFigClients { display: flex; }
#tt2dRevenue:checked ~ .tt2d-metric-section #tt2dFigRevenue { display: flex; }
#tt2dClients:checked ~ .tt2d-metric-section #tt2dFigEvents, #tt2dRevenue:checked ~ .tt2d-metric-section #tt2dFigEvents { display: none; }
.tt2d-num { font-size: 4.2rem; font-weight: 900; line-height: 1; background: linear-gradient(135deg, #fff 0%, #f472b6 50%, #38bdf8 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; filter: drop-shadow(0 0 25px rgba(244,114,182,.45)); letter-spacing: -.06em; }
@supports not (-webkit-background-clip: text) { .tt2d-num { color: #f472b6; -webkit-text-fill-color: initial; } }
.tt2d-label { font-size: .7rem; font-weight: 800; letter-spacing: .12em; color: #ec4899; margin-left: .7rem; text-shadow: 0 0 10px rgba(236,72,153,.5); }
.tt2d-gauges { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: .5rem; position: relative; z-index: 2; }
.tt2d-gauge { background: linear-gradient(180deg, rgba(255,255,255,.05) 0%, rgba(255,255,255,.01) 100%); border: 1px solid rgba(255,255,255,.08); border-radius: 16px; padding: .68rem .25rem; text-align: center; box-shadow: inset 0 1px 0 rgba(255,255,255,.1); }
.tt2d-gauge.highlight { border-color: rgba(244,114,182,.4); box-shadow: 0 0 15px rgba(244,114,182,.15), inset 0 1px 0 rgba(255,255,255,.2); }
.tt2d-gauge-val { overflow: hidden; font-size: 1.05rem; font-weight: 800; color: #fff; text-overflow: ellipsis; white-space: nowrap; }
.tt2d-gauge-val.pink { color: #f472b6; text-shadow: 0 0 8px rgba(244,114,182,.6); }
.tt2d-gauge-lbl { font-size: .48rem; font-weight: 800; color: #64748b; letter-spacing: .05em; margin-top: .18rem; }
.tt2d-source-line { display: flex; justify-content: space-between; gap: .75rem; margin-top: .75rem; color: #566176; font-size: .48rem; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; }
</style>
"""
    st.markdown(compact(css), unsafe_allow_html=True)

    design_a = (
        '<div class="tt2-label">Design 1 &mdash; Kinetic Minimal</div>'
        '<div class="tt2a-card">'
        '<input type="radio" name="tt2aMetric" id="tt2aEvents" class="tt2a-toggle" checked>'
        '<input type="radio" name="tt2aMetric" id="tt2aClients" class="tt2a-toggle">'
        '<input type="radio" name="tt2aMetric" id="tt2aRevenue" class="tt2a-toggle">'
        '<div class="tt2a-seg">'
        '<label for="tt2aEvents" class="tt2a-seg-btn">Events</label>'
        '<label for="tt2aClients" class="tt2a-seg-btn">Clients</label>'
        '<label for="tt2aRevenue" class="tt2a-seg-btn">Revenue</label></div>'
        '<div class="tt2a-body">'
        '<div class="tt2a-fig" id="tt2aFigEvents"><span class="tt2a-num">88</span><span class="tt2a-tag">Events</span></div>'
        '<div class="tt2a-fig" id="tt2aFigClients"><span class="tt2a-num">31</span><span class="tt2a-tag">Clients</span></div>'
        '<div class="tt2a-fig" id="tt2aFigRevenue"><span class="tt2a-num">＄9.6k</span><span class="tt2a-tag">Revenue</span></div>'
        '</div>'
        '<div class="tt2a-strip">'
        '<span class="tt2a-strip-item"><strong>5</strong>&nbsp;day streak</span>'
        '<span class="tt2a-strip-item">Best month <strong>Jul</strong></span>'
        '<span class="tt2a-strip-item"><strong>5</strong>&nbsp;upcoming</span>'
        '</div></div>'
    )
    st.markdown(compact(design_a), unsafe_allow_html=True)

    design_b = (
        '<div class="tt2-label">Design 2 &mdash; Dual Focus</div>'
        '<div class="tt2b-card">'
        '<input type="radio" name="tt2bMetric" id="tt2bEvents" class="tt2b-toggle" checked>'
        '<input type="radio" name="tt2bMetric" id="tt2bClients" class="tt2b-toggle">'
        '<input type="radio" name="tt2bMetric" id="tt2bRevenue" class="tt2b-toggle">'
        '<div class="tt2b-left">'
        '<div class="tt2b-tabs">'
        '<label for="tt2bEvents" class="tt2b-tab">Events</label>'
        '<label for="tt2bClients" class="tt2b-tab">Clients</label>'
        '<label for="tt2bRevenue" class="tt2b-tab">Revenue</label></div>'
        '<div class="tt2b-fig" id="tt2bFigEvents"><div class="tt2b-num">88</div><div class="tt2b-unit">Events worked</div></div>'
        '<div class="tt2b-fig" id="tt2bFigClients"><div class="tt2b-num">31</div><div class="tt2b-unit">Client roster</div></div>'
        '<div class="tt2b-fig" id="tt2bFigRevenue"><div class="tt2b-num">＄9.6k</div><div class="tt2b-unit">Revenue booked</div></div>'
        '<div class="tt2b-streak"><strong>5</strong>-day streak</div>'
        '</div>'
        '<div class="tt2b-right">'
        '<div class="tt2b-next-label">Next up</div>'
        '<div class="tt2b-next-name">Eastern Shore Warehouse</div>'
        '<div class="tt2b-next-when">TODAY</div>'
        '</div></div>'
    )
    st.markdown(compact(design_b), unsafe_allow_html=True)

    design_c = (
        '<div class="tt2-label">Design 3 &mdash; Editorial Stack</div>'
        '<div class="tt2c-card">'
        '<input type="radio" name="tt2cMetric" id="tt2cEvents" class="tt2c-toggle" checked>'
        '<input type="radio" name="tt2cMetric" id="tt2cClients" class="tt2c-toggle">'
        '<input type="radio" name="tt2cMetric" id="tt2cRevenue" class="tt2c-toggle">'
        '<div class="tt2c-eyebrow">Career to date</div>'
        '<div class="tt2c-badge">'
        '<div class="tt2c-fig" id="tt2cFigEvents"><span class="tt2c-num">88</span><span class="tt2c-tag">Events</span></div>'
        '<div class="tt2c-fig" id="tt2cFigClients"><span class="tt2c-num">31</span><span class="tt2c-tag">Clients</span></div>'
        '<div class="tt2c-fig" id="tt2cFigRevenue"><span class="tt2c-num">＄9.6k</span><span class="tt2c-tag">Revenue</span></div>'
        '</div>'
        '<div class="tt2c-pills">'
        '<label for="tt2cEvents" class="tt2c-pill">Events</label>'
        '<label for="tt2cClients" class="tt2c-pill">Clients</label>'
        '<label for="tt2cRevenue" class="tt2c-pill">Revenue</label></div>'
        '<div class="tt2c-mini-row">'
        '<div class="tt2c-mini"><div class="tt2c-mini-val">5</div><div class="tt2c-mini-lab">Streak</div></div>'
        '<div class="tt2c-mini"><div class="tt2c-mini-val">5</div><div class="tt2c-mini-lab">Jurisd.</div></div>'
        '<div class="tt2c-mini"><div class="tt2c-mini-val">Jul</div><div class="tt2c-mini-lab">Best Mo.</div></div>'
        '<div class="tt2c-mini"><div class="tt2c-mini-val">5</div><div class="tt2c-mini-lab">Upcoming</div></div>'
        '</div></div>'
    )
    st.markdown(compact(design_c), unsafe_allow_html=True)

    design_d = (
        '<div class="tt2-label">Design 4 &mdash; Glass Gradient</div>'
        '<div class="tt2d-card">'
        '<svg class="tt2d-svg-bg" viewBox="0 0 300 100" fill="none" aria-hidden="true">'
        '<path d="M 0 80 C 100 80, 120 10, 300 10" stroke="url(#tt2dPink)" stroke-width="3" opacity="0.6" />'
        '<path d="M 0 90 C 110 90, 130 20, 300 20" stroke="url(#tt2dBlue)" stroke-width="2" opacity="0.4" />'
        '<defs>'
        '<linearGradient id="tt2dPink" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#ec4899" /><stop offset="100%" stop-color="#a855f7" /></linearGradient>'
        '<linearGradient id="tt2dBlue" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#3b82f6" /><stop offset="100%" stop-color="#06b6d4" /></linearGradient>'
        '</defs></svg>'
        '<input type="radio" name="tt2dMetric" id="tt2dEvents" class="tt2d-toggle" checked>'
        '<input type="radio" name="tt2dMetric" id="tt2dClients" class="tt2d-toggle">'
        '<input type="radio" name="tt2dMetric" id="tt2dRevenue" class="tt2d-toggle">'
        '<div class="tt2d-toprow">'
        '<div><div class="tt2d-section-tag">CAREER TO DATE</div>'
        '<div class="tt2d-pill-group">'
        '<label for="tt2dEvents" class="tt2d-pill">EVENTS</label>'
        '<label for="tt2dClients" class="tt2d-pill">CLIENTS</label>'
        '<label for="tt2dRevenue" class="tt2d-pill">REVENUE</label></div></div>'
        '<div class="tt2d-next-box">'
        '<div class="tt2d-next-title">NEXT UP</div>'
        '<div class="tt2d-next-val">Eastern Shore Warehouse</div>'
        '<div class="tt2d-next-sub">TODAY</div>'
        '</div></div>'
        '<div class="tt2d-metric-section">'
        '<div class="tt2d-fig" id="tt2dFigEvents"><span class="tt2d-num">88</span><span class="tt2d-label">EVENTS</span></div>'
        '<div class="tt2d-fig" id="tt2dFigClients"><span class="tt2d-num">31</span><span class="tt2d-label">CLIENTS</span></div>'
        '<div class="tt2d-fig" id="tt2dFigRevenue"><span class="tt2d-num">＄9.6K</span><span class="tt2d-label">REVENUE</span></div>'
        '</div>'
        '<div class="tt2d-gauges">'
        '<div class="tt2d-gauge"><div class="tt2d-gauge-val">5</div><div class="tt2d-gauge-lbl">STREAK</div></div>'
        '<div class="tt2d-gauge"><div class="tt2d-gauge-val">5</div><div class="tt2d-gauge-lbl">JURISD.</div></div>'
        '<div class="tt2d-gauge"><div class="tt2d-gauge-val">5</div><div class="tt2d-gauge-lbl">UPCOMING</div></div>'
        '<div class="tt2d-gauge highlight"><div class="tt2d-gauge-val pink">Jul</div><div class="tt2d-gauge-lbl">BEST MO.</div></div>'
        '</div>'
        '<div class="tt2d-source-line"><span>Timeline &middot; State Coverage &middot; Pipeline</span><span>Live workbook</span></div>'
        '</div>'
    )
    st.markdown(compact(design_d), unsafe_allow_html=True)



def render_test_tube_page() -> None:
    st.markdown("### My Month Colors")
    swatches = [
        ("January", "--kith-month-jan"),
        ("February", "--kith-month-feb"),
        ("March", "--kith-month-mar"),
        ("April", "--kith-month-apr"),
        ("May", "--kith-month-may"),
        ("June", "--kith-month-jun"),
        ("July", "--kith-month-jul"),
        ("August", "--kith-month-aug"),
        ("September", "--kith-month-sep"),
        ("October", "--kith-month-oct"),
        ("November", "--kith-month-nov"),
        ("December", "--kith-month-dec"),
    ]
    grid = '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:.6rem;margin-bottom:1.5rem;">' + "".join(
        f'<div style="aspect-ratio:1;border-radius:14px;background:var({token});display:flex;align-items:center;justify-content:center;border:1px solid rgba(255,255,255,.15);">'
        f'<span style="color:#fff;font-weight:800;font-size:.95rem;text-align:center;text-shadow:0 1px 4px rgba(0,0,0,.7), 0 0 8px rgba(0,0,0,.4);">{escape(month)}</span>'
        f'</div>'
        for month, token in swatches
    ) + '</div>'
    st.markdown(grid, unsafe_allow_html=True)

    st.markdown("### More Color Options")
    pillars = [
        ("1. The Monochromatic Grays", [
            ("Genesis", "#22252A", "34, 37, 42"),
            ("Battleship", "#434A54", "67, 74, 84"),
            ("Mantle", "#656D78", "101, 109, 120"),
            ("Mercury", "#AAB2BD", "170, 178, 189"),
            ("Chalk", "#E6E9ED", "230, 233, 237"),
        ]),
        ("2. The Slate Blues", [
            ("Anchor", "#2B3E50", "43, 62, 80"),
            ("Wave", "#4A6572", "74, 101, 114"),
            ("Echo", "#7D94A1", "125, 148, 161"),
            ("Voyage", "#A3B8C4", "163, 184, 196"),
            ("Helium", "#D1DCE2", "209, 220, 226"),
        ]),
        ("3. The Desert Earths", [
            ("Bark", "#3E2723", "62, 39, 35"),
            ("Redwood", "#5D4037", "93, 64, 55"),
            ("Molecule", "#8D6E63", "141, 110, 99"),
            ("Saddle", "#D7CCC8", "215, 204, 200"),
            ("Hallow", "#F5F5F5", "245, 245, 245"),
        ]),
        ("4. The Dusty Roses & Earthy Pinks", [
            ("Rogue", "#4A2E35", "74, 46, 53"),
            ("Aster", "#78515B", "120, 81, 91"),
            ("Dusty Quartz", "#A37B85", "163, 123, 133"),
            ("Sakura Flower", "#D4B2BA", "212, 178, 186"),
            ("Plaster", "#EFE5E7", "239, 229, 231"),
        ]),
        ("5. The Muted Sage & Olives", [
            ("Canyon", "#2E3D30", "46, 61, 48"),
            ("Leaf Green", "#4D6451", "77, 100, 81"),
            ("Plume", "#7D9480", "125, 148, 128"),
            ("Dusty Sage", "#B3C2B5", "179, 194, 181"),
            ("Alabaster", "#E6ECE7", "230, 236, 231"),
        ]),
        ("6. The Golds & Yellows", [
            ("Melancholy", "#F5E2A3", "245, 226, 163"),
            ("Solar Power", "#E5B83B", "229, 184, 59"),
            ("Super Yellow", "#FFEF00", "255, 239, 0"),
            ("Saffron / Ochre", "#C2923B", "194, 146, 59"),
            ("Honey Gold", "#DCAE5B", "220, 174, 91"),
            ("Canary", "#F4D054", "244, 208, 84"),
        ]),
        ("7. The Wines & Deep Reds", [
            ("Mulberry / Dark Wine", "#533342", "83, 51, 66"),
            ("Magma", "#8B3E2F", "139, 62, 47"),
            ("Dark Beetroot", "#6E2036", "110, 32, 54"),
            ("Roccoco Red", "#B22234", "178, 34, 52"),
            ("Oxblood", "#4A1525", "74, 21, 37"),
            ("Campus Maroon", "#7A1C2C", "122, 28, 44"),
        ]),
        ("8. The Dusty & Petrol Blues", [
            ("Aura / Dusty Blue", "#9BB2C1", "155, 178, 193"),
            ("Anchor / Petrol", "#2E4A56", "46, 74, 86"),
            ("French Clay / Slate", "#5A6E7F", "90, 110, 127"),
            ("Crystalline / Ice Blue", "#D2E2EC", "210, 226, 236"),
            ("Elevated Navy", "#1C2430", "28, 36, 48"),
            ("Cerulean / Sport Blue", "#2A6496", "42, 100, 150"),
            ("Smokey Quartz", "#788B99", "120, 139, 153"),
            ("Stratos / Steel Blue", "#4B6173", "75, 97, 115"),
        ]),
        ("9. The Wisteria & Mulberry", [
            ("Wisteria", "#B7AAB7", "183, 170, 183"),
            ("Aster / Dusty Mauve", "#8E7C85", "142, 124, 133"),
            ("Baroque / Wild Berry", "#53283E", "83, 40, 62"),
            ("Plum / Mulberry", "#4C2B36", "76, 43, 54"),
            ("Current", "#736075", "115, 96, 117"),
            ("Elevation / Midnight Violet", "#2B1E27", "43, 30, 39"),
        ]),
    ]
    for pillar_name, colors in pillars:
        st.markdown(f"**{escape(pillar_name)}**", unsafe_allow_html=True)
        swatch_row = '<div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem;">' + "".join(
            f'<div style="width:108px;border:1px solid rgba(169,162,154,.25);border-radius:10px;overflow:hidden;background:rgba(23,22,26,.5);">'
            f'<div style="height:54px;background:{hex_val};"></div>'
            f'<div style="padding:.4rem .5rem;">'
            f'<div style="color:#f7f2ea;font-size:.72rem;font-weight:700;">{escape(name)}</div>'
            f'<div style="color:#a9a29a;font-family:monospace;font-size:.62rem;">{hex_val}</div>'
            f'<div style="color:#a9a29a;font-family:monospace;font-size:.6rem;">{rgb_val}</div>'
            f'</div></div>'
            for name, hex_val, rgb_val in colors
        ) + '</div>'
        st.markdown(swatch_row, unsafe_allow_html=True)

    st.markdown("### Font Preview")
    st.caption("Same sample text, 20 font choices. Tell me which ones to keep.")
    fonts = [
        "Raleway", "Fjalla One", "Abril Fatface", "Libre Baskerville", "Crimson Text",
        "Josefin Sans", "Teko", "Bungee", "Righteous", "Outfit",
        "Sora", "Manrope", "IBM Plex Mono", "Staatliches", "Fraunces",
        "Inter", "Poppins", "Montserrat", "Work Sans", "Space Grotesk",
        "Oswald", "Bebas Neue", "Anton", "Barlow Condensed", "Archivo Black",
        "Playfair Display", "Merriweather", "Georgia", "Lora", "DM Serif Display",
        "Cormorant Garamond", "Quicksand", "Nunito", "JetBrains Mono", "Rajdhani",
    ]
    google_families = "&family=".join(f.replace(" ", "+") + ":wght@700;900" for f in fonts if f not in ("Georgia",))
    font_import = f'<link href="https://fonts.googleapis.com/css2?family={google_families}&display=swap" rel="stylesheet">'
    st.markdown(font_import, unsafe_allow_html=True)

    half = (len(fonts) + 1) // 2
    col_left, col_right = st.columns(2)
    for col, group in ((col_left, fonts[:half]), (col_right, fonts[half:])):
        with col:
            rows = "".join(
                f'<div style="border:1px solid rgba(169,162,154,.22);border-radius:10px;padding:.6rem .7rem;margin-bottom:.5rem;background:rgba(23,22,26,.5);">'
                f'<div style="color:#a9a29a;font-family:monospace;font-size:.55rem;margin-bottom:.25rem;">{escape(fname)}</div>'
                f'<div style="color:#f7f2ea;font-family:\'{escape(fname)}\',sans-serif;font-weight:800;font-size:1.15rem;line-height:1.15;">Events 88 Clients 31 Weekly</div>'
                f'</div>'
                for fname in group
            )
            st.markdown(compact(rows), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
