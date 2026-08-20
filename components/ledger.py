from __future__ import annotations

from html import escape

import pandas as pd
import streamlit.components.v1 as components

from services.money_view import annualize_gross, gross_up, DAYS_PER_YEAR, WEEKS_PER_YEAR, MONTHS_PER_YEAR
from services.tz import eastern_today_naive


def _money(value: float) -> str:
    return f"\uFF04{value:,.2f}"


DASH = "\u2014"


def _month_index(date: pd.Timestamp, career_start: pd.Timestamp) -> int:
    months_diff = (date.year - career_start.year) * 12 + (date.month - career_start.month)
    if date.day < career_start.day:
        months_diff -= 1
    return months_diff


def _compute_l10wk(dated: pd.DataFrame) -> list[dict]:
    """Last 10 weeks (9 prior + current), using the same career-relative
    week numbering as the Performance Trends chart (W1 = first ISO week
    with data), so W-labels match exactly across the app.
    """
    weeks: list[dict] = []
    if dated.empty:
        return weeks

    career_start = dated["__date"].min()
    start_iso = career_start.isocalendar()
    start_index = start_iso.year * 52 + start_iso.week

    today = eastern_today_naive()
    # Monday of the current ISO week, walking backward in real calendar
    # time (not reverse-engineering year/week from a combined index,
    # which isn't a safe inversion near year boundaries since ISO years
    # have 52 or 53 weeks).
    this_monday = today - pd.Timedelta(days=today.weekday())

    iso = dated["__date"].dt.isocalendar()
    week_index = iso["year"] * 52 + iso["week"]

    for offset in range(9, -1, -1):
        week_start = this_monday - pd.Timedelta(weeks=offset)
        week_end = week_start + pd.Timedelta(days=6)
        wk_iso = week_start.isocalendar()
        wk_index = wk_iso.year * 52 + wk_iso.week
        wk_number = wk_index - start_index + 1
        is_current = offset == 0
        label = f"W{wk_number}*" if is_current else f"W{wk_number}"
        subset = dated[week_index == wk_index]
        events = len(subset)
        confirmed = int((subset["Verified?"] == "Yes").sum())
        days_worked = int(subset["__date"].dt.normalize().nunique())
        revenue = float(subset.loc[subset["Verified?"] == "Yes", "__amount"].sum())
        avg = revenue / confirmed if confirmed else 0.0
        weeks.append({
            "label": label,
            "start": week_start.strftime("%b %d"),
            "end": week_end.strftime("%b %d"),
            "events": events, "confirmed": confirmed, "days_worked": days_worked,
            "revenue": revenue, "avg": avg,
        })
    return weeks


def _compute_l10d(dated: pd.DataFrame, limit: int = 10) -> list[dict]:
    """Last N actual worked calendar days (only days with >=1 event —
    not just any 10 consecutive calendar dates, which could include
    empty ones). Reuses the exact same card shape as L10WK/CAREER/
    CALENDAR (built with the same _build_month_cards renderer), just at
    daily granularity — "days_worked" is trivially 1 for a single day
    with data, and "AVG REV/DAY" collapses to equal "REVENUE" for the
    same reason, which is expected at this granularity, not a bug.
    """
    if dated.empty:
        return []

    unique_days = sorted(dated["__date"].dt.normalize().unique())
    recent_days = unique_days[-limit:]

    days: list[dict] = []
    for day in recent_days:
        day_ts = pd.Timestamp(day)
        subset = dated[dated["__date"].dt.normalize() == day_ts]
        events = len(subset)
        confirmed = int((subset["Verified?"] == "Yes").sum())
        revenue = float(subset.loc[subset["Verified?"] == "Yes", "__amount"].sum())
        avg = revenue / confirmed if confirmed else 0.0
        label = day_ts.strftime("%b %d")
        days.append({
            "label": label,
            "start": label,
            "end": label,
            "events": events, "confirmed": confirmed, "days_worked": 1,
            "revenue": revenue, "avg": avg,
        })
    return days


