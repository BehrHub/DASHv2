from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from services.money_view import gross_up, WEEKS_PER_YEAR, MONTHS_PER_YEAR
from services.tz import eastern_today_naive


def _fmt(value: float, metric: str) -> str:
    if metric == "revenue":
        return f"\uFF04{value:,.0f}"
    if metric in ("avgrevperevent", "avgrevperday"):
        return f"\uFF04{value:,.2f}"
    if metric == "avgevent":
        return f"{value:,.1f}"
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


def _with_avg_metrics(rows: list[dict], events_denom: float | None = None) -> list[dict]:
    """Adds 'avgevent' (AVG/EVNT - event count), 'avgrevperevent' (AVG
    REV/EVNT - revenue/events), and 'avgrevperday' (AVG REV/DAY -
    revenue/days_worked) to each row, in place. All three now apply
    uniformly across every period (Weekly/Monthly/Career/DayO'Wk/
    Clients/Cities) - both revenue averages are always computed and
    always available as separate buttons, rather than picking one or
    the other per period like an earlier version of this did.

    avgevent: events_denom=None means this bucket type has no
    recurring-unit denominator (Weekly/Monthly/Career/Clients/Cities -
    each bar already represents ONE unique, non-repeating period or
    entity, so there's nothing further to average over) - falls back
    to the bucket's own raw event count, identical to the EVENTS tab.
    DayO'Wk passes the current career week number instead, since each
    weekday bucket sums MULTIPLE occurrences of that weekday across
    every week so far - confirmed formula, not a guess.
    """
    for r in rows:
        r["avgevent"] = round((r["events"] / events_denom), 2) if events_denom else float(r["events"])
        r["avgrevperevent"] = round((r["revenue"] / r["events"]), 2) if r["events"] else 0.0
        r["avgrevperday"] = round((r["revenue"] / r["days_worked"]), 2) if r.get("days_worked") else 0.0
    return rows


def _month_index(date: pd.Timestamp, career_start: pd.Timestamp) -> int:
    """Same career-month math as ledger.py's _compute_career_months —
    kept in sync so 'Month 3' here means the exact same date range as
    'Month 3' there, not a coincidentally-similar but separately
    computed value."""
    months_diff = (date.year - career_start.year) * 12 + (date.month - career_start.month)
    if date.day < career_start.day:
        months_diff -= 1
    return months_diff


def _prepare_buckets(timeline: pd.DataFrame) -> dict[str, list[dict]]:
    working = timeline.copy()
    working["__date"] = pd.to_datetime(working["Service Date"], errors="coerce")
    working["__revenue"] = pd.to_numeric(working["Amount"], errors="coerce").fillna(0)
    dated = working.dropna(subset=["__date"])

    weekly: list[dict] = []
    monthly: list[dict] = []
    weekday: list[dict] = []
    career: list[dict] = []
    current_career_week = 1

    if not dated.empty:
        wk = dated.copy()
        iso = wk["__date"].dt.isocalendar()
        wk["iso_year"], wk["iso_week"] = iso["year"], iso["week"]
        wk["week_index"] = wk["iso_year"] * 52 + wk["iso_week"]
        start_index = int(wk["week_index"].min())
        # Current career week number, same W-numbering formula as the
        # weekly bucket below - used by DayO'Wk's AVG EVENTS metric.
        today_iso = eastern_today_naive().isocalendar()
        today_week_index = today_iso.year * 52 + today_iso.week
        current_career_week = today_week_index - start_index + 1
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
        _with_avg_metrics(weekly)

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
        _with_avg_metrics(monthly)

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
        _with_avg_metrics(weekday, events_denom=current_career_week)

        cr = dated.copy()
        career_start = cr["__date"].min().normalize()
        cr["career_month_idx"] = cr["__date"].apply(lambda d: _month_index(d, career_start))
        grouped_cr = (
            cr.groupby("career_month_idx")
            .agg(
                events=("Client", "count"),
                revenue=("__revenue", "sum"),
                days_worked=("__date", lambda s: s.dt.normalize().nunique()),
            )
            .reset_index()
            .sort_values("career_month_idx")
            .tail(6)
        )
        career = _build_series([
            {
                "label": f"M{int(row['career_month_idx']) + 1}",
                "events": int(row["events"]),
                "revenue": round(row["revenue"]),
                "days_worked": int(row["days_worked"]),
            }
            for _, row in grouped_cr.iterrows()
        ])
        _with_avg_metrics(career)

    return {
        "weekly": weekly, "monthly": monthly, "weekday": weekday, "career": career,
        "current_career_week": current_career_week,
    }


