"""Data builder for the V2 preview pages (Main V2, Clients V2, Ledger V2,
Stats+ V2). Pure pandas -> plain dict; no Streamlit calls, no writes.
Ported from the standalone BehrHub preview builder and hardened for live
Sheet data (missing columns, blank amounts, non-Completed rows). Any
failure here is caught by components/v2_pages.py so it can only ever
affect a V2 tab, never the original pages."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from services.groups import CLIENT_GROUPS, LOCATION_GROUPS

START = pd.Timestamp("2026-04-20")
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
REG_MAP = {"maryland": "MD", "virginia": "VA", "washington, d.c.": "DC", "washington dc": "DC", "dc": "DC",
           "district of columbia": "DC", "pennsylvania": "PA", "west virginia": "WV"}
STATE_CODES = {"MD", "VA", "DC", "PA", "WV"}
REG_NAME = {"MD": "Maryland", "VA": "Virginia", "DC": "Washington, D.C.", "PA": "Pennsylvania", "WV": "West Virginia"}
_GROUP_STYLE = {
    "TJX Group": ("TJX", "#ff5a5f", "TJX"),
    "Government Group": ("GOV", "#7aa2ff", "Government"),
    "Nursing Home Group": ("NH", "#35d07f", "Nursing Home"),
    "Hilton Worldwide Group": ("HLT", "#38c6f4", "Hilton"),
    "Macy's Inc. Group": ("MCY", "#f472b6", "Macy's"),
    "Grocery Group": ("GRO", "#a3e635", "Grocery"),
    "DunkBR Group": ("D&B", "#fb923c", "Dunkin / BR"),
    "Standalone clients": ("SOLO", "#a78bfa", "Standalone"),
}
_SPARE_COLORS = ["#fbbf24", "#2dd4bf", "#e879f9", "#60a5fa", "#f87171"]


def city_nm(l):
    parts = str(l).rsplit(", ", 1)
    return f"{parts[0]} {parts[1]}" if len(parts) == 2 else str(l)


def _col(frame, *names):
    norm = {str(c).strip().casefold(): c for c in frame.columns}
    for n in names:
        if n.casefold() in norm:
            return norm[n.casefold()]
    return None


def _prep(timeline: pd.DataFrame, today: pd.Timestamp) -> pd.DataFrame:
    t = timeline.copy()
    src = {
        "client": _col(t, "Client"), "region": _col(t, "State/Region", "State / Region", "Region"),
        "status": _col(t, "Status"), "amt": _col(t, "Amount"), "date": _col(t, "Service Date", "Date"),
        "loc": _col(t, "Location Detail", "Location"), "bill": _col(t, "Billing Type"),
        "eid": _col(t, "Event ID"), "ver": _col(t, "Verified?", "Verified"),
    }
    if not src["client"] or not src["date"]:
        raise ValueError("Timeline is missing Client or Service Date columns")
    df = pd.DataFrame({"client": t[src["client"]].astype(str).str.strip()})
    df["Service Date"] = t[src["date"]]
    df["d"] = pd.to_datetime(t[src["date"]], errors="coerce").dt.normalize()
    df["amt"] = pd.to_numeric(t[src["amt"]], errors="coerce").fillna(0.0).astype(float) if src["amt"] else 0.0
    df["loc"] = t[src["loc"]].fillna("").astype(str).str.strip() if src["loc"] else ""
    df["region"] = t[src["region"]].fillna("").astype(str).str.strip() if src["region"] else ""
    df["Billing Type"] = t[src["bill"]].where(t[src["bill"]].astype(str).str.strip() != "", None) if src["bill"] else None
    df["Event ID"] = t[src["eid"]].astype(str) if src["eid"] else [f"R{i:04d}" for i in range(len(t))]
    df["Verified?"] = t[src["ver"]].astype(str).str.strip() if src["ver"] else "Yes"
    if src["status"]:
        df = df[t[src["status"]].astype(str).str.strip().str.casefold().eq("completed").values]
    df = df[df["d"].notna() & (df["client"] != "") & (df["client"].str.casefold() != "nan")]
    df = df[(df["d"] >= START) & (df["d"] <= today)].copy()
    df.loc[df["loc"] == "", "loc"] = "Unknown, ??"

    def _rc(row):
        r = REG_MAP.get(row["region"].casefold())
        if r:
            return r
        tail = row["loc"].rsplit(",", 1)[-1].strip().upper()
        return tail if tail in STATE_CODES else "OT"
    df["rc"] = df.apply(_rc, axis=1)
    if df.empty:
        raise ValueError("No completed events to show yet")
    return df.reset_index(drop=True)


def build_v2_data(timeline: pd.DataFrame, pipeline: pd.DataFrame | None, today) -> dict:
    TODAY = pd.Timestamp(today).normalize()
    df = _prep(timeline, TODAY)
    upcoming_rows = 0
    if pipeline is not None and len(pipeline):
        pc = _col(pipeline, "Client")
        if pc:
            upcoming_rows = int(pipeline[pc].astype(str).str.strip().replace({"nan": "", "None": ""}).ne("").sum())
    MONTHS = list(pd.period_range(START, TODAY, freq="M"))
    df["cw"] = (df["d"] - START).dt.days // 7 + 1
    CUR_CW = int((TODAY - START).days // 7 + 1)


    def cyc_idx(d):
        m = (d.year - 2026) * 12 + d.month - 4
        if d.day < 20:
            m -= 1
        return m + 1


    df["cyc"] = df["d"].apply(cyc_idx)
    CUR_CYC = cyc_idx(TODAY)
    MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


    def cyc_start(k):
        m = 4 + (k - 1)
        y = 2026 + (m - 1) // 12
        mm = (m - 1) % 12 + 1
        return pd.Timestamp(year=y, month=mm, day=20)


    # business days (weekdays) in the open cycle, for run-rate projection
    cs = cyc_start(CUR_CYC)
    ce = cyc_start(CUR_CYC + 1)  # exclusive
    BD_TOTAL = int(np.busday_count(cs.date(), ce.date()))
    BD_DONE = int(np.busday_count(cs.date(), (TODAY + pd.Timedelta(days=1)).date()))
    PROJ = BD_TOTAL / BD_DONE

    # ---- groups ------------------------------------------------------------
    CG = dict(CLIENT_GROUPS)
    GROUP_STYLE = dict(_GROUP_STYLE)
    for _i, _g in enumerate(CG):
        if _g not in GROUP_STYLE:
            GROUP_STYLE[_g] = (_g.split()[0][:4].upper(), _SPARE_COLORS[_i % len(_SPARE_COLORS)], _g.replace(" Group", ""))
    FLAGGED = []  # ungrouped clients now fold into Standalone
    client_group = {}
    for g, ms in CG.items():
        for m in ms:
            client_group[m] = g
    all_clients = sorted(df["client"].unique())
    for c in all_clients:
        if c not in client_group:
            client_group[c] = "Not grouped yet" if c in FLAGGED else "Standalone clients"
    df["cgroup"] = df["client"].map(client_group)

    LG = {k.replace("-proper", ""): v for k, v in LOCATION_GROUPS.items()}
    loc_group = {}
    for g, ms in LG.items():
        for m in ms:
            loc_group[m] = g
    df["ckey"] = df["loc"].apply(lambda x: ("G:" + loc_group[x]) if x in loc_group else ("S:" + x))

    # ---- labels (chart-only; never touches data) ---------------------------
    CLIENT_LBL = {"Dunkin'": "DNKN'", "Marshalls": "MARSH", "7-Eleven": "7-11", "Giant Food Stores": "GIANT",
                  "Food Lion": "FOOD LION", "Senate Sergeant at Arms": "SGT. ARMS", "Hebrew Home GW": "HBRW HOME"}
    CITY_GRP_LBL = {"Rockville": "ROCK", "Owings Mills": "O.MIL", "Elkridge": "ELK", "Tysons": "TYSON", "Bel Air": "BEL.A",
                    "Annapolis": "ANNA", "Towson": "TOWS", "Glen Burnie": "GLN.B", "Largo": "LRGO", "Landover": "LNDVR"}
    CITY_SOLO_LBL = {"Frederick, MD": "FRED", "Washington, DC": "D.C.", "College Park, MD": "C.PARK"}


    def client_label(c):
        if c in CLIENT_LBL:
            return CLIENT_LBL[c]
        u = c.upper()
        if len(u) <= 9:
            return u
        w = [x[:5] for x in u.replace("&", " ").split() if x not in ("OF", "AT")]
        return " ".join(w[:2])


    def city_label(key):
        kind, name = key[0], key[2:]
        if kind == "G":
            base = CITY_GRP_LBL.get(name) or (name.upper() if len(name) <= 6 else name.upper()[:6])
            return base + " GRP"
        if name in CITY_SOLO_LBL:
            return CITY_SOLO_LBL[name]
        city = name.split(",")[0].upper()
        return city if len(city) <= 7 else city[:6] + "."


    # ---- helpers -----------------------------------------------------------
    def agg(s):
        return {"ev": int(len(s)), "rev": round(float(s["amt"].sum()), 2), "days": int(s["d"].nunique())}


    def streaks(s):
        ds = sorted(s["d"].unique())
        ds = [pd.Timestamp(x) for x in ds]
        run, best, runs = 0, 0, []
        prev = None
        for d in ds:
            if prev is not None and d == pd.Timestamp(np.busday_offset(prev.date(), 1, roll="forward")):
                run += 1
            else:
                run = 1
            best = max(best, run)
            runs.append(run)
            prev = d
        if not ds:
            return 0, 0
        last = ds[-1]
        prev_bd = pd.Timestamp(np.busday_offset(TODAY.date(), -1, roll="backward")) if TODAY.weekday() < 5 else pd.Timestamp(np.busday_offset(TODAY.date(), 0, roll="backward"))
        current = runs[-1] if last >= prev_bd else 0
        return current, best


    def top_by(s, key, n=7, labeler=lambda k: k):
        rows = []
        for k, sub in s.groupby(key):
            a = agg(sub)
            a["l"] = labeler(k)
            rows.append(a)
        rows.sort(key=lambda r: (-r["ev"], -r["rev"]))
        return rows[:n]


    def pct(cur, prev):
        if prev in (0, None) or cur is None:
            return None
        return round((cur - prev) / prev * 100, 1)


    def region_block(s, code, name, color):
        a = agg(s)
        clients = int(s["client"].nunique())
        cities = int(s["loc"].nunique())
        mo = s.groupby(s["d"].dt.to_period("M"))["amt"].sum()
        best_mo = mo.idxmax().strftime("%b") if len(mo) else "-"
        cur_s, rec_s = streaks(s)

        # weekly (last 6 career weeks)
        weekly = []
        for cw in range(CUR_CW - 5, CUR_CW + 1):
            x = agg(s[s["cw"] == cw]); x["l"] = f"W{cw}"; weekly.append(x)
        # calendar months
        monthly = []
        for per in MONTHS:
            x = agg(s[s["d"].dt.to_period("M") == per]); x["l"] = per.strftime("%b").upper(); monthly.append(x)
        # career cycles (20th to 19th)
        career = []
        for k in range(1, CUR_CYC + 1):
            x = agg(s[s["cyc"] == k]); x["l"] = f"{MON[cyc_start(k).month - 1].upper()} 20"; career.append(x)
        dow = []
        for i, nm in enumerate(["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]):
            x = agg(s[s["d"].dt.dayofweek == i]); x["l"] = nm; dow.append(x)
        clients_chart = top_by(s, "client", labeler=client_label)
        cities_chart = top_by(s, "ckey", labeler=city_label)

        # cycle comparison (current open vs previous), run-rate on revenue/events only
        cur = agg(s[s["cyc"] == CUR_CYC]); prv = agg(s[s["cyc"] == CUR_CYC - 1])
        cur_rev_p, cur_ev_p = cur["rev"] * PROJ, cur["ev"] * PROJ
        avg_ev_c = cur["rev"] / cur["ev"] if cur["ev"] else None
        avg_ev_p = prv["rev"] / prv["ev"] if prv["ev"] else None
        avg_d_c = cur["rev"] / cur["days"] if cur["days"] else None
        avg_d_p = prv["rev"] / prv["days"] if prv["days"] else None
        mom = {
            "rev": pct(cur_rev_p, prv["rev"]), "ev": pct(cur_ev_p, prv["ev"]),
            "avgEv": pct(avg_ev_c, avg_ev_p), "avgDay": pct(avg_d_c, avg_d_p), "days": pct(cur["days"], prv["days"]),
        }

        wk = s.groupby("cw")["amt"].sum()
        spark = [round(float(wk.get(w, 0.0)), 2) for w in range(1, CUR_CW + 1)]
        day_rev = s.groupby("d")["amt"].sum()
        best_day = day_rev.idxmax()
        wk_best = wk.idxmax()
        mo_best = mo.idxmax()

        return {
            "code": code, "name": name, "color": color,
            "events": a["ev"], "revenue": a["rev"], "days": a["days"], "clients": clients, "cities": cities,
            "avgEv": round(a["rev"] / a["ev"], 2), "avgDay": round(a["rev"] / a["days"], 2),
            "evPerDay": round(a["ev"] / a["days"], 2),
            "bestMo": best_mo, "streak": cur_s, "streakRec": rec_s,
            "jurisd": int(s["rc"].nunique()),
            "mom": mom,
            "spark": spark,
            "records": {
                "day": {"v": round(float(day_rev.max()), 2), "l": best_day.strftime("%b %-d")},
                "week": {"v": round(float(wk.max()), 2), "l": f"W{int(wk_best)}"},
                "month": {"v": round(float(mo.max()), 2), "l": mo_best.strftime("%b")},
            },
            "charts": {"Weekly": weekly, "Monthly": monthly, "Career": career, "DAYofWK": dow,
                       "Clients": clients_chart, "Cities": cities_chart},
        }


    REGIONS = [("ALL", "All regions", "#7aa2ff", df),
               ("MD", "Maryland", "#ff5a5f", df[df.rc == "MD"]),
               ("VA", "Virginia", "#38c6f4", df[df.rc == "VA"]),
               ("DC", "Washington DC", "#a78bfa", df[df.rc == "DC"]),
               ("PA", "Pennsylvania", "#35d07f", df[df.rc == "PA"]),
               ("WV", "West Virginia", "#f5a524", df[df.rc == "WV"])]
    regions = [region_block(s, c, n, col) for c, n, col, s in REGIONS if len(s)]

    # ---- clients -----------------------------------------------------------
    cs_ = df.groupby("client").agg(visits=("amt", "size"), rev=("amt", "sum"), avg=("amt", "mean"),
                                   med=("amt", "median"), days=("d", "nunique"),
                                   first=("d", "min"), last=("d", "max"))
    cs_["rank"] = cs_["avg"].rank(ascending=False, method="min").astype(int)
    N_CLIENTS = len(cs_)
    BANDS = [("Diamond", "#7dd3fc", 7), ("Platinum", "#e8edf3", 11), ("Gold", "#ffce54", 16),
             ("Silver", "#a8b3c2", 20), ("Bronze", "#cd8a4f", 27), ("Wood", "#a97a4a", 10 ** 6)]


    def tier_for(rank):
        for nm, col, hi in BANDS:
            if rank <= hi:
                return nm, col


    tier_counts = {nm: 0 for nm, _, _ in BANDS}
    standings = []
    for name, r in cs_.iterrows():
        tn, tc = tier_for(int(r["rank"]))
        tier_counts[tn] += 1
        sub = df[df.client == name]
        top_c = sub["loc"].value_counts().head(3).index.tolist()
        g = client_group[name]
        standings.append({
            "name": name, "group": g, "gcolor": GROUP_STYLE[g][1],
            "visits": int(r["visits"]), "rev": round(float(r["rev"]), 2), "avg": round(float(r["avg"]), 2),
            "avgS": f"{r['avg']:,.0f}", "medS": f"{r['med']:,.0f}", "days": int(r["days"]),
            "rank": int(r["rank"]), "tier": tn, "tcolor": tc,
            "first": r["first"].strftime("%b %-d"), "last": r["last"].strftime("%b %-d"),
            "cities": top_c,
        })
    standings.sort(key=lambda x: (-x["visits"], -x["rev"]))
    medals = [{"n": nm, "c": col, "v": tier_counts[nm]} for nm, col, _ in BANDS]

    groups = []
    for g in list(CG.keys()) + ["Standalone clients"]:
        sub = df[df.cgroup == g]
        if sub.empty:
            continue
        code, color, label = GROUP_STYLE[g]
        members = []
        for c, ss in sub.groupby("client"):
            members.append({"n": c, "v": int(len(ss))})
        members.sort(key=lambda m: (-m["v"], m["n"]))
        groups.append({"name": g, "label": label, "code": code, "color": color,
                       "events": int(len(sub)), "rev": round(float(sub["amt"].sum()), 2),
                       "locs": int(sub["loc"].nunique()), "members": members})
    groups.sort(key=lambda x: (x["name"] == "Standalone clients", -x["rev"]))

    PRIORITY = []
    def prio(c):
        if client_group[c] == "TJX Group": return 0
        if client_group[c] == "Government Group": return 1
        if c in ("Dunkin'", "McDonald's", "7-Eleven"): return 2
        if client_group[c] == "Macy's Inc. Group": return 3
        if c in ("Verizon", "Carvana") or client_group[c] == "Hilton Worldwide Group": return 4
        if client_group[c] == "Grocery Group": return 5
        if client_group[c] == "Nursing Home Group": return 7
        return 6
    cur_clients = [c for c, r in cs_.iterrows() if (TODAY - r["last"]).days <= 90]
    cur_clients.sort(key=lambda c: (prio(c), -int(cs_.loc[c, "visits"]), c))
    ticker = [{"n": c, "color": GROUP_STYLE[client_group[c]][1]} for c in cur_clients]

    # ---- location groups ---------------------------------------------------
    loc_groups = []
    for g, ms in LG.items():
        sub = df[df["loc"].isin(ms)]
        cities = [{"n": m.split(",")[0], "v": int((sub["loc"] == m).sum())} for m in ms if (sub["loc"] == m).any()]
        loc_groups.append({"name": g, "visits": int(len(sub)), "rev": round(float(sub["amt"].sum()), 2), "cities": cities})
    loc_groups.sort(key=lambda x: (-x["visits"], -x["rev"]))
    solo = df[~df["loc"].isin(loc_group.keys())]
    solo_cities = []
    for c, ss in solo.groupby("loc"):
        solo_cities.append({"n": city_nm(c), "v": int(len(ss)), "rev": round(float(ss['amt'].sum()), 2)})
    solo_cities.sort(key=lambda x: (-x["v"], -x["rev"], x["n"]))

    # ---- LEDGER + STATS+ ---------------------------------------------------
    def fd(d): return d.strftime("%b %-d")
    def _unused_city_nm(l):
        parts = str(l).rsplit(", ", 1)
        return f"{parts[0]} {parts[1]}" if len(parts) == 2 else str(l)
    def period_block(label, a, b, sub, open_, bd_done, bd_total, partial=False):
        ev, rev, days = int(len(sub)), round(float(sub["amt"].sum()), 2), int(sub["d"].nunique())
        f = (bd_total / bd_done) if (open_ and bd_done) else 1.0
        return {"l": label, "range": f"{fd(a)} – {fd(b)}", "bd": bd_total, "bdDone": bd_done, "open": bool(open_), "partial": partial,
                "ev": ev, "rev": rev, "days": days, "avgEv": round(rev / ev, 2) if ev else 0, "avgDay": round(rev / days, 2) if days else 0,
                "pEv": ev * f, "pRev": rev * f}
    def add_mom(items):
        for i, it in enumerate(items):
            if i == 0: it["mom"] = None; continue
            p = items[i - 1]
            it["mom"] = {"rev": pct(it["pRev"], p["pRev"]), "ev": pct(it["pEv"], p["pEv"]), "avgEv": pct(it["avgEv"], p["avgEv"]),
                         "avgDay": pct(it["avgDay"], p["avgDay"]), "days": pct(it["days"], p["days"])}
    cycles = []
    for k in range(1, CUR_CYC + 1):
        a, b = cyc_start(k), cyc_start(k + 1) - pd.Timedelta(days=1)
        op = k == CUR_CYC
        cycles.append(period_block(f"Cycle {k}", a, b, df[df.cyc == k], op, BD_DONE if op else 0, int(np.busday_count(a.date(), (b + pd.Timedelta(days=1)).date()))))
    add_mom(cycles)
    months = []
    for per in MONTHS:
        a = per.start_time.normalize(); b = per.end_time.normalize()
        part = per == MONTHS[0]
        if part: a = max(a, START)
        op = per == MONTHS[-1]
        if op: b = min(b, b)
        sub = df[(df.d >= a) & (df.d <= b)]
        months.append(period_block(per.strftime("%b %Y"), a, b, sub, op, int(np.busday_count(a.date(), (TODAY + pd.Timedelta(days=1)).date())) if op else 0,
                                   int(np.busday_count(a.date(), (b + pd.Timedelta(days=1)).date())), partial=part))
    add_mom(months)
    cycles.reverse(); months.reverse()

    dd = df.groupby("d").agg(ev=("amt", "size"), rev=("amt", "sum")).reset_index().sort_values(["rev", "ev"], ascending=False).head(10)
    top_days = []
    for _, r in dd.iterrows():
        cl = df[df.d == r["d"]].groupby("client")["amt"].sum().sort_values(ascending=False)
        top_days.append({"l": fd(r["d"]), "dow": r["d"].strftime("%a"), "ev": int(r["ev"]), "rev": round(float(r["rev"]), 2), "sub": " · ".join(cl.index[:2])})
    ww = df.groupby("cw").agg(ev=("amt", "size"), rev=("amt", "sum"), days=("d", "nunique"), a=("d", "min"), b=("d", "max")).reset_index().sort_values("rev", ascending=False).head(10)
    top_weeks = [{"l": f"W{int(r['cw'])}", "dow": f"{fd(START + pd.Timedelta(days=7*(int(r['cw'])-1)))} week", "ev": int(r["ev"]), "rev": round(float(r["rev"]), 2), "sub": f"{int(r['days'])} days worked"} for _, r in ww.iterrows()]
    cc = df.groupby("client").agg(ev=("amt", "size"), rev=("amt", "sum")).sort_values(["rev", "ev"], ascending=False).head(10)
    top_clients = [{"l": c, "dow": "", "ev": int(r["ev"]), "rev": round(float(r["rev"]), 2), "sub": f"${r['rev']/r['ev']:.0f} / visit"} for c, r in cc.iterrows()]
    lc = df.groupby("loc").agg(ev=("amt", "size"), rev=("amt", "sum")).sort_values(["rev", "ev"], ascending=False).head(10)
    top_cities = [{"l": city_nm(c), "dow": "", "ev": int(r["ev"]), "rev": round(float(r["rev"]), 2), "sub": f"${r['rev']/r['ev']:.0f} / visit"} for c, r in lc.iterrows()]
    events = [{"d": fd(r.d), "c": r.client, "p": city_nm(r["loc"]), "r": r.rc, "a": float(r.amt), "b": (r["Billing Type"] if isinstance(r["Billing Type"], str) else "")}
              for _, r in df.sort_values(["d", "Event ID"], ascending=[False, False]).iterrows()]
    ledger = {"cycles": cycles, "months": months, "topDays": top_days, "topWeeks": top_weeks, "topClients": top_clients, "topCities": top_cities, "events": events}

    amts = df["amt"].astype(float)
    by_day = df.groupby("d").agg(ev=("amt", "size"), rev=("amt", "sum"))
    HB = [("Under $50", 0, 50), ("$50–99", 50, 100), ("$100–149", 100, 150), ("$150–199", 150, 200), ("$200–299", 200, 300), ("$300–399", 300, 400), ("$400+", 400, 1e9)]
    amt_hist = [{"l": l, "v": int(((amts >= lo) & (amts < hi)).sum())} for l, lo, hi in HB]
    epd = [{"l": str(n) if n < 5 else "5+", "v": int((by_day["ev"] == n).sum() if n < 5 else (by_day["ev"] >= 5).sum())} for n in range(1, 6)]
    wk = df.groupby("cw")["amt"].sum().reindex(range(1, CUR_CW + 1), fill_value=0)
    cum = [round(float(x), 2) for x in wk.cumsum()]
    cal = []
    for d in pd.date_range(START, TODAY):
        if d in by_day.index: cal.append({"d": fd(d), "w": int((d - START).days // 7), "x": d.weekday(), "ev": int(by_day.loc[d, "ev"]), "rev": round(float(by_day.loc[d, "rev"]), 2)})
        else: cal.append({"d": fd(d), "w": int((d - START).days // 7), "x": d.weekday(), "ev": 0, "rev": 0})
    dow = []
    for i, nm in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        ss = df[df.d.dt.weekday == i]
        dow.append({"l": nm, "ev": int(len(ss)), "rev": round(float(ss["amt"].sum()), 2), "days": int(ss["d"].nunique())})
    cl_rev = df.groupby("client")["amt"].sum().sort_values(ascending=False)
    cl_vis = df.groupby("client").size()
    mx = df.loc[df["amt"].idxmax()]
    busiest = by_day.sort_values(["ev", "rev"], ascending=False).iloc[0]
    bill = df["Billing Type"].fillna("Standard").value_counts()
    statsx = {
        "kpis": [
            {"l": "Median event", "v": f"${amts.median():,.0f}", "s": f"mean ${amts.mean():,.0f}"},
            {"l": "Top 10% of events", "v": f"${amts.quantile(.9):,.0f}+", "s": "90th percentile"},
            {"l": "Biggest single event", "v": f"${mx['amt']:,.0f}", "s": f"{mx['client']} · {fd(mx['d'])}"},
            {"l": "Busiest day", "v": f"{int(busiest['ev'])} events", "s": f"{fd(busiest.name)} · ${busiest['rev']:,.0f}"},
            {"l": "Events / week", "v": f"{len(df)/CUR_CW:.1f}", "s": f"over {CUR_CW} career weeks"},
            {"l": "Top 3 clients", "v": f"{cl_rev.head(3).sum()/cl_rev.sum()*100:.0f}%", "s": "of revenue · " + ", ".join(cl_rev.index[:3])},
            {"l": "Repeat clients", "v": f"{int((cl_vis >= 2).sum())} of {len(cl_vis)}", "s": "visited 2+ times"},
            {"l": "Verified", "v": f"{(df['Verified?'] == 'Yes').mean()*100:.0f}%", "s": "of all events"},
        ],
        "amtHist": amt_hist, "epd": epd, "cum": cum, "cal": cal, "calMax": round(float(by_day["rev"].max()), 2), "dow": dow,
        "bill": [{"l": k, "v": int(v)} for k, v in bill.items()],
        "regionShare": [{"l": r["code"], "rev": r["revenue"], "ev": r["events"], "c": r["color"]} for r in regions[1:]],
        "pace": {"weeks": CUR_CW, "avgWk": round(float(wk.mean()), 2)},
    }

    # ---- JOURNEY + EVENTS FORM --------------------------------------------
    dsort = df.sort_values(["d", "Event ID"]).reset_index(drop=True)
    dsort["cum"] = dsort["amt"].astype(float).cumsum()
    def fdy(d): return d.strftime("%b %-d")
    miles = []
    for T in [1000, 2500, 5000, 10000, 15000, 20000]:
        hit = dsort[dsort["cum"] >= T]
        if len(hit):
            r = hit.iloc[0]; miles.append({"d": fdy(r.d), "k": "rev", "t": f"${T:,} earned", "s": f"event #{int(hit.index[0])+1} · {r.client}", "o": int(r.d.value // 86400e9)})
    for n in [1, 10, 25, 50, 75, 100, 125, 150]:
        if len(dsort) >= n:
            r = dsort.iloc[n - 1]
            miles.append({"d": fdy(r.d), "k": "ev", "t": "First event" if n == 1 else f"Event #{n}", "s": f"{r.client} · {city_nm(r['loc'])}", "o": int(r.d.value // 86400e9)})
    ud = sorted(dsort["d"].unique())
    for n in [10, 25, 50, 75, 100]:
        if len(ud) >= n:
            d0 = pd.Timestamp(ud[n - 1]); miles.append({"d": fdy(d0), "k": "day", "t": f"Day {n} worked", "s": f"career week {int((d0 - START).days // 7 + 1)}", "o": int(d0.value // 86400e9)})
    seen = set()
    for _, r in dsort.iterrows():
        if r.rc not in seen:
            seen.add(r.rc); 
            if len(seen) > 1 or True:
                nm = REG_NAME.get(r.rc, "Other")
                miles.append({"d": fdy(r.d), "k": "reg", "t": f"First {nm} event" if len(seen) > 1 else f"Started in {nm}", "s": f"{r.client} · {city_nm(r['loc'])}", "o": int(r.d.value // 86400e9)})
    first_client = {}
    for _, r in dsort.iterrows():
        first_client.setdefault(r.cgroup, r)
    bd_ = by_day.sort_values("rev", ascending=False).iloc[0]
    miles.append({"d": fdy(bd_.name), "k": "rec", "t": f"Best day · ${bd_['rev']:,.0f}", "s": f"{int(bd_['ev'])} events", "o": int(bd_.name.value // 86400e9)})
    mxr = dsort.loc[dsort["amt"].astype(float).idxmax()]
    miles.append({"d": fdy(mxr.d), "k": "rec", "t": f"Biggest event · ${mxr['amt']:,.0f}", "s": f"{mxr.client} · {city_nm(mxr['loc'])}", "o": int(mxr.d.value // 86400e9)})
    wkb = df.groupby("cw")["amt"].sum().sort_values(ascending=False)
    bw = int(wkb.index[0]); bws = START + pd.Timedelta(days=7 * (bw - 1))
    miles.append({"d": fdy(bws), "k": "rec", "t": f"Best week · W{bw} · ${wkb.iloc[0]:,.0f}", "s": "week starting " + fdy(bws), "o": int(bws.value // 86400e9)})
    miles.sort(key=lambda m: m["o"])
    for m in miles: m.pop("o")
    tot = float(df["amt"].sum()); wks = CUR_CW
    def eta(remaining, per_week):
        return fdy(TODAY + pd.Timedelta(days=int(math.ceil(remaining / per_week * 7))))
    nxt_rev = next(g for g in [5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000] if g > tot)
    nxt_ev = next(g for g in [25, 50, 100, 150, 200, 250, 300] if g > len(df))
    nxt_day = next(g for g in [25, 50, 100, 125, 150, 200] if g > len(ud))
    journey = {
        "next": [
            {"l": "Revenue", "cur": round(tot, 2), "goal": nxt_rev, "left": round(nxt_rev - tot, 2), "eta": eta(nxt_rev - tot, tot / wks), "money": True},
            {"l": "Events", "cur": len(df), "goal": nxt_ev, "left": nxt_ev - len(df), "eta": eta(nxt_ev - len(df), len(df) / wks), "money": False},
            {"l": "Days worked", "cur": len(ud), "goal": nxt_day, "left": nxt_day - len(ud), "eta": eta(nxt_day - len(ud), len(ud) / wks), "money": False},
        ],
        "pace": f"at your career average ({tot/wks:,.0f} $ / week, {len(df)/wks:.1f} events / week)".replace(" $ /", " /").replace("(", "(\\$").replace("\\$", "$"),
        "miles": miles, "weeks": wks, "start": fdy(START),
    }
    cinfo = {}
    for c, ss in df.groupby("client"):
        cinfo[c] = {"loc": ss["loc"].mode().iloc[0], "amt": float(ss["amt"].astype(float).median()),
                    "bill": (ss["Billing Type"].dropna().mode().iloc[0] if ss["Billing Type"].notna().any() else "")}
    STATE_REGION = {"MD": "Maryland", "VA": "Virginia", "DC": "Washington, D.C.", "PA": "Pennsylvania", "WV": "West Virginia"}
    form = {"clients": cinfo, "locs": sorted(df["loc"].unique()), "stateRegion": STATE_REGION, "today": TODAY.strftime("%Y-%m-%d"),
            "recent": events[:8], "totals": {"ev": int(len(df)), "rev": round(tot, 2), "days": int(len(ud))}, "dayset": [pd.Timestamp(x).strftime("%Y-%m-%d") for x in ud]}


    return {
        "journey": journey, "form": form,
        "ledger": ledger, "statsx": statsx,
        "asOf": TODAY.strftime("%b %-d, %Y"),
        "upcomingRows": upcoming_rows,
        "regions": regions,
        "nClients": N_CLIENTS,
        "standings": standings, "medals": medals,
        "groups": groups, "ticker": ticker,
        "locGroups": loc_groups, "soloCities": solo_cities,
        "proj": {"bdDone": BD_DONE, "bdTotal": BD_TOTAL, "cycStart": cs.strftime("%b %-d"), "cycEnd": (ce - pd.Timedelta(days=1)).strftime("%b %-d"),
                 "prevStart": cyc_start(CUR_CYC - 1).strftime("%b %-d"), "prevEnd": (cs - pd.Timedelta(days=1)).strftime("%b %-d")},
    }
