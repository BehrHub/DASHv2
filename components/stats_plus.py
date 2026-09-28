from __future__ import annotations

from html import escape

import pandas as pd
import streamlit.components.v1 as components

from services.money_view import gross_up
from services.groups import (
    CLIENT_GROUPS,
    LOCATION_GROUPS,
    compute_client_group_ranking,
    compute_location_group_ranking,
)


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
    return months_diff, f"Career Month {months_diff + 1}"


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
        clients = sorted(
            (
                {"client": str(c), "first": first_seen[c]}
                for c, lab in labeled.items() if lab[0] == idx
            ),
            key=lambda x: x["first"],
        )
        rows.append({
            "month": label, "count": int(count),
            "avg": round(avg, 1), "pct_vs_avg": pct_vs_avg, "clients": clients,
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
    fix and reasoning as _new_client_pace) vs the running average.
    Each row also carries the actual cities first visited that month
    (with first-visit date and the location group each rolls up to,
    if any) for the tap-to-reveal drawer."""
    if "Location Detail" not in confirmed.columns:
        return []
    career_start = confirmed["__date"].min()
    loc_to_group = {m: gname for gname, members in LOCATION_GROUPS.items() for m in members}
    first_seen = confirmed.groupby("Location Detail")["__date"].min()
    labeled = first_seen.map(lambda d: _career_month_label(d, career_start))
    by_month = labeled.value_counts().sort_index()
    avg = by_month.mean()
    rows = []
    for (idx, label), count in by_month.items():
        pct_vs_avg = ((count / avg) - 1) * 100 if avg else 0.0
        cities = sorted(
            (
                {"city": str(city), "first": first_seen[city], "group": loc_to_group.get(city)}
                for city, lab in labeled.items() if lab[0] == idx
            ),
            key=lambda x: x["first"],
        )
        rows.append({"month": label, "count": int(count), "pct_vs_avg": pct_vs_avg, "cities": cities})
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


def _group_concentration(client_rank: list[dict]) -> dict:
    """How much of total revenue comes from the 7 formal CLIENT_GROUPS
    (services/groups.py) vs standalone/ungrouped clients - answers
    "are my grouped accounts really where the money is" directly,
    distinct from the existing per-CLIENT revenue Pareto stat above
    which doesn't distinguish grouped from standalone at all.
    Confirmed real numbers (2026-09-20 data): the 7 formal groups are
    23 of 35 clients (66%) but 77.8% of total revenue; the top-ranked
    entries (mixing groups and standalone clients together) cross 85%
    within the first 6-7 entries - close to, but a bit under, an even
    90% round number.
    """
    total_rev = sum(r["revenue"] for r in client_rank)
    total_clients = sum(r["member_count"] for r in client_rank)
    grouped_rows = [r for r in client_rank if r["is_group"]]
    grouped_rev = sum(r["revenue"] for r in grouped_rows)
    grouped_clients = sum(r["member_count"] for r in grouped_rows)
    if total_rev <= 0:
        return {"n_groups": 0, "grouped_clients": 0, "total_clients": total_clients,
                "group_rev_pct": 0.0, "top_n": 0, "top_n_pct": 0.0}
    ranked = sorted(client_rank, key=lambda r: -r["revenue"])
    cum, top_n = 0.0, 0
    for r in ranked:
        cum += r["revenue"]
        top_n += 1
        if cum / total_rev >= 0.85:
            break
    return {
        "n_groups": len(grouped_rows), "grouped_clients": grouped_clients,
        "total_clients": total_clients, "group_rev_pct": grouped_rev / total_rev * 100,
        "top_n": top_n, "top_n_pct": cum / total_rev * 100,
    }


def _group_vs_standalone_premium(client_rank: list[dict]) -> dict | None:
    """Do clients that belong to a formal group actually earn more on
    average per client than standalone/ungrouped ones? Confirmed real
    numbers (2026-09-20): grouped clients average $727/client vs
    $398/client for standalone ones - a genuine ~83% premium, checked
    to be broad-based (TJX/Government/DunkBR/Grocery all contribute),
    not one outlier group inflating the whole figure."""
    grouped_rows = [r for r in client_rank if r["is_group"]]
    standalone_rows = [r for r in client_rank if not r["is_group"]]
    g_clients = sum(r["member_count"] for r in grouped_rows)
    s_clients = sum(r["member_count"] for r in standalone_rows)
    if g_clients == 0 or s_clients == 0:
        return None
    g_avg = sum(r["revenue"] for r in grouped_rows) / g_clients
    s_avg = sum(r["revenue"] for r in standalone_rows) / s_clients
    if s_avg <= 0:
        return None
    return {"grouped_avg": g_avg, "standalone_avg": s_avg, "premium_pct": (g_avg / s_avg - 1) * 100}


def _group_efficiency(client_rank: list[dict], n: int = 7) -> list[dict]:
    """Formal client groups ranked by average revenue PER EVENT, not
    total volume - reveals which relationships are the most valuable
    per visit versus which just show up often. A different cut than
    the concentration stat above, which is about total dollars, not
    rate: confirmed real numbers show Macy's Inc. Group tops this at
    $255/event despite being 7th by total volume, while Nursing Home
    Group is lowest at $52/event."""
    rows = [
        {"name": r["name"], "avg": r["avg"], "events": r["confirmed"]}
        for r in client_rank if r["is_group"] and r["confirmed"] > 0
    ]
    rows.sort(key=lambda x: -x["avg"])
    return rows[:n]


def _territory_concentration(loc_rank: list[dict]) -> dict:
    """Same concentration question as _group_concentration, applied to
    LOCATION_GROUPS/territory instead of clients - which handful of
    markets your revenue actually comes from. Confirmed real numbers:
    the top 5 territories (mixing city groups and standalone cities)
    account for roughly 40% of all revenue, led by Landover-proper."""
    total_rev = sum(r["revenue"] for r in loc_rank)
    if total_rev <= 0:
        return {"top": [], "total_rev": 0.0}
    ranked = sorted(loc_rank, key=lambda r: -r["revenue"])
    top, cum = [], 0.0
    for r in ranked[:5]:
        cum += r["revenue"]
        top.append({"name": r["name"], "revenue": r["revenue"], "cum_pct": cum / total_rev * 100})
    return {"top": top, "total_rev": total_rev}


def _diverse_markets(confirmed: pd.DataFrame, n: int = 5) -> list[dict]:
    """Which territories (city groups or standalone cities) you've
    served the WIDEST range of distinct clients in - a different
    signal than revenue or event volume: a market can be modest in
    dollars but still be where you're building the broadest client
    base. Confirmed real numbers: Rockville-proper leads with 7
    distinct clients, Washington DC 6, Owings Mills-proper 5.
    Each row also carries the actual client list (with event counts
    in that territory) for the tap-to-reveal drawer."""
    loc_to_group = {m: gname for gname, members in LOCATION_GROUPS.items() for m in members}
    tmp = confirmed.copy()
    tmp["__loc_group"] = tmp["Location Detail"].map(loc_to_group).fillna(tmp["Location Detail"])
    diversity = tmp.groupby("__loc_group")["Client"].nunique().sort_values(ascending=False)
    rows = []
    for name, count in diversity.head(n).items():
        sub = tmp[tmp["__loc_group"] == name]
        clients = sub.groupby("Client").size().sort_values(ascending=False)
        rows.append({
            "name": str(name), "count": int(count), "events": int(len(sub)),
            "n_cities": int(sub["Location Detail"].nunique()),
            "clients": [{"client": str(c), "events": int(e)} for c, e in clients.items()],
        })
    return rows


def _territory_members(confirmed: pd.DataFrame, name: str) -> dict:
    """Drill-down for one TERRITORY CONCENTRATION row. A formal location
    group returns its member cities that actually appear in confirmed
    events, each with revenue and event count. A standalone city has no
    members to list, so it returns the clients served there instead."""
    members = LOCATION_GROUPS.get(name)
    if members:
        sub = confirmed[confirmed["Location Detail"].isin(members)]
        by = sub.groupby("Location Detail").agg(rev=("__amount", "sum"), events=("__amount", "size"))
        by = by.sort_values("rev", ascending=False)
        return {"kind": "group", "items": [
            {"label": str(city), "rev": float(r.rev), "events": int(r.events)} for city, r in by.iterrows()
        ]}
    sub = confirmed[confirmed["Location Detail"] == name]
    by = sub.groupby("Client").agg(rev=("__amount", "sum"), events=("__amount", "size"))
    by = by.sort_values("rev", ascending=False)
    return {"kind": "standalone", "items": [
        {"label": str(c), "rev": float(r.rev), "events": int(r.events)} for c, r in by.iterrows()
    ]}


def _group_momentum(confirmed: pd.DataFrame, today: pd.Timestamp, n: int = 4) -> list[dict]:
    """Trailing 30 days vs the 30 days before that, by DOLLAR revenue,
    for each formal client group - shown as a $ delta rather than a
    percentage on purpose: with several groups sitting near a near-
    zero prior-period baseline, a %-based framing produces wild,
    misleading swings (one real group in this data works out to a
    literal 1264% figure that is really just $124 -> $1,688 - not a
    meaningful trend). This is the same project-burst-style distortion
    already fixed in the AT-RISK CLIENTS stat above, just showing up
    here as an unstable percentage instead of a false overdue flag."""
    client_to_group = {m: gname for gname, members in CLIENT_GROUPS.items() for m in members}
    tmp = confirmed.copy()
    tmp["__group"] = tmp["Client"].map(client_to_group)
    grouped_only = tmp[tmp["__group"].notna()]
    recent = grouped_only[grouped_only["__date"] > today - pd.Timedelta(days=30)]
    prior = grouped_only[
        (grouped_only["__date"] <= today - pd.Timedelta(days=30))
        & (grouped_only["__date"] > today - pd.Timedelta(days=60))
    ]
    r_sum = recent.groupby("__group")["__amount"].sum()
    p_sum = prior.groupby("__group")["__amount"].sum()
    rows = []
    for g in set(r_sum.index) | set(p_sum.index):
        r, p = float(r_sum.get(g, 0.0)), float(p_sum.get(g, 0.0))
        rows.append({"name": g, "recent": r, "prior": p, "delta": r - p})
    rows.sort(key=lambda x: -x["delta"])
    return rows[:n]


# ---------------------------------------------------------------------------
# Rendering
#
# Layout contract for every list row (.sp-row), so every section lines up
# the same way regardless of how long a name or stat is:
#   col 1 = name (full width, WRAPS - never truncated)
#   col 2 = badge (fixed min-width, right-aligned)
#   col 3 = chevron (only on expandable rows)
#   line 2 = detail stat, always starting at the same left edge as the name
# Expandable rows use native <details>/<summary>: opens inline with no
# Streamlit rerun, no widget state, and no JS required for the toggle itself.
# ---------------------------------------------------------------------------

def _badge(text: str, tone: str = "up") -> str:
    return f'<div class="sp-badge sp-{tone}">{escape(text)}</div>'


def _row(name: str, badge_html: str = "", detail: str = "", drawer: str = "", extra: str = "") -> str:
    """detail is pre-escaped HTML (so it can carry <b> emphasis);
    name is raw text and escaped here."""
    chevron = '<div class="sp-chev" aria-hidden="true"></div>' if drawer else ""
    head = (
        f'<div class="sp-name">{escape(name)}</div>'
        f'{badge_html}{chevron}'
        + (f'<div class="sp-detail">{detail}</div>' if detail else "")
        + extra
    )
    if drawer:
        return (
            f'<details class="sp-row sp-expand"><summary class="sp-grid">{head}</summary>'
            f'<div class="sp-drawer">{drawer}</div></details>'
        )
    return f'<div class="sp-row"><div class="sp-grid">{head}</div></div>'


def _sub_list(items: list[dict], note: str = "") -> str:
    """Drawer body: a compact list of (label, value, optional tag,
    optional share bar). items: {label, value, tag?, share?}."""
    out = [f'<div class="sp-drawer-note">{escape(note)}</div>'] if note else []
    for it in items:
        tag = f'<span class="sp-sub-tag">{escape(it["tag"])}</span>' if it.get("tag") else ""
        bar = (
            f'<div class="sp-sub-bar"><div style="width:{max(it["share"], 2):.1f}%"></div></div>'
            if it.get("share") is not None else ""
        )
        out.append(
            f'<div class="sp-sub"><div class="sp-sub-label">{escape(it["label"])}{tag}</div>'
            f'<div class="sp-sub-val">{escape(it["value"])}</div>{bar}</div>'
        )
    return "".join(out)


def _client_revenue_ranking(confirmed: pd.DataFrame) -> list[dict]:
    """Every client by total revenue, with its share and running share -
    the drill-down behind REVENUE CONCENTRATION's "N of M" pill. Uses the
    exact same groupby as _revenue_concentration so the lists agree."""
    by_client = confirmed.groupby("Client")["__amount"].sum().sort_values(ascending=False)
    total = by_client.sum()
    if total <= 0:
        return []
    out, cum = [], 0.0
    for c, v in by_client.items():
        cum += v
        out.append({"client": str(c), "rev": float(v), "pct": v / total * 100, "cum_pct": cum / total * 100})
    return out


def _client_median_gaps(confirmed: pd.DataFrame) -> dict:
    """Median days between visits per client (2+ visits) - the same
    measure _cadence_classification buckets on, shown in its drill-down."""
    out = {}
    for client, grp in confirmed.groupby("Client"):
        dates = grp["__date"].sort_values()
        if len(dates) >= 2:
            out[str(client)] = (float(dates.diff().dt.days.dropna().median()), len(dates))
    return out


def _pill_panel(group: str, key: str, inner: str) -> str:
    return f'<div class="sp-panel" data-group="{group}" id="{group}-{key}" hidden>{inner}</div>'


def _section(title: str, subtitle: str, body_html: str, hint: bool | str = False) -> str:
    hint_text = hint if isinstance(hint, str) else "Tap a row to see who\'s in it"
    hint_html = f'<div class="sp-hint">{escape(hint_text)}</div>' if hint else ""
    return (
        '<section class="sp-section">'
        f'<div class="sp-section-title">{escape(title)}</div>'
        f'<div class="sp-section-sub">{escape(subtitle)}</div>'
        f'{hint_html}{body_html}'
        '</section>'
    )


def _list(rows: str) -> str:
    return f'<div class="sp-list">{rows}</div>'


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def render_stats_plus(timeline: pd.DataFrame, gross_view: bool = False) -> None:
    confirmed = _prep(timeline)
    if confirmed.empty:
        components.html('<div style="color:#94a3b8;padding:20px;">No confirmed events yet.</div>', height=200)
        return
    today = confirmed["__date"].max()
    conv = gross_up if gross_view else (lambda x: x)

    def m(v: float) -> str:
        return escape(_money(conv(v)))

    n_rows = 0  # counted for the fallback iframe height estimate

    # --- 1. Hottest clients ---
    hottest = _hottest_clients(confirmed, today)
    n_rows += len(hottest)
    hottest_rows = "".join(
        _row(r["client"], _badge(f'+{r["change"]}'),
             f'{r["prior"]} \u2192 <b>{r["recent"]}</b> events in the last 30 days')
        for r in hottest
    ) or '<div class="sp-empty">Not enough recent activity yet.</div>'

    # --- 2. New client pace ---
    pace = _new_client_pace(confirmed)
    n_rows += len(pace)
    pace_rows = "".join(
        _row(
            r["month"], _badge(f'{r["pct_vs_avg"]:+.0f}%', "up" if r["pct_vs_avg"] >= 0 else "down"),
            f'<b>{_plural(r["count"], "new client")}</b>',
            drawer=_sub_list(
                [{"label": c["client"], "value": c["first"].strftime("%b %d")} for c in r["clients"]],
                note="First visit",
            ),
        )
        for r in pace
    )
    pace_avg_html = (
        f'<div class="sp-avg-strip"><span class="sp-avg-num">{pace[0]["avg"]}</span>'
        '<span class="sp-avg-lbl">average new clients per career month</span></div>'
    ) if pace else ""

    # --- 3. Revenue concentration ---
    conc = _revenue_concentration(confirmed)
    ranking = _client_revenue_ranking(confirmed)
    conc_items = [
        {"label": r["client"], "value": f'{_money(conv(r["rev"]))} \u00b7 {r["pct"]:.1f}%',
         "share": r["pct"] / ranking[0]["pct"] * 100}
        for r in ranking
    ]
    n80 = conc["n_for_80"]
    conc_panel = (
        _sub_list(conc_items[:n80], note="All clients by revenue")
        + f'<div class="sp-cutline">\u2191 These {n80} drive 80% of revenue</div>'
        + f'<div class="sp-tail">{_sub_list(conc_items[n80:])}</div>'
    ) if conc_items[n80:] else _sub_list(conc_items, note="All clients by revenue")
    conc_html = (
        '<div class="sp-stat-pair">'
        '<button class="sp-stat sp-tap" data-group="conc" data-key="all" aria-expanded="false">'
        f'<div class="sp-stat-val">{conc["n_for_80"]}<span class="sp-stat-of"> of {conc["total_clients"]}</span></div>'
        '<div class="sp-stat-lbl">Clients drive 80% of revenue</div><div class="sp-tap-chev"></div></button>'
        f'<div class="sp-stat"><div class="sp-stat-val">{conc["top_client_pct"]:.1f}%</div>'
        f'<div class="sp-stat-lbl">From {escape(conc["top_client"])} alone</div></div>'
        '</div>'
        + _pill_panel("conc", "all", conc_panel)
    )

    # --- 4. At-risk clients ---
    at_risk = _at_risk_clients(confirmed, today)
    n_rows += len(at_risk)
    risk_rows = "".join(
        _row(r["client"], _badge(f'{r["ratio"]:.1f}x', "down"),
             f'Usually every {r["median_gap"]:.0f}d \u00b7 now <b>{r["days_since_last"]}d silent</b>')
        for r in at_risk
    ) or '<div class="sp-empty">Nothing overdue right now.</div>'

    # --- 5. New vs repeat revenue ---
    nvr = _new_vs_repeat_revenue(confirmed, today)
    n_rows += len(nvr) + 1
    nvr_rows = "".join(
        _row(
            r["month"], _badge(f'{100 - r["new_pct"]:.0f}% repeat', "teal"),
            f'<span class="sp-pink">{m(r["new_rev"])} new</span> \u00b7 '
            f'<span class="sp-teal">{m(r["repeat_rev"])} repeat</span>',
            extra=(f'<div class="sp-split-bar"><div class="sp-split-new" '
                   f'style="width:{r["new_pct"]:.1f}%"></div></div>'),
        )
        for r in nvr
    )

    # --- 6. Lifetime trajectory ---
    traj = _lifetime_trajectory(confirmed)
    n_rows += len(traj)
    traj_rows = "".join(
        _row(r["client"], _badge(f'{r["pct_change"]:+.0f}%', "up" if r["pct_change"] >= 0 else "down"),
             f'{m(r["first_rate"])} \u2192 <b>{m(r["last_rate"])}</b> per event \u00b7 {r["visits"]} visits')
        for r in traj
    ) or '<div class="sp-empty">Not enough repeat history yet.</div>'

    # --- 7. Cadence classification ---
    cadence = _cadence_classification(confirmed)
    gaps = _client_median_gaps(confirmed)
    cadence_html = '<div class="sp-cadence-row">' + "".join(
        f'<button class="sp-cadence-pill sp-tap" data-group="cad" data-key="{i}" aria-expanded="false"'
        f'{" disabled" if not members else ""}>'
        f'<div class="sp-cadence-count">{len(members)}</div>'
        f'<div class="sp-cadence-label">{escape(label)}</div>'
        f'{"<div class=\"sp-tap-chev\"></div>" if members else ""}</button>'
        for i, (label, members) in enumerate(cadence.items())
    ) + '</div>' + "".join(
        _pill_panel("cad", str(i), _sub_list(
            [{"label": c, "value": f'every {gaps[c][0]:.0f}d \u00b7 {_plural(gaps[c][1], "visit")}'}
             for c in sorted(members, key=lambda c: gaps.get(c, (999, 0))[0])],
            note=f"{label} clients",
        ))
        for i, (label, members) in enumerate(cadence.items()) if members
    )

    # --- 8. Best rolling 30 ---
    best30 = _best_rolling_30(confirmed)
    if best30["start"] is not None:
        is_current = best30["end"].normalize() == today.normalize()
        now_tag = '<div class="sp-now">That\'s right now</div>' if is_current else ""
        best30_html = (
            '<div class="sp-highlight">'
            f'<div class="sp-highlight-val">{m(best30["revenue"])}</div>'
            f'<div class="sp-highlight-sub">{best30["start"].strftime("%b %d")} \u2013 {best30["end"].strftime("%b %d")}</div>'
            f'{now_tag}</div>'
        )
    else:
        best30_html = '<div class="sp-empty">Not enough history yet (need 30+ days worked).</div>'

    # --- 9. Geographic expansion (expandable: cities introduced that month) ---
    geo = _geo_expansion_pace(confirmed)
    n_rows += len(geo)
    geo_rows = "".join(
        _row(
            r["month"], _badge(f'{r["pct_vs_avg"]:+.0f}%', "up" if r["pct_vs_avg"] >= 0 else "down"),
            f'<b>{_plural(r["count"], "new city", "new cities")}</b>',
            drawer=_sub_list([
                {"label": c["city"], "value": c["first"].strftime("%b %d"), "tag": c["group"]}
                for c in r["cities"]
            ], note="First visited"),
        )
        for r in geo
    )

    # --- 10. Frequency vs rate correlation ---
    freq = _frequency_vs_rate(confirmed)
    if freq["correlation"] is not None:
        c = freq["correlation"]
        strength = "strong" if abs(c) > 0.5 else ("weak" if abs(c) > 0.2 else "no real")
        direction = "more" if c > 0 else "less"
        if strength == "no real":
            freq_sub = "No real relationship \u2014 frequent clients pay about the same per event as occasional ones."
        else:
            freq_sub = (f"A {strength} relationship \u2014 your more frequent clients tend to pay "
                        f"{direction} per event.")
        freq_html = (
            '<div class="sp-highlight">'
            f'<div class="sp-highlight-val">{c:+.2f}</div>'
            f'<div class="sp-highlight-sub">{freq_sub}</div>'
            '</div>'
        )
    else:
        freq_html = '<div class="sp-empty">Not enough repeat clients yet to check this.</div>'

    # --- Group / territory sourced stats ---
    client_rank = compute_client_group_ranking(timeline, gross_view=False)
    loc_rank = compute_location_group_ranking(timeline)

    # --- 11. Client group concentration ---
    gconc = _group_concentration(client_rank)
    gconc_html = (
        '<div class="sp-stat-pair">'
        f'<div class="sp-stat"><div class="sp-stat-val">{gconc["group_rev_pct"]:.1f}%</div>'
        f'<div class="sp-stat-lbl">Of revenue from {gconc["n_groups"]} formal groups '
        f'({gconc["grouped_clients"]} of {gconc["total_clients"]} clients)</div></div>'
        f'<div class="sp-stat"><div class="sp-stat-val">Top {gconc["top_n"]}</div>'
        f'<div class="sp-stat-lbl">Groups/clients = {gconc["top_n_pct"]:.0f}% of revenue</div></div>'
        '</div>'
    )

    # --- 12. Group vs standalone premium ---
    premium = _group_vs_standalone_premium(client_rank)
    if premium:
        premium_html = (
            '<div class="sp-highlight">'
            f'<div class="sp-highlight-val{"" if premium["premium_pct"] >= 0 else " sp-neg"}">{premium["premium_pct"]:+.0f}%</div>'
            f'<div class="sp-highlight-sub">Grouped clients average <b>{m(premium["grouped_avg"])}</b> per client vs '
            f'<b>{m(premium["standalone_avg"])}</b> for standalone ones.</div>'
            '</div>'
        )
    else:
        premium_html = '<div class="sp-empty">Not enough data on both sides yet.</div>'

    # --- 13. Group efficiency (avg $/event) ---
    geff = _group_efficiency(client_rank)
    n_rows += len(geff)
    geff_rows = "".join(
        _row(r["name"], _badge(f'{_money(conv(r["avg"]))}/evt'), f'{_plural(r["events"], "event")}')
        for r in geff
    ) or '<div class="sp-empty">No group event data yet.</div>'

    # --- 14. Territory concentration (expandable: member cities / clients) ---
    tconc = _territory_concentration(loc_rank)
    n_rows += len(tconc["top"])
    terr_parts = []
    for r in tconc["top"]:
        own_pct = r["revenue"] / tconc["total_rev"] * 100 if tconc["total_rev"] else 0.0
        mem = _territory_members(confirmed, r["name"])
        mem_total = sum(i["rev"] for i in mem["items"]) or 1.0
        drawer = _sub_list(
            [{"label": i["label"], "value": f'{_money(conv(i["rev"]))} \u00b7 {_plural(i["events"], "evt")}',
              "share": i["rev"] / mem_total * 100} for i in mem["items"]],
            note=("Member cities" if mem["kind"] == "group" else "Standalone city \u2014 clients served here"),
        ) if mem["items"] else '<div class="sp-drawer-note">No member detail found.</div>'
        terr_parts.append(_row(
            r["name"], _badge(_money(conv(r["revenue"]))),
            f'<b>{own_pct:.0f}%</b> of revenue \u00b7 {r["cum_pct"]:.0f}% running total',
            drawer=drawer,
        ))
    terr_rows = "".join(terr_parts) or '<div class="sp-empty">No location revenue yet.</div>'

    # --- 15. Most diverse markets (expandable: the clients themselves) ---
    diverse = _diverse_markets(confirmed)
    n_rows += len(diverse)
    diverse_rows = "".join(
        _row(
            r["name"], _badge(_plural(r["count"], "client")),
            _plural(r["events"], "event")
            + (f' across {_plural(r["n_cities"], "city", "cities")}' if r["name"] in LOCATION_GROUPS else ""),
            drawer=_sub_list(
                [{"label": c["client"], "value": _plural(c["events"], "evt")} for c in r["clients"]],
                note="Clients served here",
            ),
        )
        for r in diverse
    ) or '<div class="sp-empty">Not enough location data yet.</div>'

    # --- 16. Group momentum ---
    mom = _group_momentum(confirmed, today)
    n_rows += len(mom)
    mom_rows = "".join(
        _row(
            r["name"],
            _badge(f'{_money(conv(abs(r["delta"])))} {"up" if r["delta"] >= 0 else "down"}',
                   "up" if r["delta"] >= 0 else "down"),
            f'{m(r["prior"])} \u2192 <b>{m(r["recent"])}</b>',
        )
        for r in mom
    ) or '<div class="sp-empty">Not enough group history yet.</div>'

    body = "".join([
        _section("\U0001F525 Hottest Clients", "Biggest jump, last 30 days vs the 30 before that", _list(hottest_rows)),
        _section("\U0001F195 New Client Pace", "New clients acquired per career month vs your running average", pace_avg_html + _list(pace_rows), hint="Tap a month to see who you gained"),
        _section("\U0001F4CA Revenue Concentration", "How exposed you are to your biggest accounts", conc_html, hint="Tap the client count to see the full list"),
        _section("\U0001F331 New vs Repeat Revenue", "Share of each month's revenue from returning clients", _list(nvr_rows)),
        _section("\U0001F501 Visit Cadence", "Every client classified by their own real visit rhythm", cadence_html, hint="Tap a rhythm to see its clients"),
        _section("\U0001F3C6 Best-Ever 30-Day Stretch", "Any 30 consecutive days, not locked to calendar months", best30_html),
        _section("\U0001F5FA\uFE0F Geographic Expansion", "New cities visited per career month vs your running average", _list(geo_rows), hint="Tap a month to see the cities"),
        _section("\U0001F30D Territory Concentration", "The handful of markets your revenue actually comes from", _list(terr_rows), hint=True),
        _section("\U0001F30E Most Diverse Markets", "Territories with the widest range of distinct clients served", _list(diverse_rows), hint=True),
        _section("\U0001F517 Frequency vs Rate", "Do your regulars pay more or less per visit than one-off clients?", freq_html),
        _section("\U0001F465 Client Group Concentration", "How much of your revenue rides on your formal client groups", gconc_html),
        _section("\u2696\uFE0F Group Efficiency", "Formal groups ranked by average revenue per event, not total volume", _list(geff_rows)),
        _section("\u26A1 Group Momentum", "Revenue, last 30 days vs the 30 before that, by formal client group", _list(mom_rows)),
        _section("\u26A0\uFE0F At-Risk Clients", "Overdue relative to their own normal rhythm, not a flat cutoff", _list(risk_rows)),
        _section("\U0001F4B0 Group Premium", "Grouped clients vs standalone ones, average revenue per client", premium_html),
        _section("\U0001F4C8 Client Rate Trajectory", "First visit's rate vs most recent, per client", _list(traj_rows)),
    ])

    html = f"""<!doctype html><html><head><meta charset="utf-8">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
    <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    html,body{{width:100%;background:transparent;color:#fff;overflow-x:hidden}}
    body{{font-family:"Space Grotesk",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
    .sp-page{{padding:6px 2px 28px}}
    .sp-title{{font-family:"Bebas Neue",Impact,sans-serif;font-size:34px;letter-spacing:1.5px;line-height:1}}
    .sp-subtitle{{font-size:13px;color:#a5b1c7;margin:4px 0 22px}}
    .sp-section{{background:linear-gradient(180deg,rgba(22,30,48,.55),rgba(12,17,28,.55));border:1px solid rgba(255,255,255,.07);border-radius:18px;padding:20px 16px 18px;margin-bottom:18px}}
    .sp-section-title{{font-family:"Bebas Neue",Impact,sans-serif;font-size:24px;letter-spacing:1.2px;line-height:1.05}}
    .sp-section-sub{{font-size:13px;color:#a5b1c7;margin-top:5px;line-height:1.35}}
    .sp-hint{{font-size:11.5px;color:#7dd3fc;margin-top:6px;font-weight:600}}
    .sp-list{{display:flex;flex-direction:column;gap:10px;margin-top:16px}}
    .sp-row{{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.04);border-radius:13px}}
    .sp-grid{{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;row-gap:6px;align-items:center;padding:13px 14px}}
    .sp-expand .sp-grid{{grid-template-columns:minmax(0,1fr) auto 18px}}
    .sp-name{{font-family:"Bebas Neue",Impact,sans-serif;font-size:21px;letter-spacing:.8px;line-height:1.1;overflow-wrap:anywhere}}
    .sp-detail{{grid-column:1/-1;font-size:14.5px;font-weight:500;color:#dbe3f0;line-height:1.35}}
    .sp-detail b{{font-weight:700;color:#fff}}
    .sp-badge{{justify-self:end;min-width:84px;text-align:center;font-size:14px;font-weight:700;padding:5px 10px;border-radius:9px;white-space:nowrap;font-variant-numeric:tabular-nums}}
    .sp-up{{color:#4ade80;background:rgba(74,222,128,.13)}}
    .sp-down{{color:#f87171;background:rgba(248,113,113,.13)}}
    .sp-pink{{color:#f9a8d4}}
    .sp-teal{{color:#6ee7b7}}
    .sp-badge.sp-pink{{background:rgba(244,114,182,.14)}}
    .sp-badge.sp-teal{{background:rgba(110,231,183,.13)}}
    .sp-split-bar{{grid-column:1/-1;height:9px;border-radius:5px;background:rgba(52,211,153,.28);overflow:hidden}}
    .sp-split-new{{height:100%;background:#f472b6;border-radius:5px 0 0 5px}}
    .sp-expand summary{{list-style:none;cursor:pointer;-webkit-tap-highlight-color:transparent}}
    .sp-expand summary::-webkit-details-marker{{display:none}}
    .sp-chev{{width:10px;height:10px;border-right:2.5px solid #7dd3fc;border-bottom:2.5px solid #7dd3fc;transform:rotate(45deg) translate(-2px,-2px);transition:transform .2s ease;justify-self:center}}
    .sp-expand[open] .sp-chev{{transform:rotate(225deg) translate(-2px,-2px)}}
    .sp-expand[open]{{border-color:rgba(125,211,252,.35);background:rgba(125,211,252,.05)}}
    .sp-expand summary:focus-visible{{outline:2px solid #7dd3fc;outline-offset:-2px;border-radius:13px}}
    .sp-drawer{{padding:2px 14px 14px;animation:spOpen .22s ease}}
    @keyframes spOpen{{from{{opacity:0;transform:translateY(-4px)}}to{{opacity:1;transform:none}}}}
    @media (prefers-reduced-motion:reduce){{.sp-drawer{{animation:none}}.sp-chev{{transition:none}}}}
    .sp-drawer-note{{font-size:11.5px;font-weight:700;color:#7dd3fc;letter-spacing:.4px;text-transform:uppercase;padding:10px 0 6px;border-top:1px solid rgba(255,255,255,.08)}}
    .sp-sub{{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:10px;row-gap:5px;align-items:baseline;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.05)}}
    .sp-sub:last-child{{border-bottom:none}}
    .sp-sub-label{{font-size:15px;font-weight:600;color:#fff;overflow-wrap:anywhere}}
    .sp-sub-tag{{display:inline-block;margin-left:8px;font-size:11px;font-weight:700;color:#a5b1c7;background:rgba(255,255,255,.07);padding:2px 7px;border-radius:6px;vertical-align:2px}}
    .sp-cutline{{font-size:12px;font-weight:700;color:#f9a8d4;text-align:center;padding:8px 0;margin:4px 0;border-top:1.5px dashed rgba(244,114,182,.45);border-bottom:1.5px dashed rgba(244,114,182,.45)}}
    .sp-tail{{opacity:.6}}
    .sp-sub-val{{font-size:14px;font-weight:700;color:#dbe3f0;white-space:nowrap;font-variant-numeric:tabular-nums}}
    .sp-sub-bar{{grid-column:1/-1;height:5px;border-radius:3px;background:rgba(255,255,255,.06);overflow:hidden}}
    .sp-sub-bar div{{height:100%;background:#7dd3fc;border-radius:3px}}
    .sp-empty{{font-size:13px;color:#8391a8;padding:14px 0 4px;text-align:center}}
    .sp-stat-pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}}
    .sp-stat{{background:rgba(255,255,255,.035);border-radius:14px;padding:18px 12px;text-align:center;display:flex;flex-direction:column;justify-content:center}}
    .sp-stat-val{{font-size:30px;font-weight:700;color:#f472b6;line-height:1.05}}
    .sp-stat-of{{font-size:17px;color:#f9a8d4}}
    .sp-stat-lbl{{font-size:12.5px;font-weight:600;color:#a5b1c7;margin-top:8px;line-height:1.3}}
    .sp-cadence-row{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:16px}}
    .sp-cadence-pill{{background:rgba(255,255,255,.035);border-radius:14px;padding:16px 8px;text-align:center}}
    button.sp-tap{{font:inherit;color:inherit;border:1px solid rgba(125,211,252,.18);cursor:pointer;position:relative;-webkit-tap-highlight-color:transparent;width:100%}}
    button.sp-tap:disabled{{cursor:default;opacity:.55;border-color:transparent}}
    button.sp-tap[aria-expanded="true"]{{border-color:rgba(125,211,252,.6);background:rgba(125,211,252,.08)}}
    button.sp-tap:focus-visible{{outline:2px solid #7dd3fc;outline-offset:2px}}
    .sp-tap-chev{{width:9px;height:9px;margin:10px auto 0;border-right:2.5px solid #7dd3fc;border-bottom:2.5px solid #7dd3fc;transform:rotate(45deg);transition:transform .2s ease}}
    button.sp-tap[aria-expanded="true"] .sp-tap-chev{{transform:rotate(225deg);margin-top:14px}}
    .sp-panel{{margin-top:12px;background:rgba(125,211,252,.05);border:1px solid rgba(125,211,252,.35);border-radius:13px;padding:2px 14px 12px;animation:spOpen .22s ease}}
    .sp-panel .sp-drawer-note{{border-top:none}}
    .sp-avg-strip{{display:flex;align-items:baseline;gap:10px;margin-top:14px;padding:12px 14px;border-radius:12px;background:rgba(125,211,252,.06);border:1px dashed rgba(125,211,252,.25)}}
    .sp-avg-num{{font-size:26px;font-weight:700;color:#7dd3fc;line-height:1}}
    .sp-avg-lbl{{font-size:13.5px;font-weight:600;color:#c3cddd}}
    @media (prefers-reduced-motion:reduce){{.sp-panel{{animation:none}}.sp-tap-chev{{transition:none}}}}
    .sp-cadence-count{{font-size:30px;font-weight:700;color:#7dd3fc;line-height:1}}
    .sp-cadence-label{{font-family:"Bebas Neue",Impact,sans-serif;font-size:18px;letter-spacing:1px;color:#a5b1c7;margin-top:6px}}
    .sp-highlight{{text-align:center;padding:18px 6px 4px}}
    .sp-highlight-val{{font-size:40px;font-weight:700;color:#34d399;line-height:1}}
    .sp-highlight-val.sp-neg{{color:#f87171}}
    .sp-highlight-sub{{font-size:14px;color:#c3cddd;margin-top:10px;line-height:1.4}}
    .sp-highlight-sub b{{color:#fff}}
    .sp-now{{display:inline-block;margin-top:10px;font-size:12px;font-weight:700;color:#34d399;background:rgba(52,211,153,.13);padding:4px 10px;border-radius:8px}}
    @media (min-width:700px){{.sp-cadence-row{{grid-template-columns:repeat(4,1fr)}}}}
    </style></head><body>
    <div class="sp-page" id="sp-page">
    <div class="sp-title">STATS+</div>
    <div class="sp-subtitle">Deeper patterns your other tabs don't surface on their own</div>
    {body}
    </div>
    <script>
    (function(){{
      function fit(){{
        try{{
          var f = window.frameElement;
          if(!f) return;
          var h = document.getElementById("sp-page").getBoundingClientRect().height + 16;
          f.style.height = h + "px";
          f.setAttribute("height", Math.ceil(h));
        }}catch(e){{}}
      }}
      document.querySelectorAll("details").forEach(function(d){{ d.addEventListener("toggle", fit); }});
      document.querySelectorAll("button.sp-tap").forEach(function(b){{
        b.addEventListener("click", function(){{
          var g = b.dataset.group, open = b.getAttribute("aria-expanded") === "true";
          document.querySelectorAll('button.sp-tap[data-group="'+g+'"]').forEach(function(o){{ o.setAttribute("aria-expanded","false"); }});
          document.querySelectorAll('.sp-panel[data-group="'+g+'"]').forEach(function(p){{ p.hidden = true; }});
          if(!open){{
            b.setAttribute("aria-expanded","true");
            var p = document.getElementById(g+"-"+b.dataset.key);
            if(p) p.hidden = false;
          }}
          fit();
        }});
      }});
      if(window.ResizeObserver){{ new ResizeObserver(fit).observe(document.getElementById("sp-page")); }}
      window.addEventListener("load", fit);
      if(document.fonts && document.fonts.ready){{ document.fonts.ready.then(fit); }}
      fit();
    }})();
    </script>
    </body></html>"""

    # Fallback height if the frame can't resize itself (JS above is the
    # primary mechanism). Generous per-row estimate + fixed blocks; any
    # overflow from an opened drawer still scrolls inside the frame.
    est_height = 16 * 110 + n_rows * 92 + 6 * 150 + 200
    components.html(html, height=max(est_height, 3200), scrolling=True)