CHART_CLIENT_LABEL_OVERRIDES: dict[str, str] = {
    "Dunkin'": "DNKN'",
    "Marshalls": "MARSH",
    "7-Eleven": "7-11",
    "Giant Food Stores": "GIANT",
    "Food Lion": "FOOD LION",
    "Senate Sergeant at Arms": "SGT. ARMS",
    "Hebrew Home GW": "HBRW HOME",
}


def _client_top7(timeline: pd.DataFrame, rank_by: str) -> list[dict]:
    """Top 7 clients ranked by `rank_by` ('events' or 'revenue') --
    kept separate from _prepare_buckets() deliberately, since unlike
    weekly/monthly/weekday (one shared set of periods, metric only
    changes which value is plotted), the top-7-by-events and
    top-7-by-revenue lists can genuinely be different clients in a
    different order, not just the same rows redisplayed. Self-contained
    (does its own revenue parsing) rather than depending on a
    pre-processed dataframe, since it's called on the raw timeline.

    CHART_CLIENT_LABEL_OVERRIDES applies ONLY to this chart's axis
    labels -- the real client name everywhere else in the app (Client
    Hub, Ledger, the ticker, etc.) is completely untouched. This exists
    purely to fix display crowding for specific names, not to rename
    anything about the underlying data.
    """
    if timeline.empty or "Client" not in timeline.columns:
        return []
    working = timeline.copy()
    working["__revenue"] = pd.to_numeric(working["Amount"], errors="coerce").fillna(0)
    working["__date"] = pd.to_datetime(working["Service Date"], errors="coerce")
    grouped = (
        working.groupby("Client")
        .agg(
            events=("Client", "count"),
            revenue=("__revenue", "sum"),
            days_worked=("__date", lambda s: s.dt.normalize().nunique()),
        )
        .reset_index()
        .sort_values(rank_by, ascending=False)
        .head(7)
        # Selection above must stay descending (to correctly pick the
        # actual top 7). This second sort only re-orders THAT subset
        # for DISPLAY -- ascending left-to-right, so the #1 client lands
        # on the right, matching every other chart here (weekly/monthly
        # progress oldest-to-newest left-to-right, so "most current" is
        # also rightmost; this keeps CLIENTS visually consistent with
        # that same convention instead of being backwards).
        .sort_values(rank_by, ascending=True)
    )
    rows = [
        {
            "label": CHART_CLIENT_LABEL_OVERRIDES.get(
                str(row["Client"]),
                (str(row["Client"])[:8].upper() + "\u2026") if len(str(row["Client"])) > 8 else str(row["Client"]).upper(),
            ),
            "events": int(row["events"]),
            "revenue": round(row["revenue"]),
            "days_worked": int(row["days_worked"]),
        }
        for _, row in grouped.iterrows()
    ]
    return _with_avg_metrics(_build_series(rows))


CHART_CITY_GROUP_LABEL_OVERRIDES: dict[str, str] = {
    "Rockville-proper": "ROCK GRP",
    "Owings Mills-proper": "O.MIL GRP",
    "Elkridge-proper": "ELK GRP",
    "Tysons-proper": "TYSON GRP",
    "Bel Air-proper": "BEL.A GRP",
    "Annapolis-proper": "ANNA GRP",
    "Towson-proper": "TOWS GRP",
    "Glen Burnie-proper": "GLN.B GRP",
    "Largo-proper": "LRGO GRP",
    "Landover-proper": "LNDVR GRP",
}


CHART_STANDALONE_CITY_OVERRIDES: dict[str, str] = {
    "Frederick, MD": "FRED",
    "Washington, DC": "D.C.",
    # Bowie and College Park are standalone again now - Bowie-proper
    # and College Park-proper were both deleted (Bowie down to a
    # single member wasn't a real group anymore; College Park moved
    # out of the Landover-centered group entirely, no group of its
    # own until real neighboring cities of its own get visited).
    # Bowie, MD is already short enough (5 chars) to need no override.
    "College Park, MD": "C.PARK",
}


