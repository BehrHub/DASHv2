from __future__ import annotations

import re
from html import escape

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


# ============================================================
# Real production logic, pulled verbatim from app.py
# (JURISDICTION_COLORS, jurisdiction_group, compact_state_code,
# state_debut_label, career_milestones_for_row/after_row,
# format_currency)
# ============================================================

ACHIEVEMENT_ICON_DEBUT = "\U0001F3C1"
ACHIEVEMENT_ICON_MILESTONE = "\U0001F3C6"


@st.cache_data(show_spinner=False)
def _journey_car_data_uri() -> str:
    import base64
    from pathlib import Path

    data = (Path(__file__).resolve().parent.parent / "assets" / "icons" / "journey-car.png").read_bytes()
    return f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"


JURISDICTION_COLORS = {
    "Maryland": "#d0264f",           # deep rose red
    "Virginia": "#4c9be8",           # Cookie Monster blue
    "Washington, D.C.": "#6a3fd1",   # royal purple
    "West Virginia": "#eab308",      # yellow
    "Pennsylvania / Other": "#22c55e",  # green
}

TERRITORY_CENTER_COLOR = "#ffffff"  # white

# Journey doesn't have production's --kith-month-* design tokens in this
# standalone build, so stop accents use this palette instead — tuned to
# fit the existing pink/blue/purple neon theme rather than KITH's tokens.
MONTH_COLORS = {
    # Q1 of career (Apr-Jun): blue, light -> dark
    4: ("#7dd3fc", "125,211,252"),
    5: ("#38bdf8", "56,189,248"),
    6: ("#0369a1", "3,105,161"),
    # Q2 (Jul-Sep): green, light -> dark
    7: ("#6ee7b7", "110,231,183"),
    8: ("#34d399", "52,211,153"),
    9: ("#047857", "4,120,87"),
    # Q3 (Oct-Dec): amber, light -> dark
    10: ("#fde68a", "253,230,138"),
    11: ("#fbbf24", "251,191,36"),
    12: ("#b45309", "180,83,9"),
    # Q4 (Jan-Mar): violet, light -> dark
    1: ("#c4b5fd", "196,181,253"),
    2: ("#a78bfa", "167,139,250"),
    3: ("#5b21b6", "91,33,182"),
}


def jurisdiction_group(state: object) -> str:
    normalized = re.sub(r"[^a-z]", "", str(state or "").lower())
    if normalized in {"md", "maryland"}:
        return "Maryland"
    if normalized in {"va", "virginia"}:
        return "Virginia"
    if normalized in {"dc", "washingtondc", "districtofcolumbia"}:
        return "Washington, D.C."
    if normalized in {"wv", "westvirginia"}:
        return "West Virginia"
    return "Pennsylvania / Other"


def compact_state_code(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z]+", " ", str(value or "")).strip().upper()
    if not normalized:
        return ""
    if normalized.startswith("DC") or "DISTRICT OF COLUMBIA" in normalized or normalized == "WASHINGTON D C":
        return "DC"
    if normalized.startswith("MD") or normalized == "MARYLAND":
        return "MD"
    if normalized.startswith("VA") or normalized == "VIRGINIA":
        return "VA"
    if normalized.startswith("PA") or normalized == "PENNSYLVANIA":
        return "PA"
    if normalized.startswith("WV") or normalized == "WEST VIRGINIA":
        return "WV"
    if normalized.startswith("DE") or normalized == "DELAWARE":
        return "DE"
    return str(value or "").strip()


def state_debut_label(row: dict) -> str:
    state = str(row.get("state_region", "") or "").strip()
    normalized = jurisdiction_group(state)
    if normalized == "Washington, D.C.":
        return "D.C. DEBUT"
    if normalized == "Pennsylvania / Other":
        state_code = compact_state_code(state) or "NEW TERRITORY"
        if state_code == "PA":
            return "PENNSYLVANIA DEBUT"
        return f"{state_code.upper()} DEBUT"
    return f"{normalized.upper()} DEBUT"


def career_milestones_for_row(row: dict) -> list[str]:
    client = str(row.get("client", "") or "").lower()
    notes = str(row.get("notes", "") or "").lower()
    visit_number = int(row.get("visit_number", 0) or 0)
    milestones = []

    if "senator" in client or "van hollen" in client or "alsobrooks" in client:
        milestones.append("FIRST SENATE OFFICE")
    if "joint base andrews" in client:
        milestones.append("FIRST MILITARY INSTALLATION")
    if client == "usda":
        milestones.append("USDA MAJOR PROJECT")
    if client in {"tj maxx", "marshalls", "homegoods"} and (
        "tjx" in notes or "trifecta" in notes or visit_number >= 35
    ):
        milestones.append("TJX CONTRACT AWARDED")
    if "baskin robbins" in client or "dunkin" in notes:
        milestones.append("DUNKIN\u2019 CONTRACT AWARDED")

    return milestones


