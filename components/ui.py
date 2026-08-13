from __future__ import annotations

from html import escape
from typing import Dict, Iterable, Tuple
from textwrap import dedent

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from services.metrics import ExecutiveMetrics, _compact_money
from services.money_view import annualize_gross, gross_up, DAYS_PER_YEAR
from components.trends import build_trends_fragment, TRENDS_CSS_RULES
from components.journey import JURISDICTION_COLORS, TERRITORY_CENTER_COLOR, jurisdiction_group


PALETTE = [
    "#f05d73",
    "#f2b84b",
    "#5c8dff",
    "#59d39a",
    "#a879ff",
    "#37c7d4",
]


def render_html(markup: str) -> None:
    normalized = "".join(
        line.strip()
        for line in dedent(markup).splitlines()
        if line.strip()
    )
    st.markdown(
        normalized,
        unsafe_allow_html=True,
    )


ICONS = {
    "Completed Events": "✓",
    "Unique Clients": "◆",
    "Repeat Clients": "↻",
    "Jurisdictions": "⌖",
    "Career Revenue": "$",
    "Verified Revenue": "✓$",
    "Upcoming": "→",
    "Completion Rate": "%",
}



def render_dashboard(metrics: ExecutiveMetrics, timeline: "pd.DataFrame", gross_view: bool = False) -> None:
    hero = metrics.hero
    data = metrics.data_views
    leaderboard = list(data.get("leaderboard", []))
    jurisdictions = list(data.get("jurisdictions", []))
    palette = ["#f472b6", "#38bdf8", "#fde68a", "#c084fc", "#34d399", "#fb7185"]

    events_value = escape(str(hero["events_value"]))
    clients_value = escape(str(hero["clients_value"]))
    revenue_value = escape(
        _compact_money(gross_up(metrics.total_revenue)) if gross_view else str(hero["revenue_value"])
    )
    next_client = escape(str(hero["next_client"]))
    next_date = escape(str(hero["next_date"]))
    streak_value = escape(str(hero["streak_value"]))
    cities_value = escape(str(hero["cities_value"]))
    longest_streak_value = escape(str(hero["longest_streak_value"]))
    current_streak_value = escape(str(hero["current_streak_value"]))
    jurisdictions_value = escape(str(hero["jurisdictions_value"]))
    upcoming_value = escape(str(hero["upcoming_value"]))
    best_month_value = escape(str(hero["best_month_value"]))
    best_month_events = hero.get("best_month_events")
    best_month_caption = (
        f"{int(best_month_events)} events" if best_month_events is not None else "Service dates unavailable"
    )
    streak_caption = "business-day streak" if hero.get("streak_available") else "Service dates unavailable"

    if leaderboard:
        leader = leaderboard[0]
        leader_summary = (
            f'<span class="pink-highlight">{escape(str(leader["client"]))}</span> '
            f'leads at <span class="pink-highlight">{int(leader["events"]):,}</span> events.'
        )
    else:
        leader_summary = "No completed client activity is available."

    leaderboard_rows = []
    for rank, item in enumerate(leaderboard, start=1):
        active = " active" if rank == 1 else ""
        leaderboard_rows.append(
            f'<div class="tower-block{active}">'
            f'<div class="rank-num{active}">{rank}</div>'
            f'<div class="client-name">{escape(str(item["client"]))}</div>'
            f'<div class="event-total">{int(item["events"]):,}</div>'
            f'</div>'
        )
    if not leaderboard_rows:
        leaderboard_rows.append('<div class="empty-state">No completed client activity.</div>')

    total_events = int(data.get("completed_events", metrics.completed_events))
    jurisdiction_count = int(data.get("jurisdiction_count", len(jurisdictions)))

    if jurisdictions:
        leader_j = jurisdictions[0]
        jurisdiction_summary = (
            f'<span class="pink-highlight">{escape(str(leader_j["name"]))}</span> leads with '
            f'<span class="pink-highlight">{int(leader_j["events"]):,}</span> events'
        )
    else:
        jurisdiction_summary = "No completed jurisdiction activity."

    offset = 0.0
    arc_paths = []
    jurisdiction_rows = []
    for index, item in enumerate(jurisdictions):
        color = JURISDICTION_COLORS.get(jurisdiction_group(item["name"]), JURISDICTION_COLORS["Pennsylvania / Other"])
        share = float(item["share"])
        arc_paths.append(
            f'<path class="arc-segment" style="stroke:{color};" '
            f'stroke-dasharray="{share:.3f} 100" stroke-dashoffset="-{offset:.3f}" '
            f'd="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 '
            f'a 15.9155 15.9155 0 0 1 0 -31.831"/>'
        )
        offset += share
        jurisdiction_rows.append(
            f'<div class="juris-item">'
            f'<div class="color-dot" style="background-color:{color};"></div>'
            f'<div class="juris-name">{escape(str(item["name"]))}</div>'
            f'<div class="juris-pct">{share:.1f}%</div>'
            f'</div>'
        )
    if not jurisdiction_rows:
        jurisdiction_rows.append('<div class="empty-state">No completed jurisdiction activity.</div>')

    trends_fragment = build_trends_fragment(timeline, gross_view)

    repeat_clients = int(timeline["Client"].value_counts().gt(1).sum()) if not timeline.empty else 0
    unique_clients_count = int(timeline["Client"].nunique()) if not timeline.empty else 0
    repeat_rate = round(repeat_clients / max(1, unique_clients_count) * 100)

    ticker_work = timeline.copy()
    ticker_work["__date"] = pd.to_datetime(ticker_work["Service Date"], errors="coerce")
    ticker_work["__amount"] = pd.to_numeric(ticker_work["Amount"], errors="coerce").fillna(0)
    ticker_dated = ticker_work.dropna(subset=["__date"])
    ticker_confirmed = ticker_dated[ticker_dated["Verified?"] == "Yes"]

    business_days = int(ticker_dated["__date"].dt.normalize().nunique()) or 1
    total_events_count = len(ticker_work)
    avg_events_per_day = total_events_count / business_days
    avg_dollar_per_day = float(ticker_confirmed["__amount"].sum()) / business_days

    if not ticker_confirmed.empty:
        calendar_month = ticker_confirmed["__date"].dt.to_period("M")
        highest_month = float(ticker_confirmed.groupby(calendar_month)["__amount"].sum().max())
        iso = ticker_confirmed["__date"].dt.isocalendar()
        highest_week = float(ticker_confirmed.groupby([iso["year"], iso["week"]])["__amount"].sum().max())
        highest_day = float(ticker_confirmed.groupby(ticker_confirmed["__date"].dt.normalize())["__amount"].sum().max())
    else:
        highest_month = highest_week = highest_day = 0.0

    if gross_view:
        avg_day_display = annualize_gross(avg_dollar_per_day, DAYS_PER_YEAR)
        avg_day_item = f'\U0001F4B5 avg <strong>\uFF04{escape(f"{avg_day_display:,.0f}")}</strong>/yr'
    else:
        avg_day_item = f'\U0001F4B5 avg <strong>\uFF04{escape(f"{avg_dollar_per_day:,.0f}")}</strong>/day worked'

    ticker_items = [
        f'\U0001F3C6 <strong>{total_events_count}</strong> events in <strong>{business_days}</strong> days',
        f'\U0001F3AF avg <strong>{avg_events_per_day:.2f}</strong> events/day',
        f'\U0001F91D <strong>{clients_value}</strong> clients &middot; {repeat_rate}% repeat',
        f'\U0001F525 Current Streak: <strong>{current_streak_value} day{"s" if current_streak_value != "1" else ""}</strong> (Record: <strong>{longest_streak_value}</strong>)',
        f'\U0001F3C5 best month <strong>{best_month_value}</strong>',
        avg_day_item,
        f'\U0001F4C8 top month pace <strong>\uFF04{escape(f"{highest_month * 12:,.0f}")}</strong>/yr',
        f'\U0001F4C8 top week pace <strong>\uFF04{escape(f"{highest_week * 52:,.0f}")}</strong>/yr',
        f'\U0001F4C8 top day pace <strong>\uFF04{escape(f"{highest_day * 365:,.0f}")}</strong>/yr',
    ]
    ticker_markup = "".join(f'<span class="main-ticker-item">{item}</span>' for item in ticker_items * 2)

    html = f"""
    <!DOCTYPE html>
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
    *{{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
    html,body{{width:100%;overflow:hidden;background:transparent}}
    body{{padding:8px 4px 12px;color:#fff}}
    .panel{{margin-bottom:16px}}
    .glass-card{{background:radial-gradient(circle at 102% -15%,rgba(244,114,182,.15),transparent 42%),linear-gradient(135deg,rgba(255,255,255,.055) 0%,rgba(255,255,255,.012) 100%);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.12);border-radius:24px;padding:20px;position:relative;overflow:hidden;box-shadow:0 20px 44px rgba(0,0,0,.52),inset 0 1px 0 rgba(255,255,255,.15)}}
    .top-row{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:15px;position:relative;z-index:2}}
    .section-tag{{color:#ec4899;font-size:9px;font-weight:800;letter-spacing:1.5px;margin-bottom:8px;display:flex;align-items:center;gap:6px;white-space:nowrap}}
    .section-tag::before{{content:"";width:6px;height:6px;background-color:#ec4899;border-radius:50%;box-shadow:0 0 8px #ec4899}}
    .pill-group{{display:flex;gap:6px}}
    .pill{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:20px;padding:5px 12px;font-size:11.5px;font-weight:800;color:#b8c4d9;letter-spacing:.5px;white-space:nowrap;cursor:pointer;user-select:none}}
    .pill.active{{background:rgba(244,114,182,.1);border-color:#f472b6;color:#f472b6;box-shadow:0 0 12px rgba(244,114,182,.3)}}
    .next-up-box{{background:rgba(15,20,32,.68);border:1px solid rgba(244,114,182,.25);border-radius:14px;padding:8px 14px;text-align:right;box-shadow:0 4px 20px rgba(0,0,0,.4);min-width:128px;max-width:48%;flex:0 0 auto}}
    .next-up-title{{color:#b8c4d9;font-size:10px;font-weight:800;letter-spacing:1px}}
    .next-up-val{{overflow:hidden;font-size:14px;font-weight:900;letter-spacing:.6px;text-transform:uppercase;color:#fff;text-overflow:ellipsis;white-space:nowrap}}
    .next-up-sub{{color:#f9a8d4;font-size:11.5px;font-weight:900;letter-spacing:.5px;text-transform:uppercase;text-shadow:0 0 10px rgba(244,114,182,.6)}}
    .hero-metric-section{{position:relative;z-index:2;margin:10px 0 20px;display:flex;align-items:baseline}}
    .hero-number{{font-size:76px;font-weight:900;line-height:1;background:linear-gradient(135deg,#fff 0%,#f472b6 50%,#38bdf8 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;filter:drop-shadow(0 0 25px rgba(244,114,182,.45));letter-spacing:-2px;transition:opacity .15s ease}}
    .hero-label{{font-size:12px;font-weight:800;letter-spacing:2px;color:#ec4899;margin-left:12px;text-shadow:0 0 10px rgba(236,72,153,.5)}}
    .svg-bg{{position:absolute;top:20px;right:-10px;width:70%;height:100px;pointer-events:none;z-index:0}}
    .gauges-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;position:relative;z-index:2}}
    .gauge-item{{background:linear-gradient(180deg,rgba(255,255,255,.05) 0%,rgba(255,255,255,.01) 100%);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:10px 4px;text-align:center;box-shadow:inset 0 1px 0 rgba(255,255,255,.1)}}
    .gauge-item.highlight{{border-color:rgba(244,114,182,.4);box-shadow:0 0 15px rgba(244,114,182,.15),inset 0 1px 0 rgba(255,255,255,.2)}}
    .gauge-clickable{{cursor:pointer;transition:transform .15s ease,box-shadow .15s ease}}
    .gauge-clickable:active{{transform:scale(.95)}}
    .gauge-clickable:hover{{border-color:rgba(244,114,182,.5);box-shadow:0 0 12px rgba(244,114,182,.2),inset 0 1px 0 rgba(255,255,255,.15)}}
    .gauge-val{{overflow:hidden;font-size:18px;font-weight:800;color:#fff;text-overflow:ellipsis;white-space:nowrap}}
    .gauge-val.pink{{color:#f472b6;text-shadow:0 0 8px rgba(244,114,182,.6)}}
    .gauge-lbl{{font-size:10px;font-weight:800;color:#b8c4d9;letter-spacing:.9px;margin-top:3px}}
    .source-line{{display:flex;justify-content:space-between;gap:12px;margin-top:10px;color:#566176;font-size:8px;font-weight:700;letter-spacing:.45px;text-transform:uppercase}}
    .frosted-panel{{background:radial-gradient(circle at 100% -10%,rgba(244,114,182,.08),transparent 42%),rgba(23,27,40,.55);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.12);border-radius:20px;padding:20px;position:relative;overflow:hidden;box-shadow:0 15px 35px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.1)}}
    .section-header{{margin-bottom:15px;position:relative;z-index:2}}
    .section-title{{font-size:13px;font-weight:800;letter-spacing:1.5px;color:#fff;text-transform:uppercase}}
    .section-sub{{font-size:11.5px;font-weight:800;letter-spacing:.3px;color:#b8c4d9;margin-top:3px;line-height:1.5;text-transform:uppercase}}
    .pink-highlight{{color:#f472b6;font-weight:700}}
    .leaderboard-tower{{display:flex;flex-direction:column;gap:8px}}
    .tower-block{{display:grid;grid-template-columns:20px minmax(0,1fr) 32px;align-items:center;background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.01));border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:8px 12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.1)}}
    .tower-block.active{{border-color:rgba(244,114,182,.4);box-shadow:0 0 15px rgba(244,114,182,.15),inset 0 1px 0 rgba(255,255,255,.2)}}
    .rank-num{{font-size:11.5px;font-weight:800;color:#b8c4d9;text-align:center}} .rank-num.active{{color:#f472b6}}
    .client-name{{overflow:hidden;font-size:11px;font-weight:700;color:#fff;text-transform:uppercase;padding:0 10px;text-overflow:ellipsis;white-space:nowrap}}
    .event-total{{font-size:14px;font-weight:900;color:#f472b6;text-align:right;text-shadow:0 0 8px rgba(244,114,182,.6)}}
    .territory-split{{display:grid;grid-template-columns:minmax(140px,.9fr) minmax(0,1.1fr);align-items:center;gap:8px;position:relative}}
    .neon-pipe-bg{{position:absolute;top:20px;right:-20px;width:80%;height:60px;pointer-events:none;z-index:1}}
    .chart-section{{display:flex;justify-content:center;position:relative;z-index:2}}
    .arc-container{{width:189px;height:189px;position:relative;display:flex;align-items:center;justify-content:center}}
    .total-number{{position:absolute;font-size:48px;font-weight:900;color:{TERRITORY_CENTER_COLOR};filter:drop-shadow(0 0 18px rgba(255,255,255,.5));line-height:1}}
    .arc-svg{{transform:rotate(-90deg)}} .arc-base{{fill:none;stroke:rgba(255,255,255,.05);stroke-width:13.5}} .arc-segment{{fill:none;stroke-width:13.5;stroke-linecap:butt}}
    .jurisdiction-list{{display:flex;flex-direction:column;gap:10px;position:relative;z-index:2}}
    .juris-item{{display:grid;grid-template-columns:20px minmax(0,1fr) 46px;align-items:center;background:rgba(15,23,42,.6);border:1px solid rgba(255,255,255,.05);border-radius:50px;padding:8px 12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)}}
    .color-dot{{width:10px;height:10px;border-radius:50%}}
    .juris-name{{overflow:hidden;font-size:11.5px;font-weight:800;color:#c5d0e0;text-transform:uppercase;padding:0 10px;text-overflow:ellipsis;white-space:nowrap}}
    .juris-pct{{font-size:12px;font-weight:900;color:#fff;text-align:right}}
    .empty-state{{color:#b8c4d9;font-size:12.5px;padding:12px;text-align:center}}
    @media(max-width:520px){{
      body{{padding:4px 0 10px}}
      .glass-card{{padding:16px 14px}}
      .top-row{{gap:8px}}
      .pill{{padding:5px 8px;font-size:9px}}
      .next-up-box{{min-width:104px;padding:7px 10px}}
      .hero-number{{font-size:64px}}
      .hero-label{{margin-left:8px}}
      .gauges-grid{{gap:6px}}
      .gauge-item{{padding:9px 2px}}
      .gauge-val{{font-size:17px}}
      .gauge-lbl{{font-size:9px}}
      .frosted-panel{{padding:16px 14px}}
      .territory-split{{grid-template-columns:132px minmax(0,1fr)}}
      .arc-container{{width:173px;height:173px}}
      .total-number{{font-size:42px}}
      .jurisdiction-list{{gap:7px}}
      .juris-item{{grid-template-columns:16px minmax(0,1fr) 42px;padding:7px 9px}}
      .juris-name{{padding:0 6px;font-size:10.5px}}
      .juris-pct{{font-size:11px}}
    }}
    {TRENDS_CSS_RULES}
    .main-ticker{{position:relative;overflow:hidden;height:28px;margin:0 0 8px;border-radius:10px;border:1px solid rgba(255,255,255,.08);background:linear-gradient(90deg,rgba(23,27,40,.7),rgba(15,20,32,.7))}}
    .main-ticker::before,.main-ticker::after{{content:"";position:absolute;top:0;bottom:0;width:20px;z-index:1;pointer-events:none}}
    .main-ticker::before{{left:0;background:linear-gradient(90deg,rgba(15,20,32,.9),transparent)}}
    .main-ticker::after{{right:0;background:linear-gradient(270deg,rgba(15,20,32,.9),transparent)}}
    .main-ticker-track{{display:flex;align-items:center;gap:1.5rem;width:max-content;height:100%;padding:0 .8rem;animation:mainTickerScroll 60s linear infinite}}
    .main-ticker-item{{display:inline-block;flex-shrink:0;white-space:nowrap;font-size:10px;font-weight:800;letter-spacing:.03em;text-transform:uppercase;color:#b8c4d9}}
    .main-ticker-item strong{{color:#f472b6;font-weight:900}}
    @keyframes mainTickerScroll{{from{{transform:translateX(0)}}to{{transform:translateX(-50%)}}}}
    </style></head>
    <body>
      <div class="main-ticker"><div class="main-ticker-track">{ticker_markup}</div></div>
      <div class="glass-card panel">
        <svg class="svg-bg" viewBox="0 0 300 100" fill="none" aria-hidden="true">
          <path d="M 0 80 C 100 80, 120 10, 300 10" stroke="url(#pink-grad)" stroke-width="3" opacity="0.6"/>
          <path d="M 0 90 C 110 90, 130 20, 300 20" stroke="url(#blue-grad)" stroke-width="2" opacity="0.4"/>
          <defs>
            <linearGradient id="pink-grad" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#ec4899"/><stop offset="100%" stop-color="#a855f7"/></linearGradient>
            <linearGradient id="blue-grad" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#3b82f6"/><stop offset="100%" stop-color="#06b6d4"/></linearGradient>
          </defs>
        </svg>

        <div class="top-row">
          <div>
            <div class="section-tag">CAREER TO DATE</div>
            <div class="pill-group">
              <div class="pill active" id="pillEvents" data-value="{events_value}" data-label="EVENTS" title="{events_value} completed events">EVENTS</div>
              <div class="pill" id="pillClients" data-value="{clients_value}" data-label="CLIENTS" title="{clients_value} unique clients">CLIENTS</div>
              <div class="pill" id="pillRevenue" data-value="{revenue_value}" data-label="REVENUE" title="{revenue_value} known revenue">REVENUE</div>
            </div>
          </div>
          <div class="next-up-box">
            <div class="next-up-title">NEXT UP</div>
            <div class="next-up-val">{next_client}</div>
            <div class="next-up-sub">{next_date}</div>
          </div>
        </div>

        <div class="hero-metric-section">
          <span class="hero-number" id="heroNumber">{events_value}</span>
          <span class="hero-label" id="heroLabel">EVENTS</span>
        </div>

        <div class="gauges-grid">
          <div class="gauge-item" title="Unique cities visited">
            <div class="gauge-val">{cities_value}</div>
            <div class="gauge-lbl">CITIES</div>
          </div>
          <div class="gauge-item gauge-clickable" id="gaugeJurisd" title="Jump to Territory &amp; Jurisdictions">
            <div class="gauge-val">{jurisdictions_value}</div>
            <div class="gauge-lbl">JURISD.</div>
          </div>
          <div class="gauge-item gauge-clickable" id="gaugeUpcoming" title="Go to Events">
            <div class="gauge-val">{upcoming_value}</div>
            <div class="gauge-lbl">UPCOMING</div>
          </div>
          <div class="gauge-item highlight gauge-clickable" id="gaugeBestMonth" title="{escape(best_month_caption)} &mdash; jump to Performance Trends">
            <div class="gauge-val pink">{best_month_value}</div>
            <div class="gauge-lbl">BEST MO.</div>
          </div>
        </div>
      </div>

      {trends_fragment}

      <div class="frosted-panel panel" id="territoryPanel">
        <svg class="neon-pipe-bg" viewBox="0 0 300 100" fill="none" aria-hidden="true">
          <path d="M 0 60 C 100 60, 150 10, 300 10" stroke="url(#blue-grad2)" stroke-width="2" opacity="0.4"/>
          <path d="M 0 70 C 110 70, 160 20, 300 20" stroke="url(#pink-grad2)" stroke-width="3" opacity="0.6"/>
          <defs>
            <linearGradient id="pink-grad2" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#ec4899"/><stop offset="100%" stop-color="#a855f7"/></linearGradient>
            <linearGradient id="blue-grad2" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#3b82f6"/><stop offset="100%" stop-color="#06b6d4"/></linearGradient>
          </defs>
        </svg>
        <div class="section-header">
          <div class="section-title">TERRITORY &amp; JURISDICTIONS</div>
          <div class="section-sub">{jurisdiction_summary}</div>
        </div>
        <div class="territory-split">
          <div class="chart-section">
            <div class="arc-container">
              <svg class="arc-svg" width="135" height="135" viewBox="0 0 36 36">
                <path class="arc-base" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
                {''.join(arc_paths)}
              </svg>
              <div class="total-number">{total_events:,}</div>
            </div>
          </div>
          <div class="jurisdiction-list">{''.join(jurisdiction_rows)}</div>
        </div>
      </div>

      <script>
        (function() {{
          var pills = [document.getElementById('pillEvents'), document.getElementById('pillClients'), document.getElementById('pillRevenue')];
          var heroNumber = document.getElementById('heroNumber');
          var heroLabel = document.getElementById('heroLabel');
          pills.forEach(function(pill) {{
            pill.addEventListener('click', function() {{
              pills.forEach(function(p) {{ p.classList.remove('active'); }});
              pill.classList.add('active');
              heroNumber.style.opacity = '0';
              setTimeout(function() {{
                heroNumber.textContent = pill.getAttribute('data-value');
                heroLabel.textContent = pill.getAttribute('data-label');
                heroNumber.style.opacity = '1';
              }}, 120);
            }});
          }});

          function scrollParentToElement(el) {{
            if (!el) return;
            try {{
              el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
            }} catch (e) {{}}
          }}

          var gaugeJurisd = document.getElementById('gaugeJurisd');
          if (gaugeJurisd) {{
            gaugeJurisd.addEventListener('click', function() {{
              scrollParentToElement(document.getElementById('territoryPanel'));
            }});
          }}

          var gaugeBestMonth = document.getElementById('gaugeBestMonth');
          if (gaugeBestMonth) {{
            gaugeBestMonth.addEventListener('click', function() {{
              var monthlyTab = document.querySelector('[data-period="monthly"]');
              var revenueTab = document.querySelector('[data-metric="revenue"]');
              if (monthlyTab) monthlyTab.click();
              if (revenueTab) revenueTab.click();
              scrollParentToElement(document.getElementById('trendsPanel'));
            }});
          }}

          var gaugeUpcoming = document.getElementById('gaugeUpcoming');
          if (gaugeUpcoming) {{
            gaugeUpcoming.addEventListener('click', function() {{
              try {{
                var doc = window.parent.document;
                var btns = doc.querySelectorAll('div[data-testid="stButton"] button');
                for (var i = 0; i < btns.length; i++) {{
                  if (btns[i].textContent.trim() === 'View Upcoming Events') {{
                    btns[i].click();
                    break;
                  }}
                }}
              }} catch (e) {{}}
            }});
          }}

          (function hideHeroNavHelper() {{
            try {{
              var doc = window.parent.document;
              var btns = doc.querySelectorAll('div[data-testid="stButton"] button');
              for (var i = 0; i < btns.length; i++) {{
                if (btns[i].textContent.trim() === 'View Upcoming Events') {{
                  var wrap = btns[i].closest('div[data-testid="stButton"]');
                  if (wrap) wrap.style.display = 'none';
                  break;
                }}
              }}
            }} catch (e) {{}}
          }})();
        }})();
      </script>
    </body></html>
    """

    height = 36 + 300 + 472 + 16 + 240 + max(len(jurisdictions) - 4, 0) * 36
    components.html(html, height=height, scrolling=False)


