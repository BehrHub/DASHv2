from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from services.money_view import gross_up, WEEKS_PER_YEAR, MONTHS_PER_YEAR


def _fmt(value: float, metric: str) -> str:
    if metric == "revenue":
        return f"\uFF04{value:,.0f}"
    return f"{value:,.0f}"


def _axis_ceiling(peak: float) -> tuple[int, int]:
    if peak <= 0:
        return 1, 4
    for step in (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 75,
                 100, 125, 150, 200, 250, 300, 400, 500, 600, 750,
                 1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000, 7500, 10000):
        if step * 4 >= peak:
            return step, step * 4
    return 25000, 100000


def _build_series(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    peak_events = max(r["events"] for r in rows)
    peak_revenue = max(r["revenue"] for r in rows)
    for r in rows:
        r["is_record"] = r["events"] == peak_events or r["revenue"] == peak_revenue
    return rows


def _prepare_buckets(timeline: pd.DataFrame) -> dict[str, list[dict]]:
    working = timeline.copy()
    working["__date"] = pd.to_datetime(working["Service Date"], errors="coerce")
    working["__revenue"] = pd.to_numeric(working["Amount"], errors="coerce").fillna(0)
    dated = working.dropna(subset=["__date"])

    weekly: list[dict] = []
    monthly: list[dict] = []
    weekday: list[dict] = []

    if not dated.empty:
        wk = dated.copy()
        iso = wk["__date"].dt.isocalendar()
        wk["iso_year"], wk["iso_week"] = iso["year"], iso["week"]
        wk["week_index"] = wk["iso_year"] * 52 + wk["iso_week"]
        start_index = int(wk["week_index"].min())
        grouped = (
            wk.groupby("week_index")
            .agg(
                events=("Client", "count"),
                revenue=("__revenue", "sum"),
                days_worked=("__date", lambda s: s.dt.normalize().nunique()),
            )
            .reset_index()
            .sort_values("week_index")
            .tail(6)
        )
        weekly = _build_series([
            {
                "label": f"W{int(row['week_index']) - start_index + 1}",
                "events": int(row["events"]),
                "revenue": round(row["revenue"]),
                "days_worked": int(row["days_worked"]),
            }
            for _, row in grouped.iterrows()
        ])

        mo = dated.copy()
        mo["month_order"] = mo["__date"].dt.to_period("M")
        mo["month_label"] = mo["__date"].dt.strftime("%b").str.upper()
        grouped_m = (
            mo.groupby(["month_order", "month_label"])
            .agg(
                events=("Client", "count"),
                revenue=("__revenue", "sum"),
                days_worked=("__date", lambda s: s.dt.normalize().nunique()),
            )
            .reset_index()
            .sort_values("month_order")
            .tail(6)
        )
        monthly = _build_series([
            {
                "label": str(row["month_label"]),
                "events": int(row["events"]),
                "revenue": round(row["revenue"]),
                "days_worked": int(row["days_worked"]),
            }
            for _, row in grouped_m.iterrows()
        ])

        wd = dated.copy()
        wd["weekday_name"] = wd["__date"].dt.day_name()
        order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        grouped_wd = (
            wd.groupby("weekday_name")
            .agg(
                events=("Client", "count"),
                revenue=("__revenue", "sum"),
                days_worked=("__date", lambda s: s.dt.normalize().nunique()),
            )
            .reindex(order)
            .dropna(how="all")
            .fillna(0)
            .reset_index()
        )
        weekday = _build_series([
            {
                "label": str(row["weekday_name"])[:3].upper(),
                "events": int(row["events"]),
                "revenue": round(row["revenue"]),
                "days_worked": int(row["days_worked"]),
            }
            for _, row in grouped_wd.iterrows()
        ])

    return {"weekly": weekly, "monthly": monthly, "weekday": weekday}


PLOT_H, BAR_MAX, BAR_MIN = 128, 108, 5


def _chart(series: list[dict], metric: str, view_id: str, suppress_total: bool = False) -> str:
    if not series:
        return (
            f'<div class="trend-view" data-view="{view_id}">'
            '<div class="trend-empty">Not enough dated history yet.</div></div>'
        )

    values = [row[metric] for row in series]
    peak = max(values) if values else 0
    step, top = _axis_ceiling(peak)

    grid = []
    for level_index in range(4, -1, -1):
        level = step * level_index
        y = min(PLOT_H - 1, PLOT_H - round((level / top) * BAR_MAX))
        cls = "trend-grid-line is-base" if level_index == 0 else "trend-grid-line"
        grid.append(f'<div class="{cls}" style="top:{y}px"></div>')
        if level_index in (0, 2, 4):
            grid.append(f'<span class="trend-grid-tag" style="top:{y}px">{escape(_fmt(level, metric))}</span>')

    bars, axis = [], []
    for row in series:
        value = row[metric]
        height = max(BAR_MIN, round(value / top * BAR_MAX)) if value > 0 else 3
        record = " is-record" if row["is_record"] else ""
        bars.append(
            f'<div class="trend-bar-col{record}">'
            f'<div class="trend-bar-value">{escape(_fmt(value, metric))}</div>'
            f'<div class="trend-bar-shape{record}" style="height:{height}px"></div>'
            "</div>"
        )
        axis.append(f'<span>{escape(row["label"])}</span>')

    best = max(series, key=lambda row: row[metric])
    total = sum(values)
    average = total / len(values)
    days_worked = best.get("days_worked", 0)
    total_display = "N/A" if suppress_total else escape(_fmt(total, metric))
    foot = (
        '<div class="trend-foot">'
        f'<span>Peak <strong>{escape(best["label"])}</strong> (<strong>{escape(_fmt(best[metric], metric))}</strong>)</span>'
        f'<span>Average <strong>{escape(_fmt(round(average), metric))}</strong></span>'
        f'<span>Total <strong>{total_display}</strong></span>'
        f'<span class="trend-foot-days">{days_worked} day{"s" if days_worked != 1 else ""} worked</span>'
        "</div>"
    )

    return (
        f'<div class="trend-view" data-view="{view_id}">'
        f'<div class="trend-plot"><div class="trend-grid-wrap">{"".join(grid)}</div><div class="trend-bar-row">{"".join(bars)}</div></div>'
        f'<div class="trend-axis">{"".join(axis)}</div>{foot}</div>'
    )


TRENDS_CSS_RULES = """
.trend-panel {
    background: linear-gradient(155deg, #0c1118 0%, #080b11 85%);
    border: 1px solid rgba(244,114,182,.28);
    border-radius: 20px;
    padding: 20px;
    box-shadow: 0 15px 35px rgba(0,0,0,.5);
}
.trend-head-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.trend-title { font-size: 15px; font-weight: 900; letter-spacing: .5px; color: #fff; text-shadow: 0 0 18px rgba(244,114,182,.3); }
.trend-tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.trend-tab { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); border-radius: 20px; padding: 6px 14px; font-size: 11.5px; font-weight: 800; letter-spacing: .5px; color: #c5d0e0; cursor: pointer; user-select: none; }
.trend-tab.is-active { background: rgba(244,114,182,.1); border-color: #f472b6; color: #f9a8d4; box-shadow: 0 0 12px rgba(244,114,182,.3); }
.trend-metric-row { display: flex; gap: 6px; margin-bottom: 14px; }
.trend-annualized-badge { display: block; font-size: 10px; font-weight: 800; color: #7dd3fc; letter-spacing: .3px; margin-bottom: 8px; }
.trend-view { display: none; }
.trend-view.is-active { display: block; }
.trend-plot { position: relative; height: 190px; margin-bottom: 8px; }
.trend-grid-wrap { position: absolute; left: 0; right: 0; bottom: 0; height: 128px; }
.trend-grid-line { position: absolute; left: 0; right: 0; height: 1px; background: rgba(255,255,255,.07); }
.trend-grid-line.is-base { background: rgba(255,255,255,.18); }
.trend-grid-tag { position: absolute; left: 0; transform: translateY(-100%); font-size: 11px; color: #a8b4c8; font-weight: 800; }
.trend-bar-row { position: absolute; left: 34px; right: 0; bottom: 0; display: flex; align-items: flex-end; justify-content: space-between; gap: 6px; height: 128px; }
.trend-bar-col { display: flex; flex-direction: column; align-items: center; justify-content: flex-end; flex: 1 1 0; min-width: 0; height: 100%; }
.trend-bar-value { font-size: 13.5px; font-weight: 900; color: #d6e6ff; white-space: nowrap; margin-bottom: 7px; padding: 4px 9px; border-radius: 9px; background: rgba(15,23,42,.9); border: 1px solid rgba(96,165,250,.6); box-shadow: 0 0 12px rgba(96,165,250,.5); }
.trend-bar-col.is-record .trend-bar-value { color: #ffe9f5; background: rgba(35,10,26,.9); border-color: rgba(244,114,182,.85); box-shadow: 0 0 16px rgba(244,114,182,.7); }
.trend-bar-shape { width: 70%; max-width: 26px; border-radius: 6px 6px 2px 2px; background: linear-gradient(180deg, #60a5fa, #3b5b8f); box-shadow: inset 0 1px 0 rgba(255,255,255,.15); }
.trend-bar-shape.is-record { background: linear-gradient(180deg, #f9a8d4, #ec4899); box-shadow: 0 0 14px rgba(244,114,182,.4), inset 0 1px 0 rgba(255,255,255,.25); }
.trend-axis { display: flex; justify-content: space-between; gap: 6px; padding-left: 34px; margin-bottom: 10px; }
.trend-axis span { flex: 1 1 0; min-width: 0; text-align: center; font-size: 11.5px; font-weight: 800; color: #b8c4d9; }
.trend-foot { display: flex; gap: 14px; flex-wrap: wrap; padding-top: 10px; border-top: 1px solid rgba(255,255,255,.08); font-size: 12.5px; color: #b8c4d9; }
.trend-foot strong { color: #fff; }
.trend-foot-days { margin-left: auto; color: #7dd3fc; font-weight: 700; white-space: nowrap; }
.trend-empty { color: #b8c4d9; font-size: 13px; padding: 30px 0; text-align: center; }
@media (max-width: 480px) {
  .trend-panel { padding: 16px 14px; }
  .trend-title { font-size: 13px; }
  .trend-tab { padding: 5px 10px; font-size: 10.5px; }
  .trend-bar-row { left: 30px; }
  .trend-axis { padding-left: 30px; }
  .trend-bar-value { font-size: 11px; padding: 3px 6px; margin-bottom: 5px; }
  .trend-grid-tag { font-size: 10px; }
}
"""

TRENDS_CSS = f"<style>{TRENDS_CSS_RULES}</style>"


def _annualized_revenue_series(series: list[dict], multiplier: float) -> list[dict]:
    return [{**row, "revenue": gross_up(row["revenue"]) * multiplier} for row in series]


def _grossed_revenue_series(series: list[dict]) -> list[dict]:
    return [{**row, "revenue": gross_up(row["revenue"])} for row in series]


def build_trends_fragment(timeline: pd.DataFrame, gross_view: bool = False) -> str:
    """Returns the Performance Trends panel as an embeddable HTML fragment
    (CSS + markup + script), for insertion into a larger single-iframe
    document such as render_dashboard()'s combined Hero/Leaderboard/Territory
    HTML — keeping the same 16px inter-panel spacing everywhere.
    """
    buckets = _prepare_buckets(timeline)

    weekly_revenue = buckets["weekly"]
    monthly_revenue = buckets["monthly"]
    weekday_revenue = buckets["weekday"]
    if gross_view:
        weekly_revenue = _annualized_revenue_series(weekly_revenue, WEEKS_PER_YEAR)
        monthly_revenue = _annualized_revenue_series(monthly_revenue, MONTHS_PER_YEAR)
        # Weekday view has no single clean annualization multiplier (it
        # aggregates revenue across every real occurrence of that weekday,
        # not one period) — but it still gets the gross-up applied like
        # every other dollar figure on the dashboard, just without a /yr
        # extrapolation on top.
        weekday_revenue = _grossed_revenue_series(weekday_revenue)

    charts = "".join([
        _chart(buckets["weekly"], "events", "weekly-events"),
        _chart(weekly_revenue, "revenue", "weekly-revenue", suppress_total=gross_view),
        _chart(buckets["monthly"], "events", "monthly-events"),
        _chart(monthly_revenue, "revenue", "monthly-revenue", suppress_total=gross_view),
        _chart(buckets["weekday"], "events", "weekday-events"),
        _chart(weekday_revenue, "revenue", "weekday-revenue", suppress_total=gross_view),
    ])

    return f"""
      <div class="trend-panel panel" id="trendsPanel">
        <div class="trend-head-row">
          <div class="trend-title">PERFORMANCE TRENDS</div>
          <div class="trend-tabs" id="periodTabs">
            <div class="trend-tab is-active" data-period="weekly">WEEKLY</div>
            <div class="trend-tab" data-period="monthly">MONTHLY</div>
            <div class="trend-tab" data-period="weekday">WEEKDAY</div>
          </div>
        </div>
        <div class="trend-metric-row" id="metricTabs">
          <div class="trend-tab is-active" data-metric="events">EVENTS</div>
          <div class="trend-tab" data-metric="revenue">REVENUE</div>
        </div>
        <div id="trendViews">{charts}</div>
      </div>
      <script>
        (function() {{
          let period = 'weekly';
          let metric = 'events';
          try {{
            var savedPeriod = window.parent.localStorage.getItem('barristerTrendsPeriod');
            var savedMetric = window.parent.localStorage.getItem('barristerTrendsMetric');
            if (savedPeriod) period = savedPeriod;
            if (savedMetric) metric = savedMetric;
          }} catch (e) {{}}

          function applyActiveTabs() {{
            document.querySelectorAll('#periodTabs .trend-tab').forEach(function(t) {{
              t.classList.toggle('is-active', t.getAttribute('data-period') === period);
            }});
            document.querySelectorAll('#metricTabs .trend-tab').forEach(function(t) {{
              t.classList.toggle('is-active', t.getAttribute('data-metric') === metric);
            }});
          }}
          function sync() {{
            document.querySelectorAll('#trendViews .trend-view').forEach(function(v) {{
              v.classList.toggle('is-active', v.getAttribute('data-view') === period + '-' + metric);
            }});
          }}
          function persist() {{
            try {{
              window.parent.localStorage.setItem('barristerTrendsPeriod', period);
              window.parent.localStorage.setItem('barristerTrendsMetric', metric);
            }} catch (e) {{}}
          }}

          document.querySelectorAll('#periodTabs .trend-tab').forEach(function(tab) {{
            tab.addEventListener('click', function() {{
              period = tab.getAttribute('data-period');
              applyActiveTabs();
              sync();
              persist();
            }});
          }});
          document.querySelectorAll('#metricTabs .trend-tab').forEach(function(tab) {{
            tab.addEventListener('click', function() {{
              metric = tab.getAttribute('data-metric');
              applyActiveTabs();
              sync();
              persist();
            }});
          }});
          applyActiveTabs();
          sync();
        }})();
      </script>
    """


def render_performance_trends(timeline: pd.DataFrame) -> None:
    """Standalone render (own iframe) — not used by render_dashboard(),
    which embeds build_trends_fragment() directly for uniform spacing.
    Kept for cases where Trends needs to render on its own.
    """
    fragment = build_trends_fragment(timeline)
    html = f"""
    <!DOCTYPE html>
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
    {TRENDS_CSS}
    </head><body>{fragment}</body></html>
    """
    components.html(html, height=472, scrolling=False)
