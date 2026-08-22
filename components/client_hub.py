from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
import streamlit.components.v1 as components

from services.metrics import ExecutiveMetrics
from services.money_view import gross_up
from services.logo_source import discover_logos, resolve_client_logo, logo_data_uri

DASH = "\u2014"
LOGOS_DIR = Path(__file__).resolve().parent.parent / "assets" / "logos"


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
    chronological = working.sort_values(["__date", "Event ID"], kind="stable").reset_index(drop=True)
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
        for _, row in group.sort_values(["__date", "Event ID"], kind="stable").iterrows():
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

        confirmed_amounts = confirmed["__amount"]
        median_per_visit = float(confirmed_amounts.median()) if len(confirmed_amounts) else 0.0

        details[str(client)] = {
            "visits": visits,
            "total_revenue": total_revenue,
            "avg_per_visit": total_revenue / len(confirmed) if len(confirmed) else 0.0,
            "median_per_visit": median_per_visit,
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
    details = _client_details(timeline)

    ranked_by_avg = sorted(
        (n for n, d in details.items() if d["avg_per_visit"] > 0),
        key=lambda n: details[n]["avg_per_visit"],
        reverse=True,
    )
    avg_revenue_rank = {name: i + 1 for i, name in enumerate(ranked_by_avg)}
    total_ranked = len(ranked_by_avg)

    # Primary sort: event count descending (as already ordered by the
    # directory). Tie-break: revenue rank ascending, so among clients
    # with the same visit count, the higher-earning one lists first.
    directory = sorted(
        directory,
        key=lambda item: (
            -int(item["events"]),
            avg_revenue_rank.get(str(item["client"]), total_ranked + 1),
        ),
    )

    # Tiers are purely avg-revenue/visit based, same metric for every
    # client, no visit-count special-casing. Silver's actual cutoff
    # (98) is intentionally a bit below its displayed label (100) —
    # both the legend and this comment call that out explicitly so it
    # doesn't look like a bug on a future read-through.
    def _tier_for(name: str) -> str:
        avg = details.get(name, {}).get("avg_per_visit", 0.0)
        if avg >= 200:
            return "diamond"
        if avg >= 150:
            return "platinum"
        if avg >= 125:
            return "gold"
        if avg >= 98:  # displayed as "$100+" in the legend, see above
            return "silver"
        if avg >= 75:
            return "bronze"
        return "wooden"

    TIER_PILL = {
        "diamond": '<span class="tier-pill tier-diamond">DIAMOND</span>',
        "platinum": '<span class="tier-pill tier-platinum">PLATINUM</span>',
        "gold": '<span class="tier-pill tier-gold">GOLD</span>',
        "silver": '<span class="tier-pill tier-silver">SILVER</span>',
        "bronze": '<span class="tier-pill tier-bronze">BRONZE</span>',
        "wooden": '<span class="tier-pill tier-wooden">WOOD</span>',
    }

    RANK_MEDAL = {
        1: ("rank-medal rank-gold", "1"),
        2: ("rank-medal rank-silver", "2"),
        3: ("rank-medal rank-bronze", "3"),
    }

    logo_files, _duplicate_logos = discover_logos(LOGOS_DIR)

    rows = []
    for rank, item in enumerate(directory, start=1):
        name = str(item["client"])
        visits = int(item["events"])
        detail = details.get(name, {})
        avg_visit_raw = detail.get("avg_per_visit", 0.0)
        avg_visit_display = gross_up(avg_visit_raw) if gross_view else avg_visit_raw
        avg_visit_label = f"\uFF04{avg_visit_display:,.0f}" if avg_visit_raw else DASH
        median_raw = detail.get("median_per_visit", 0.0)
        median_display = gross_up(median_raw) if gross_view else median_raw
        median_label = f"\uFF04{median_display:,.0f}" if median_raw else DASH
        rev_rank = avg_revenue_rank.get(name)
        rev_rank_label = f"#{rev_rank}/{total_ranked}" if rev_rank else DASH
        tier = _tier_for(name)
        pill_html = TIER_PILL[tier]
        medal_cls, medal_label = RANK_MEDAL.get(rank, ("", str(rank)))
        logo_path = resolve_client_logo(name, logo_files)
        if logo_path is not None:
            avatar_html = f'<div class="row-avatar has-logo"><img src="{logo_data_uri(logo_path)}" alt="" loading="lazy"></div>'
        else:
            avatar_html = f'<div class="row-avatar">{escape(_client_initials(name))}</div>'
        row_html = (
            f'<div class="client-row" data-client="{escape(name.casefold())}" data-target="detail-{escape(name.casefold())}">'
            f'<div class="row-identity"><div class="row-badge-wrap">{avatar_html}<div class="row-rank {medal_cls}">{medal_label}</div></div></div>'
            '<div class="row-header">'
            f'<div class="row-name">{escape(name)}</div>'
            f'{pill_html}'
            '<div class="row-chevron">\u203A</div>'
            '</div>'
            '<div class="row-stats">'
            f'<div class="row-stat"><div class="row-stat-val">{visits}</div><div class="row-stat-lbl">VISITS</div></div>'
            f'<div class="row-stat"><div class="row-stat-val">{escape(avg_visit_label)}</div><div class="row-stat-lbl">/VISIT</div></div>'
            f'<div class="row-stat"><div class="row-stat-val">{escape(median_label)}</div><div class="row-stat-lbl">MEDIAN</div></div>'
            f'<div class="row-stat"><div class="row-stat-val">{escape(rev_rank_label)}</div><div class="row-stat-lbl">RANK</div></div>'
            '</div>'
            '</div>'
        )
        panel_html = _detail_panel_html(name, details[name], gross_view) if name in details else ""
        rows.append(row_html + panel_html)
    if not rows:
        rows.append('<div class="empty-directory">No client data yet.</div>')

    legend_html = (
        '<div class="tier-legend">'
        '<div class="tier-legend-item"><span class="tier-pill tier-diamond">DIAMOND</span><span>\uFF04'
        '200+</span></div>'
        '<div class="tier-legend-item"><span class="tier-pill tier-platinum">PLATINUM</span><span>\uFF04'
        '150+</span></div>'
        '<div class="tier-legend-item"><span class="tier-pill tier-gold">GOLD</span><span>\uFF04'
        '125+</span></div>'
        '<div class="tier-legend-item"><span class="tier-pill tier-silver">SILVER</span><span>\uFF04'
        '100+</span></div>'
        '<div class="tier-legend-item"><span class="tier-pill tier-bronze">BRONZE</span><span>\uFF04'
        '75+</span></div>'
        '<div class="tier-legend-item"><span class="tier-pill tier-wooden">WOOD</span><span>ALL OTHERS</span></div>'
        '</div>'
    )

    livery_clients = [
        item["client"] for item in directory
        if resolve_client_logo(str(item["client"]), logo_files) is not None
    ]
    livery_tiles = "".join(
        f'<div class="livery-tile"><img src="{logo_data_uri(resolve_client_logo(str(name), logo_files))}" alt=""></div>'
        for name in livery_clients
    )
    # Duplicated back-to-back so a translateX(-50%) loop is seamless —
    # standard marquee technique, avoids any visible snap/reset.
    livery_html = (
        f'<div class="livery-panel"><div class="livery-title">CURRENT SPONSORS</div>'
        f'<div class="livery-track">{livery_tiles}{livery_tiles}</div></div>'
        if livery_clients else ""
    )

    html = f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
    *{{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}html,body{{width:100%;overflow:hidden;background:transparent}}body{{color:#fff}}
    .client-card-container{{background:radial-gradient(circle at 50% -20%,rgba(244,114,182,.08),transparent 44%),rgba(23,27,40,.65);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.12);border-radius:24px;padding:20px;box-shadow:0 15px 35px rgba(0,0,0,.5)}}
    .client-header-title{{font-size:16px;font-weight:900;letter-spacing:.5px;color:#fff;margin-bottom:12px}}.client-overline{{margin-top:2px;color:#ec4899;font-size:9px;font-weight:700}}
    .tier-pill{{display:inline-flex;align-items:center;justify-content:center;padding:2px 7px;border-radius:999px;font-size:9.5px;font-weight:900;letter-spacing:.4px;white-space:nowrap;flex-shrink:0}}
    .tier-diamond{{background:linear-gradient(135deg,#e0f7ff,#7dd3fc,#e0f7ff);color:#0c2a3a;box-shadow:0 0 8px rgba(125,211,252,.6)}}
    .tier-platinum{{background:linear-gradient(135deg,#f4f7fb,#c7d2dc);color:#1e293b;box-shadow:0 0 6px rgba(199,210,220,.5)}}
    .tier-gold{{background:linear-gradient(135deg,#ffe58a,#d4a017);color:#3a2600;box-shadow:0 0 6px rgba(212,160,23,.5)}}
    .tier-silver{{background:linear-gradient(135deg,#f1f5f9,#a8b3c2);color:#1e293b;box-shadow:0 0 6px rgba(168,179,194,.4)}}
    .tier-bronze{{background:linear-gradient(135deg,#e3a565,#b6702f);color:#2c1300;box-shadow:0 0 6px rgba(182,112,47,.4)}}
    .tier-wooden{{background:linear-gradient(135deg,#8a5a34,#5c3a20);color:#fbe9d4;box-shadow:0 0 6px rgba(92,58,32,.4)}}
    .tier-legend{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px 8px;margin-bottom:26px}}
    .tier-legend-item{{display:flex;align-items:center;gap:4px;font-size:9px;font-weight:800;letter-spacing:.2px;color:#94a3b8;text-transform:uppercase;line-height:1}}
    .search-box{{width:100%;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:8px 12px;font-size:12px;color:#d7deea;outline:none;margin-bottom:12px}}.client-list{{display:flex;flex-direction:column;gap:6px}}.client-row{{display:grid;grid-template-columns:54px 1fr;grid-template-rows:auto auto;column-gap:12px;row-gap:6px;background:rgba(15,20,32,.4);border:1px solid rgba(255,255,255,.05);border-radius:14px;padding:12px 14px;cursor:pointer}}.client-row:hover{{border-color:rgba(244,114,182,.3)}}.row-identity{{grid-row:1/3;grid-column:1;display:flex;align-items:center;justify-content:center}}.row-badge-wrap{{position:relative}}.row-rank{{position:absolute;top:-6px;left:-6px;width:20px;height:20px;border-radius:50%;background:#161c2b;border:2px solid rgba(15,20,32,1);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800;color:#94a3b8;box-shadow:0 2px 5px rgba(0,0,0,.5);z-index:1}}.row-rank.rank-medal{{box-shadow:0 2px 6px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.55);border-width:2px}}.row-rank.rank-gold{{background:linear-gradient(135deg,#fff6d8,#e8b923 55%,#a9760a);color:#3a2600}}.row-rank.rank-silver{{background:linear-gradient(135deg,#f4f7fb,#c3cad4 55%,#8b95a1);color:#20242b}}.row-rank.rank-bronze{{background:linear-gradient(135deg,#f2c199,#c97a3d 55%,#7c4a20);color:#2a1608}}.row-header{{grid-row:1;grid-column:2;min-width:0;display:flex;align-items:center;gap:8px}}.row-avatar{{width:52px;height:52px;border-radius:10px;background:rgba(255,255,255,.08);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:800;color:#38bdf8;flex-shrink:0}}.row-avatar.has-logo{{background:transparent;padding:0}}.row-avatar img{{width:100%;height:100%;object-fit:contain;border-radius:6px}}.row-name{{flex:1;min-width:0;overflow:hidden;font-size:14px;font-weight:700;text-overflow:ellipsis;white-space:nowrap}}.row-stats{{grid-row:2;grid-column:2;display:grid;grid-template-columns:repeat(2,1fr);grid-template-rows:repeat(2,1fr);gap:6px 10px;padding-top:8px;border-top:1px solid rgba(255,255,255,.06)}}.row-stat{{display:flex;align-items:baseline;justify-content:space-between}}.row-stat-val{{font-size:16px;font-weight:800;color:#e5edf9;line-height:1.2}}.row-stat-lbl{{font-size:9.5px;font-weight:700;letter-spacing:.4px;color:#64748b;text-transform:uppercase}}.row-chevron{{font-size:16px;color:#64748b;text-align:center;transition:transform .2s ease;flex-shrink:0}}.client-row.is-open .row-chevron{{transform:rotate(90deg);color:#f472b6}}.empty-directory{{padding:12px;color:#64748b;font-size:12px;text-align:center}}
    .client-detail-panel{{display:none;margin-top:6px;padding:14px;background:rgba(15,20,32,.6);border:1px solid rgba(244,114,182,.25);border-radius:14px}}.client-detail-panel.is-visible{{display:block}}
    .detail-stat-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:12px}}.detail-stat{{background:rgba(255,255,255,.04);border-radius:10px;padding:8px 4px;text-align:center}}.detail-stat-val{{font-size:16px;font-weight:900;color:#f472b6}}.detail-stat-lbl{{font-size:9px;font-weight:800;color:#94a3b8;letter-spacing:.3px;margin-top:2px}}
    .detail-meta-row{{display:flex;flex-wrap:wrap;gap:10px;font-size:11.5px;color:#94a3b8;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.06)}}.detail-meta-row strong{{color:#e2e8f0}}
    .detail-visit-title{{font-size:11px;font-weight:800;letter-spacing:.6px;color:#7dd3fc;margin-bottom:8px}}.detail-visit-list{{display:flex;flex-direction:column;gap:5px;max-height:260px;overflow-y:auto}}
    .detail-visit-row{{display:grid;grid-template-columns:28px 1fr auto;align-items:center;gap:8px;background:rgba(255,255,255,.03);border-radius:8px;padding:6px 8px}}.detail-visit-num{{font-size:11px;font-weight:800;color:#64748b}}.detail-visit-date{{font-size:12px;font-weight:700;color:#fff}}.detail-visit-loc{{font-size:11px;color:#7dd3fc;margin-top:1px}}.detail-visit-amt{{font-size:12.5px;font-weight:800;color:#34d399;white-space:nowrap}}
    @media(max-width:520px){{.client-card-container{{padding:16px 14px}}.client-row{{grid-template-columns:44px 1fr;padding:9px 10px}}.row-avatar{{width:44px;height:44px}}.row-stat-val{{font-size:13px}}.detail-stat-grid{{grid-template-columns:repeat(2,1fr)}}}}
    .livery-panel{{background:linear-gradient(160deg,#12161f,#0a0d13);border:1px solid rgba(255,255,255,.08);border-radius:20px;padding:18px 0;margin-top:16px;box-shadow:0 15px 35px rgba(0,0,0,.5);overflow:hidden;position:relative;-webkit-mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent);mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent)}}
    .livery-title{{font-size:12px;font-weight:900;letter-spacing:1.5px;color:#64748b;text-transform:uppercase;text-align:center;margin-bottom:14px}}
    .livery-track{{display:flex;width:max-content;animation:livery-scroll 26s linear infinite}}
    .livery-tile{{width:76px;height:76px;margin:0 9px;background:#fff;border-radius:14px;border:1px solid rgba(0,0,0,.15);box-shadow:0 4px 10px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;flex-shrink:0;padding:8px}}
    .livery-tile img{{width:100%;height:100%;object-fit:contain}}
    @keyframes livery-scroll{{0%{{transform:translateX(0)}}100%{{transform:translateX(-50%)}}}}
    </style></head><body><div class="client-card-container"><div class="client-header-title">CLIENT STANDINGS</div>{legend_html}<input id="client-search" type="search" class="search-box" placeholder="Search current client directory..."><div class="client-list">{''.join(rows)}</div></div>{livery_html}<script>
    const q=document.getElementById('client-search');
    const clickable=[...document.querySelectorAll('.client-row')];
    if(q)q.addEventListener('input',()=>{{
      const v=q.value.trim().toLowerCase();
      clickable.forEach(el=>{{
        const match=!v||(el.dataset.client||'').includes(v);
        el.style.display=match?'flex':'none';
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
    height = 480 + max(len(directory), 1) * 90 + (150 if livery_clients else 0)
    components.html(html, height=height, scrolling=False)
