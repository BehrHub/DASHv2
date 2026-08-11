from __future__ import annotations

from html import escape

import pandas as pd
import streamlit.components.v1 as components

from services.money_view import annualize_gross, gross_up, DAYS_PER_YEAR, MONTHS_PER_YEAR


def _money(value: float) -> str:
    return f"\uFF04{value:,.2f}"


DASH = "\u2014"


def _month_index(date: pd.Timestamp, career_start: pd.Timestamp) -> int:
    months_diff = (date.year - career_start.year) * 12 + (date.month - career_start.month)
    if date.day < career_start.day:
        months_diff -= 1
    return months_diff


def _compute_summary_and_months(
    timeline: pd.DataFrame, gross_view: bool = False
) -> tuple[list[tuple[str, str]], list[dict], list[dict]]:
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

    summary = [
        (revenue_label, _money(displayed_revenue)),
        (avg_day_label, _money(displayed_avg_day)),
        ("Completed Events", f"{completed_events}"),
        ("Confirmed EV w/ Rev", f"{events_confirmed}"),
        ("Payments Missing", f"{breakdowns_missing}"),
        ("Payments Flagged", "1"),  # not modeled in the simplified Timeline schema; see ACTION_ITEMS
    ]

    career_months = _compute_career_months(dated)
    calendar_months = _compute_calendar_months(dated)

    return summary, career_months, calendar_months


def _compute_career_months(dated: pd.DataFrame) -> list[dict]:
    """30-ish-day cycles anchored to the career start date (e.g. Apr 20 -
    May 19, May 20 - Jun 19, ...). This is the original Ledger view.

    The final bonus period (beyond the last cycle with real data) is
    special-cased as "Speed Era" — a fixed since-June-30 snapshot
    marking when production ramped up (new contracts signed), rather
    than continuing the standard 30-day cycle math. It deliberately
    overlaps earlier cycle periods since it's a standalone "since X"
    view, not meant to be a clean non-overlapping bucket.
    """
    months: list[dict] = []
    if dated.empty:
        return months

    SPEED_ERA_START = pd.Timestamp("2026-06-30")

    career_start = dated["__date"].min().normalize()
    dated = dated.assign(__month_idx=dated["__date"].apply(lambda d: _month_index(d, career_start)))
    latest_month_idx = int(dated["__month_idx"].max())
    # Always show one month beyond the last one with real data, as a
    # live "current period" card — it'll show real zeros until dated
    # events actually land in that window.
    cycle_count = latest_month_idx + 2
    speed_era_index = cycle_count - 1

    for i in range(cycle_count):
        if i == speed_era_index:
            start = SPEED_ERA_START
            end = pd.Timestamp.now().normalize()
            label = "Speed Era"
            subset = dated[dated["__date"] >= SPEED_ERA_START]
            start_label = start.strftime("%b %d")
            end_label = "Current"
        else:
            start = career_start + pd.DateOffset(months=i)
            end = career_start + pd.DateOffset(months=i + 1) - pd.Timedelta(days=1)
            label = f"Month {i + 1}"
            subset = dated[dated["__month_idx"] == i]
            start_label = start.strftime("%b %d")
            end_label = end.strftime("%b %d")
        events = len(subset)
        confirmed = int((subset["Verified?"] == "Yes").sum())
        missing = events - confirmed
        revenue = float(subset.loc[subset["Verified?"] == "Yes", "__amount"].sum())
        avg = revenue / confirmed if confirmed else 0.0
        months.append({
            "label": label,
            "start": start_label,
            "end": end_label,
            "events": events, "confirmed": confirmed, "missing": missing,
            "revenue": revenue, "avg": avg,
        })
    return months


