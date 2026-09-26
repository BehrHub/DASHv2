from __future__ import annotations

from html import escape

import pandas as pd
import streamlit.components.v1 as components

from services.money_view import gross_up


def _money(value: float) -> str:
    return f"\uFF04{value:,.0f}"


def _prep(timeline: pd.DataFrame) -> pd.DataFrame:
    df = timeline.copy()
    df["__date"] = pd.to_datetime(df["Service Date"], errors="coerce")
    df["__amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    return df[df["Verified?"] == "Yes"].dropna(subset=["__date"])


def _hottest_clients(confirmed: pd.DataFrame, today: pd.Timestamp, n: int = 5) -> list[dict]:
    """Trailing 30 days vs the 30 days before that, by event count -
    surfaces who's accelerating RIGHT NOW, a different signal than who
    simply has the most events or revenue overall."""
    recent = confirmed[confirmed["__date"] > today - pd.Timedelta(days=30)]
    prior = confirmed[
        (confirmed["__date"] <= today - pd.Timedelta(days=30))
        & (confirmed["__date"] > today - pd.Timedelta(days=60))
    ]
    recent_counts = recent.groupby("Client").size()
    prior_counts = prior.groupby("Client").size()
    all_clients = set(recent_counts.index) | set(prior_counts.index)
    rows = []
    for c in all_clients:
        r, p = int(recent_counts.get(c, 0)), int(prior_counts.get(c, 0))
        if r == 0:
            continue  # not active in the recent window at all - not "hot"
        rows.append({"client": c, "recent": r, "prior": p, "change": r - p})
    rows.sort(key=lambda x: (-x["change"], -x["recent"]))
    return rows[:n]


def _career_month_label(d: pd.Timestamp, career_start: pd.Timestamp) -> tuple[int, str]:
    """Same anchor-date career-month formula used everywhere else in
    this app (ledger.py, trends.py). Returns (sortable index, display
    label) - used here instead of calendar months so every "month"
    compared is a fair, equal ~30-day window. Confirmed real problem
    this fixes: April as a CALENDAR month only had the ~10-11 days
    between career start (Apr 20) and month-end, making its new-client/
    new-city count look artificially small next to every full month
    that followed - not because less was actually happening, just
    because the bucket itself was shorter.
    """
    months_diff = (d.year - career_start.year) * 12 + (d.month - career_start.month)
    if d.day < career_start.day:
        months_diff -= 1
    period_start = career_start + pd.DateOffset(months=months_diff)
    return months_diff, period_start.strftime("%b %d")


def _new_client_pace(confirmed: pd.DataFrame) -> list[dict]:
    """New clients acquired per CAREER month (not calendar month - see
    _career_month_label) vs the running average across every career
    month on record."""
    career_start = confirmed["__date"].min()
    first_seen = confirmed.groupby("Client")["__date"].min()
    labeled = first_seen.map(lambda d: _career_month_label(d, career_start))
    by_month = labeled.value_counts().sort_index()
    avg = by_month.mean()
    rows = []
    for (idx, label), count in by_month.items():
        pct_vs_avg = ((count / avg) - 1) * 100 if avg else 0.0
        rows.append({
            "month": label, "count": int(count),
            "avg": round(avg, 1), "pct_vs_avg": pct_vs_avg,
        })
    return rows


def _revenue_concentration(confirmed: pd.DataFrame) -> dict:
    """Pareto/80-20 check - what share of clients actually drive 80% of
    revenue, and how exposed the business is to its single biggest
    client going quiet."""
    by_client = confirmed.groupby("Client")["__amount"].sum().sort_values(ascending=False)
    total = by_client.sum()
    if total <= 0 or by_client.empty:
        return {"n_for_80": 0, "total_clients": 0, "pct_clients_for_80": 0.0, "top_client": "", "top_client_pct": 0.0}
    cum_pct = by_client.cumsum() / total * 100
    n_for_80 = int((cum_pct <= 80).sum()) + 1
    n_for_80 = min(n_for_80, len(by_client))
    return {
        "n_for_80": n_for_80,
        "total_clients": len(by_client),
        "pct_clients_for_80": n_for_80 / len(by_client) * 100,
        "top_client": str(by_client.index[0]),
        "top_client_pct": float(by_client.iloc[0] / total * 100),
    }


def _at_risk_clients(confirmed: pd.DataFrame, today: pd.Timestamp, n: int = 6, min_span_days: int = 14) -> list[dict]:
    """Overdue relative to each client's OWN normal visit rhythm, not one
    flat cutoff for everyone - a client who visits daily going quiet for
    2 weeks is far more alarming than a monthly client doing the same.

    min_span_days excludes clients whose ENTIRE known visit history was
    compressed into a short burst (confirmed real cases: USDA, 6 visits
    all within 8 days; Senate Sergeant at Arms, 5 visits within 4 days) -
    that pattern means a short project, not an ongoing relationship with
    a real recurring cadence to be "overdue" from. A tiny median gap
    from a burst of consecutive project-days isn't a rhythm the client
    was ever expected to repeat, so treating a long silence afterward as
    dramatically overdue is misleading. Genuine at-risk clients in real
    data all span 58+ days of actual history - 14 draws a clean, wide
    margin below every one of them.
    """
    rows = []
    for client, grp in confirmed.groupby("Client"):
        dates = grp["__date"].sort_values()
        if len(dates) < 3:
            continue
        span_days = (dates.iloc[-1] - dates.iloc[0]).days
        if span_days < min_span_days:
            continue
        gaps = dates.diff().dt.days.dropna()
        median_gap = gaps.median()
        days_since_last = (today - dates.iloc[-1]).days
        if median_gap > 0 and days_since_last > median_gap * 2:
            rows.append({
                "client": str(client), "visits": len(dates), "median_gap": round(median_gap, 1),
                "days_since_last": int(days_since_last), "ratio": days_since_last / median_gap,
            })
    rows.sort(key=lambda x: -x["ratio"])
    return rows[:n]


def _new_vs_repeat_revenue(confirmed: pd.DataFrame, today: pd.Timestamp, n_months: int = 3) -> list[dict]:
    """What share of each month's revenue came from clients seen for the
    very first time that month, vs already-established repeat clients -
    a growth-vs-retention story invisible in a plain revenue total."""
    first_seen = confirmed.groupby("Client")["__date"].min()
    rows = []
    for offset in range(n_months - 1, -1, -1):
        period = today.to_period("M") - offset
        month_start, month_end = period.start_time, period.end_time
        events = confirmed[(confirmed["__date"] >= month_start) & (confirmed["__date"] <= month_end)]
        if events.empty:
            continue
        new_rev = events[events["Client"].map(lambda c: first_seen[c] >= month_start)]["__amount"].sum()
        total = events["__amount"].sum()
        repeat_rev = total - new_rev
        rows.append({
            "month": month_start.strftime("%B"), "new_rev": float(new_rev),
            "repeat_rev": float(repeat_rev), "new_pct": (new_rev / total * 100) if total else 0.0,
        })
    return rows


def _lifetime_trajectory(confirmed: pd.DataFrame, min_visits: int = 3, n: int = 6) -> list[dict]:
    """For clients with a real visit history, is their rate per event
    trending up (upsell/earned trust) or down (discount creep) from
    their very first visit to their most recent one?"""
    rows = []
    for client, grp in confirmed.groupby("Client"):
        dates_sorted = grp.sort_values("__date")
        if len(dates_sorted) < min_visits:
            continue
        first_rate = float(dates_sorted["__amount"].iloc[0])
        last_rate = float(dates_sorted["__amount"].iloc[-1])
        if first_rate <= 0:
            continue
        pct_change = ((last_rate - first_rate) / first_rate) * 100
        rows.append({
            "client": str(client), "visits": len(dates_sorted),
            "first_rate": first_rate, "last_rate": last_rate, "pct_change": pct_change,
        })
    rows.sort(key=lambda x: -abs(x["pct_change"]))
    return rows[:n]


def _cadence_classification(confirmed: pd.DataFrame) -> dict:
    """Labels every client with 2+ visits by their own median gap between
    visits, so the pattern of who's a true regular vs occasional is
    explicit rather than something only held in memory."""
    buckets = {"Weekly": [], "Biweekly": [], "Monthly": [], "Occasional": []}
    for client, grp in confirmed.groupby("Client"):
        dates = grp["__date"].sort_values()
        if len(dates) < 2:
            continue
        median_gap = dates.diff().dt.days.dropna().median()
        if median_gap <= 9:
            buckets["Weekly"].append(str(client))
        elif median_gap <= 18:
            buckets["Biweekly"].append(str(client))
        elif median_gap <= 40:
            buckets["Monthly"].append(str(client))
        else:
            buckets["Occasional"].append(str(client))
    return buckets


def _best_rolling_30(confirmed: pd.DataFrame) -> dict:
    """The single best 30-CONSECUTIVE-day stretch anywhere in the whole
    career, starting on any real day it was actually worked - not locked
    to calendar-month boundaries the way 'best month' normally is, so a
    hot streak spanning e.g. July 20 - Aug 18 doesn't get artificially
    split and hidden across two separate calendar months."""
    daily = confirmed.groupby(confirmed["__date"].dt.normalize())["__amount"].sum()
    if daily.empty:
        return {"start": None, "end": None, "revenue": 0.0}
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_range, fill_value=0.0)
    rolling = daily.rolling(window=30, min_periods=30).sum()
    if rolling.dropna().empty:
        return {"start": None, "end": None, "revenue": 0.0}
    best_end = rolling.idxmax()
    best_start = best_end - pd.Timedelta(days=29)
    return {"start": best_start, "end": best_end, "revenue": float(rolling.max())}


