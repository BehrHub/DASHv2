"""Shared back-to-top rocket for the long Streamlit pages (Main, Clients,
Ledger). One call at the very bottom of a page's render function:

    from components.rocket import render_back_to_top_rocket
    render_back_to_top_rocket()

Why this is a separate file from the STAT+ rocket: STAT+ is one big
components.html page, so its rocket lives inside that iframe. These pages
are normal st.markdown pages, so this version renders only the small
glowing button in an iframe and builds the rocket in the PARENT document
(position: fixed) - the same window.parent technique journey.py already
uses for the race car. Nothing else on the page is touched.

Art: assets/icons/stats-rocket.png (the Genmoji cutout already used by
STAT+). If it is missing, the plain 🚀 emoji is used at the same size.
"""
from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path

import streamlit.components.v1 as components

ROCKET_BASE_PX_PER_SEC = 145   # same base as journey.py's car
DEFAULT_SPEED = 3.0            # multiplier; STAT+ uses 5.0 (it is the longest page)
IFRAME_HEIGHT = 150


@lru_cache(maxsize=1)
def _rocket_data_uri() -> str | None:
    path = Path(__file__).resolve().parent.parent / "assets" / "icons" / "stats-rocket.png"
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:transparent;overflow:hidden}
.wrap{display:flex;flex-direction:column;align-items:center;gap:10px;padding:22px 0 6px}
.btn{width:72px;height:72px;border-radius:50%;font-size:32px;line-height:1;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#fff;
  background:radial-gradient(circle at 50% 38%,rgba(125,211,252,.28),rgba(15,23,42,.95) 70%);border:2px solid rgba(125,211,252,.7);
  animation:glow 2.2s ease-out infinite;-webkit-tap-highlight-color:transparent;transition:transform .25s ease,opacity .25s ease;font-family:inherit}