def _compute_calendar_months(dated: pd.DataFrame) -> list[dict]:
    """Real calendar months (1st to end-of-month), the more familiar
    'January, February, ...' framing instead of career-anchored cycles.
    """
    months: list[dict] = []
    if dated.empty:
        return months

    periods = dated["__date"].dt.to_period("M")
    for period in sorted(periods.unique()):
        subset = dated[periods == period]
        start = period.start_time
        end = period.end_time.normalize()
        events = len(subset)
        confirmed = int((subset["Verified?"] == "Yes").sum())
        missing = events - confirmed
        revenue = float(subset.loc[subset["Verified?"] == "Yes", "__amount"].sum())
        avg = revenue / confirmed if confirmed else 0.0
        months.append({
            "label": start.strftime("%B"),
            "start": start.strftime("%b %d"),
            "end": end.strftime("%b %d"),
            "events": events, "confirmed": confirmed, "missing": missing,
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
.ledger-title-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 2px; }
.month-view-tabs { display: flex; gap: 6px; flex-shrink: 0; }
.month-view-tab { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); border-radius: 20px; padding: 5px 12px; font-size: 10px; font-weight: 800; letter-spacing: .5px; color: #c5d0e0; cursor: pointer; }
.month-view-tab.is-active { background: rgba(244,114,182,.1); border-color: #f472b6; color: #f9a8d4; box-shadow: 0 0 10px rgba(244,114,182,.25); }
.month-view { display: none; margin-top: 12px; }
.month-view.is-active { display: block; }
.month-card-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.month-card-name { font-size: 16px; font-weight: 900; letter-spacing: .8px; color: #fff; }
.month-card-range { font-size: 11.5px; color: #7dd3fc; font-weight: 700; }
.month-stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 8px; }
.month-stat { background: rgba(15,23,42,.5); border-radius: 10px; padding: 8px 4px; text-align: center; }
.month-stat-val { font-size: 18px; font-weight: 900; color: #fff; }
.month-stat.is-missing .month-stat-val { color: #fb7185; }
.month-stat-lbl { font-size: 9px; font-weight: 800; color: #b8c4d9; letter-spacing: .4px; margin-top: 2px; }
.month-revenue-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
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


def _build_month_cards(months: list[dict], gross_view: bool = False) -> str:
    revenue_lbl = "REVENUE"
    avg_lbl = "AVG / EVENT"
    return "".join(
        '<div class="month-card">'
        '<div class="month-card-head">'
        f'<div class="month-card-name">{escape(m["label"].upper())}</div>'
        f'<div class="month-card-range">{escape(m["start"])} \u2013 {escape(m["end"])}</div>'
        '</div>'
        '<div class="month-stat-grid">'
        f'<div class="month-stat"><div class="month-stat-val">{m["events"]}</div><div class="month-stat-lbl">EVENTS</div></div>'
        f'<div class="month-stat"><div class="month-stat-val">{m["confirmed"]}</div><div class="month-stat-lbl">CONFIRMED</div></div>'
        f'<div class="month-stat{" is-missing" if m["missing"] else ""}"><div class="month-stat-val">{m["missing"]}</div><div class="month-stat-lbl">MISSING</div></div>'
        '</div>'
        '<div class="month-revenue-row">'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(annualize_gross(m["revenue"], MONTHS_PER_YEAR) if gross_view else m["revenue"]))}</div><div class="month-revenue-lbl">{revenue_lbl}</div></div>'
        f'<div class="month-revenue-item"><div class="month-revenue-val">{escape(_money(gross_up(m["avg"]) if gross_view else m["avg"]))}</div><div class="month-revenue-lbl">{avg_lbl}</div></div>'
        '</div></div>'
        for m in months
    )


def render_ledger(timeline: pd.DataFrame, gross_view: bool = False) -> None:
    summary, career_months, calendar_months = _compute_summary_and_months(timeline, gross_view)

    kpi_html = "".join(
        f'<div class="ledger-kpi"><div class="ledger-kpi-val">{escape(val)}</div>'
        f'<div class="ledger-kpi-lbl">{escape(label)}</div></div>'
        for label, val in summary
    )

    career_cards = _build_month_cards(career_months, gross_view)
    calendar_cards = _build_month_cards(calendar_months, gross_view)

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

    html = f"""
    <!DOCTYPE html>
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
    {LEDGER_CSS}
    </head><body>
      <div class="ledger-panel">
        <div class="ledger-title" style="margin-bottom:14px">FINANCIAL CLOSEOUT</div>
        <div class="ledger-kpi-grid">{kpi_html}</div>
      </div>

      <div class="ledger-panel">
        <div class="ledger-title-row">
          <div><div class="ledger-title">MONTHLY BREAKDOWN</div></div>
          <div class="month-view-tabs">
            <div class="month-view-tab is-active" data-view="career">CAREER</div>
            <div class="month-view-tab" data-view="calendar">CALENDAR</div>
          </div>
        </div>
        <div class="month-view is-active" data-view="career">{career_cards}</div>
        <div class="month-view" data-view="calendar">{calendar_cards}</div>
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

    height = 320 + 220 + max(len(career_months), len(calendar_months)) * 190 + len(ACTION_ITEMS) * 175
    components.html(html, height=height, scrolling=False)
