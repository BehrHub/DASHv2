from __future__ import annotations

import pandas as pd

# Every group here was individually verified against real event/location
# data before being approved — see the conversation this shipped from
# for the actual mileage checks (haversine, not eyeballed) behind each
# location group, and the real-parent-company confirmation (web search,
# not assumed) behind Hilton Worldwide / Macy's Inc. / Grocery.

CLIENT_GROUPS: dict[str, list[str]] = {
    "TJX Group": ["TJ Maxx", "Marshalls", "HomeGoods", "HomeSense"],
    "DunkBR Group": ["Dunkin'", "Baskin-Robbins"],
    "Government Group": [
        "USDA", "Senator A. Alsobrooks", "Senator C. Van Hollen", "Joint Base Andrews",
    ],
    "Nursing Home Group": [
        "Hebrew Home GW", "Atrium Village", "Autumn Lake Healthcare", "Maryland Baptist Age Home",
    ],
    "Hilton Worldwide Group": ["Hampton Inn & Suites", "Hilton Garden Inn"],
    "Macy's Inc. Group": ["Bloomingdale's", "Macy's"],
    "Grocery Group": ["Giant Food Stores", "Food Lion", "Weis Markets"],
}

# Bowie-proper uses Largo as the connecting anchor for both Bowie (6.9mi,
# clean) and Clinton (9.5mi, borderline — same tolerance already accepted
# for Aberdeen/Edgewood in Bel Air-proper) — Bowie and Clinton themselves
# are 15.8mi apart and are NOT close to each other; Largo is what ties
# the group together, not mutual proximity between every pair.
LOCATION_GROUPS: dict[str, list[str]] = {
    "Rockville-proper": ["Rockville, MD", "North Bethesda, MD"],
    "Owings Mills-proper": ["Owings Mills, MD", "Reisterstown, MD"],
    "Bel Air-proper": ["Aberdeen, MD", "Bel Air, MD", "Edgewood, MD"],
    # Timonium added — 1.3-3.0mi from every existing member, tighter
    # than the original three are to each other.
    "Towson-proper": ["Cockeysville, MD", "Lutherville, MD", "Towson, MD", "Timonium, MD"],
    "Tysons-proper": ["Tysons, VA", "McLean, VA"],
    # Upper Marlboro (6.5mi to Largo) and Lanham (5.8-6.6mi to
    # Largo/Bowie) added — same anchor pattern as the original group:
    # Lanham is 14.8mi from Clinton specifically, not mutually close to
    # every member, exactly like Bowie and Clinton aren't close to each
    # other either. Largo/Bowie is what ties this together.
    "Bowie-proper": ["Largo, MD", "Bowie, MD", "Clinton, MD", "Upper Marlboro, MD", "Lanham, MD"],
    # New groups below, all verified by real distance before adding.
    "Laurel-proper": ["Scaggsville, MD", "Laurel, MD"],  # 5.7mi
    "Ellicott City-proper": ["West Friendship, MD", "Ellicott City, MD"],  # 9.8mi, same tolerance as Aberdeen/Bel Air
    "Silver Spring-proper": ["Wheaton, MD", "Silver Spring, MD"],  # 3.7mi
    "College Park-proper": ["Hyattsville, MD", "College Park, MD"],  # 1.8mi, tightest pairing so far
    # New group — Glen Burnie is the anchor. Severna Park is 7.66mi
    # straight-line (8mi driving, confirmed via web search) from Glen
    # Burnie — wider than most existing pairs but still inside the
    # tolerance already accepted for Ellicott City (9.8mi). Pasadena
    # sits roughly halfway between the two (~4mi from Glen Burnie) and
    # has zero events so far — listed anyway so the group picks it up
    # automatically the moment a real visit lands, same "not yet
    # visited" mechanism already used elsewhere.
    "Glen Burnie-proper": ["Glen Burnie, MD", "Severna Park, MD", "Pasadena, MD"],
    # New group — Fairfax-proper did not exist before this; created here.
    # Fairfax to Herndon is 9.5mi straight-line (11-14mi driving,
    # confirmed via web search, not assumed) — comparable to the
    # Clinton/Ellicott City borderline cases already accepted above.
    "Fairfax-proper": ["Fairfax, VA", "Herndon, VA"],
}


def compute_client_group_ranking(timeline: pd.DataFrame, gross_view: bool = False) -> list[dict]:
    """One combined, revenue-ranked list: every defined group PLUS every
    client not in any group, each as its own entry — matches the
    explicit spec ("rank them along with all clients that are not part
    of the group"), not just the groups alone. Confirmed-only revenue,
    matching the exact convention already used everywhere else in this
    app (Ledger, Client Hub's own individual client rows).
    """
    from services.money_view import gross_up

    grouped_clients: set[str] = set()
    for members in CLIENT_GROUPS.values():
        grouped_clients.update(members)

    all_clients = set(timeline["Client"].dropna().unique())
    standalone = sorted(all_clients - grouped_clients)

    def _stats(members: list[str]) -> dict:
        subset = timeline[timeline["Client"].isin(members)]
        confirmed = subset[subset["Verified?"] == "Yes"]
        events = len(subset)
        confirmed_n = len(confirmed)
        revenue = float(confirmed["Amount"].sum())
        avg = revenue / confirmed_n if confirmed_n else 0.0
        if gross_view:
            revenue = gross_up(revenue)
            avg = gross_up(avg)
        return {"events": events, "confirmed": confirmed_n, "revenue": revenue, "avg": avg}

    rows: list[dict] = []
    for name, members in CLIENT_GROUPS.items():
        row = {"name": name, "members": members, "member_count": len(members), "is_group": True}
        row.update(_stats(members))
        rows.append(row)
    for client in standalone:
        row = {"name": client, "members": [client], "member_count": 1, "is_group": False}
        row.update(_stats([client]))
        rows.append(row)

    rows.sort(key=lambda r: -r["revenue"])
    return rows


def compute_location_group_ranking(timeline: pd.DataFrame) -> list[dict]:
    """Same shape as compute_client_group_ranking, but for location
    (city) trip counts instead of client revenue."""
    grouped_locations: set[str] = set()
    for members in LOCATION_GROUPS.values():
        grouped_locations.update(members)

    counts = timeline["Location Detail"].value_counts()
    all_locations = set(timeline["Location Detail"].dropna().unique())
    standalone = sorted(all_locations - grouped_locations)

    confirmed = timeline[timeline["Verified?"] == "Yes"]
    revenue_by_loc = confirmed.groupby("Location Detail")["Amount"].sum()

    def _revenue(members: list[str]) -> float:
        return float(sum(revenue_by_loc.get(m, 0.0) for m in members))

    rows: list[dict] = []
    for name, members in LOCATION_GROUPS.items():
        trips = int(sum(counts.get(m, 0) for m in members))
        missing = [m for m in members if m not in all_locations]
        rows.append({
            "name": name, "members": members, "member_count": len(members),
            "is_group": True, "trips": trips, "revenue": _revenue(members),
            "not_yet_visited": missing,
        })
    for loc in standalone:
        rows.append({
            "name": loc, "members": [loc], "member_count": 1,
            "is_group": False, "trips": int(counts.get(loc, 0)),
            "revenue": _revenue([loc]), "not_yet_visited": [],
        })

    # Tie-break by revenue when trip counts match — a straight event-count
    # sort with no tiebreak left ties in whatever order groupby happened
    # to produce, which could put a lower-revenue location ahead of a
    # higher-revenue one despite equal visit counts.
    rows.sort(key=lambda r: (-r["trips"], -r["revenue"]))
    return rows
