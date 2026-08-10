from __future__ import annotations

from html import escape

import pandas as pd
import streamlit.components.v1 as components

from services.metrics import ExecutiveMetrics
from services.money_view import gross_up

DASH = "\u2014"


def _client_initials(name: str) -> str:
    words = [part for part in name.replace("&", " ").split() if part]
    if not words:
        return "\u2014"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


# Our location data only has city-level granularity (no street address),
# so counting distinct "City, ST" values undercounts clients who've
# visited multiple different physical stores that happen to share a
# city name. Confirmed by bravo echo (2026-08-08): Dunkin has visited
# 2 different Owings Mills stores and 2 different Reisterstown stores;
# Aberdeen is the only genuine repeat visit to the same store. Real
# distinct-location count is 8 (out of 9 visits), not the 5-6 that
# city-only dedup produces. Add more entries here if this comes up for
# other clients (7-Eleven was checked and does NOT need an override —
# its 4 visits are 4 genuinely different cities).
LOCATION_COUNT_OVERRIDES = {
    "Dunkin'": 8,
}


def _client_details(timeline: pd.DataFrame) -> dict[str, dict]:
    """Per-client stats + full chronological visit list, keyed by client name."""
    working = timeline.copy()
    working["__date"] = pd.to_datetime(working["Service Date"], errors="coerce")
    working["__amount"] = pd.to_numeric(working["Amount"], errors="coerce").fillna(0)
    chronological = working.sort_values("__date").reset_index(drop=True)
    chronological["__visit_num"] = range(1, len(chronological) + 1)

    details: dict[str, dict] = {}
    for client, group in chronological.groupby("Client"):
        confirmed = group[group["Verified?"] == "Yes"]
        total_revenue = float(confirmed["__amount"].sum())
        visits = len(group)
        locations = group["Location Detail"].dropna().astype(str).str.strip()
        locations = locations[locations != ""]
        dated = group.dropna(subset=["__date"])

        visit_rows = []
        for _, row in group.sort_values("__date").iterrows():
            date_val = row["__date"]
            date_label = date_val.strftime("%b %d, %Y") if pd.notna(date_val) else "\u2014"
            loc = str(row.get("Location Detail") or row.get("State/Region") or "\u2014")
            visit_rows.append({
                "visit_num": int(row["__visit_num"]),
                "date": date_label,
                "location": loc,
                "amount_raw": float(row["__amount"]),
                "confirmed": row["Verified?"] == "Yes",
            })

        details[str(client)] = {
            "visits": visits,
            "total_revenue": total_revenue,
            "avg_per_visit": total_revenue / len(confirmed) if len(confirmed) else 0.0,
            "locations": LOCATION_COUNT_OVERRIDES.get(str(client), int(locations.nunique())),
            "states": sorted(group["State/Region"].dropna().astype(str).unique().tolist()),
            "first_visit": int(group["__visit_num"].min()),
            "last_visit": int(group["__visit_num"].max()),
            "date_start": dated["__date"].min().strftime("%b %d, %Y") if not dated.empty else "\u2014",
            "date_end": dated["__date"].max().strftime("%b %d, %Y") if not dated.empty else "\u2014",
            "visit_rows": visit_rows,
        }
    return details


def _detail_panel_html(name: str, detail: dict, gross_view: bool = False) -> str:
    display_total = gross_up(detail["total_revenue"]) if gross_view else detail["total_revenue"]
    display_avg = gross_up(detail["avg_per_visit"]) if gross_view else detail["avg_per_visit"]
    total_lbl = "TOTAL REVENUE (GROSS)" if gross_view else "TOTAL REVENUE"
    avg_lbl = "AVG / VISIT (GROSS)" if gross_view else "AVG / VISIT"
    stats_html = (
        '<div class="detail-stat-grid">'
        f'<div class="detail-stat"><div class="detail-stat-val">{detail["visits"]}</div><div class="detail-stat-lbl">VISITS</div></div>'
        f'<div class="detail-stat"><div class="detail-stat-val">\uFF04{display_total:,.0f}</div><div class="detail-stat-lbl">{total_lbl}</div></div>'
        f'<div class="detail-stat"><div class="detail-stat-val">\uFF04{display_avg:,.0f}</div><div class="detail-stat-lbl">{avg_lbl}</div></div>'
        f'<div class="detail-stat"><div class="detail-stat-val">{detail["locations"]}</div><div class="detail-stat-lbl">LOCATIONS</div></div>'
        '</div>'
    )
    states_label = ", ".join(detail["states"]) or DASH
    meta_html = (
        '<div class="detail-meta-row">'
        f'<span>States: <strong>{escape(states_label)}</strong></span>'
        f'<span>Visits #{detail["first_visit"]}\u2013#{detail["last_visit"]}</span>'
        f'<span>{escape(detail["date_start"])} \u2013 {escape(detail["date_end"])}</span>'
        '</div>'
    )
    def _visit_amount_label(v: dict) -> str:
        if not v["confirmed"]:
            return "Pending"
        amount = gross_up(v["amount_raw"]) if gross_view else v["amount_raw"]
        return f"\uFF04{amount:,.0f}"

    timeline_html = "".join(
        '<div class="detail-visit-row">'
        f'<div class="detail-visit-num">#{v["visit_num"]}</div>'
        f'<div class="detail-visit-info"><div class="detail-visit-date">{escape(v["date"])}</div>'
        f'<div class="detail-visit-loc">{escape(v["location"])}</div></div>'
        f'<div class="detail-visit-amt">{escape(_visit_amount_label(v))}</div>'
        '</div>'
        for v in detail["visit_rows"]
    )
    return (
        f'<div class="client-detail-panel" id="detail-{escape(name.casefold())}">'
        f'{stats_html}{meta_html}'
        f'<div class="detail-visit-title">VISIT HISTORY</div>'
        f'<div class="detail-visit-list">{timeline_html}</div>'
        '</div>'
    )