def _compute_top_days(dated: pd.DataFrame, limit: int = 10) -> list[dict]:
    """Top N calendar days ranked by confirmed revenue earned that day
    (not per event) — reuses the same DAYS-tab card shape regardless of
    how many distinct clients/events contributed to that day's total.
    """
    if dated.empty:
        return []

    confirmed = dated[dated["Verified?"] == "Yes"].copy()
    if confirmed.empty:
        return []

    confirmed["__day"] = confirmed["__date"].dt.normalize()
    grouped = confirmed.groupby("__day").agg(
        revenue=("__amount", "sum"),
        events=("__amount", "size"),
    ).reset_index()
    grouped = grouped[grouped["revenue"] > 0]
    grouped = grouped.sort_values("revenue", ascending=False).head(limit)

    days = []
    for rank, row in enumerate(grouped.to_dict("records"), start=1):
        day = row["__day"]
        days.append({
            "rank": rank,
            "label": day.strftime("%b %d, %Y").upper(),
            "weekday": day.strftime("%A"),
            "events": int(row["events"]),
            "revenue": float(row["revenue"]),
        })
    return days


def _compute_top_clients(dated: pd.DataFrame, limit: int = 10) -> list[dict]:
    """Top N clients ranked by career-to-date confirmed revenue."""
    if dated.empty:
        return []

    grouped = dated.groupby("Client")
    rows = []
    for client, group in grouped:
        confirmed = group[group["Verified?"] == "Yes"]
        revenue = float(confirmed["__amount"].sum())
        if revenue <= 0:
            continue
        events = len(group)
        confirmed_count = len(confirmed)
        avg = revenue / confirmed_count if confirmed_count else 0.0
        rows.append({"client": str(client), "revenue": revenue, "events": events, "avg": avg})

    rows.sort(key=lambda r: r["revenue"], reverse=True)
    for rank, r in enumerate(rows[:limit], start=1):
        r["rank"] = rank
    return rows[:limit]


def _city_only(detail: object) -> str:
    """Same convention used on the Journey page — city name, state
    dropped, from a "City, ST" Location Detail string."""
    text = "" if pd.isna(detail) else str(detail).strip()
    return text.rsplit(",", 1)[0].strip() if "," in text else text


def _compute_top_cities(dated: pd.DataFrame, limit: int = 10) -> list[dict]:
    """Top N cities ranked by how many times visited (event count) —
    reuses the exact same card shape as Clients (built with the same
    _build_client_cards renderer), just grouped by city and ranked by
    visit frequency instead of by revenue.
    """
    if dated.empty:
        return []

    working = dated.copy()
    working["__city"] = working.get("Location Detail", pd.Series(dtype=object)).map(_city_only)
    working = working[working["__city"] != ""]
    if working.empty:
        return []

    rows = []
    for city, group in working.groupby("__city"):
        confirmed = group[group["Verified?"] == "Yes"]
        revenue = float(confirmed["__amount"].sum())
        events = len(group)
        confirmed_count = len(confirmed)
        avg = revenue / confirmed_count if confirmed_count else 0.0
        rows.append({"client": str(city), "revenue": revenue, "events": events, "avg": avg})

    rows.sort(key=lambda r: r["events"], reverse=True)
    for rank, r in enumerate(rows[:limit], start=1):
        r["rank"] = rank
    return rows[:limit]