def _city_group_top7(timeline: pd.DataFrame, pipeline: pd.DataFrame | None, rank_by: str) -> list[dict]:
    """Top 7 locations overall — city GROUPS (Rockville-proper, Bowie-
    proper, etc) combined with any standalone city that isn't part of
    a formal group, ranked together in one pool. Explicit instruction
    was to pull from city groups since combining related cities into
    one group produces a more meaningful bar than many small
    individual-city bars — but that's about grouping what CAN be
    grouped, not excluding everything that can't. Confirmed bug this
    fixes: filtering to is_group-only entries silently dropped every
    standalone city, including Washington DC — the single highest-
    volume, highest-revenue location overall — from both the events
    and revenue charts entirely, regardless of how it actually ranked.
    Same self-contained top-7-then-redisplay-ascending convention as
    _client_top7 above.
    """
    from services.groups import compute_location_group_ranking

    if timeline.empty:
        return []
    results = compute_location_group_ranking(timeline, pipeline)
    if not results:
        return []

    metric_key = "trips" if rank_by == "events" else "revenue"
    ranked = sorted(results, key=lambda r: -r[metric_key])[:7]
    ranked = sorted(ranked, key=lambda r: r[metric_key])

    def _label(r: dict) -> str:
        if r["is_group"]:
            name = str(r["name"])
            if name in CHART_CITY_GROUP_LABEL_OVERRIDES:
                return CHART_CITY_GROUP_LABEL_OVERRIDES[name]
            # A group with no explicit short name yet (one of the 6
            # location groups not currently in the override dict above)
            # still gets the same "GRP" second line for consistency -
            # only the short-name PART falls back to auto-truncation.
            short = name.replace("-proper", "").strip()
            short = (short[:8].upper() + "\u2026") if len(short) > 8 else short.upper()
            return f"{short} GRP"
        # Standalone city - "City, ST" with the state dropped, same
        # convention used in ledger.py and the Journey page.
        raw = str(r["name"])
        if raw in CHART_STANDALONE_CITY_OVERRIDES:
            return CHART_STANDALONE_CITY_OVERRIDES[raw]
        city = raw.rsplit(",", 1)[0].strip() if "," in raw else raw
        return (city[:8].upper() + "\u2026") if len(city) > 8 else city.upper()

    # Real distinct days worked per group/city, computed from the UNION
    # of dates across all its members - NOT the sum of each member's own
    # days_worked, which would double-count any day where two member
    # cities in the same group were both visited (e.g. Rockville AND
    # North Bethesda on the same day would otherwise count as 2 days,
    # not the 1 real day it actually was).
    working = timeline.copy()
    working["__date"] = pd.to_datetime(working["Service Date"], errors="coerce")

    def _days_worked_for(members: list[str]) -> int:
        subset = working[working["Location Detail"].isin(members)]
        return int(subset["__date"].dt.normalize().nunique())

    rows = [
        {
            "label": _label(r),
            "events": int(r["trips"]),
            "revenue": round(r["revenue"]),
            "days_worked": _days_worked_for(r["members"]),
        }
        for r in ranked
    ]
    return _with_avg_metrics(_build_series(rows))


PLOT_H, BAR_MAX, BAR_MIN = 128, 108, 5


