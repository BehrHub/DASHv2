from __future__ import annotations

import pandas as pd

CLIENT_GROUPS: dict[str, list[str]] = {
    "TJX Group": ["TJ Maxx", "Marshalls", "HomeGoods", "HomeSense", "Sierra"],
    "DunkBR Group": ["Dunkin'", "Baskin-Robbins"],
    "Government Group": [
        "USDA", "Senator A. Alsobrooks", "Senator C. Van Hollen", "Joint Base Andrews",
        "Senate Sergeant at Arms",
    ],
    "Nursing Home Group": [
        "Hebrew Home GW", "Atrium Village", "Autumn Lake Healthcare", "Maryland Baptist Age Home",
    ],
    "Hilton Worldwide Group": ["Hampton Inn & Suites", "Hilton Garden Inn"],
    "Macy's Inc. Group": ["Bloomingdale's", "Macy's"],
    "Grocery Group": ["Giant Food Stores", "Food Lion", "Weis Markets"],
}

LOCATION_GROUPS: dict[str, list[str]] = {
    "Rockville-proper": ["Rockville, MD", "North Bethesda, MD", "Bethesda, MD"],
    "Owings Mills-proper": ["Owings Mills, MD", "Reisterstown, MD"],
    "Bel Air-proper": ["Bel Air, MD", "Aberdeen, MD", "Edgewood, MD"],
    "Towson-proper": ["Towson, MD", "Cockeysville, MD", "Lutherville, MD", "Timonium, MD"],
    "Tysons-proper": ["Tysons, VA", "McLean, VA", "Falls Church, VA"],
    # Reduced to just Bowie/Lanham - Largo, Clinton, and Upper Marlboro
    # split off into their own new Largo-proper group below.
    "Bowie-proper": ["Bowie, MD", "Lanham, MD"],
    "Laurel-proper": ["Laurel, MD", "Scaggsville, MD"],
    "Ellicott City-proper": ["Ellicott City, MD", "West Friendship, MD"],
    "Silver Spring-proper": ["Silver Spring, MD", "Wheaton, MD"],
    # New group, split off from Bowie-proper. Uses "Andrews AFB, MD" -
    # the actual Location Detail string in the real data - NOT "Joint
    # Base Andrews, MD" (that's the separate CLIENT name in
    # CLIENT_GROUPS' Government Group; confirmed these are two
    # different strings before using either).
    "Largo-proper": ["Largo, MD", "Andrews AFB, MD", "Upper Marlboro, MD", "Clinton, MD"],
    "College Park-proper": ["College Park, MD", "Hyattsville, MD", "Landover, MD"],
    "Glen Burnie-proper": ["Glen Burnie, MD", "Severna Park, MD", "Pasadena, MD"],
    "Fairfax-proper": ["Fairfax, VA", "Herndon, VA"],
    "Eastern Shore-proper": ["Salisbury, MD", "Berlin, MD"],
    "Elkridge-proper": ["Elkridge, MD", "Columbia, MD", "Hanover, MD"],
    "Annapolis-proper": ["Annapolis, MD", "Annapolis Neck, MD"],
}


def compute_client_group_ranking(timeline: pd.DataFrame, gross_view: bool = False) -> list[dict]:
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


def compute_location_group_ranking(timeline: pd.DataFrame, pipeline: pd.DataFrame | None = None) -> list[dict]:
    grouped_locations: set[str] = set()
    for members in LOCATION_GROUPS.values():
        grouped_locations.update(members)

    counts = timeline["Location Detail"].value_counts()
    all_locations = set(timeline["Location Detail"].dropna().unique())
    standalone = sorted(all_locations - grouped_locations)

    confirmed = timeline[timeline["Verified?"] == "Yes"]
    revenue_by_loc = confirmed.groupby("Location Detail")["Amount"].sum()

    pending_by_loc: dict = {}
    if pipeline is not None and "Location" in pipeline.columns:
        pending_by_loc = (
            pipeline["Location"].dropna().astype(str).str.strip().value_counts().to_dict()
        )

    def _revenue(members: list[str]) -> float:
        return float(sum(revenue_by_loc.get(m, 0.0) for m in members))

    def _pending(members: list[str]) -> int:
        return int(sum(pending_by_loc.get(m, 0) for m in members))

    rows: list[dict] = []
    for name, members in LOCATION_GROUPS.items():
        trips = int(sum(counts.get(m, 0) for m in members))
        rows.append({
            "name": name, "members": members, "member_count": len(members),
            "is_group": True, "trips": trips, "revenue": _revenue(members),
            "pending": _pending(members),
        })
    for loc in standalone:
        rows.append({
            "name": loc, "members": [loc], "member_count": 1,
            "is_group": False, "trips": int(counts.get(loc, 0)),
            "revenue": _revenue([loc]), "pending": _pending([loc]),
        })

    rows.sort(key=lambda r: (-r["trips"], -r["revenue"]))
    return rows