def _compute_summary_and_months(
    timeline: pd.DataFrame, gross_view: bool = False
) -> tuple[list[tuple[str, str]], list[dict], list[dict], list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    working = timeline.copy()
    working["__date"] = pd.to_datetime(working["Service Date"], errors="coerce")
    working["__amount"] = pd.to_numeric(working["Amount"], errors="coerce").fillna(0)
    confirmed_mask = working["Verified?"] == "Yes"

    completed_events = len(working)
    events_confirmed = int(confirmed_mask.sum())
    breakdowns_missing = completed_events - events_confirmed
    confirmed_revenue = float(working.loc[confirmed_mask, "__amount"].sum())

    dated = working.dropna(subset=["__date"])
    days_worked = dated["__date"].dt.normalize().nunique()
    avg_revenue_per_day = confirmed_revenue / days_worked if days_worked else 0.0

    # Confirmed Revenue is a career-to-date point total, not a rate —
    # gross it up. Avg Revenue/Day IS a genuine rate — annualize it.
    displayed_revenue = gross_up(confirmed_revenue) if gross_view else confirmed_revenue
    displayed_avg_day = (
        annualize_gross(avg_revenue_per_day, DAYS_PER_YEAR) if gross_view else avg_revenue_per_day
    )
    revenue_label = "Confirmed Revenue"
    avg_day_label = "Avg Revenue / Day"

    payments_flagged = 1  # not modeled in the simplified Timeline schema; see ACTION_ITEMS

    summary = [
        (revenue_label, _money(displayed_revenue)),
        (avg_day_label, _money(displayed_avg_day)),
        ("Confirmed EV w/ Rev", f"{events_confirmed} ({completed_events})"),
        ("Pay Missing/Flagged", f"{breakdowns_missing}/{payments_flagged}"),
    ]

    # L10WK, CAREER, and CALENDAR are computed oldest-first internally
    # (simplest way to walk the date ranges), then reversed here so the
    # most recent period displays first — that's the requested order for
    # these three specifically. ERAS, DAYS, and CLIENTS are left as-is.
    career_months = _compute_career_months(dated)[::-1]
    calendar_months = _compute_calendar_months(dated)[::-1]
    eras = _compute_eras(dated)

    l10wk = _compute_l10wk(dated)[::-1]
    l10d = _compute_l10d(dated)[::-1]
    top_days = _compute_top_days(dated)
    top_clients = _compute_top_clients(dated)
    top_cities = _compute_top_cities(dated)

    return summary, career_months, calendar_months, eras, l10wk, top_days, top_clients, top_cities, l10d


def _compute_career_months(dated: pd.DataFrame) -> list[dict]:
    """30-ish-day cycles anchored to the career start date (e.g. Apr 20 -
    May 19, May 20 - Jun 19, ...). This is the original Ledger view.
    """
    months: list[dict] = []
    if dated.empty:
        return months

    career_start = dated["__date"].min().normalize()
    dated = dated.assign(__month_idx=dated["__date"].apply(lambda d: _month_index(d, career_start)))
    latest_month_idx = int(dated["__month_idx"].max())
    # Always show one month beyond the last one with real data, as a
    # live "current period" card — it'll show real zeros until dated
    # events actually land in that window.
    cycle_count = latest_month_idx + 2

    today = eastern_today_naive()
    for i in range(cycle_count):
        start = career_start + pd.DateOffset(months=i)
        end = career_start + pd.DateOffset(months=i + 1) - pd.Timedelta(days=1)
        is_current = start <= today <= end
        label = f"Month {i + 1}*" if is_current else f"Month {i + 1}"
        subset = dated[dated["__month_idx"] == i]
        start_label = start.strftime("%b %d")
        end_label = end.strftime("%b %d")
        events = len(subset)
        confirmed = int((subset["Verified?"] == "Yes").sum())
        days_worked = int(subset["__date"].dt.normalize().nunique())
        revenue = float(subset.loc[subset["Verified?"] == "Yes", "__amount"].sum())
        avg = revenue / confirmed if confirmed else 0.0
        months.append({
            "label": label,
            "start": start_label,
            "end": end_label,
            "events": events, "confirmed": confirmed, "days_worked": days_worked,
            "revenue": revenue, "avg": avg,
        })
    return months


def _compute_eras(dated: pd.DataFrame) -> list[dict]:
    """Named career eras — same card shape as Month/Calendar views, just
    a different, business-meaningful grouping instead of fixed-length
    cycles. Currently only "Speed Era" (since Jun 30, marking the
    production ramp-up from new contracts) has a confirmed definition.
    Add more named eras here once their start dates are confirmed.
    """
    eras: list[dict] = []
    if dated.empty:
        return eras

    ERA_DEFINITIONS = [
        ("Introduction Phase", pd.Timestamp("2026-04-20"), pd.Timestamp("2026-05-25")),
        ("Momentum Era", pd.Timestamp("2026-05-26"), pd.Timestamp("2026-06-29")),
        ("Speed Era", pd.Timestamp("2026-06-30"), None),
    ]

    for label, start, end in ERA_DEFINITIONS:
        end_ts = end if end is not None else eastern_today_naive()
        subset = dated[(dated["__date"] >= start) & (dated["__date"] <= end_ts)]
        end_label = end.strftime("%b %d") if end is not None else "Current"
        events = len(subset)
        confirmed = int((subset["Verified?"] == "Yes").sum())
        days_worked = int(subset["__date"].dt.normalize().nunique())
        revenue = float(subset.loc[subset["Verified?"] == "Yes", "__amount"].sum())
        avg = revenue / confirmed if confirmed else 0.0
        eras.append({
            "label": label,
            "start": start.strftime("%b %d"),
            "end": end_label,
            "events": events, "confirmed": confirmed, "days_worked": days_worked,
            "revenue": revenue, "avg": avg,
        })
    return eras


def _compute_calendar_months(dated: pd.DataFrame) -> list[dict]:
    """Real calendar months (1st to end-of-month), the more familiar
    'January, February, ...' framing instead of career-anchored cycles.
    """
    months: list[dict] = []
    if dated.empty:
        return months

    periods = dated["__date"].dt.to_period("M")
    today = eastern_today_naive()
    for period in sorted(periods.unique()):
        subset = dated[periods == period]
        start = period.start_time
        end = period.end_time.normalize()
        is_current = start <= today <= end
        label = f"{start.strftime('%B')}*" if is_current else start.strftime("%B")
        events = len(subset)
        confirmed = int((subset["Verified?"] == "Yes").sum())
        days_worked = int(subset["__date"].dt.normalize().nunique())
        revenue = float(subset.loc[subset["Verified?"] == "Yes", "__amount"].sum())
        avg = revenue / confirmed if confirmed else 0.0
        months.append({
            "label": label,
            "start": start.strftime("%b %d"),
            "end": end.strftime("%b %d"),
            "events": events, "confirmed": confirmed, "days_worked": days_worked,
            "revenue": revenue, "avg": avg,
        })
    return months


# Action items carry Work Order numbers and specific review-flag reasons
# that only exist in the original Financial Closeout sheet, not in the
# simplified real Timeline schema — kept as a static, manually-verified
# list rather than computed, unlike Summary/Monthly Breakdown above.
ACTION_ITEMS = [
    {"event": 77, "who": "Marshalls \u2014 Towson", "wo": "5906849", "status": "ACH confirmed", "amount": 130.00, "action": "Historical gap closed", "flag": "ok"},
    {"event": 91, "who": "Marshalls \u2014 Frederick", "wo": "5924273", "status": "Confirmed", "amount": 180.00, "action": "Locked", "flag": "ok"},
    {"event": 92, "who": "Dunkin' \u2014 Owings Mills", "wo": "5900744", "status": "Confirmed", "amount": 292.50, "action": "Locked", "flag": "ok"},
    {"event": 93, "who": "Food Lion \u2014 Essex", "wo": "5927446", "status": "Confirmed", "amount": 123.75, "action": "Manual authoritative update", "flag": "ok"},
    {"event": 94, "who": "Food Lion \u2014 Scaggsville", "wo": DASH, "status": "Confirmed", "amount": 161.24, "action": "Manual authoritative update", "flag": "ok"},
    {"event": 95, "who": "Marshalls \u2014 Clinton", "wo": "5930832", "status": "Confirmed", "amount": 200.00, "action": "Manual authoritative update", "flag": "ok"},
    {"event": 96, "who": "TJ Maxx \u2014 Prince Frederick", "wo": "5931220", "status": "Confirmed", "amount": 183.33, "action": "Manual authoritative update", "flag": "ok"},
]

LEDGER_CSS = """
<style>
*{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
html,body{width:100%;overflow:hidden;background:transparent}
body{color:#fff}
.ledger-panel { background: linear-gradient(155deg, #0c1118 0%, #080b11 85%); border: 1px solid rgba(244,114,182,.28); border-radius: 20px; padding: 20px; margin-bottom: 16px; box-shadow: 0 15px 35px rgba(0,0,0,.5); }
.ledger-title { font-size: 16px; font-weight: 900; letter-spacing: .5px; color: #fff; margin-bottom: 3px; }
.ledger-sub { font-size: 12px; color: #b8c4d9; margin-bottom: 16px; }
.ledger-kpi-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.ledger-kpi { background: linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.01)); border: 1px solid rgba(255,255,255,.08); border-radius: 12px; padding: 11px 12px; }
.ledger-kpi-val { font-size: 20px; font-weight: 900; color: #f9a8d4; text-shadow: 0 0 10px rgba(244,114,182,.5); }
.ledger-kpi-lbl { font-size: 10.5px; font-weight: 800; color: #c5d0e0; letter-spacing: .4px; text-transform: uppercase; margin-top: 3px; line-height: 1.35; }
.month-card { background: linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.01)); border: 1px solid rgba(255,255,255,.08); border-radius: 14px; padding: 14px; margin-bottom: 10px; }
.month-card:last-child { margin-bottom: 0; }
.month-view-tabs { display: grid; grid-template-columns: repeat(4, max-content); gap: 8px 8px; justify-content: start; justify-items: start; }
.month-view-tab { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); border-radius: 20px; padding: 7px 13px; font-size: 11px; font-weight: 800; letter-spacing: .5px; color: #c5d0e0; cursor: pointer; }
.month-view-tab.is-active { background: rgba(244,114,182,.1); border-color: #f472b6; color: #f9a8d4; box-shadow: 0 0 10px rgba(244,114,182,.25); }
.month-view { display: none; margin-top: 12px; }
.month-view.is-active { display: block; }
.month-card-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.month-card-name { font-size: 16px; font-weight: 900; letter-spacing: .8px; color: #fff; }
.month-card-range { font-size: 11.5px; color: #7dd3fc; font-weight: 700; }
.month-stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 8px; }
.month-stat { background: rgba(15,23,42,.5); border-radius: 10px; padding: 8px 4px; text-align: center; }
.month-stat-val { font-size: 18px; font-weight: 900; color: #fff; }
.month-stat-lbl { font-size: 9px; font-weight: 800; color: #b8c4d9; letter-spacing: .4px; margin-top: 2px; }
.month-revenue-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.month-revenue-item { background: rgba(244,114,182,.08); border: 1px solid rgba(244,114,182,.2); border-radius: 10px; padding: 8px 10px; text-align: center; }
.month-revenue-val { font-size: 17px; font-weight: 900; color: #f9a8d4; text-shadow: 0 0 8px rgba(244,114,182,.4); }
.month-revenue-lbl { font-size: 9px; font-weight: 800; color: #c5d0e0; letter-spacing: .4px; margin-top: 2px; }
.action-list { display: flex; flex-direction: column; gap: 8px; }
.action-item { background: rgba(15,20,32,.6); border: 1px solid rgba(255,255,255,.06); border-radius: 12px; padding: 11px 13px; }
.action-item.flag-missing { border-color: rgba(251,113,133,.4); background: rgba(60,15,25,.4); }
.action-item.flag-review { border-color: rgba(253,230,138,.35); background: rgba(50,40,10,.35); }
.action-row-top { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
.action-event { font-size: 11px; font-weight: 800; color: #b8c4d9; }
.action-who { font-size: 14.5px; font-weight: 900; letter-spacing: .3px; text-transform: uppercase; color: #fff; margin-top: 3px; }
.action-amount { font-size: 16px; font-weight: 900; color: #7dd3fc; white-space: nowrap; text-shadow: 0 0 8px rgba(56,189,248,.5); }
.action-item.flag-missing .action-amount { color: #fb7185; text-shadow: 0 0 8px rgba(251,113,133,.5); }
.action-status { font-size: 10.5px; font-weight: 800; margin-top: 5px; display: inline-block; padding: 3px 9px; border-radius: 999px; background: rgba(52,211,153,.15); color: #6ee7b7; }
.action-item.flag-review .action-status { background: rgba(253,230,138,.18); color: #fde68a; }
.action-item.flag-missing .action-status { background: rgba(251,113,133,.18); color: #fca5b1; }
.action-note { font-size: 11.5px; color: #c5d0e0; margin-top: 6px; }
@media (max-width: 480px) {
  .ledger-panel { padding: 16px 14px; }
  .ledger-kpi-grid { grid-template-columns: 1fr 1fr; }
  .month-stat-val { font-size: 16px; }
  .month-revenue-val { font-size: 15px; }
}
</style>
"""


def _build_month_cards(months: list[dict], gross_view: bool = False, periods_per_year: float = MONTHS_PER_YEAR) -> str:
    """periods_per_year controls how REVENUE gets annualized when gross
    is on — must match what period each card actually represents.
    Was previously hardcoded to MONTHS_PER_YEAR everywhere, which is
    correct for CAREER/CALENDAR/ERAS (real month-length periods) but
    was mathematically wrong for L10WK and L10DAY: a week's revenue x12
    doesn't represent a year (that's ~12 weeks, not 52), and a day's
    revenue x12 represents 12 days, nowhere close to annualized. Callers
    for those two now pass WEEKS_PER_YEAR / DAYS_PER_YEAR respectively.

    AVG REV/DAY now uses gross_up() only (matching AVG/EVENT's existing
    treatment) instead of annualize_gross() — it shows the grossed-up
    per-day figure, not an annualized rate, for every tab.
    """
    revenue_lbl = "REVENUE"
    avg_lbl = "AVG / EVENT"
    avg_day_lbl = "AVG REV/DAY"
    return "".join(
        '<div class="month-card">'
        '<div class="month-card-head">'
        f'<div class="month-card-name">{escape(m["label"].upper())}</div>'
        f'<div class="month-card-range">{escape(m["start"])} \u2013 {escape(m["end"])}</div>'
        '</div>'
        '<div class="month-stat-grid">'
        f'<div class="month-stat"><div class="month-stat-val">{m["events"]}</div><div class="month-stat-lbl">EVENTS</div></div>'
        f'<div class="month-stat"><div class="month-stat-val">{m["confirmed"]}</div><div class="month-stat-lbl">CONFIRMED</div></div>'
        f'<div class="month-stat"><div class="month-stat-val">{m["days_worked"]}</div><div class="month-stat-lbl">DAYS WORKED</div></div>'
        '</div>'
        '<div class="month-revenue-row">'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(annualize_gross(m["revenue"], periods_per_year) if gross_view else m["revenue"]))}</div><div class="month-revenue-lbl">{revenue_lbl}</div></div>'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(gross_up(m["avg"]) if gross_view else m["avg"]))}</div><div class="month-revenue-lbl">{avg_lbl}</div></div>'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(gross_up((m["revenue"] / m["days_worked"]) if m["days_worked"] else 0.0) if gross_view else ((m["revenue"] / m["days_worked"]) if m["days_worked"] else 0.0)))}</div><div class="month-revenue-lbl">{avg_day_lbl}</div></div>'
        '</div></div>'
        for m in months
    )