def _geo_expansion_pace(confirmed: pd.DataFrame) -> list[dict]:
    """New cities visited per CAREER month (not calendar month - same
    fix and reasoning as _new_client_pace) vs the running average."""
    if "Location Detail" not in confirmed.columns:
        return []
    career_start = confirmed["__date"].min()
    first_seen = confirmed.groupby("Location Detail")["__date"].min()
    labeled = first_seen.map(lambda d: _career_month_label(d, career_start))
    by_month = labeled.value_counts().sort_index()
    avg = by_month.mean()
    rows = []
    for (idx, label), count in by_month.items():
        pct_vs_avg = ((count / avg) - 1) * 100 if avg else 0.0
        rows.append({"month": label, "count": int(count), "pct_vs_avg": pct_vs_avg})
    return rows


def _frequency_vs_rate(confirmed: pd.DataFrame) -> dict:
    """Do more frequent (higher-volume) clients pay MORE or LESS per
    event than occasional ones? A simple correlation between a client's
    total visit count and their average $/event."""
    by_client = confirmed.groupby("Client").agg(visits=("__amount", "count"), avg_rate=("__amount", "mean"))
    by_client = by_client[by_client["visits"] >= 2]
    if len(by_client) < 4:
        return {"correlation": None, "n_clients": len(by_client)}
    corr = float(by_client["visits"].corr(by_client["avg_rate"]))
    return {"correlation": corr, "n_clients": len(by_client)}