def _chart(
    series: list[dict], metric: str, view_id: str, suppress_total: bool = False,
    description: str = "", show_mom_connectors: bool = False,
) -> str:
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

    # Month-over-month connectors (Career/Monthly only) - a small %
    # marker floating between each consecutive pair of bars (real
    # change from the bar just before it), plus one final marker after
    # the LAST bar showing total growth from the very FIRST bar to the
    # current one - "how far this has come since it started."
    # Positioned as an absolute overlay computed from each bar's real
    # horizontal center, rather than squeezed into the bar row's own
    # tight 6px gaps, so the existing bar layout is never disturbed.
    connectors = []
    n = len(series)
    if show_mom_connectors and n > 1:
        def _connector_html(pct: float | None, left_pct: float, is_total: bool = False) -> str:
            if pct is None:
                return ""
            sign = "+" if pct >= 0 else ""
            cls = "trend-connector"
            cls += " is-total" if is_total else (" is-positive" if pct >= 0 else " is-negative")
            return f'<div class="{cls}" style="left:{left_pct:.4f}%;transform:translateX(-50%)">{sign}{pct:.1f}%</div>'

        for i in range(1, n):
            prev_val, cur_val = values[i - 1], values[i]
            pct = ((cur_val - prev_val) / prev_val * 100) if prev_val else None
            left_pct = (i / n) * 100
            connectors.append(_connector_html(pct, left_pct))

        first_val, last_val = values[0], values[-1]
        total_pct = ((last_val - first_val) / first_val * 100) if first_val else None
        connectors.append(_connector_html(total_pct, 100.0, is_total=True))

    best = max(series, key=lambda row: row[metric])
    total = sum(values)
    average = total / len(values)
    days_worked = best.get("days_worked", 0)
    total_display = "N/A" if suppress_total else escape(_fmt(total, metric))
    total_span = (
        f'<span>Total <strong>{total_display}</strong></span>' if suppress_total
        else f'<span><strong>{days_worked}</strong> day{"s" if days_worked != 1 else ""} worked. <strong>{total_display}</strong> Total</span>'
    )
    # Explicit two-row footer, not flex-wrap's incidental behavior -
    # confirmed bug this replaces: dollar-formatted values (AVG REVENUE)
    # are wider than plain numbers (AVG EVENTS), so the exact same
    # flex-wrap row wrapped to 2 lines for one metric and stayed on 1
    # for another, purely by accident of content width, not by design.
    foot = (
        '<div class="trend-foot">'
        '<div class="trend-foot-row1">'
        f'<span>Peak <strong>{escape(best["label"])}</strong> (<strong>{escape(_fmt(best[metric], metric))}</strong>)</span>'
        f'<span>Average <strong>{escape(_fmt(round(average), metric))}</strong></span>'
        '</div>'
        '<div class="trend-foot-row2">'
        f'{total_span}'
        f'<span class="trend-foot-desc">{escape(description)}</span>'
        '</div>'
        "</div>"
    )

    return (
        f'<div class="trend-view" data-view="{view_id}">'
        f'<div class="trend-plot"><div class="trend-grid-wrap">{"".join(grid)}</div>'
        f'<div class="trend-bar-row">{"".join(bars)}{"".join(connectors)}</div></div>'
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
.trend-head-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.trend-title { font-size: 15px; font-weight: 900; letter-spacing: .5px; color: #fff; text-shadow: 0 0 18px rgba(244,114,182,.3); }
.trend-tabs { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.trend-tabs-row { display: flex; gap: 6px; }
.trend-tabs-row .trend-tab { flex: 1 1 0; text-align: center; }
.trend-tab { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); border-radius: 20px; padding: 6px 14px; font-size: 11.5px; font-weight: 800; letter-spacing: .5px; color: #c5d0e0; cursor: pointer; user-select: none; }
.trend-tab.is-active { background: rgba(244,114,182,.1); border-color: #f472b6; color: #f9a8d4; box-shadow: 0 0 12px rgba(244,114,182,.3); }
.trend-metric-row { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.trend-metric-tabs-row { display: flex; gap: 6px; }
.trend-metric-tabs-row .trend-tab { flex: 1 1 0; text-align: center; }
.trend-annualized-badge { display: block; font-size: 10px; font-weight: 800; color: #7dd3fc; letter-spacing: .3px; margin-bottom: 8px; }
.trend-view { display: none; }
.trend-view.is-active { display: block; }
.trend-plot { position: relative; height: 158px; margin-bottom: 8px; }
.trend-grid-wrap { position: absolute; left: 0; right: 0; bottom: 0; height: 128px; }
.trend-grid-line { position: absolute; left: 0; right: 0; height: 1px; background: rgba(255,255,255,.07); }
.trend-grid-line.is-base { background: rgba(255,255,255,.18); }
.trend-grid-tag { position: absolute; left: 0; transform: translateY(-100%); font-size: 11px; color: #a8b4c8; font-weight: 800; }
.trend-bar-row { position: absolute; left: 34px; right: 0; bottom: 0; display: flex; align-items: flex-end; justify-content: space-between; gap: 6px; height: 128px; }
.trend-bar-col { display: flex; flex-direction: column; align-items: center; justify-content: flex-end; flex: 1 1 0; min-width: 0; height: 100%; }
.trend-connector {
    position: absolute;
    top: 4px;
    transform-origin: center;
    font-size: 10.5px;
    font-weight: 900;
    white-space: nowrap;
    padding: 2px 5px;
    border-radius: 6px;
    pointer-events: none;
    z-index: 2;
}
.trend-connector.is-positive { color: #4ade80; background: rgba(74,222,128,.12); border: 1px solid rgba(74,222,128,.4); }
.trend-connector.is-negative { color: #f87171; background: rgba(248,113,113,.12); border: 1px solid rgba(248,113,113,.4); }
.trend-connector.is-total { color: #f9a8d4; background: rgba(244,114,182,.18); border: 1px solid #f472b6; font-size: 11px; box-shadow: 0 0 10px rgba(244,114,182,.4); }
.trend-bar-value { font-size: 13.5px; font-weight: 900; color: #d6e6ff; white-space: nowrap; margin-bottom: 7px; padding: 4px 9px; border-radius: 9px; background: rgba(15,23,42,.9); border: 1px solid rgba(96,165,250,.6); box-shadow: 0 0 12px rgba(96,165,250,.5); }
.trend-bar-col.is-record .trend-bar-value { color: #ffe9f5; background: rgba(35,10,26,.9); border-color: rgba(244,114,182,.85); box-shadow: 0 0 16px rgba(244,114,182,.7); }
.trend-bar-shape { width: 70%; max-width: 26px; border-radius: 6px 6px 2px 2px; background: linear-gradient(180deg, #60a5fa, #3b5b8f); box-shadow: inset 0 1px 0 rgba(255,255,255,.15); }
.trend-bar-shape.is-record { background: linear-gradient(180deg, #f9a8d4, #ec4899); box-shadow: 0 0 14px rgba(244,114,182,.4), inset 0 1px 0 rgba(255,255,255,.25); }
.trend-axis { display: flex; justify-content: space-between; gap: 6px; padding-left: 34px; margin-bottom: 10px; }
.trend-axis span { flex: 1 1 0; min-width: 0; text-align: center; font-size: 11.5px; font-weight: 800; color: #b8c4d9; }
.trend-foot { display: flex; flex-direction: column; gap: 6px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,.08); font-size: 12.5px; color: #b8c4d9; }
.trend-foot-row1 { display: flex; gap: 14px; flex-wrap: wrap; }
.trend-foot-row2 { display: flex; gap: 14px; align-items: baseline; justify-content: space-between; }
.trend-foot strong { color: #fff; }
.trend-foot-desc { margin-left: auto; color: #7dd3fc; font-weight: 700; white-space: nowrap; text-transform: uppercase; letter-spacing: .3px; }
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


def _grossed_field_series(series: list[dict], field: str) -> list[dict]:
    """Applies gross_up to a single named field (AVG REV/EVNT or AVG
    REV/DAY - both $-per-something ratios) — same gross_up-only
    treatment as ledger.py's AVG/EVENT, never annualized, since a
    per-event or per-day average isn't a time-based rate to extrapolate."""
    return [{**row, field: gross_up(row[field])} for row in series]


def build_trends_fragment(timeline: pd.DataFrame, gross_view: bool = False, pipeline: pd.DataFrame | None = None) -> str:
    """Returns the Performance Trends panel as an embeddable HTML fragment
    (CSS + markup + script), for insertion into a larger single-iframe
    document such as render_dashboard()'s combined Hero/Leaderboard/Territory
    HTML — keeping the same 16px inter-panel spacing everywhere.
    """
    buckets = _prepare_buckets(timeline)

    weekly_revenue = buckets["weekly"]
    monthly_revenue = buckets["monthly"]
    weekday_revenue = buckets["weekday"]
    career_revenue = buckets["career"]
    weekly_avgrevperevent = buckets["weekly"]
    monthly_avgrevperevent = buckets["monthly"]
    weekday_avgrevperevent = buckets["weekday"]
    career_avgrevperevent = buckets["career"]
    weekly_avgrevperday = buckets["weekly"]
    monthly_avgrevperday = buckets["monthly"]
    weekday_avgrevperday = buckets["weekday"]
    career_avgrevperday = buckets["career"]
    if gross_view:
        weekly_revenue = _annualized_revenue_series(weekly_revenue, WEEKS_PER_YEAR)
        monthly_revenue = _annualized_revenue_series(monthly_revenue, MONTHS_PER_YEAR)
        # Career months are real month-length periods too (same as
        # MONTHLY, just anchored to career start instead of the
        # calendar) — same annualization treatment.
        career_revenue = _annualized_revenue_series(career_revenue, MONTHS_PER_YEAR)
        # Weekday view has no single clean annualization multiplier (it
        # aggregates revenue across every real occurrence of that weekday,
        # not one period) — but it still gets the gross-up applied like
        # every other dollar figure on the dashboard, just without a /yr
        # extrapolation on top.
        weekday_revenue = _grossed_revenue_series(weekday_revenue)
        weekly_avgrevperevent = _grossed_field_series(weekly_avgrevperevent, "avgrevperevent")
        monthly_avgrevperevent = _grossed_field_series(monthly_avgrevperevent, "avgrevperevent")
        career_avgrevperevent = _grossed_field_series(career_avgrevperevent, "avgrevperevent")
        weekday_avgrevperevent = _grossed_field_series(weekday_avgrevperevent, "avgrevperevent")
        weekly_avgrevperday = _grossed_field_series(weekly_avgrevperday, "avgrevperday")
        monthly_avgrevperday = _grossed_field_series(monthly_avgrevperday, "avgrevperday")
        career_avgrevperday = _grossed_field_series(career_avgrevperday, "avgrevperday")
        weekday_avgrevperday = _grossed_field_series(weekday_avgrevperday, "avgrevperday")

    # CLIENTS/CITIES are ranked lists of distinct entities, not time
    # periods — same "grossed but not annualized" treatment as WEEKDAY
    # above, since a total isn't a rate that should be extrapolated.
    clients_events = _client_top7(timeline, "events")
    clients_revenue = _client_top7(timeline, "revenue")
    cities_events = _city_group_top7(timeline, pipeline, "events")
    cities_revenue = _city_group_top7(timeline, pipeline, "revenue")
    clients_avgrevperevent = clients_revenue
    cities_avgrevperevent = cities_revenue
    clients_avgrevperday = clients_revenue
    cities_avgrevperday = cities_revenue
    if gross_view:
        clients_revenue = _grossed_revenue_series(clients_revenue)
        cities_revenue = _grossed_revenue_series(cities_revenue)
        clients_avgrevperevent = _grossed_field_series(clients_avgrevperevent, "avgrevperevent")
        cities_avgrevperevent = _grossed_field_series(cities_avgrevperevent, "avgrevperevent")
        clients_avgrevperday = _grossed_field_series(clients_avgrevperday, "avgrevperday")
        cities_avgrevperday = _grossed_field_series(cities_avgrevperday, "avgrevperday")

    # Confirmed bug this fixes: clients_avgrevperevent/day (and the
    # cities equivalents) started as a COPY of the revenue-ranked list
    # above — right for REVENUE, but AVG REV/EVNT and AVG REV/DAY are
    # DIFFERENT metrics with their own peak, so displaying them in
    # revenue's order left the bars completely unsorted by the value
    # actually being charted. Re-sorting each one by its own metric,
    # ascending (so the actual peak lands rightmost, same convention
    # as every other chart here).
    clients_avgrevperevent = sorted(clients_avgrevperevent, key=lambda r: r["avgrevperevent"])
    cities_avgrevperevent = sorted(cities_avgrevperevent, key=lambda r: r["avgrevperevent"])
    clients_avgrevperday = sorted(clients_avgrevperday, key=lambda r: r["avgrevperday"])
    cities_avgrevperday = sorted(cities_avgrevperday, key=lambda r: r["avgrevperday"])

    charts = "".join([
        _chart(buckets["weekly"], "events", "weekly-events", description="TOTAL"),
        _chart(weekly_revenue, "revenue", "weekly-revenue", suppress_total=gross_view, description="TOTAL"),
        _chart(buckets["weekly"], "avgevent", "weekly-avgevent", description="TOTAL"),
        _chart(weekly_avgrevperevent, "avgrevperevent", "weekly-avgrevperevent", suppress_total=gross_view, description="PER EVENT"),
        _chart(weekly_avgrevperday, "avgrevperday", "weekly-avgrevperday", suppress_total=gross_view, description="PER DAY"),
        _chart(buckets["monthly"], "events", "monthly-events", description="TOTAL", show_mom_connectors=True),
        _chart(monthly_revenue, "revenue", "monthly-revenue", suppress_total=gross_view, description="TOTAL", show_mom_connectors=True),
        _chart(buckets["monthly"], "avgevent", "monthly-avgevent", description="TOTAL", show_mom_connectors=True),
        _chart(monthly_avgrevperevent, "avgrevperevent", "monthly-avgrevperevent", suppress_total=gross_view, description="PER EVENT", show_mom_connectors=True),
        _chart(monthly_avgrevperday, "avgrevperday", "monthly-avgrevperday", suppress_total=gross_view, description="PER DAY", show_mom_connectors=True),
        _chart(buckets["career"], "events", "career-events", description="TOTAL", show_mom_connectors=True),
        _chart(career_revenue, "revenue", "career-revenue", suppress_total=gross_view, description="TOTAL", show_mom_connectors=True),
        _chart(buckets["career"], "avgevent", "career-avgevent", description="TOTAL", show_mom_connectors=True),
        _chart(career_avgrevperevent, "avgrevperevent", "career-avgrevperevent", suppress_total=gross_view, description="PER EVENT", show_mom_connectors=True),
        _chart(career_avgrevperday, "avgrevperday", "career-avgrevperday", suppress_total=gross_view, description="PER DAY", show_mom_connectors=True),
        _chart(buckets["weekday"], "events", "weekday-events", description="TOTAL"),
        _chart(weekday_revenue, "revenue", "weekday-revenue", suppress_total=gross_view, description="TOTAL"),
        _chart(buckets["weekday"], "avgevent", "weekday-avgevent", description="PER WEEK"),
        _chart(weekday_avgrevperevent, "avgrevperevent", "weekday-avgrevperevent", suppress_total=gross_view, description="PER EVENT"),
        _chart(weekday_avgrevperday, "avgrevperday", "weekday-avgrevperday", suppress_total=gross_view, description="PER DAY"),
        _chart(clients_events, "events", "clients-events", description="TOTAL"),
        _chart(clients_revenue, "revenue", "clients-revenue", suppress_total=gross_view, description="TOTAL"),
        _chart(clients_events, "avgevent", "clients-avgevent", description="TOTAL"),
        _chart(clients_avgrevperevent, "avgrevperevent", "clients-avgrevperevent", suppress_total=gross_view, description="PER EVENT"),
        _chart(clients_avgrevperday, "avgrevperday", "clients-avgrevperday", suppress_total=gross_view, description="PER DAY"),
        _chart(cities_events, "events", "cities-events", description="TOTAL"),
        _chart(cities_revenue, "revenue", "cities-revenue", suppress_total=gross_view, description="TOTAL"),
        _chart(cities_events, "avgevent", "cities-avgevent", description="TOTAL"),
        _chart(cities_avgrevperevent, "avgrevperevent", "cities-avgrevperevent", suppress_total=gross_view, description="PER EVENT"),
        _chart(cities_avgrevperday, "avgrevperday", "cities-avgrevperday", suppress_total=gross_view, description="PER DAY"),
    ])

    return f"""
      <div class="trend-panel panel" id="trendsPanel">
        <div class="trend-head-row">
          <div class="trend-title">PERFORMANCE TRENDS</div>
        </div>
        <div class="trend-tabs" id="periodTabs">
          <div class="trend-tabs-row">
            <div class="trend-tab is-active" data-period="weekly">WEEKLY</div>
            <div class="trend-tab" data-period="monthly">MONTHLY</div>
            <div class="trend-tab" data-period="career">CAREER</div>
          </div>
          <div class="trend-tabs-row">
            <div class="trend-tab" data-period="weekday">DAYofWK</div>
            <div class="trend-tab" data-period="clients">CLIENTS</div>
            <div class="trend-tab" data-period="cities">CITIES</div>
          </div>
        </div>
        <div class="trend-metric-row" id="metricTabs">
          <div class="trend-metric-tabs-row">
            <div class="trend-tab is-active" data-metric="events">EVENTS</div>
            <div class="trend-tab" data-metric="revenue">REVENUE</div>
          </div>
          <div class="trend-metric-tabs-row">
            <div class="trend-tab" data-metric="avgevent">AVG/EVNT</div>
            <div class="trend-tab" data-metric="avgrevperevent">AVG REV/EVNT</div>
            <div class="trend-tab" data-metric="avgrevperday">AVG REV/DAY</div>
          </div>
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