def _build_day_cards(days: list[dict]) -> str:
    return "".join(
        '<div class="month-card">'
        '<div class="month-card-head">'
        f'<div class="month-card-name">#{d["rank"]} \u00b7 {escape(d["label"])}</div>'
        f'<div class="month-card-range">{escape(d["weekday"].upper())} \u00b7 {d["events"]} EVENTS</div>'
        '</div>'
        '<div class="month-revenue-row">'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(d["revenue"]))}</div><div class="month-revenue-lbl">TOTAL REVENUE</div></div>'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(gross_up(d["revenue"])))}</div><div class="month-revenue-lbl">GROSS REVENUE</div></div>'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(annualize_gross(d["revenue"], DAYS_PER_YEAR)))}</div><div class="month-revenue-lbl">ANNUALIZED</div></div>'
        '</div></div>'
        for d in days
    )


def _build_client_cards(clients: list[dict], gross_view: bool = False) -> str:
    return "".join(
        '<div class="month-card">'
        '<div class="month-card-head">'
        f'<div class="month-card-name">#{c["rank"]} \u00b7 {escape(c["client"].upper())}</div>'
        '</div>'
        '<div class="month-revenue-row">'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{c["events"]}</div><div class="month-revenue-lbl">EVENTS</div></div>'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(gross_up(c["revenue"]) if gross_view else c["revenue"]))}</div><div class="month-revenue-lbl">TOTAL REVENUE</div></div>'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(gross_up(c["avg"]) if gross_view else c["avg"]))}</div><div class="month-revenue-lbl">AVG / EVENT</div></div>'
        '</div></div>'
        for c in clients
    )


