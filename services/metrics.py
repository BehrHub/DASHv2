from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import pandas as pd

from services.data_source import WorkbookSnapshot
from services.tz import eastern_today_naive


def _normalized(value: object) -> str:
    return "".join(
        character
        for character in str(value).casefold()
        if character.isalnum()
    )


def _column(
    frame: pd.DataFrame,
    aliases: Iterable[str],
    *,
    required: bool = True,
) -> str | None:
    alias_set = {
        _normalized(alias)
        for alias in aliases
    }

    for column in frame.columns:
        if _normalized(column) in alias_set:
            return str(column)

    if required:
        raise ValueError(
            "Missing required column. Expected one of "
            f"{sorted(aliases)}; available={list(frame.columns)}"
        )

    return None


def _status_completed(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.casefold()
        .eq("completed")
    )


def _money(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(r"[^0-9.\-]", "", regex=True)
    )

    return pd.to_numeric(
        cleaned,
        errors="coerce",
    ).fillna(0.0)


def _truthy(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.casefold()
        .isin(
            {
                "yes",
                "true",
                "verified",
                "confirmed",
                "1",
            }
        )
    )



def _dates(
    frame: pd.DataFrame,
    aliases: Iterable[str],
) -> pd.Series:
    column = _column(
        frame,
        aliases,
        required=False,
    )

    if not column:
        return pd.Series(
            pd.NaT,
            index=frame.index,
            dtype="datetime64[ns]",
        )

    return pd.to_datetime(
        frame[column],
        errors="coerce",
    )


def _business_day_streak(
    values: pd.Series,
) -> int | None:
    valid = (
        pd.to_datetime(values, errors="coerce")
        .dropna()
        .dt.normalize()
        .drop_duplicates()
        .sort_values()
    )

    if valid.empty:
        return None

    dates = set(valid.tolist())
    cursor = valid.iloc[-1]
    streak = 0

    while cursor in dates:
        streak += 1
        cursor -= pd.offsets.BDay(1)

    return streak


def _longest_business_day_streak(values: pd.Series) -> int | None:
    """True historical-max consecutive-day streak anywhere in the
    career. A weekday with no event breaks a run; a weekend day
    (Sat/Sun) with no event does NOT break a run (just gets stepped
    over); a weekend day that WAS worked counts as a real +1 like any
    other day. Kept consistent with _current_business_day_streak below
    so "record" and "current" measure the exact same thing.
    """
    valid = (
        pd.to_datetime(values, errors="coerce")
        .dropna()
        .dt.normalize()
        .drop_duplicates()
        .sort_values()
    )
    if valid.empty:
        return None

    dates = set(valid.tolist())
    longest = 0
    for d in dates:
        # Only start counting from the true beginning of a run: walk
        # backward past any unworked weekend to see if an earlier
        # connected work day exists. Landing on an unworked WEEKDAY
        # means d really is where this run starts; landing on ANY
        # worked day (weekday or weekend) means it isn't.
        probe = d - pd.Timedelta(days=1)
        while probe.weekday() >= 5 and probe not in dates:
            probe -= pd.Timedelta(days=1)
        if probe in dates:
            continue

        length = 0
        cursor = d
        while True:
            if cursor in dates:
                length += 1
                cursor += pd.Timedelta(days=1)
                continue
            if cursor.weekday() >= 5:
                cursor += pd.Timedelta(days=1)
                continue
            break
        longest = max(longest, length)
    return longest


def _current_business_day_streak(values: pd.Series) -> int:
    """Consecutive-day streak as of today.

    A weekday with no event breaks the streak. An unworked weekend day
    (Sat/Sun) never breaks anything -- just stepped over. A WORKED
    weekend day counts as a genuine +1, same as any other day. The one
    exception is today itself: if today simply hasn't had its event
    logged yet, that alone doesn't count as a break -- evaluation just
    continues from yesterday. That grace applies ONLY to today, not to
    any earlier day.

    A previous version searched up to 7 days back for "the most recent
    worked day" whenever today had no event, with no check on whether
    it was walking past a genuinely missed WEEKDAY along the way.
    Concretely: today Wednesday with no event, Tuesday also genuinely
    missed, Monday worked -- that search walked straight past Tuesday
    without noticing it was a real weekday gap, anchored on Monday, and
    reported a streak as if Tuesday never happened. Confirmed bug,
    fixed by giving the "not logged yet" grace only to today and
    nowhere else -- any earlier unworked weekday is a real break.
    """
    valid = (
        pd.to_datetime(values, errors="coerce")
        .dropna()
        .dt.normalize()
        .drop_duplicates()
    )
    dates = set(valid.tolist())
    if not dates:
        return 0

    today = eastern_today_naive()
    cursor = today
    streak = 0
    today_grace_used = False

    while True:
        if cursor in dates:
            streak += 1
            cursor -= pd.Timedelta(days=1)
            continue
        if cursor.weekday() >= 5:
            cursor -= pd.Timedelta(days=1)
            continue
        if cursor == today and not today_grace_used:
            today_grace_used = True
            cursor -= pd.Timedelta(days=1)
            continue
        break

    return streak


