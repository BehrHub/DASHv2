"""Region card for the Main page - replaces the old Territory &
Jurisdictions panel inside render_dashboard()'s iframe.

Brought over from the Main V2 preview: ◀ ▶ arrows cycle All regions ->
MD -> VA -> DC -> PA -> WV, and the card shows the outlined region code,
its name, its event count, the NEXT UP chip, and Cities / Days on the
right. Numbers come from the same cached V2 builder (services/v2_data.py)
that already feeds the V2 tabs, so nothing is computed twice.

build_region_panel() returns a self-contained HTML string (scoped
"rg-" classes + its own small script), or raises; ui.py catches any
error and falls back to the original Territory panel, so a problem here
can never blank out the Main page.
"""
from __future__ import annotations

import json
from html import escape

import pandas as pd

from components.v2_pages import _cached_payload, _frame_fingerprint
from services.tz import eastern_today_naive

_CSS = """
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:ital,wght@0,600;0,700;1,700&display=swap" rel="stylesheet">
<style>
.rg-nav{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.rg-btn{width:48px;height:48px;border-radius:50%;border:1px solid rgba(255,255,255,.16);background:rgba(15,26,56,.9);color:#fff;font-size:17px;cursor:pointer;-webkit-tap-highlight-color:transparent}
.rg-btn:active{transform:scale(.94)}
.rg-btn:focus-visible{outline:2px solid #fff;outline-offset:2px}
.rg-count{font-family:'Barlow Condensed',Arial Narrow,sans-serif;font-weight:600;font-size:22px;letter-spacing:.08em;color:#dbe4ff;white-space:nowrap;font-variant-numeric:tabular-nums}
.rg-name{font-family:'Barlow Condensed',Arial Narrow,sans-serif;font-weight:700;font-size:24px;letter-spacing:.06em;text-transform:uppercase;color:#fff}
.rg-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:center;border-radius:16px;padding:18px 18px 20px;
  background:radial-gradient(110% 90% at 90% 105%,color-mix(in srgb,var(--rc) 22%,transparent),transparent 62%),rgba(15,26,56,.55);border:1px solid rgba(255,255,255,.1)}
.rg-code{font-family:'Barlow Condensed',Arial Narrow,sans-serif;font-style:italic;font-weight:700;font-size:96px;line-height:.85;color:transparent;-webkit-text-stroke:2px var(--rc);letter-spacing:.01em}
.rg-full{font-family:'Barlow Condensed',Arial Narrow,sans-serif;font-weight:700;font-size:26px;letter-spacing:.06em;text-transform:uppercase;color:#fff;margin-top:10px}
.rg-ev{display:flex;align-items:baseline;gap:10px;margin-top:6px}
.rg-ev b{font-family:'Barlow Condensed',Arial Narrow,sans-serif;font-weight:700;font-size:64px;line-height:1;color:#fff;font-variant-numeric:tabular-nums}
.rg-ev span{font-size:13px;letter-spacing:.16em;font-weight:700;color:#dbe4ff}
.rg-next{display:inline-block;margin-top:12px;font-size:13px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;color:#fff;padding:7px 14px;border-radius:12px;
  border:1px solid color-mix(in srgb,var(--rc) 50%,transparent);background:color-mix(in srgb,var(--rc) 14%,transparent);max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rg-side{display:flex;flex-direction:column;gap:18px;align-items:flex-end;text-align:right;padding-left:6px}
.rg-stat b{display:block;font-family:'Barlow Condensed',Arial Narrow,sans-serif;font-weight:700;font-size:44px;line-height:1;color:#fff;font-variant-numeric:tabular-nums}
.rg-stat span{display:block;margin-top:4px;font-size:13px;letter-spacing:.14em;font-weight:700;color:#dbe4ff}
.rg-fade{transition:opacity .18s ease}
@media(max-width:520px){.rg-code{font-size:78px}.rg-ev b{font-size:54px}.rg-stat b{font-size:38px}.rg-name{font-size:21px}.rg-card{padding:16px 14px 18px}}
</style>
"""


def build_region_panel(timeline: pd.DataFrame, pipeline: pd.DataFrame | None, next_label: str) -> str:
    payload = _cached_payload(
        _frame_fingerprint(timeline) + "|" + _frame_fingerprint(pipeline),
        pd.Timestamp(eastern_today_naive()).strftime("%Y-%m-%d"),
        False,
        timeline,
        pipeline,
    )
    regions = json.loads(payload)["regions"]
    if not regions:
        raise ValueError("no regions")
    slim = [
        {"code": r["code"], "name": r["name"], "color": r["color"],
         "events": r["events"], "cities": r["cities"], "days": r["days"]}
        for r in regions
    ]
    blob = json.dumps(slim, separators=(",", ":")).replace("</", "<\\/")
    first = slim[0]
    return (
        _CSS
        + '<div class="frosted-panel panel" id="territoryPanel" style="--rc:' + escape(first["color"]) + '">'
        + '<div class="rg-nav">'
        + '<button class="rg-btn" id="rgPrev" type="button" aria-label="Previous region">&#9664;</button>'
        + '<button class="rg-btn" id="rgNext" type="button" aria-label="Next region">&#9654;</button>'
        + '<span class="rg-count" id="rgCount">01 / ' + f"{len(slim):02d}" + '</span>'
        + '<span class="rg-name" id="rgName">' + escape(first["name"]) + '</span>'
        + '</div>'
        + '<div class="rg-card rg-fade" id="rgCard">'
        + '<div><div class="rg-code" id="rgCode">' + escape(first["code"]) + '</div>'
        + '<div class="rg-full" id="rgFull">' + escape(first["name"]) + '</div>'
        + '<div class="rg-ev"><b id="rgEv">' + str(first["events"]) + '</b><span>EVENTS</span></div>'
        + '<div class="rg-next">NEXT UP &middot; ' + next_label + '</div></div>'
        + '<div class="rg-side">'
        + '<div class="rg-stat"><b id="rgCities">' + str(first["cities"]) + '</b><span>CITIES</span></div>'
        + '<div class="rg-stat"><b id="rgDays">' + str(first["days"]) + '</b><span>DAYS</span></div>'
        + '</div></div></div>'
        + '<script>(function(){var R=' + blob + ',i=0;'
        + 'function $(id){return document.getElementById(id);}'
        + 'function pad(n){return (n<10?"0":"")+n;}'
        + 'function show(k){i=(k+R.length)%R.length;var r=R[i],card=$("rgCard");card.style.opacity="0";'
        + 'setTimeout(function(){$("territoryPanel").style.setProperty("--rc",r.color);'
        + '$("rgCount").textContent=pad(i+1)+" / "+pad(R.length);$("rgName").textContent=r.name;'
        + '$("rgCode").textContent=r.code;$("rgFull").textContent=r.name;$("rgEv").textContent=r.events;'
        + '$("rgCities").textContent=r.cities;$("rgDays").textContent=r.days;card.style.opacity="1";},150);}'
        + '$("rgPrev").addEventListener("click",function(){show(i-1);});'
        + '$("rgNext").addEventListener("click",function(){show(i+1);});'
        + '})();</script>'
    )