def career_milestones_after_row(row: dict) -> list[str]:
    client = str(row.get("client", "") or "").lower()
    notes = str(row.get("notes", "") or "").lower()
    milestones = []
    if "montpelier liquors" in client or "catalina" in notes:
        milestones.append("CATALINA CONTRACT AWARDED")
    if "alsobrooks" in client:
        milestones.append("BOTH MARYLAND SENATORS\u2019 OFFICES COMPLETED")
    return milestones


def format_currency(value: object) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "Incomplete"
    if amount != amount:  # NaN check without importing math
        return "Incomplete"
    return f"\uFF04{amount:,.0f}"


def compact(markup: str) -> str:
    return "\n".join(line.strip() for line in markup.splitlines() if line.strip())


# ============================================================
# CSS — journey track, dots, car, fuel button
# Adapted from the extracted production stylesheet: --kith-month-*
# tokens replaced with the --month-accent custom properties set
# per-stop below, and the KITH battleship reference removed.
# ============================================================
JOURNEY_CSS = """
<style>
.journey-fuel-button { border: 1px solid rgba(244,114,182,.32); border-radius: 999px; background: linear-gradient(135deg, rgba(35,20,35,.94), rgba(13,17,26,.96)); color: #fff; box-shadow: 0 8px 18px rgba(0,0,0,.3), inset 0 1px 0 rgba(255,255,255,.06); font-weight: 800; cursor: pointer; appearance: none; -webkit-appearance: none; -webkit-tap-highlight-color: transparent; width: 34px; height: 34px; display: inline-flex; align-items: center; justify-content: center; padding: 0; font-size: 1rem; }
.journey-fuel-button:hover { border-color: rgba(244,114,182,.6); background: linear-gradient(135deg, rgba(60,25,55,.92), rgba(13,17,26,.96)); }
.journey-track { position: relative; display: grid; gap: .72rem; margin: .2rem 0 1rem; padding: .4rem 0 .6rem 1.2rem; }
.journey-track::before { content: ""; position: absolute; top: 2.8rem; bottom: 2.8rem; left: .68rem; width: 4px; border-radius: 999px; background: repeating-linear-gradient(to bottom, #f8fafc 0 12px, #05070b 12px 22px); box-shadow: 0 0 16px rgba(248,250,252,.18); opacity: .82; }
.journey-replay-car { position: absolute; left: -.12rem; top: .9rem; z-index: 5; width: 80px; height: 80px; display: flex; align-items: center; justify-content: center; padding: 0; appearance: none; -webkit-appearance: none; background: transparent; border: none; box-shadow: none; color: #fff; font-size: 1rem; line-height: 1; opacity: 0; pointer-events: none; cursor: pointer; transform: translateY(-50%); transition-property: top, opacity; transition-timing-function: cubic-bezier(.2,.72,.22,1); }
.journey-car-departing { transition: transform 900ms cubic-bezier(.4,0,.7,1) !important; transform: translateY(-50%) translateX(140vw) !important; }
.journey-car-icon { display: block; width: 78%; height: 78%; object-fit: contain; transform: scaleX(-1); transform-origin: center center; }
.journey-track.replay-active .journey-replay-car { opacity: 1; pointer-events: auto; }
.journey-stop.new-client-celebration { animation: journeyClientGlow 1.45s ease-out both; }
@keyframes journeyClientGlow { 0% { box-shadow: 0 0 0 rgba(244,114,182,0); } 30% { box-shadow: 0 0 26px rgba(244,114,182,.55); } 100% { box-shadow: 0 0 0 rgba(244,114,182,0); } }
.journey-achievement-badge { position: absolute; left: 2.6rem; top: 50%; z-index: 6; padding: .18rem .38rem; border: 1px solid rgba(244,114,182,.4); border-radius: 999px; background: rgba(5,7,11,.92); color: #f9a8d4; font-size: .55rem; font-weight: 900; letter-spacing: .06em; text-transform: uppercase; box-shadow: 0 0 14px rgba(244,114,182,.25); opacity: 0; pointer-events: none; transform: translateY(calc(-50% - 2px)) translateX(-3px); transition: opacity .18s ease, transform .18s ease; white-space: nowrap; }
.journey-achievement-badge.is-visible { opacity: 1; transform: translateY(calc(-50% - 2px)) translateX(0); }
.journey-puff { position: absolute; left: 6px; top: 50%; opacity: 0; pointer-events: none; }
.journey-replay-car.is-smoke .journey-puff { width: 8px; height: 8px; border-radius: 50%; background: rgba(203,213,225,.6); animation: journeySmokePuff .9s ease-out infinite; }
.journey-replay-car.is-turbo .journey-puff { width: 10px; height: 14px; margin-top: 2px; border-radius: 50% 50% 45% 45% / 60% 60% 40% 40%; background: radial-gradient(circle at 50% 68%, #fff6cc 0%, #ffcf5c 28%, #ff8a1f 55%, #ff3b1f 78%, #b81900 100%); filter: blur(.2px); animation: journeyFireFlicker .38s ease-in-out infinite; }
.journey-replay-car .journey-puff:nth-child(2) { animation-delay: .1s !important; }
.journey-replay-car .journey-puff:nth-child(3) { animation-delay: .2s !important; }
.journey-replay-car.is-smoke .journey-puff:nth-child(2) { animation-delay: .3s !important; }
.journey-replay-car.is-smoke .journey-puff:nth-child(3) { animation-delay: .6s !important; }
@keyframes journeySmokePuff {
  0% { opacity: 0; transform: translate(0, -50%) scale(.4); }
  18% { opacity: .75; }
  100% { opacity: 0; transform: translate(-26px, calc(-50% - 16px)) scale(1.7); }
}
@keyframes journeyFireFlicker {
  0% { opacity: 0; transform: translate(0, -50%) scale(.5) rotate(-5deg); }
  28% { opacity: 1; transform: translate(-5px, calc(-50% - 3px)) scale(1.15) rotate(4deg); }
  60% { opacity: .85; transform: translate(-11px, calc(-50% - 1px)) scale(.85) rotate(-3deg); }
  100% { opacity: 0; transform: translate(-19px, -50%) scale(.4) rotate(5deg); }
}
.journey-finish-line { position: relative; z-index: 1; margin-left: .2rem; padding: .55rem .75rem; display: flex; align-items: center; justify-content: space-between; gap: .75rem; border: 1px dashed rgba(248,250,252,.42); border-radius: 12px; background: repeating-linear-gradient(45deg, rgba(248,250,252,.14) 0 8px, rgba(5,7,11,.85) 8px 16px); color: #f8fafc; font-size: .72rem; font-weight: 850; letter-spacing: .08em; text-transform: uppercase; opacity: 0; transform: translateY(4px); transition: opacity .25s ease, transform .25s ease; }
.journey-finish-line.is-visible { opacity: 1; transform: translateY(0); }
.journey-start { position: relative; z-index: 1; margin-left: .2rem; padding: .7rem .85rem; border: 1px solid rgba(244,114,182,.4); border-radius: 12px; background: linear-gradient(135deg, rgba(60,25,55,.78), rgba(5,7,11,.9)); color: #f8fafc; font-size: .82rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.journey-checkpoint { position: relative; z-index: 1; margin-left: .2rem; padding: .48rem .7rem; border: 1px solid rgba(56,189,248,.36); border-radius: 999px; background: rgba(15,23,42,.9); color: #7dd3fc; font-size: .72rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; width: fit-content; max-width: 100%; }
.journey-milestone { position: relative; z-index: 1; margin-left: .2rem; padding: .56rem .78rem; border: 1px solid rgba(253,230,138,.46); border-radius: 12px; background: linear-gradient(135deg, rgba(91,64,16,.85), rgba(13,17,26,.9)); color: #ffe8a3; font-size: .74rem; font-weight: 850; letter-spacing: .07em; text-transform: uppercase; width: fit-content; max-width: 100%; box-shadow: 0 10px 22px rgba(0,0,0,.2), inset 0 1px 0 rgba(255,255,255,.06); }
.journey-achievement-line { font-size: .6rem; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; line-height: 1.3; white-space: normal; }
.journey-achievement-line.is-debut { color: #7dd3fc; }
.journey-achievement-line.is-milestone { color: #ffe8a3; }
.journey-stop { position: relative; z-index: 1; display: grid; grid-template-columns: 54px 1fr; gap: .72rem; align-items: stretch; margin-left: .2rem; padding: .62rem .72rem; border: 1px solid rgba(var(--month-accent-rgb, 244,114,182), .5); border-radius: 16px; background: linear-gradient(145deg, rgba(var(--month-accent-rgb, 244,114,182), .12), rgba(13,17,26,.97)); box-shadow: 0 9px 22px rgba(0,0,0,.2), inset 0 0 0 1px rgba(var(--month-accent-rgb, 244,114,182), .15); }
/* Trial styling for stops #1 and #2, ahead of deciding on the rest. */
.journey-stop-test-white { border: 1px solid rgba(255,255,255,.4) !important; background: linear-gradient(145deg, rgba(255,255,255,.16), rgba(20,26,38,.92)) !important; backdrop-filter: blur(6px); box-shadow: 0 9px 22px rgba(0,0,0,.2), inset 0 0 0 1px rgba(255,255,255,.18) !important; }
.journey-stop-test-blue { border: 1px solid rgba(56,189,248,.45) !important; background: linear-gradient(145deg, rgba(56,189,248,.18), rgba(13,20,32,.94)) !important; backdrop-filter: blur(6px); box-shadow: 0 9px 22px rgba(0,0,0,.2), inset 0 0 0 1px rgba(56,189,248,.2) !important; }
.journey-stop::before { content: ""; position: absolute; left: -1.02rem; top: 50%; width: 13px; height: 13px; transform: translateY(-50%); border: 2px solid #05070b; border-radius: 999px; background: var(--stop-accent, #f472b6); box-shadow: 0 0 0 3px rgba(244,114,182,.2); }
.journey-number { display: flex; align-items: center; justify-content: center; border-radius: 12px; background: linear-gradient(180deg, #171325, #0b0d16); border: 1px solid rgba(255,255,255,.14); color: var(--month-accent, #f472b6); font-size: .72rem; font-weight: 850; text-transform: uppercase; text-align: center; line-height: 1.05; }
.journey-content { position: relative; min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 46%); gap: .9rem; align-items: start; }
.journey-left-stack { min-width: 0; display: grid; gap: .3rem; padding-right: .15rem; }
.journey-client { min-width: 0; color: #f8fafc; font-size: 1rem; font-weight: 800; line-height: 1.12; }
.journey-location { color: #93c5fd; font-size: .82rem; line-height: 1.25; font-weight: 600; }
.journey-right-meta { min-width: 0; display: flex; flex-direction: column; align-items: flex-end; justify-content: flex-start; justify-self: end; gap: .24rem; text-align: right; }
.journey-status { padding: .15rem .42rem; border: 1px solid rgba(255,255,255,.2); border-radius: 999px; background: rgba(15,23,42,.9); color: #e2e8f0; font-size: .68rem; font-weight: 800; text-transform: uppercase; white-space: nowrap; }
.journey-top-button { border: 1px solid rgba(244,114,182,.35); border-radius: 999px; background: rgba(15,23,42,.85); color: #f472b6; width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
.journey-top-button:hover { background: rgba(244,114,182,.15); }
@media (max-width: 520px) {
  .journey-track { padding-left: .85rem; gap: .52rem; }
  .journey-track::before { left: .42rem; }
  .journey-fuel-button { width: 32px; height: 32px; font-size: .95rem; }
  .journey-replay-car { left: -.24rem; width: 72px; height: 72px; font-size: .92rem; }
  .journey-achievement-badge { left: 2.3rem; font-size: .5rem; padding: .15rem .32rem; }
  .journey-stop { grid-template-columns: 42px 1fr; gap: .52rem; padding: .54rem .58rem; border-radius: 13px; }
  .journey-stop::before { left: -.76rem; width: 10px; height: 10px; }
  .journey-number { font-size: .58rem; border-radius: 10px; }
  .journey-client { font-size: .9rem; }
  .journey-content { grid-template-columns: minmax(0, 1fr) minmax(0, 46%); gap: .48rem; }
  .journey-left-stack { gap: .24rem; }
  .journey-location { font-size: .72rem; }
  .journey-achievement-line { font-size: .52rem; }
  .journey-checkpoint { font-size: .6rem; padding: .38rem .55rem; }
  .journey-milestone { font-size: .61rem; padding: .42rem .58rem; }
}
</style>
"""