def render_client_standings(metrics: ExecutiveMetrics, timeline: pd.DataFrame, gross_view: bool = False) -> None:
    directory = list(metrics.data_views.get("client_directory", []))
    top = directory[:3]
    rest = directory[3:]
    maximum = max((int(item["events"]) for item in directory), default=1)
    ranked = {index + 1: item for index, item in enumerate(top)}
    details = _client_details(timeline)

    podium = []
    podium_panels = []
    for rank in (2, 1, 3):
        item = ranked.get(rank)
        if item is None:
            podium.append(
                f'<div class="podium-card"><div class="podium-badge">#{rank}</div>'
                '<div class="podium-name">\u2014</div><div class="podium-count">0</div>'
                '<div class="podium-label">EVENTS</div></div>'
            )
            continue
        primary = " rank-1" if rank == 1 else ""
        badge = "\u2605 #1" if rank == 1 else f"#{rank}"
        name = str(item["client"])
        podium.append(
            f'<div class="podium-card{primary}" data-client="{escape(name.casefold())}" '
            f'data-target="detail-{escape(name.casefold())}"><div class="podium-badge">{badge}</div>'
            f'<div class="podium-name">{escape(name)}</div>'
            f'<div class="podium-count">{int(item["events"]):,}</div>'
            '<div class="podium-label">EVENTS</div></div>'
        )
        if name in details:
            podium_panels.append(_detail_panel_html(name, details[name], gross_view))

    rows = []
    for rank, item in enumerate(rest, start=4):
        name = str(item["client"])
        visits = int(item["events"])
        width = visits / maximum * 100 if maximum else 0
        row_html = (
            f'<div class="client-row" data-client="{escape(name.casefold())}" data-target="detail-{escape(name.casefold())}">'
            f'<div class="row-rank">{rank}</div>'
            f'<div class="row-info"><div class="row-avatar">{escape(_client_initials(name))}</div>'
            f'<div class="row-name">{escape(name)}</div></div>'
            f'<div class="mini-progress-bg"><div class="mini-progress-fill" style="width:{width:.1f}%"></div></div>'
            f'<div class="row-visits">{visits:,}</div>'
            '<div class="row-chevron">\u203A</div></div>'
        )
        panel_html = _detail_panel_html(name, details[name], gross_view) if name in details else ""
        rows.append(row_html + panel_html)
    if not rows:
        rows.append('<div class="empty-directory">The first three clients contain the full current ranking.</div>')

    html = f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
    *{{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}html,body{{width:100%;overflow:hidden;background:transparent}}body{{color:#fff}}
    .client-card-container{{background:radial-gradient(circle at 50% -20%,rgba(244,114,182,.08),transparent 44%),rgba(23,27,40,.65);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.12);border-radius:24px;padding:20px;box-shadow:0 15px 35px rgba(0,0,0,.5)}}
    .client-header-title{{font-size:13px;font-weight:900;letter-spacing:1.5px}}.client-overline{{margin-top:2px;color:#ec4899;font-size:9px;font-weight:700}}
    .podium-grid{{display:grid;grid-template-columns:1fr 1.1fr 1fr;gap:8px;align-items:end;margin:20px 0 25px}}.podium-card{{background:rgba(15,20,32,.6);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:12px 8px;text-align:center;position:relative;cursor:pointer}}.podium-card:hover{{border-color:rgba(244,114,182,.35)}}.podium-card.is-open{{border-color:#f472b6;box-shadow:0 0 16px rgba(244,114,182,.25)}}.podium-card.rank-1{{background:linear-gradient(180deg,rgba(244,114,182,.15),rgba(15,20,32,.8));border-color:rgba(244,114,182,.5);box-shadow:0 0 20px rgba(244,114,182,.2);padding-top:20px}}
    .podium-badge{{position:absolute;top:-10px;left:50%;transform:translateX(-50%);background:#0d0f17;border:1px solid rgba(255,255,255,.2);border-radius:10px;padding:2px 8px;font-size:9px;font-weight:900;color:#64748b;white-space:nowrap}}.rank-1 .podium-badge{{border-color:#f472b6;color:#f472b6}}.podium-name{{font-size:11px;font-weight:800;margin-top:6px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.podium-count{{font-size:20px;font-weight:900;color:#38bdf8}}.rank-1 .podium-count{{font-size:26px;color:#f472b6}}.podium-label{{font-size:8px;font-weight:700;color:#64748b}}
    .search-box{{width:100%;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:8px 12px;font-size:10px;color:#d7deea;outline:none;margin-bottom:12px}}.client-list{{display:flex;flex-direction:column;gap:6px}}.client-row{{display:grid;grid-template-columns:24px minmax(0,1fr) 80px 40px 16px;align-items:center;background:rgba(15,20,32,.4);border:1px solid rgba(255,255,255,.05);border-radius:12px;padding:8px 12px;cursor:pointer}}.client-row:hover{{border-color:rgba(244,114,182,.3)}}.row-rank{{font-size:10px;font-weight:800;color:#64748b}}.row-info{{min-width:0;display:flex;align-items:center;gap:8px}}.row-avatar{{width:22px;height:22px;border-radius:6px;background:rgba(255,255,255,.08);display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:800;color:#38bdf8}}.row-name{{overflow:hidden;font-size:11px;font-weight:700;text-overflow:ellipsis;white-space:nowrap}}.mini-progress-bg{{height:4px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden}}.mini-progress-fill{{height:100%;background:linear-gradient(90deg,#38bdf8,#f472b6)}}.row-visits{{font-size:12px;font-weight:800;text-align:right}}.row-chevron{{font-size:14px;color:#64748b;text-align:center;transition:transform .2s ease}}.client-row.is-open .row-chevron{{transform:rotate(90deg);color:#f472b6}}.empty-directory{{padding:12px;color:#64748b;font-size:10px;text-align:center}}
    .client-detail-panel{{display:none;margin-top:6px;padding:14px;background:rgba(15,20,32,.6);border:1px solid rgba(244,114,182,.25);border-radius:14px}}.client-detail-panel.is-visible{{display:block}}
    .podium-detail-wrap{{margin-bottom:12px}}
    .detail-stat-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:12px}}.detail-stat{{background:rgba(255,255,255,.04);border-radius:10px;padding:8px 4px;text-align:center}}.detail-stat-val{{font-size:14px;font-weight:900;color:#f472b6}}.detail-stat-lbl{{font-size:7px;font-weight:800;color:#94a3b8;letter-spacing:.3px;margin-top:2px}}
    .detail-meta-row{{display:flex;flex-wrap:wrap;gap:10px;font-size:9.5px;color:#94a3b8;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.06)}}.detail-meta-row strong{{color:#e2e8f0}}
    .detail-visit-title{{font-size:9px;font-weight:800;letter-spacing:.6px;color:#7dd3fc;margin-bottom:8px}}.detail-visit-list{{display:flex;flex-direction:column;gap:5px;max-height:260px;overflow-y:auto}}
    .detail-visit-row{{display:grid;grid-template-columns:28px 1fr auto;align-items:center;gap:8px;background:rgba(255,255,255,.03);border-radius:8px;padding:6px 8px}}.detail-visit-num{{font-size:9px;font-weight:800;color:#64748b}}.detail-visit-date{{font-size:10px;font-weight:700;color:#fff}}.detail-visit-loc{{font-size:9px;color:#7dd3fc;margin-top:1px}}.detail-visit-amt{{font-size:10.5px;font-weight:800;color:#34d399;white-space:nowrap}}
    @media(max-width:520px){{.client-card-container{{padding:16px 14px}}.client-row{{grid-template-columns:20px minmax(0,1fr) 62px 32px 14px;padding:8px 9px}}.detail-stat-grid{{grid-template-columns:repeat(2,1fr)}}}}
    </style></head><body><div class="client-card-container"><div class="client-header-title">CLIENT STANDINGS</div><div class="client-overline">\u25cf TOP PERFORMERS &amp; DIRECTORY</div><div class="podium-grid">{''.join(podium)}</div><div class="podium-detail-wrap">{''.join(podium_panels)}</div><input id="client-search" type="search" class="search-box" placeholder="Search current client directory..."><div class="client-list">{''.join(rows)}</div></div><script>
    const q=document.getElementById('client-search');
    const clickable=[...document.querySelectorAll('.client-row,.podium-card')];
    if(q)q.addEventListener('input',()=>{{
      const v=q.value.trim().toLowerCase();
      clickable.forEach(el=>{{
        const match=!v||(el.dataset.client||'').includes(v);
        el.style.display=match?(el.classList.contains('podium-card')?'block':'grid'):'none';
      }});
    }});
    clickable.forEach(el=>{{
      el.addEventListener('click',()=>{{
        const targetId=el.dataset.target;
        const panel=targetId?document.getElementById(targetId):null;
        if(!panel)return;
        const willOpen=!panel.classList.contains('is-visible');
        document.querySelectorAll('.client-detail-panel.is-visible').forEach(p=>p.classList.remove('is-visible'));
        document.querySelectorAll('.is-open').forEach(r=>r.classList.remove('is-open'));
        if(willOpen){{panel.classList.add('is-visible');el.classList.add('is-open');}}
      }});
    }});
    </script></body></html>"""
    height = 326 + max(len(rest), 1) * 50 + 480
    components.html(html, height=height, scrolling=False)