def render_performance_hero(

    metrics: ExecutiveMetrics,
) -> None:
    hero = metrics.hero

    events_value = escape(
        str(hero["events_value"])
    )
    clients_value = escape(
        str(hero["clients_value"])
    )
    revenue_value = escape(
        str(hero["revenue_value"])
    )
    next_client = escape(
        str(hero["next_client"])
    )
    next_date = escape(
        str(hero["next_date"])
    )
    streak_value = escape(
        str(hero["streak_value"])
    )
    jurisdictions_value = escape(
        str(hero["jurisdictions_value"])
    )
    upcoming_value = escape(
        str(hero["upcoming_value"])
    )
    best_month_value = escape(
        str(hero["best_month_value"])
    )

    best_month_events = hero.get(
        "best_month_events"
    )

    best_month_caption = (
        f"{int(best_month_events)} events"
        if best_month_events is not None
        else "Service dates unavailable"
    )

    streak_caption = (
        "business-day streak"
        if hero.get("streak_available")
        else "Service dates unavailable"
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >

        <style>
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
                font-family:
                    -apple-system,
                    BlinkMacSystemFont,
                    "Segoe UI",
                    Roboto,
                    sans-serif;
            }}

            html,
            body {{
                width: 100%;
                overflow: hidden;
                background: transparent;
            }}

            body {{
                color: #ffffff;
                padding: 8px 4px 12px;
            }}

            .glass-card {{
                background:
                    radial-gradient(
                        circle at 102% -15%,
                        rgba(244, 114, 182, 0.15),
                        transparent 42%
                    ),
                    linear-gradient(
                        135deg,
                        rgba(255,255,255,0.055) 0%,
                        rgba(255,255,255,0.012) 100%
                    );
                backdrop-filter: blur(20px);
                -webkit-backdrop-filter: blur(20px);
                border:
                    1px solid
                    rgba(255, 255, 255, 0.12);
                border-radius: 24px;
                padding: 20px;
                position: relative;
                overflow: hidden;
                box-shadow:
                    0 20px 44px rgba(0,0,0,0.52),
                    inset 0 1px 0 rgba(255,255,255,0.15);
            }}

            .top-row {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 12px;
                margin-bottom: 15px;
                position: relative;
                z-index: 2;
            }}

            .section-tag {{
                color: #ec4899;
                font-size: 9px;
                font-weight: 800;
                letter-spacing: 1.5px;
                margin-bottom: 8px;
                display: flex;
                align-items: center;
                gap: 6px;
                white-space: nowrap;
            }}

            .section-tag::before {{
                content: "";
                width: 6px;
                height: 6px;
                background-color: #ec4899;
                border-radius: 50%;
                box-shadow: 0 0 8px #ec4899;
            }}

            .pill-group {{
                display: flex;
                gap: 6px;
            }}

            .pill {{
                background: rgba(255, 255, 255, 0.04);
                border:
                    1px solid
                    rgba(255, 255, 255, 0.08);
                border-radius: 20px;
                padding: 5px 12px;
                font-size: 10px;
                font-weight: 700;
                color: #64748b;
                letter-spacing: 0.5px;
                white-space: nowrap;
            }}

            .pill.active {{
                background: rgba(244, 114, 182, 0.1);
                border-color: #f472b6;
                color: #f472b6;
                box-shadow:
                    0 0 12px
                    rgba(244, 114, 182, 0.3);
            }}

            .next-up-box {{
                background: rgba(15, 20, 32, 0.68);
                border:
                    1px solid
                    rgba(244, 114, 182, 0.25);
                border-radius: 14px;
                padding: 8px 14px;
                text-align: right;
                box-shadow:
                    0 4px 20px
                    rgba(0,0,0,0.4);
                min-width: 128px;
                max-width: 48%;
                flex: 0 0 auto;
            }}

            .next-up-title {{
                color: #64748b;
                font-size: 8px;
                font-weight: 800;
                letter-spacing: 1px;
            }}

            .next-up-val {{
                overflow: hidden;
                font-size: 14px;
                font-weight: 900;
                letter-spacing: 0.3px;
                color: #fff;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}

            .next-up-sub {{
                color: #ec4899;
                font-size: 10px;
                font-weight: 700;
            }}

            .hero-metric-section {{
                position: relative;
                z-index: 2;
                margin: 10px 0 20px;
                display: flex;
                align-items: baseline;
            }}

            .hero-number {{
                font-size: 76px;
                font-weight: 900;
                line-height: 1;
                background:
                    linear-gradient(
                        135deg,
                        #ffffff 0%,
                        #f472b6 50%,
                        #38bdf8 100%
                    );
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                filter:
                    drop-shadow(
                        0 0 25px
                        rgba(244, 114, 182, 0.45)
                    );
                letter-spacing: -2px;
            }}

            .hero-label {{
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 2px;
                color: #ec4899;
                margin-left: 12px;
                text-shadow:
                    0 0 10px
                    rgba(236, 72, 153, 0.5);
            }}

            .svg-bg {{
                position: absolute;
                top: 20px;
                right: -10px;
                width: 70%;
                height: 100px;
                pointer-events: none;
                z-index: 0;
            }}

            .gauges-grid {{
                display: grid;
                grid-template-columns:
                    repeat(4, minmax(0, 1fr));
                gap: 8px;
                position: relative;
                z-index: 2;
            }}

            .gauge-item {{
                background:
                    linear-gradient(
                        180deg,
                        rgba(255,255,255,0.05) 0%,
                        rgba(255,255,255,0.01) 100%
                    );
                border:
                    1px solid
                    rgba(255, 255, 255, 0.08);
                border-radius: 16px;
                padding: 10px 4px;
                text-align: center;
                box-shadow:
                    inset 0 1px 0
                    rgba(255,255,255,0.1);
            }}

            .gauge-item.highlight {{
                border-color:
                    rgba(244, 114, 182, 0.4);
                box-shadow:
                    0 0 15px
                    rgba(244, 114, 182, 0.15),
                    inset 0 1px 0
                    rgba(255,255,255,0.2);
            }}

            .gauge-val {{
                overflow: hidden;
                font-size: 18px;
                font-weight: 800;
                color: #ffffff;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}

            .gauge-val.pink {{
                color: #f472b6;
                text-shadow:
                    0 0 8px
                    rgba(244, 114, 182, 0.6);
            }}

            .gauge-lbl {{
                font-size: 8px;
                font-weight: 800;
                color: #64748b;
                letter-spacing: 0.9px;
                margin-top: 2px;
            }}

            .source-line {{
                display: flex;
                justify-content: space-between;
                gap: 12px;
                margin-top: 10px;
                color: #566176;
                font-size: 8px;
                font-weight: 700;
                letter-spacing: 0.45px;
                text-transform: uppercase;
            }}

            @media (max-width: 520px) {{
                body {{
                    padding: 4px 0 10px;
                }}

                .glass-card {{
                    padding: 16px 14px;
                }}

                .top-row {{
                    gap: 8px;
                }}

                .pill {{
                    padding: 5px 8px;
                    font-size: 9px;
                }}

                .next-up-box {{
                    min-width: 104px;
                    padding: 7px 10px;
                }}

                .hero-number {{
                    font-size: 64px;
                }}

                .hero-label {{
                    margin-left: 8px;
                }}

                .gauges-grid {{
                    gap: 6px;
                }}

                .gauge-item {{
                    padding: 9px 2px;
                }}

                .gauge-val {{
                    font-size: 17px;
                }}

                .gauge-lbl {{
                    font-size: 7px;
                }}
            }}
        </style>
    </head>

    <body>
        <div class="glass-card">
            <svg
                class="svg-bg"
                viewBox="0 0 300 100"
                fill="none"
                aria-hidden="true"
            >
                <path
                    d="M 0 80 C 100 80, 120 10, 300 10"
                    stroke="url(#pink-grad)"
                    stroke-width="3"
                    opacity="0.6"
                />
                <path
                    d="M 0 90 C 110 90, 130 20, 300 20"
                    stroke="url(#blue-grad)"
                    stroke-width="2"
                    opacity="0.4"
                />

                <defs>
                    <linearGradient
                        id="pink-grad"
                        x1="0%"
                        y1="0%"
                        x2="100%"
                        y2="0%"
                    >
                        <stop
                            offset="0%"
                            stop-color="#ec4899"
                        />
                        <stop
                            offset="100%"
                            stop-color="#a855f7"
                        />
                    </linearGradient>

                    <linearGradient
                        id="blue-grad"
                        x1="0%"
                        y1="0%"
                        x2="100%"
                        y2="0%"
                    >
                        <stop
                            offset="0%"
                            stop-color="#3b82f6"
                        />
                        <stop
                            offset="100%"
                            stop-color="#06b6d4"
                        />
                    </linearGradient>
                </defs>
            </svg>

            <div class="top-row">
                <div>
                    <div class="section-tag">
                        CAREER TO DATE
                    </div>

                    <div class="pill-group">
                        <div
                            class="pill active"
                            title="{events_value} completed events"
                        >
                            EVENTS
                        </div>
                        <div
                            class="pill"
                            title="{clients_value} unique clients"
                        >
                            CLIENTS
                        </div>
                        <div
                            class="pill"
                            title="{revenue_value} known revenue"
                        >
                            REVENUE
                        </div>
                    </div>
                </div>

                <div class="next-up-box">
                    <div class="next-up-title">
                        NEXT UP
                    </div>
                    <div class="next-up-val">
                        {next_client}
                    </div>
                    <div class="next-up-sub">
                        {next_date}
                    </div>
                </div>
            </div>

            <div class="hero-metric-section">
                <span class="hero-number">
                    {events_value}
                </span>
                <span class="hero-label">
                    EVENTS
                </span>
            </div>

            <div class="gauges-grid">
                <div
                    class="gauge-item"
                    title="{streak_caption}"
                >
                    <div class="gauge-val">
                        {streak_value}
                    </div>
                    <div class="gauge-lbl">
                        STREAK
                    </div>
                </div>

                <div class="gauge-item">
                    <div class="gauge-val">
                        {jurisdictions_value}
                    </div>
                    <div class="gauge-lbl">
                        JURISD.
                    </div>
                </div>

                <div class="gauge-item">
                    <div class="gauge-val">
                        {upcoming_value}
                    </div>
                    <div class="gauge-lbl">
                        UPCOMING
                    </div>
                </div>

                <div
                    class="gauge-item highlight"
                    title="{escape(best_month_caption)}"
                >
                    <div class="gauge-val pink">
                        {best_month_value}
                    </div>
                    <div class="gauge-lbl">
                        BEST MO.
                    </div>
                </div>
            </div>

            <div class="source-line">
                <span>
                    Timeline · State Coverage · Pipeline
                </span>
                <span>
                    Live workbook
                </span>
            </div>
        </div>
    </body>
    </html>
    """

    components.html(
        html,
        height=320,
        scrolling=False,
    )



def render_refined_data_views(metrics: ExecutiveMetrics) -> None:
    data = metrics.data_views
    leaderboard = list(data.get("leaderboard", []))
    jurisdictions = list(data.get("jurisdictions", []))
    palette = ["#f472b6", "#38bdf8", "#fde68a", "#c084fc", "#34d399", "#fb7185"]

    if leaderboard:
        leader = leaderboard[0]
        leader_summary = (
            f'<span class="pink-highlight">{escape(str(leader["client"]))}</span> '
            f'leads at <span class="pink-highlight">{int(leader["events"]):,}</span> events.'
        )
    else:
        leader_summary = "No completed client activity is available."

    leaderboard_rows = []
    for rank, item in enumerate(leaderboard, start=1):
        active = " active" if rank == 1 else ""
        leaderboard_rows.append(
            f'<div class="tower-block{active}">'
            f'<div class="rank-num{active}">{rank}</div>'
            f'<div class="client-name">{escape(str(item["client"]))}</div>'
            f'<div class="event-total">{int(item["events"]):,}</div>'
            f'</div>'
        )

    if not leaderboard_rows:
        leaderboard_rows.append('<div class="empty-state">No completed client activity.</div>')

    total_events = int(data.get("completed_events", metrics.completed_events))
    jurisdiction_count = int(data.get("jurisdiction_count", len(jurisdictions)))

    if jurisdictions:
        leader_j = jurisdictions[0]
        jurisdiction_summary = (
            f'<span class="pink-highlight">{jurisdiction_count} Jurisdictions</span> • '
            f'<span class="pink-highlight">{escape(str(leader_j["name"]))}</span> leads with '
            f'<span class="pink-highlight">{int(leader_j["events"]):,}</span> events'
        )
    else:
        jurisdiction_summary = "No completed jurisdiction activity."

    offset = 0.0
    arc_paths = []
    jurisdiction_rows = []

    for index, item in enumerate(jurisdictions):
        color = JURISDICTION_COLORS.get(jurisdiction_group(item["name"]), JURISDICTION_COLORS["Pennsylvania / Other"])
        share = float(item["share"])
        arc_paths.append(
            f'<path class="arc-segment" style="stroke:{color};" '
            f'stroke-dasharray="{share:.3f} 100" stroke-dashoffset="-{offset:.3f}" '
            f'd="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 '
            f'a 15.9155 15.9155 0 0 1 0 -31.831"/>'
        )
        offset += share
        jurisdiction_rows.append(
            f'<div class="juris-item">'
            f'<div class="color-dot" style="background-color:{color};"></div>'
            f'<div class="juris-name">{escape(str(item["name"]))}</div>'
            f'<div class="juris-pct">{share:.1f}%</div>'
            f'</div>'
        )

    if not jurisdiction_rows:
        jurisdiction_rows.append('<div class="empty-state">No completed jurisdiction activity.</div>')

    html = f"""
    <!DOCTYPE html>
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
    *{{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
    html,body{{width:100%;overflow:hidden;background:transparent}}
    body{{padding:8px 4px 12px;color:#fff}}
    .frosted-panel{{background:radial-gradient(circle at 100% -10%,rgba(244,114,182,.08),transparent 42%),rgba(23,27,40,.55);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.12);border-radius:20px;padding:20px;margin-bottom:16px;position:relative;overflow:hidden;box-shadow:0 15px 35px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.1)}}
    .section-header{{margin-bottom:15px;position:relative;z-index:2}}
    .section-title{{font-size:13px;font-weight:800;letter-spacing:1.5px;color:#fff;text-transform:uppercase}}
    .section-sub{{font-size:11.5px;font-weight:800;letter-spacing:.3px;color:#b8c4d9;margin-top:3px;line-height:1.5;text-transform:uppercase}}
    .pink-highlight{{color:#f472b6;font-weight:700}}
    .leaderboard-tower{{display:flex;flex-direction:column;gap:8px}}
    .tower-block{{display:grid;grid-template-columns:20px minmax(0,1fr) 32px;align-items:center;background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.01));border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:8px 12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.1)}}
    .tower-block.active{{border-color:rgba(244,114,182,.4);box-shadow:0 0 15px rgba(244,114,182,.15),inset 0 1px 0 rgba(255,255,255,.2)}}
    .rank-num{{font-size:11.5px;font-weight:800;color:#b8c4d9;text-align:center}} .rank-num.active{{color:#f472b6}}
    .client-name{{overflow:hidden;font-size:11px;font-weight:700;color:#fff;text-transform:uppercase;padding:0 10px;text-overflow:ellipsis;white-space:nowrap}}
    .event-total{{font-size:14px;font-weight:900;color:#f472b6;text-align:right;text-shadow:0 0 8px rgba(244,114,182,.6)}}
    .territory-split{{display:grid;grid-template-columns:minmax(140px,.9fr) minmax(0,1.1fr);align-items:center;gap:8px;position:relative}}
    .neon-pipe-bg{{position:absolute;top:20px;right:-20px;width:80%;height:60px;pointer-events:none;z-index:1}}
    .chart-section{{display:flex;justify-content:center;position:relative;z-index:2}}
    .arc-container{{width:189px;height:189px;position:relative;display:flex;align-items:center;justify-content:center}}
    .total-number{{position:absolute;font-size:48px;font-weight:900;color:{TERRITORY_CENTER_COLOR};filter:drop-shadow(0 0 18px rgba(255,255,255,.5));line-height:1}}
    .arc-svg{{transform:rotate(-90deg)}} .arc-base{{fill:none;stroke:rgba(255,255,255,.05);stroke-width:13.5}} .arc-segment{{fill:none;stroke-width:13.5;stroke-linecap:butt}}
    .jurisdiction-list{{display:flex;flex-direction:column;gap:10px;position:relative;z-index:2}}
    .juris-item{{display:grid;grid-template-columns:20px minmax(0,1fr) 46px;align-items:center;background:rgba(15,23,42,.6);border:1px solid rgba(255,255,255,.05);border-radius:50px;padding:8px 12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)}}
    .color-dot{{width:10px;height:10px;border-radius:50%}}
    .juris-name{{overflow:hidden;font-size:11.5px;font-weight:800;color:#c5d0e0;text-transform:uppercase;padding:0 10px;text-overflow:ellipsis;white-space:nowrap}}
    .juris-pct{{font-size:12px;font-weight:900;color:#fff;text-align:right}}
    .empty-state{{color:#b8c4d9;font-size:12.5px;padding:12px;text-align:center}}
    @media(max-width:520px){{body{{padding:4px 0 10px}}.frosted-panel{{padding:16px 14px}}.territory-split{{grid-template-columns:132px minmax(0,1fr)}}.arc-container{{width:173px;height:173px}}.total-number{{font-size:42px}}.jurisdiction-list{{gap:7px}}.juris-item{{grid-template-columns:16px minmax(0,1fr) 42px;padding:7px 9px}}.juris-name{{padding:0 6px;font-size:10.5px}}.juris-pct{{font-size:11px}}}}
    </style></head>
    <body>
      <div class="frosted-panel">
        <div class="section-header">
          <div class="section-title">CLIENT LEADERBOARD</div>
          <div class="section-sub">Top clients by completed-event volume. {leader_summary}</div>
        </div>
        <div class="leaderboard-tower">{''.join(leaderboard_rows)}</div>
      </div>

      <div class="frosted-panel">
        <svg class="neon-pipe-bg" viewBox="0 0 300 100" fill="none" aria-hidden="true">
          <path d="M 0 60 C 100 60, 150 10, 300 10" stroke="url(#blue-grad)" stroke-width="2" opacity="0.4"/>
          <path d="M 0 70 C 110 70, 160 20, 300 20" stroke="url(#pink-grad)" stroke-width="3" opacity="0.6"/>
          <defs>
            <linearGradient id="pink-grad" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#ec4899"/><stop offset="100%" stop-color="#a855f7"/></linearGradient>
            <linearGradient id="blue-grad" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#3b82f6"/><stop offset="100%" stop-color="#06b6d4"/></linearGradient>
          </defs>
        </svg>
        <div class="section-header">
          <div class="section-title">TERRITORY &amp; JURISDICTIONS</div>
          <div class="section-sub">{jurisdiction_summary}</div>
        </div>
        <div class="territory-split">
          <div class="chart-section">
            <div class="arc-container">
              <svg class="arc-svg" width="135" height="135" viewBox="0 0 36 36">
                <path class="arc-base" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
                {''.join(arc_paths)}
              </svg>
              <div class="total-number">{total_events:,}</div>
            </div>
          </div>
          <div class="jurisdiction-list">{''.join(jurisdiction_rows)}</div>
        </div>
      </div>
    </body></html>
    """

    height = 360 + max(len(leaderboard), 1) * 44 + max(len(jurisdictions) - 4, 0) * 36
    components.html(html, height=height, scrolling=False)


def render_kpi_cards(
    cards: Iterable[Dict[str, str]],
) -> None:
    parts = [
        '<section class="kpi-section" aria-label="Executive metrics">',
        '<div class="section-heading">',
        '<div>',
        '<div class="section-kicker">Core Performance</div>',
        '<h2>Career at a glance</h2>',
        '</div>',
        '<div class="section-count">8 LIVE METRICS</div>',
        '</div>',
        '<div class="kpi-grid">',
    ]

    for index, card in enumerate(
        cards,
        start=1,
    ):
        label = escape(card["label"])
        value = escape(card["value"])
        detail = escape(card["detail"])
        accent = escape(card["accent"])
        icon = escape(
            ICONS.get(
                card["label"],
                "•",
            )
        )

        parts.append(
            f"""
            <article
                class="kpi-card accent-{accent}"
                aria-label="{label}: {value}"
            >
                <div class="kpi-card-top">
                    <span class="kpi-index">{index:02d}</span>
                    <span class="kpi-icon" aria-hidden="true">
                        {icon}
                    </span>
                </div>

                <div class="kpi-label">{label}</div>
                <div class="kpi-value">{value}</div>
                <div class="kpi-detail">{detail}</div>
                <div class="kpi-sheen"></div>
            </article>
            """
        )

    parts.extend(
        [
            "</div>",
            "</section>",
        ]
    )

    render_html(
        "".join(parts)
    )


def render_operational_brief(
    metrics: ExecutiveMetrics,
) -> None:
    render_html(
        f"""
        <section class="brief-strip" aria-label="Operational brief">
            <div class="brief-lead">
                <span class="brief-pulse"></span>

                <div>
                    <strong>Operational brief</strong>
                    <span>Current workbook position</span>
                </div>
            </div>

            <div class="brief-stat">
                <span>Average paid event</span>
                <strong>${metrics.average_paid_event:,.2f}</strong>
            </div>

            <div class="brief-stat">
                <span>Revenue verified</span>
                <strong>{metrics.revenue_completion:.1f}%</strong>
            </div>

            <div class="brief-stat">
                <span>Top-client share</span>
                <strong>{metrics.top_client_share:.1f}%</strong>
            </div>
        </section>
        """
    )


def render_3d_donut(
    rows: Iterable[Tuple[str, int]],
    center_value: str,
) -> None:
    cleaned = [
        (
            str(name),
            int(value),
        )
        for name, value in rows
        if int(value) > 0
    ]

    total = sum(
        value
        for _, value in cleaned
    )

    cursor = 0.0
    stops = []
    legend = []

    for index, (name, value) in enumerate(
        cleaned,
    ):
        color = PALETTE[
            index % len(PALETTE)
        ]

        share = (
            value / total * 100.0
            if total
            else 0.0
        )

        start = cursor * 3.6
        cursor += share
        end = cursor * 3.6

        stops.append(
            f"{color} {start:.2f}deg {end:.2f}deg"
        )

        legend.append(
            (
                name,
                value,
                share,
                color,
                index + 1,
            )
        )

    gradient = (
        ", ".join(stops)
        if stops
        else "#243044 0deg 360deg"
    )

    leader = (
        legend[0]
        if legend
        else None
    )

    legend_html = "".join(
        f"""
        <div class="legend-row">
            <span class="legend-rank">{rank:02d}</span>

            <span
                class="legend-dot"
                style="--dot:{color}"
                aria-hidden="true"
            ></span>

            <span class="legend-name">
                {escape(name)}
            </span>

            <strong>{value:,}</strong>
            <em>{share:.1f}%</em>
        </div>
        """
        for (
            name,
            value,
            share,
            color,
            rank,
        ) in legend
    )

    leader_text = (
        f"{escape(leader[0])} leads with "
        f"{leader[2]:.1f}% of completed activity."
        if leader
        else "No completed jurisdiction activity available."
    )

    render_html(
        f"""
        <section class="distribution-panel">
            <div class="panel-heading">
                <div>
                    <div class="section-kicker">
                        Operating Footprint
                    </div>

                    <h2>
                        Completed activity by jurisdiction
                    </h2>

                    <p>
                        Live distribution generated directly
                        from State Coverage.
                    </p>
                </div>

                <div class="panel-badge">
                    <span class="status-dot"></span>
                    LIVE
                </div>
            </div>

            <div class="donut-layout">
                <div class="donut-stage">
                    <div class="donut-shadow"></div>

                    <div
                        class="donut-3d"
                        style="--segments:{gradient}"
                        role="img"
                        aria-label="Completed activity by jurisdiction"
                    >
                        <div class="donut-gloss"></div>
                        <div class="donut-hole"></div>
                    </div>

                    <div class="donut-center">
                        <span>Total</span>
                        <strong>{escape(center_value)}</strong>
                        <small>completed events</small>
                    </div>
                </div>

                <div class="legend-panel">
                    <div class="legend-header">
                        <span>Jurisdiction</span>
                        <span>Events</span>
                        <span>Share</span>
                    </div>

                    <div class="donut-legend">
                        {legend_html}
                    </div>

                    <div class="leader-note">
                        <span class="leader-line"></span>
                        <p>{leader_text}</p>
                    </div>
                </div>
            </div>
        </section>
        """
    )


def _client_rows(
    metrics: ExecutiveMetrics,
) -> str:
    if not metrics.top_clients:
        return """
        <div class="empty-state">
            No client revenue records are available.
        </div>
        """

    maximum = max(
        float(item["revenue"])
        for item in metrics.top_clients
    ) or 1.0

    rows = []

    for rank, item in enumerate(
        metrics.top_clients,
        start=1,
    ):
        width = (
            float(item["revenue"])
            / maximum
            * 100.0
        )

        rows.append(
            f"""
            <div class="client-row">
                <span class="client-rank">{rank:02d}</span>

                <div class="client-main">
                    <div class="client-line">
                        <strong>{escape(str(item["client"]))}</strong>
                        <span>{int(item["events"]):,} events</span>
                    </div>

                    <div class="client-track">
                        <span style="width:{width:.1f}%"></span>
                    </div>
                </div>

                <div class="client-money">
                    <strong>${float(item["revenue"]):,.2f}</strong>
                    <span>{float(item["share"]):.1f}%</span>
                </div>
            </div>
            """
        )

    return "".join(rows)


def _upcoming_rows(
    metrics: ExecutiveMetrics,
) -> str:
    if not metrics.upcoming_items:
        return """
        <div class="empty-state">
            No upcoming assignments are currently listed.
        </div>
        """

    rows = []

    for item in metrics.upcoming_items:
        location = escape(
            item["location"]
            or "Location pending"
        )

        rows.append(
            f"""
            <div class="upcoming-row">
                <div class="upcoming-date">
                    {escape(item["date"])}
                </div>

                <div class="upcoming-copy">
                    <strong>{escape(item["client"])}</strong>
                    <span>{location}</span>
                </div>

                <span class="upcoming-arrow">→</span>
            </div>
            """
        )

    return "".join(rows)


def render_executive_insights(
    metrics: ExecutiveMetrics,
) -> None:
    quality_class = (
        "quality-good"
        if metrics.data_quality_score >= 80
        else "quality-warn"
    )

    render_html(
        f"""
        <section class="insights-section">
            <div class="section-heading">
                <div>
                    <div class="section-kicker">
                        Executive Detail
                    </div>
                    <h2>Concentration and forward workload</h2>
                </div>

                <div class="quality-badge {quality_class}">
                    Data integrity
                    <strong>{metrics.data_quality_score:.0f}%</strong>
                </div>
            </div>

            <div class="insights-grid">
                <article class="insight-panel top-clients-panel">
                    <div class="insight-header">
                        <div>
                            <span>Revenue concentration</span>
                            <h3>Top clients</h3>
                        </div>

                        <strong>
                            {metrics.top_client_share:.1f}%
                            <small>leader share</small>
                        </strong>
                    </div>

                    <div class="client-list">
                        {_client_rows(metrics)}
                    </div>
                </article>

                <article class="insight-panel upcoming-panel">
                    <div class="insight-header">
                        <div>
                            <span>Pipeline</span>
                            <h3>Upcoming work</h3>
                        </div>

                        <strong>
                            {metrics.scheduled_events:,}
                            <small>scheduled</small>
                        </strong>
                    </div>

                    <div class="upcoming-list">
                        {_upcoming_rows(metrics)}
                    </div>
                </article>
            </div>
        </section>
        """
    )