def _section(title: str, subtitle: str, body_html: str) -> str:
    return (
        '<div class="sp-section">'
        f'<div class="sp-section-title">{escape(title)}</div>'
        f'<div class="sp-section-sub">{escape(subtitle)}</div>'
        f'{body_html}'
        '</div>'
    )


def render_stats_plus(timeline: pd.DataFrame, gross_view: bool = False) -> None:
    confirmed = _prep(timeline)
    if confirmed.empty:
        components.html('<div style="color:#94a3b8;padding:20px;">No confirmed events yet.</div>', height=200)
        return
    today = confirmed["__date"].max()
    conv = gross_up if gross_view else (lambda x: x)

    # --- 1. Hottest clients ---
    hottest = _hottest_clients(confirmed, today)
    hottest_rows = "".join(
        f'<div class="sp-row"><div class="sp-row-name">{escape(r["client"])}</div>'
        f'<div class="sp-row-detail">{r["prior"]} \u2192 {r["recent"]} events (last 30d)</div>'
        f'<div class="sp-row-badge sp-up">+{r["change"]}</div></div>'
        for r in hottest
    ) or '<div class="sp-empty">Not enough recent activity yet.</div>'

    # --- 2. New client pace ---
    pace = _new_client_pace(confirmed)
    pace_rows = "".join(
        f'<div class="sp-row"><div class="sp-row-name">{escape(r["month"])}</div>'
        f'<div class="sp-row-detail">{r["count"]} new (avg {r["avg"]}/mo)</div>'
        f'<div class="sp-row-badge {"sp-up" if r["pct_vs_avg"] >= 0 else "sp-down"}">{r["pct_vs_avg"]:+.0f}%</div></div>'
        for r in pace
    )

    # --- 3. Revenue concentration ---
    conc = _revenue_concentration(confirmed)
    conc_html = (
        '<div class="sp-stat-pair">'
        f'<div class="sp-stat"><div class="sp-stat-val">{conc["n_for_80"]} of {conc["total_clients"]}</div>'
        '<div class="sp-stat-lbl">CLIENTS DRIVE 80% OF REVENUE</div></div>'
        f'<div class="sp-stat"><div class="sp-stat-val">{conc["top_client_pct"]:.1f}%</div>'
        f'<div class="sp-stat-lbl">FROM {escape(conc["top_client"].upper())} ALONE</div></div>'
        '</div>'
    )

    # --- 4. At-risk clients ---
    at_risk = _at_risk_clients(confirmed, today)
    risk_rows = "".join(
        f'<div class="sp-row"><div class="sp-row-name">{escape(r["client"])}</div>'
        f'<div class="sp-row-detail">usually every {r["median_gap"]:.0f}d, now {r["days_since_last"]}d silent</div>'
        f'<div class="sp-row-badge sp-down">{r["ratio"]:.1f}x</div></div>'
        for r in at_risk
    ) or '<div class="sp-empty">Nothing overdue right now.</div>'

    # --- 5. New vs repeat revenue ---
    nvr = _new_vs_repeat_revenue(confirmed, today)
    nvr_rows = "".join(
        f'<div class="sp-row"><div class="sp-row-name">{escape(r["month"])}</div>'
        f'<div class="sp-split-bar"><div class="sp-split-new" style="width:{r["new_pct"]:.1f}%"></div></div>'
        f'<div class="sp-row-detail">{escape(_money(conv(r["new_rev"])))} new / {escape(_money(conv(r["repeat_rev"])))} repeat</div></div>'
        for r in nvr
    )

    # --- 6. Lifetime trajectory ---
    traj = _lifetime_trajectory(confirmed)
    traj_rows = "".join(
        f'<div class="sp-row"><div class="sp-row-name">{escape(r["client"])}</div>'
        f'<div class="sp-row-detail">{escape(_money(conv(r["first_rate"])))} \u2192 {escape(_money(conv(r["last_rate"])))} /event</div>'
        f'<div class="sp-row-badge {"sp-up" if r["pct_change"] >= 0 else "sp-down"}">{r["pct_change"]:+.0f}%</div></div>'
        for r in traj
    ) or '<div class="sp-empty">Not enough repeat history yet.</div>'

    # --- 7. Cadence classification ---
    cadence = _cadence_classification(confirmed)
    cadence_html = "".join(
        f'<div class="sp-cadence-pill"><div class="sp-cadence-count">{len(members)}</div>'
        f'<div class="sp-cadence-label">{escape(label.upper())}</div></div>'
        for label, members in cadence.items()
    )

    # --- 8. Best rolling 30 ---
    best30 = _best_rolling_30(confirmed)
    if best30["start"] is not None:
        is_current = best30["end"].normalize() == today.normalize()
        best30_html = (
            '<div class="sp-highlight">'
            f'<div class="sp-highlight-val">{escape(_money(conv(best30["revenue"])))}</div>'
            f'<div class="sp-highlight-sub">{best30["start"].strftime("%b %d")} \u2013 {best30["end"].strftime("%b %d")}'
            f'{" \u2014 that\'s RIGHT NOW" if is_current else ""}</div>'
            '</div>'
        )
    else:
        best30_html = '<div class="sp-empty">Not enough history yet (need 30+ days worked).</div>'

    # --- 9. Geographic expansion ---
    geo = _geo_expansion_pace(confirmed)
    geo_rows = "".join(
        f'<div class="sp-row"><div class="sp-row-name">{escape(r["month"])}</div>'
        f'<div class="sp-row-detail">{r["count"]} new cities</div>'
        f'<div class="sp-row-badge {"sp-up" if r["pct_vs_avg"] >= 0 else "sp-down"}">{r["pct_vs_avg"]:+.0f}%</div></div>'
        for r in geo
    )

    # --- 10. Frequency vs rate correlation ---
    freq = _frequency_vs_rate(confirmed)
    if freq["correlation"] is not None:
        c = freq["correlation"]
        strength = "strong" if abs(c) > 0.5 else ("weak" if abs(c) > 0.2 else "no real")
        direction = "MORE" if c > 0 else "LESS"
        freq_html = (
            '<div class="sp-highlight">'
            f'<div class="sp-highlight-val">{c:+.2f}</div>'
            f'<div class="sp-highlight-sub">A {strength} relationship \u2014 your more frequent clients tend to pay {direction} per event, not the opposite.</div>'
            '</div>'
        )
    else:
        freq_html = '<div class="sp-empty">Not enough repeat clients yet to check this.</div>'

    body = "".join([
        _section("\U0001F525 HOTTEST CLIENTS", "Biggest jump, last 30 days vs the 30 before that", f'<div class="sp-list">{hottest_rows}</div>'),
        _section("\U0001F195 NEW CLIENT PACE", "New clients acquired per month vs your running average", f'<div class="sp-list">{pace_rows}</div>'),
        _section("\U0001F4CA REVENUE CONCENTRATION", "How exposed you are to your biggest accounts", conc_html),
        _section("\u26A0\uFE0F AT-RISK CLIENTS", "Overdue relative to their OWN normal rhythm, not a flat cutoff", f'<div class="sp-list">{risk_rows}</div>'),
        _section("\U0001F331 NEW VS REPEAT REVENUE", "Growth from new clients vs retention of existing ones", f'<div class="sp-list">{nvr_rows}</div>'),
        _section("\U0001F4C8 CLIENT RATE TRAJECTORY", "First visit's rate vs most recent, per client", f'<div class="sp-list">{traj_rows}</div>'),
        _section("\U0001F501 VISIT CADENCE", "Every client classified by their own real visit rhythm", f'<div class="sp-cadence-row">{cadence_html}</div>'),
        _section("\U0001F3C6 BEST-EVER 30-DAY STRETCH", "Any 30 consecutive days, not locked to calendar months", best30_html),
        _section("\U0001F5FA\uFE0F GEOGRAPHIC EXPANSION", "New cities visited per month vs your running average", f'<div class="sp-list">{geo_rows}</div>'),
        _section("\U0001F517 FREQUENCY vs RATE", "Do your regulars pay more or less per visit than one-off clients?", freq_html),
    ])

    html = f"""<!doctype html><html><head><meta charset="utf-8">
    <style>
    *{{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
    html,body{{width:100%;background:transparent;color:#fff}}
    .sp-page{{padding:4px 2px 24px}}
    .sp-title{{font-size:20px;font-weight:900;letter-spacing:.5px;margin-bottom:2px}}
    .sp-subtitle{{font-size:11px;color:#94a3b8;margin-bottom:18px}}
    .sp-section{{background:rgba(15,20,32,.4);border:1px solid rgba(255,255,255,.06);border-radius:16px;padding:16px;margin-bottom:14px}}
    .sp-section-title{{font-size:13.5px;font-weight:800;letter-spacing:.3px}}
    .sp-section-sub{{font-size:10.5px;color:#7d8aa3;margin-top:2px;margin-bottom:12px}}
    .sp-list{{display:flex;flex-direction:column;gap:8px}}
    .sp-row{{display:flex;align-items:center;gap:10px;background:rgba(255,255,255,.03);border-radius:10px;padding:9px 11px}}
    .sp-row-name{{font-size:12.5px;font-weight:700;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
    .sp-row-detail{{font-size:10.5px;color:#94a3b8;flex-shrink:0}}
    .sp-row-badge{{font-size:11px;font-weight:900;padding:3px 8px;border-radius:8px;flex-shrink:0}}
    .sp-up{{color:#4ade80;background:rgba(74,222,128,.12)}}
    .sp-down{{color:#f87171;background:rgba(248,113,113,.12)}}
    .sp-empty{{font-size:11px;color:#64748b;padding:8px 0;text-align:center}}
    .sp-stat-pair{{display:flex;gap:10px}}
    .sp-stat{{flex:1;background:rgba(255,255,255,.03);border-radius:12px;padding:14px;text-align:center}}
    .sp-stat-val{{font-size:20px;font-weight:900;color:#f472b6}}
    .sp-stat-lbl{{font-size:9px;font-weight:800;color:#94a3b8;letter-spacing:.3px;margin-top:4px}}
    .sp-split-bar{{flex:1;height:8px;border-radius:4px;background:rgba(52,211,153,.25);overflow:hidden}}
    .sp-split-new{{height:100%;background:#f472b6}}
    .sp-cadence-row{{display:flex;gap:8px;flex-wrap:wrap}}
    .sp-cadence-pill{{flex:1;min-width:70px;background:rgba(255,255,255,.03);border-radius:12px;padding:12px 6px;text-align:center}}
    .sp-cadence-count{{font-size:18px;font-weight:900;color:#7dd3fc}}
    .sp-cadence-label{{font-size:8.5px;font-weight:800;color:#94a3b8;letter-spacing:.3px;margin-top:2px}}
    .sp-highlight{{text-align:center;padding:10px 0}}
    .sp-highlight-val{{font-size:26px;font-weight:900;color:#34d399}}
    .sp-highlight-sub{{font-size:11px;color:#94a3b8;margin-top:6px}}
    </style></head><body>
    <div class="sp-page">
    <div class="sp-title">STATS+</div>
    <div class="sp-subtitle">Deeper patterns your other tabs don't surface on their own</div>
    {body}
    </div>
    </body></html>"""

    components.html(html, height=2350, scrolling=True)