def render_barrister_journey(timeline: pd.DataFrame) -> None:
    """Real-data adaptation of the production Journey page.

    `timeline` is expected to be the same real Timeline dataframe built
    in services/data_source.py: Client, State/Region, Status, Amount,
    Verified?, Service Date.
    """

    st.markdown(JOURNEY_CSS, unsafe_allow_html=True)

    if timeline.empty:
        st.info("No completed service events are available for the Barrister Journey.")
        return

    working = timeline.copy()
    working["__date"] = pd.to_datetime(working["Service Date"], errors="coerce")
    # Same-day events need a deterministic secondary order, or ties fall
    # back to whatever row position they happen to occupy in the sheet —
    # which shifts every time an event is deleted and recreated (it
    # always lands at a new row at the bottom), making the display order
    # flip around unpredictably on edits that shouldn't have moved
    # anything. Event ID is stable regardless of physical row position.
    # Note: the underlying data only has a *date*, not a time-of-day, so
    # this can't recover true real-world completion order within a
    # day — it can only make ties resolve the same way every time.
    chronological = working.sort_values(
        ["__date", "Event ID"], kind="stable"
    ).reset_index(drop=True)

    completed_visits = len(chronological)
    unique_clients = (
        chronological["Client"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
    )
    jurisdictions = (
        chronological["State/Region"].map(jurisdiction_group).replace("", pd.NA).dropna().nunique()
    )

    amounts = pd.to_numeric(chronological["Amount"], errors="coerce").fillna(0)
    known_revenue = float(amounts[amounts > 0].sum())

    def _city_only(detail: object) -> str:
        text = "" if pd.isna(detail) else str(detail).strip()
        return text.rsplit(",", 1)[0].strip() if "," in text else text

    unique_cities = (
        chronological.get("Location Detail", pd.Series(dtype=object))
        .map(_city_only)
        .replace("", pd.NA)
        .dropna()
        .nunique()
    )

    seen_states: set[str] = set()
    seen_clients: set[str] = set()
    seen_milestones: set[str] = set()

    pieces = [
        f'<div id="journeyTrack" class="journey-track" data-completed-visits="{escape(str(completed_visits))}" '
        f'data-unique-clients="{escape(str(unique_clients))}" data-jurisdictions="{escape(str(jurisdictions))}" '
        f'data-unique-cities="{escape(str(unique_cities))}" data-known-revenue="{escape(format_currency(known_revenue))}">'
        f'<button id="journeyReplayCar" class="journey-replay-car" type="button" aria-label="Pause or resume career replay"><img class="journey-car-icon" src="{_journey_car_data_uri()}" alt=""><span class="journey-puff"></span><span class="journey-puff"></span><span class="journey-puff"></span><span id="journeyAchievementBadge" class="journey-achievement-badge">+CLIENT</span></button>'
        '<div class="journey-start journey-stop-test-white"><span>START \U0001F3C1</span><button id="journeyFuelButton" class="journey-fuel-button" type="button" aria-label="Start or restart career replay" title="Start or restart career replay">\u26FD</button></div>'
    ]

    for index, row in enumerate(chronological.to_dict("records"), start=1):
        row["visit_number"] = index
        row["client"] = row.get("Client", "")
        row["state_region"] = row.get("State/Region", "")
        row["status"] = row.get("Status", "Completed")
        row["notes"] = ""

        state_key = jurisdiction_group(row["state_region"])
        achievements: list[tuple[str, str]] = []
        if state_key not in seen_states:
            seen_states.add(state_key)
            achievements.append(("debut", state_debut_label(row)))

        stop_milestones = career_milestones_for_row(row) + career_milestones_after_row(row)
        for milestone in stop_milestones:
            if milestone not in seen_milestones:
                seen_milestones.add(milestone)
                achievements.append(("milestone", milestone))

        achievement_markup = ""
        for kind, text in achievements:
            icon = ACHIEVEMENT_ICON_DEBUT if kind == "debut" else ACHIEVEMENT_ICON_MILESTONE
            achievement_markup += f'<div class="journey-achievement-line is-{kind}">{icon} {escape(text)}</div>'

        number = index
        status = str(row["status"] or "Completed").strip()
        client = str(row["client"] or "Unnamed client").strip()
        client_key = client.casefold()
        is_new_client = client_key not in seen_clients
        location_detail = row.get("Location Detail")
        location_detail = "" if pd.isna(location_detail) else str(location_detail).strip()
        location = location_detail or str(row["state_region"] or "").strip()
        event_date = row["__date"]
        short_date = event_date.strftime("%-m/%-d/%y") if pd.notna(event_date) else ""
        meta_line = " \u2022 ".join(part for part in (location, short_date) if part)
        month_num = int(event_date.month) if pd.notna(event_date) else 1
        month_accent, month_accent_rgb = MONTH_COLORS.get(month_num, MONTH_COLORS[1])
        stop_accent = JURISDICTION_COLORS.get(state_key, JURISDICTION_COLORS["Pennsylvania / Other"])

        test_class = " journey-stop-test-blue" if month_num == 4 else ""

        pieces.append(
            f'<div class="journey-stop{test_class}" '
            f'style="--stop-accent:{escape(stop_accent, quote=True)};--month-accent:{escape(month_accent, quote=True)};--month-accent-rgb:{escape(month_accent_rgb, quote=True)}" '
            f'data-visit="{escape(str(number))}" data-client="{escape(client, quote=True)}" '
            f'data-location="{escape(location or "Location not provided", quote=True)}" '
            f'data-new-client="{"1" if is_new_client else "0"}">'
            f'<div class="journey-number">#{escape(str(number))}</div>'
            '<div class="journey-content">'
            '<div class="journey-left-stack">'
            f'<div class="journey-client">{escape(client)}</div>'
            f'<div class="journey-location">{escape(meta_line or "Location not provided")}</div>'
            '</div>'
            f'<div class="journey-right-meta"><span class="journey-status">{escape(status)}</span>{achievement_markup}</div>'
            '</div></div>'
        )
        seen_clients.add(client_key)

    pieces.append(
        '<div id="journeyFinishLine" class="journey-finish-line"><span>\U0001F3C1 FINISH LINE</span><button id="journeyTopButton" class="journey-top-button" type="button" title="Back to top">\U0001F3C6</button></div></div>'
    )
    st.markdown(compact("".join(pieces)), unsafe_allow_html=True)
    render_journey_replay_script()


def render_journey_replay_script() -> None:
    components.html(
        """
        <script>
        (function () {
            const doc = window.parent.document;
            const win = window.parent;

            function initReplay(attempt) {
                attempt = attempt || 0;
                const replayVersion = "continuous-follow-v3";
                let fuel = doc.getElementById("journeyFuelButton");
                const track = doc.getElementById("journeyTrack");
                let car = doc.getElementById("journeyReplayCar");
                let badge = doc.getElementById("journeyAchievementBadge");
                const finishLine = doc.getElementById("journeyFinishLine");
                const journeyTopButton = doc.getElementById("journeyTopButton");

                if ((!fuel || !track || !car || !badge || !journeyTopButton) && attempt < 40) {
                    win.setTimeout(() => initReplay(attempt + 1), 200);
                    return;
                }

                if (journeyTopButton) {
                    journeyTopButton.addEventListener("click", function(event) {
                        event.preventDefault();
                        // Repurposed from the old (non-functional) scroll-
                        // to-top behavior: the car takes off from wherever
                        // it currently sits, positioned at the trophy if it
                        // wasn't already visible from an active replay,
                        // drives off the right edge, then navigates to
                        // Events once it's had time to fully clear the
                        // screen. window.parent.location is used (not a
                        // plain <a href>) since this is running inside a
                        // components.html() iframe, not the top-level page
                        // — same reasoning as the splash screen's own
                        // navigation, just via JS instead of a real link.
                        const trophyRect = journeyTopButton.getBoundingClientRect();
                        const trackRect2 = track.getBoundingClientRect();
                        car.style.top = ((trophyRect.top - trackRect2.top) + (trophyRect.height / 2)) + "px";
                        car.style.opacity = "1";
                        car.style.pointerEvents = "none";
                        void car.offsetWidth;
                        car.classList.add("journey-car-departing");
                        win.setTimeout(function () {
                            try {
                                var btns = doc.querySelectorAll('div[data-testid="stButton"] button');
                                for (var i = 0; i < btns.length; i++) {
                                    if (btns[i].textContent.trim() === "Journey Go To Events") {
                                        btns[i].click();
                                        break;
                                    }
                                }
                            } catch (e) {}
                        }, 950);
                    });
                }

                if (!fuel || !track || !car || !badge) {
                    return;
                }
                if (fuel.dataset.replayBound === replayVersion) {
                    return;
                }
                if (fuel.dataset.replayBound) {
                    const freshFuel = fuel.cloneNode(true);
                    const freshCar = car.cloneNode(true);
                    fuel.replaceWith(freshFuel);
                    car.replaceWith(freshCar);
                    fuel = freshFuel;
                    car = freshCar;
                    badge = doc.getElementById("journeyAchievementBadge");
                    if (!badge) {
                        return;
                    }
                }
                fuel.dataset.replayBound = replayVersion;

                let running = false;
                let paused = false;
                let sequenceId = 0;
                let speedIndex = 0;
                let replayY = 0;
                let lastFrame = 0;
                let nextStopIndex = 0;
                let animationFrame = null;
                let activeScroller = null;
                let previousScrollerOverflow = "";
                const speedLevels = [1.00, 1.65, 2.75, 0.00];
                const basePixelsPerSecond = 145;

                function stops() {
                    return Array.from(doc.querySelectorAll(".journey-stop[data-visit]"));
                }

                function clearCelebrations() {
                    stops().forEach((stop) => stop.classList.remove("new-client-celebration"));
                    badge.classList.remove("is-visible");
                }

                function yFor(element) {
                    return element.offsetTop + element.offsetHeight / 2;
                }

                function replayScroller() {
                    if (activeScroller && doc.contains(activeScroller)) {
                        return activeScroller;
                    }
                    activeScroller = doc.querySelector('[data-testid="stMain"]') || doc.scrollingElement || doc.documentElement;
                    return activeScroller;
                }

                function scrollerTop(scroller) {
                    return scroller === doc.scrollingElement || scroller === doc.documentElement || scroller === doc.body
                        ? (win.scrollY || doc.documentElement.scrollTop || doc.body.scrollTop || 0)
                        : scroller.scrollTop;
                }

                function setScrollerTop(scroller, top) {
                    if (scroller === doc.scrollingElement || scroller === doc.documentElement || scroller === doc.body) {
                        win.scrollTo({ top, behavior: "auto" });
                    } else {
                        scroller.scrollTo({ top, behavior: "auto" });
                    }
                }

                function celebrateNewClient(stop, id) {
                    stop.classList.remove("new-client-celebration");
                    void stop.offsetWidth;
                    stop.classList.add("new-client-celebration");
                    badge.textContent = `+CLIENT #${stop.dataset.visit || ""}`.trim();
                    badge.classList.add("is-visible");
                    win.setTimeout(() => {
                        if (id === sequenceId) {
                            badge.classList.remove("is-visible");
                        }
                    }, 1050);
                }

                function scrollWithCar() {
                    const scroller = replayScroller();
                    const trackRect = track.getBoundingClientRect();
                    const scrollerRect = scroller.getBoundingClientRect ? scroller.getBoundingClientRect() : { top: 0, height: win.innerHeight };
                    const current = scrollerTop(scroller);
                    const absoluteCarY = current + (trackRect.top - scrollerRect.top) + replayY;
                    const viewportHeight = scroller.clientHeight || win.innerHeight;
                    const desired = absoluteCarY - viewportHeight * 0.5;
                    const maxScroll = Math.max(0, scroller.scrollHeight - viewportHeight);
                    const target = Math.max(0, Math.min(desired, maxScroll));
                    const next = current + (target - current) * 0.55;
                    setScrollerTop(scroller, next);
                }

                function renderCar() {
                    car.style.top = replayY + "px";
                    scrollWithCar();
                }

                function hideOverlays() {
                    if (finishLine) {
                        finishLine.classList.remove("is-visible");
                    }
                    clearCelebrations();
                }

                function resetReplay() {
                    sequenceId += 1;
                    running = false;
                    paused = false;
                    car.classList.remove("is-turbo", "is-smoke");
                    doc.body.style.overflow = "";
                    doc.documentElement.style.overflow = "";
                    if (activeScroller) {
                        activeScroller.style.overflowY = previousScrollerOverflow;
                    }
                    track.classList.remove("replay-active");
                    car.style.transitionDuration = "0ms";
                    car.style.opacity = "0";
                    if (animationFrame) {
                        win.clearTimeout(animationFrame);
                        animationFrame = null;
                    }
                    hideOverlays();
                }

                function animateReplay(now, id, replayStops, finishY) {
                    if (!running || id !== sequenceId) {
                        return;
                    }
                    if (!lastFrame) {
                        lastFrame = now;
                    }
                    const elapsed = Math.min(48, now - lastFrame);
                    lastFrame = now;
                    if (!paused) {
                        replayY = Math.min(finishY, replayY + (basePixelsPerSecond * speedLevels[speedIndex] * elapsed / 1000));
                        renderCar();
                        while (nextStopIndex < replayStops.length && replayY >= yFor(replayStops[nextStopIndex])) {
                            const stop = replayStops[nextStopIndex];
                            if (stop.dataset.newClient === "1") {
                                celebrateNewClient(stop, id);
                            }
                            nextStopIndex += 1;
                        }
                        if (replayY >= finishY) {
                            if (finishLine) {
                                finishLine.classList.add("is-visible");
                            }
                            running = false;
                            animationFrame = null;
                            return;
                        }
                    }
                    animationFrame = win.setTimeout(() => animateReplay(Date.now(), id, replayStops, finishY), 16);
                }

                function startReplay() {
                    const replayStops = stops();
                    if (!replayStops.length) {
                        return;
                    }
                    resetReplay();
                    const id = sequenceId + 1;
                    sequenceId = id;
                    running = true;
                    paused = false;
                    doc.body.style.overflow = "";
                    doc.documentElement.style.overflow = "";
                    activeScroller = replayScroller();
                    previousScrollerOverflow = activeScroller.style.overflowY || "";
                    activeScroller.style.overflowY = previousScrollerOverflow;
                    hideOverlays();
                    track.classList.add("replay-active");

                    const start = doc.querySelector(".journey-start") || replayStops[0];
                    const finishTarget = finishLine || replayStops[replayStops.length - 1];
                    car.style.transitionDuration = "0ms";
                    car.style.opacity = "1";
                    car.classList.remove("is-turbo", "is-smoke");
                    speedIndex = 0;
                    nextStopIndex = 0;
                    replayY = yFor(start);
                    lastFrame = 0;
                    renderCar();
                    animationFrame = win.setTimeout(() => animateReplay(Date.now(), id, replayStops, yFor(finishTarget)), 16);
                }

                function cycleReplaySpeed() {
                    if (!running) {
                        return;
                    }
                    speedIndex = (speedIndex + 1) % speedLevels.length;
                    car.classList.toggle("is-smoke", speedLevels[speedIndex] === 1.65);
                    car.classList.toggle("is-turbo", speedLevels[speedIndex] === 2.75);
                }

                function togglePause() {
                    if (!running) return;
                    paused = !paused;
                    doc.body.style.overflow = paused ? "hidden" : "";
                    doc.documentElement.style.overflow = paused ? "hidden" : "";
                    const scroller = replayScroller();
                    scroller.style.overflowY = paused ? "hidden" : previousScrollerOverflow;
                }

                fuel.addEventListener("click", startReplay);
                let holdTimer = null;
                let holdTriggered = false;
                car.addEventListener("pointerdown", () => {
                    holdTriggered = false;
                    holdTimer = win.setTimeout(() => {
                        holdTriggered = true;
                        togglePause();
                    }, 420);
                });
                car.addEventListener("pointerup", () => {
                    if (holdTimer) {
                        win.clearTimeout(holdTimer);
                        holdTimer = null;
                    }
                });
                car.addEventListener("pointerleave", () => {
                    if (holdTimer) {
                        win.clearTimeout(holdTimer);
                        holdTimer = null;
                    }
                });
                car.addEventListener("click", () => {
                    if (holdTriggered) {
                        holdTriggered = false;
                        return;
                    }
                    cycleReplaySpeed();
                });
            }

            if (doc.readyState === "loading") {
                doc.addEventListener("DOMContentLoaded", () => initReplay(0), { once: true });
            } else {
                initReplay(0);
            }
        })();
        </script>
        """,
        height=0,
    )

    # Hidden native button the trophy-click JS above finds and .click()s
    # (window.parent lookup by exact button text) — same working pattern
    # already used for the Main page's hero-gauge click-throughs.
    # Directly setting window.parent.location.href from inside the
    # iframe was tried first and silently did nothing: the car
    # animation and timing all fired correctly, but the actual
    # navigation never happened, which points at the iframe's sandbox
    # simply not permitting top-level navigation even though it does
    # permit DOM read/write on the parent document (which is how the
    # rest of this replay system already works) — clicking a real
    # button that already lives in the parent page sidesteps that
    # restriction entirely, since Streamlit's own unsandboxed JS is
    # what performs the actual rerun/navigation in response.
    if st.button("Journey Go To Events", key="journey_nav_events"):
        st.query_params["view"] = "addevent"
        st.rerun()
    components.html(
        """
        <script>
        (function () {
            try {
                var doc = window.parent.document;
                var btns = doc.querySelectorAll('div[data-testid="stButton"] button');
                for (var i = 0; i < btns.length; i++) {
                    if (btns[i].textContent.trim() === 'Journey Go To Events') {
                        var wrap = btns[i].closest('div[data-testid="stButton"]');
                        if (wrap) { wrap.style.display = 'none'; }
                        break;
                    }
                }
            } catch (e) {}
        })();
        </script>
        """,
        height=0,
    )