.btn:active{transform:scale(.93)}
.btn:focus-visible{outline:2px solid #fff;outline-offset:4px}
.btn.launched{opacity:0;transform:scale(.4);pointer-events:none}
.lbl{font-family:"Bebas Neue",Impact,sans-serif;font-size:17px;letter-spacing:1.4px;color:#7dd3fc}
@keyframes glow{
  0%{box-shadow:0 0 0 0 rgba(125,211,252,.55),0 0 18px rgba(125,211,252,.35)}
  70%{box-shadow:0 0 0 18px rgba(125,211,252,0),0 0 26px rgba(125,211,252,.5)}
  100%{box-shadow:0 0 0 0 rgba(125,211,252,0),0 0 18px rgba(125,211,252,.35)}}
@media (prefers-reduced-motion:reduce){.btn{animation:none}}
</style></head><body>
<div class="wrap"><button id="btn" class="btn" type="button" aria-label="Back to top">&#x1F51D;</button><div class="lbl">Back to top</div></div>
<script>
(function(){
  var SPEED = __SPEED__, ART = __ART__, H = 96, TRAIL = 240;
  var btn = document.getElementById("btn");
  var pwin, pdoc, frame;
  try { pwin = window.parent; pdoc = pwin.document; frame = window.frameElement; } catch(e) { return; }
  if(!pdoc || !frame) return;

  // Clear anything a previous run (or a rerun mid-flight) left behind.
  ["bt-rocket","bt-trail"].forEach(function(id){ var o = pdoc.getElementById(id); if(o) o.remove(); });
  if(!pdoc.getElementById("bt-rocket-style")){
    var st = pdoc.createElement("style"); st.id = "bt-rocket-style";
    st.textContent =
      "#bt-rocket{position:fixed;width:96px;height:96px;z-index:999990;pointer-events:none;will-change:transform}"
     +"#bt-rocket .art{display:block;width:100%;height:100%;object-fit:contain;transform:rotate(-45deg);filter:drop-shadow(0 0 10px rgba(255,150,60,.55))}"
     +"#bt-rocket .emoji{font-size:60px;line-height:96px;text-align:center}"
     +"#bt-rocket.igniting .art{animation:btShake .07s linear infinite}"
     +"#bt-rocket.flying .art{animation:btFlicker .12s ease-in-out infinite alternate}"
     +"@keyframes btShake{0%{transform:rotate(-45deg) translate(1.5px,0)}50%{transform:rotate(-45deg) translate(-1.5px,1px)}100%{transform:rotate(-45deg) translate(0,-1px)}}"
     +"@keyframes btFlicker{from{filter:drop-shadow(0 0 8px rgba(255,150,60,.45))}to{filter:drop-shadow(0 0 16px rgba(255,190,80,.8))}}"
     +"#bt-trail{position:fixed;width:10px;height:0;z-index:999989;pointer-events:none;border-radius:6px;filter:blur(3px);"
     +"background:linear-gradient(to bottom,rgba(255,210,120,.85),rgba(255,120,40,.45) 35%,rgba(255,80,30,0))}";
    pdoc.head.appendChild(st);
  }

  function scroller(){ return pdoc.querySelector('[data-testid="stMain"]') || pdoc.scrollingElement || pdoc.documentElement; }
  function isDoc(s){ return s === pdoc.scrollingElement || s === pdoc.documentElement || s === pdoc.body; }
  function getTop(s){ return isDoc(s) ? (pwin.scrollY || pdoc.documentElement.scrollTop || 0) : s.scrollTop; }
  function setTop(s,t){ if(isDoc(s)) pwin.scrollTo(0,t); else s.scrollTop = t; }
  function viewH(s){ return (!isDoc(s) && s.clientHeight) || pwin.innerHeight; }

  var flying = false, raf = null, rocket = null, trail = null, aborts = [];
  function cleanup(){
    flying = false;
    if(raf) pwin.clearTimeout(raf);
    if(rocket){ rocket.remove(); rocket = null; }
    if(trail){ trail.remove(); trail = null; }
    aborts.forEach(function(w){ try{ w.removeEventListener("wheel", abort); w.removeEventListener("touchstart", abort); }catch(e){} });
    aborts = [];
    pwin.setTimeout(function(){ btn.classList.remove("launched"); }, 600);
  }
  function abort(){ if(flying) cleanup(); }
  pwin.addEventListener("pagehide", function(){ cleanup(); });
  window.addEventListener("pagehide", function(){ cleanup(); });

  btn.addEventListener("click", function(){
    if(flying) return;
    var s = scroller();
    if(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches){
      try{ s.scrollTo({top:0, behavior:"smooth"}); }catch(e){ setTop(s,0); }
      return;
    }
    flying = true;
    var fr = frame.getBoundingClientRect(), br = btn.getBoundingClientRect();
    var sx = fr.left + br.left + br.width/2;
    var y = getTop(s) + fr.top + br.top + br.height/2;     // rocket centre, in scroller content space

    rocket = pdoc.createElement("div"); rocket.id = "bt-rocket"; rocket.className = "igniting";
    rocket.innerHTML = ART ? '<img class="art" alt="" src="'+ART+'">' : '<div class="art emoji">\\uD83D\\uDE80</div>';
    trail = pdoc.createElement("div"); trail.id = "bt-trail";
    pdoc.body.appendChild(trail); pdoc.body.appendChild(rocket);
    rocket.style.left = (sx - H/2) + "px"; trail.style.left = (sx - 5) + "px";
    function place(){
      var sy = y - getTop(s);
      rocket.style.top = (sy - H/2) + "px";
      trail.style.top = (sy + H*0.28) + "px";
    }
    place();
    btn.classList.add("launched");

    pwin.setTimeout(function(){
      if(!flying) return;
      rocket.className = "flying";
      [window, pwin].forEach(function(w){ try{ w.addEventListener("wheel", abort, {passive:true}); w.addEventListener("touchstart", abort, {passive:true}); aborts.push(w);}catch(e){} });
      var start = null, last = null;
      // Drive the loop from the PARENT window's timers (same as journey.py's car),
      // not requestAnimationFrame inside this small iframe: Safari pauses rAF in an
      // iframe once it scrolls out of view, which froze the rocket mid-flight.
      function tick(){ raf = pwin.setTimeout(function(){ step(Date.now()); }, 16); }
      function step(now){
        if(!flying) return;
        if(start === null){ start = last = now; }
        var dt = Math.min(48, now - last)/1000; last = now;
        var ramp = Math.min(1, (now - start)/700);
        y -= SPEED * (0.25 + 0.75*ramp*ramp) * dt;
        // follow: keep the rocket ~60% down the screen until the page bottoms out at the top
        var want = y - viewH(s)*0.6;
        if(want < getTop(s)) setTop(s, Math.max(0, want));
        place();
        trail.style.height = Math.min(TRAIL, (now - start)*0.5) + "px";
        if(y - getTop(s) < -H*2){ cleanup(); return; }
        tick();
      }
      tick();
    }, 420);
  });
})();
</script></body></html>"""


def render_back_to_top_rocket(speed: float = DEFAULT_SPEED) -> None:
    """Render the glowing 🔝 button; tapping it launches the rocket to the top
    of the current page. Call once, as the last thing a page renders."""
    html = (
        _TEMPLATE
        .replace("__SPEED__", repr(float(ROCKET_BASE_PX_PER_SEC * speed)))
        .replace("__ART__", json.dumps(_rocket_data_uri()))
    )
    components.html(html, height=IFRAME_HEIGHT, scrolling=False)