def _best_month(
    values: pd.Series,
) -> tuple[str | None, int | None]:
    valid = pd.to_datetime(
        values,
        errors="coerce",
    ).dropna()

    if valid.empty:
        return None, None

    counts = valid.dt.to_period("M").value_counts()

    if counts.empty:
        return None, None

    best_period = counts.index[0]
    count = int(counts.iloc[0])

    return (
        best_period.to_timestamp().strftime("%b").upper(),
        count,
    )


def _compact_money(value: float) -> str:
    absolute = abs(value)

    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"

    if absolute >= 1_000:
        return f"${value / 1_000:.1f}K"

    return f"${value:,.0f}"


@dataclass(frozen=True)
class ExecutiveMetrics:
    kpis: List[Dict[str, str]]
    jurisdictions: List[Tuple[str, int]]
    top_clients: List[Dict[str, object]]
    upcoming_items: List[Dict[str, str]]
    completed_events: int
    scheduled_events: int
    total_revenue: float
    verified_revenue: float
    repeat_clients: int
    average_paid_event: float
    revenue_completion: float
    top_client_share: float
    data_quality_score: float
    source_notes: List[str]
    hero: Dict[str, object]
    data_views: Dict[str, object]


def build_executive_metrics(
    snapshot: WorkbookSnapshot,
) -> ExecutiveMetrics:
    timeline = snapshot.sheets["Timeline"].copy()
    coverage = snapshot.sheets["State Coverage"].copy()
    pipeline = snapshot.sheets["Pipeline"].copy()

    timeline_status = _column(
        timeline,
        ["Status"],
    )
    timeline_client = _column(
        timeline,
        ["Client", "Client Name"],
    )
    timeline_state = _column(
        timeline,
        [
            "State/Region",
            "State",
            "Region Code",
        ],
    )
    timeline_amount = _column(
        timeline,
        [
            "Amount",
            "Revenue",
            "Confirmed Revenue",
        ],
        required=False,
    )
    timeline_verified = _column(
        timeline,
        [
            "Verified?",
            "Verified",
            "Payment Verified",
        ],
        required=False,
    )

    timeline_dates = _dates(
        timeline,
        [
            "Service Date",
            "Actual Service Date",
            "Event Date",
            "Completed Date",
            "Date",
            "Visit Date",
        ],
    )

    completed = timeline.loc[
        _status_completed(
            timeline[timeline_status]
        )
    ].copy()

    completed_events = int(len(completed))

    completed_dates = timeline_dates.loc[
        completed.index
    ]

    current_streak = _business_day_streak(
        completed_dates
    )
    longest_streak = _longest_business_day_streak(
        completed_dates
    )
    live_current_streak = _current_business_day_streak(
        completed_dates
    )

    if "Location Detail" in completed.columns:
        _city_series = completed["Location Detail"].dropna().astype(str).str.strip()
        _city_series = _city_series[_city_series != ""]
        cities_visited = int(
            _city_series.map(lambda v: v.rsplit(",", 1)[0].strip()).nunique()
        )
    else:
        cities_visited = 0

    best_month_label, best_month_events = _best_month(
        completed_dates
    )

    client_series = (
        completed[timeline_client]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    unique_clients = int(
        client_series[client_series.ne("")]
        .nunique()
    )

    client_counts = (
        client_series[client_series.ne("")]
        .value_counts()
    )

    repeat_clients = int(
        (client_counts >= 2).sum()
    )

    jurisdiction_series = (
        completed[timeline_state]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    jurisdiction_count = int(
        jurisdiction_series[
            jurisdiction_series.ne("")
        ].nunique()
    )

    if timeline_amount:
        completed["__revenue"] = _money(
            completed[timeline_amount]
        )
    else:
        completed["__revenue"] = 0.0

    total_revenue = float(
        completed["__revenue"].sum()
    )

    paid_events = int(
        completed["__revenue"].gt(0).sum()
    )

    average_paid_event = (
        total_revenue / paid_events
        if paid_events
        else 0.0
    )

    if timeline_verified:
        verified_mask = _truthy(
            completed[timeline_verified]
        )
        verified_revenue = float(
            completed.loc[
                verified_mask,
                "__revenue",
            ].sum()
        )
    else:
        verified_revenue = 0.0

    revenue_completion = (
        verified_revenue / total_revenue * 100.0
        if total_revenue
        else 0.0
    )

    client_revenue = (
        completed.assign(
            __client=client_series
        )
        .loc[
            lambda frame: frame["__client"].ne("")
        ]
        .groupby(
            "__client",
            as_index=False,
        )
        .agg(
            events=("__client", "size"),
            revenue=("__revenue", "sum"),
        )
        .sort_values(
            ["revenue", "events", "__client"],
            ascending=[False, False, True],
            kind="stable",
        )
    )

    top_clients: List[Dict[str, object]] = []

    for _, row in client_revenue.head(5).iterrows():
        share = (
            float(row["revenue"])
            / total_revenue
            * 100.0
            if total_revenue
            else 0.0
        )

        top_clients.append(
            {
                "client": str(row["__client"]),
                "events": int(row["events"]),
                "revenue": float(row["revenue"]),
                "share": share,
            }
        )

    top_client_share = (
        float(top_clients[0]["share"])
        if top_clients
        else 0.0
    )

    pipeline_status = _column(
        pipeline,
        ["Status"],
        required=False,
    )

    if pipeline_status:
        scheduled_mask = (
            pipeline[pipeline_status]
            .astype(str)
            .str.strip()
            .str.casefold()
            .isin(
                {
                    "scheduled",
                    "upcoming",
                    "open",
                    "pending",
                    "follow-up",
                    "awaiting",
                }
            )
        )
        scheduled = pipeline.loc[
            scheduled_mask
        ].copy()
    else:
        scheduled = pipeline.copy()

    scheduled_events = int(len(scheduled))

    pipeline_client = _column(
        scheduled,
        ["Client", "Client Name"],
        required=False,
    )
    pipeline_location = _column(
        scheduled,
        ["Location", "City"],
        required=False,
    )
    pipeline_date = _column(
        scheduled,
        [
            "Date / Timing",
            "Event Date",
            "Scheduled Date",
            "Date",
        ],
        required=False,
    )

    if pipeline_date:
        scheduled["__date"] = pd.to_datetime(
            scheduled[pipeline_date],
            errors="coerce",
        )

        scheduled = scheduled.sort_values(
            "__date",
            ascending=True,
            na_position="last",
            kind="stable",
        )

    upcoming_items: List[Dict[str, str]] = []
    today = eastern_today_naive()
    tomorrow = today + pd.Timedelta(days=1)

    for _, row in scheduled.head(4).iterrows():
        if pipeline_date:
            raw_date = row.get(pipeline_date)
            parsed = pd.to_datetime(
                raw_date,
                errors="coerce",
            )

            if not pd.isna(parsed) and parsed.normalize() == today:
                date_label = "TODAY"
            elif not pd.isna(parsed) and parsed.normalize() == tomorrow:
                date_label = "TOMORROW"
            elif not pd.isna(parsed) and 2 <= (parsed.normalize() - today).days <= 6:
                date_label = parsed.strftime("%A").upper()
            else:
                date_label = (
                    parsed.strftime("%b %-d")
                    if not pd.isna(parsed)
                    else str(raw_date or "TBD")
                )
        else:
            date_label = "TBD"

        upcoming_items.append(
            {
                "client": (
                    str(row.get(pipeline_client, "")).strip()
                    if pipeline_client
                    else "Scheduled assignment"
                ),
                "location": (
                    str(row.get(pipeline_location, "")).strip()
                    if pipeline_location
                    else ""
                ),
                "date": date_label,
            }
        )

    coverage_state = _column(
        coverage,
        [
            "State/Region",
            "State",
            "Jurisdiction",
        ],
    )
    coverage_completed = _column(
        coverage,
        [
            "Completed Visits",
            "Completed Events",
            "Visits",
        ],
    )

    jurisdiction_rows = (
        coverage[
            [
                coverage_state,
                coverage_completed,
            ]
        ]
        .assign(
            **{
                coverage_completed: pd.to_numeric(
                    coverage[coverage_completed],
                    errors="coerce",
                )
                .fillna(0)
                .astype(int)
            }
        )
        .sort_values(
            coverage_completed,
            ascending=False,
            kind="stable",
        )
    )

    donut_values = [
        (
            str(row[coverage_state]),
            int(row[coverage_completed]),
        )
        for _, row in jurisdiction_rows.iterrows()
        if int(row[coverage_completed]) > 0
    ]

    quality_checks = [
        completed_events > 0,
        unique_clients > 0,
        bool(donut_values),
        timeline_amount is not None,
        pipeline is not None,
    ]

    data_quality_score = (
        sum(quality_checks)
        / len(quality_checks)
        * 100.0
    )

    total_rows = int(len(timeline))

    completion_rate = (
        completed_events
        / total_rows
        * 100.0
        if total_rows
        else 0.0
    )

    kpis = [
        {
            "label": "Completed Events",
            "value": f"{completed_events:,}",
            "detail": "Authoritative Timeline",
            "accent": "teal",
        },
        {
            "label": "Unique Clients",
            "value": f"{unique_clients:,}",
            "detail": "Completed activity",
            "accent": "blue",
        },
        {
            "label": "Repeat Clients",
            "value": f"{repeat_clients:,}",
            "detail": "Two or more visits",
            "accent": "violet",
        },
        {
            "label": "Jurisdictions",
            "value": f"{jurisdiction_count:,}",
            "detail": "Completed coverage",
            "accent": "amber",
        },
        {
            "label": "Career Revenue",
            "value": f"${total_revenue:,.2f}",
            "detail": "Known completed revenue",
            "accent": "green",
        },
        {
            "label": "Verified Revenue",
            "value": f"${verified_revenue:,.2f}",
            "detail": "Verified rows only",
            "accent": "cyan",
        },
        {
            "label": "Upcoming",
            "value": f"{scheduled_events:,}",
            "detail": "Pipeline assignments",
            "accent": "orange",
        },
        {
            "label": "Completion Rate",
            "value": f"{completion_rate:.1f}%",
            "detail": "Completed ÷ Timeline rows",
            "accent": "rose",
        },
    ]

    next_assignment = (
        upcoming_items[0]
        if upcoming_items
        else {
            "client": "No assignment",
            "location": "",
            "date": "TBD",
        }
    )

    hero = {
        "events_value": f"{completed_events:,}",
        "clients_value": f"{unique_clients:,}",
        "revenue_value": _compact_money(total_revenue),
        "next_client": (
            next_assignment.get("client")
            or "Scheduled assignment"
        ),
        "next_date": (
            next_assignment.get("date")
            or "TBD"
        ),
        "streak_value": (
            str(current_streak)
            if current_streak is not None
            else "—"
        ),
        "streak_available": current_streak is not None,
        "longest_streak_value": (
            str(longest_streak) if longest_streak is not None else "—"
        ),
        "current_streak_value": str(live_current_streak),
        "cities_value": str(cities_visited),
        "jurisdictions_value": str(jurisdiction_count),
        "upcoming_value": str(scheduled_events),
        "best_month_value": (
            best_month_label
            if best_month_label
            else "—"
        ),
        "best_month_events": best_month_events,
    }

    volume_leaderboard = [
        {"client": str(client), "events": int(events)}
        for client, events in client_counts.head(5).items()
    ]
    client_directory = [
        {"client": str(client), "events": int(events)}
        for client, events in client_counts.items()
    ]

    jurisdiction_total = sum(value for _, value in donut_values)
    jurisdiction_breakdown = [
        {
            "name": name,
            "events": value,
            "share": (
                value / jurisdiction_total * 100.0
                if jurisdiction_total else 0.0
            ),
        }
        for name, value in donut_values
    ]

    data_views = {
        "leaderboard": volume_leaderboard,
        "client_directory": client_directory,
        "jurisdictions": jurisdiction_breakdown,
        "jurisdiction_count": len(jurisdiction_breakdown),
        "completed_events": completed_events,
    }

    return ExecutiveMetrics(
        kpis=kpis,
        jurisdictions=donut_values,
        top_clients=top_clients,
        upcoming_items=upcoming_items,
        completed_events=completed_events,
        scheduled_events=scheduled_events,
        total_revenue=total_revenue,
        verified_revenue=verified_revenue,
        repeat_clients=repeat_clients,
        average_paid_event=average_paid_event,
        revenue_completion=revenue_completion,
        top_client_share=top_client_share,
        data_quality_score=data_quality_score,
        source_notes=[
            "Runtime-calculated values",
            "Read-only workbook access",
            "Automatic cache invalidation",
        ],
        hero=hero,
        data_views=data_views,
    )