def render_ledger_summary(timeline: pd.DataFrame, gross_view: bool = False) -> None:
    """Just the FINANCIAL CLOSEOUT panel — split out from the rest so a
    native Streamlit title+button row can sit between this and the
    breakdowns panel, in the exact spot the old embedded title used to
    occupy, instead of in front of the whole combined component.
    """
    summary, _, _, _, _, _, _, _, _ = _compute_summary_and_months(timeline, gross_view)
    kpi_html = "".join(
        f'<div class="ledger-kpi"><div class="ledger-kpi-val">{escape(val)}</div>'
        f'<div class="ledger-kpi-lbl">{escape(label)}</div></div>'
        for label, val in summary
    )
    html = f"""
    <!DOCTYPE html>
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
    {LEDGER_CSS}
    </head><body>
      <div class="ledger-panel">
        <div class="ledger-title" style="margin-bottom:14px">FINANCIAL CLOSEOUT</div>
        <div class="ledger-kpi-grid">{kpi_html}</div>
      </div>
    </body></html>
    """
    components.html(html, height=225, scrolling=False)


def render_ledger_breakdowns(timeline: pd.DataFrame, gross_view: bool = False, initial_tab: str = "l10wk") -> None:
    """The tab-grid breakdowns panel + Action Items — everything that
    used to sit below "MONTHLY BREAKDOWN". No title of its own now; the
    native "BREAKDOWNS" row rendered just above this (in app.py) takes
    that place, matching the original layout position exactly.

    `initial_tab` supports deep-linking here from elsewhere in the app
    (e.g. the CITIES gauge on the Main page hero card) — it picks which
    tab starts active. Server-side/one-shot: app.py reads+clears the
    query param that drives this before calling here, so it only
    affects the render immediately after navigating in, not every
    subsequent rerun while already on this page.
    """
    summary, career_months, calendar_months, eras, l10wk, top_days, top_clients, top_cities, l10d = (
        _compute_summary_and_months(timeline, gross_view)
    )

    career_cards = _build_month_cards(career_months, gross_view)
    calendar_cards = _build_month_cards(calendar_months, gross_view)
    era_cards = _build_month_cards(eras, gross_view)
    l10wk_cards = _build_month_cards(l10wk, gross_view, periods_per_year=WEEKS_PER_YEAR)
    l10d_cards = _build_month_cards(l10d, gross_view, periods_per_year=DAYS_PER_YEAR)
    day_cards = _build_day_cards(top_days)
    client_cards = _build_client_cards(top_clients, gross_view)
    city_cards = _build_client_cards(top_cities, gross_view)

    action_html = "".join(
        f'<div class="action-item flag-{item["flag"]}">'
        '<div class="action-row-top"><div>'
        f'<div class="action-event">EVENT #{item["event"]} &middot; WO {escape(item["wo"])}</div>'
        f'<div class="action-who">{escape(item["who"])}</div></div>'
        f'<div class="action-amount">{escape(_money(gross_up(item["amount"]) if gross_view else item["amount"])) if item["amount"] is not None else DASH}</div>'
        '</div>'
        f'<div class="action-status">{escape(item["status"])}</div>'
        f'<div class="action-note">{escape(item["action"])}</div>'
        '</div>'
        for item in ACTION_ITEMS
    )

    # Requested order — row 1: L10WK, ERAS, CAREER, CALENDAR
    #                   row 2: L10DAY, DAYS, CLIENTS, CITIES
    # Internal key stays "l10d" (matches _compute_l10d/l10d_cards above
    # and the deep-link query param elsewhere) — only the visible label
    # text changed to "L10DAY".
    tabs = ["l10wk", "eras", "career", "calendar", "l10d", "days", "clients", "cities"]
    if initial_tab not in tabs:
        initial_tab = "l10wk"

    def _tab_class(name: str) -> str:
        return "month-view-tab is-active" if name == initial_tab else "month-view-tab"

    def _view_class(name: str) -> str:
        return "month-view is-active" if name == initial_tab else "month-view"

    html = f"""
    <!DOCTYPE html>
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
    {LEDGER_CSS}
    </head><body>
      <div class="ledger-panel">
        <div class="month-view-tabs">
          <div class="{_tab_class('l10wk')}" data-view="l10wk">L10WK</div>
          <div class="{_tab_class('eras')}" data-view="eras">ERAS</div>
          <div class="{_tab_class('career')}" data-view="career">CAREER</div>
          <div class="{_tab_class('calendar')}" data-view="calendar">CALENDAR</div>
          <div class="{_tab_class('l10d')}" data-view="l10d">L10DAY</div>
          <div class="{_tab_class('days')}" data-view="days">DAYS</div>
          <div class="{_tab_class('clients')}" data-view="clients">CLIENTS</div>
          <div class="{_tab_class('cities')}" data-view="cities">CITIES</div>
        </div>
        <div class="{_view_class('l10wk')}" data-view="l10wk">{l10wk_cards}</div>
        <div class="{_view_class('eras')}" data-view="eras">{era_cards}</div>
        <div class="{_view_class('career')}" data-view="career">{career_cards}</div>
        <div class="{_view_class('calendar')}" data-view="calendar">{calendar_cards}</div>
        <div class="{_view_class('l10d')}" data-view="l10d">{l10d_cards}</div>
        <div class="{_view_class('days')}" data-view="days">{day_cards}</div>
        <div class="{_view_class('clients')}" data-view="clients">{client_cards}</div>
        <div class="{_view_class('cities')}" data-view="cities">{city_cards}</div>
      </div>

      <div class="ledger-panel">
        <div class="ledger-title">ACTION ITEMS</div>
        <div class="ledger-sub">Events flagged for review or missing a payment breakdown</div>
        <div class="action-list">{action_html}</div>
      </div>
      <script>
        (function() {{
          document.querySelectorAll('.month-view-tab').forEach(function(tab) {{
            tab.addEventListener('click', function() {{
              var view = tab.getAttribute('data-view');
              document.querySelectorAll('.month-view-tab').forEach(function(t) {{ t.classList.remove('is-active'); }});
              tab.classList.add('is-active');
              document.querySelectorAll('.month-view').forEach(function(v) {{
                v.classList.toggle('is-active', v.getAttribute('data-view') === view);
              }});
            }});
          }});
        }})();
      </script>
    </body></html>
    """

    height = (
        220
        + max(len(career_months), len(calendar_months), len(eras), len(l10wk), len(l10d), len(top_days), len(top_clients), len(top_cities)) * 190
        + len(ACTION_ITEMS) * 175
    )
    components.html(html, height=height, scrolling=False)


def render_ledger(timeline: pd.DataFrame, gross_view: bool = False) -> None:
    """Convenience wrapper — the two panels back-to-back with no native
    row between them. app.py calls the two pieces separately instead, so
    it can inject the native BREAKDOWNS title+toggle row between them.
    """
    render_ledger_summary(timeline, gross_view)
    render_ledger_breakdowns(timeline, gross_view)
