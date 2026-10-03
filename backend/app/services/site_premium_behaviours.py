"""
app/services/site_premium_behaviours.py
----------------------------------------
SITE-PREMIUM P2c - the Opsra-owned behaviour library (spec section 20).

Premium skeletons never contain script. Instead the designer marks an element with
data-behaviour="reveal" (or several, space separated) and the RENDERER adds one small script that
Opsra wrote and owns, plus the CSS those behaviours need. The script is the same text for every
site, so it is reviewed once and pinned in the page with a Content-Security-Policy hash: the browser
will run this script and nothing else. A page that uses no behaviour gets "script-src 'none'".

Rules every behaviour follows:
  * Content is fully visible and usable without JavaScript (the hidden start state exists only
    after the script has switched on, via the html.b-on class).
  * Nothing runs under prefers-reduced-motion: reduce.
  * Only the transform-family properties (translate, scale, rotate) and opacity are animated, using
    the individual CSS properties so a designer's own transform on the element is never overwritten
    (tilt is the exception and says so in its description).
  * No network calls, no storage, no reading of forms, no navigation.

Pure module, no I/O.
"""
from __future__ import annotations

import base64
import hashlib
import re

# name -> what it does (also the text the build prompt shows the designer)
BEHAVIOURS: dict[str, str] = {
    "reveal": "the element fades and slides up (22px) the first time it scrolls into view",
    "stagger": "the element's direct children fade and slide up one after another when it scrolls into view",
    "count": "a number counts up from 0 when it scrolls into view; put it on a leaf element whose text is the number, such as <span>120+</span>",
    "scrolled": "adds the class is-scrolled to the element once the page has scrolled 24px; use it on a sticky nav to shrink or add a background",
    "parallax": "the element drifts up to 24px as the page scrolls; put it on an image inside an overflow-hidden frame and scale the image to 1.08 so edges never show",
    "tilt": "the element tilts up to 6 degrees towards the pointer on desktop; do not set your own transform on it; use on cards",
    "progress": "an empty element becomes a 3px reading-progress bar fixed to the top of the page, in the accent colour",
}
MAX_BEHAVIOUR_USES = 40          # elements on one page carrying any behaviour (static check warns above this)

_TOKEN_RE = re.compile(r"^[a-z]{3,12}$")
_ATTR_RE = re.compile(r'data-behaviour="([^"]*)"')


def clean_behaviour_value(value: str) -> str | None:
    """Keep only known behaviour names (de-duplicated, in order). None when nothing valid is left."""
    seen: list[str] = []
    for tok in (value or "").split():
        if _TOKEN_RE.match(tok) and tok in BEHAVIOURS and tok not in seen:
            seen.append(tok)
    return " ".join(seen) or None


def used_behaviours(html: str) -> list[str]:
    """Behaviour names present in rendered/sanitised HTML, in library order."""
    found: set[str] = set()
    for m in _ATTR_RE.finditer(html or ""):
        found.update(t for t in m.group(1).split() if t in BEHAVIOURS)
    return [b for b in BEHAVIOURS if b in found]


def count_uses(html: str) -> int:
    return len(_ATTR_RE.findall(html or ""))


BEHAVIOUR_CSS = (
    "html.b-on{--b-ease:cubic-bezier(.22,1,.36,1)}"
    'html.b-on [data-behaviour~="reveal"]{opacity:0;translate:0 22px;'
    "transition:opacity .9s var(--b-ease),translate .9s var(--b-ease)}"
    'html.b-on [data-behaviour~="reveal"].b-in{opacity:1;translate:none}'
    'html.b-on [data-behaviour~="stagger"]>*{opacity:0;translate:0 18px;'
    "transition:opacity .8s var(--b-ease) calc(var(--b-i,0)*90ms),translate .8s var(--b-ease) calc(var(--b-i,0)*90ms)}"
    'html.b-on [data-behaviour~="stagger"].b-in>*{opacity:1;translate:none}'
    '[data-behaviour~="count"]{font-variant-numeric:tabular-nums}'
    '[data-behaviour~="parallax"]{will-change:translate}'
    '[data-behaviour~="tilt"]{transform:perspective(900px) rotateX(var(--b-rx,0deg)) rotateY(var(--b-ry,0deg));'
    "transition:transform .4s var(--b-ease,ease-out)}"
    '[data-behaviour~="progress"]{position:fixed;top:0;left:0;right:0;height:3px;background:var(--accent);'
    "transform-origin:0 50%;scale:0 1;z-index:50;pointer-events:none}"
)

BEHAVIOUR_JS = (
    "(function(){var d=document,h=d.documentElement;"
    'if(window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches)return;'
    'var all=function(n){return[].slice.call(d.querySelectorAll(\'[data-behaviour~="\'+n+\'"]\'))};'
    'var open=function(){all("reveal").concat(all("stagger")).forEach(function(e){e.classList.add("b-in")})};'
    'try{h.classList.add("b-on");var io="IntersectionObserver" in window;'
    "function seen(els,fn,t){if(!io){els.forEach(fn);return}"
    "var o=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){o.unobserve(e.target);fn(e.target)}})},"
    '{threshold:t||.15,rootMargin:"0px 0px -6% 0px"});els.forEach(function(el){o.observe(el)})}'
    'seen(all("reveal"),function(el){el.classList.add("b-in")});'
    'all("stagger").forEach(function(p){[].slice.call(p.children).forEach(function(c,i){c.style.setProperty("--b-i",Math.min(i,12))})});'
    'seen(all("stagger"),function(el){el.classList.add("b-in")});'
    'seen(all("count"),function(el){if(el.children.length)return;var t=el.textContent,m=t.match(/\\d[\\d,]*(\\.\\d+)?/);if(!m)return;'
    'var raw=m[0],n=parseFloat(raw.replace(/,/g,"")),dec=(raw.split(".")[1]||"").length,comma=raw.indexOf(",")>-1;'
    "if(!isFinite(n)||n<=0)return;var pre=t.slice(0,m.index),post=t.slice(m.index+raw.length),t0=null;"
    "function fmt(v){var s=v.toFixed(dec);if(comma){var p=s.split(\".\");p[0]=p[0].replace(/\\B(?=(\\d{3})+(?!\\d))/g,\",\");s=p.join(\".\")}return s}"
    "function step(ts){if(t0===null)t0=ts;var p=Math.min((ts-t0)/1400,1),e=1-Math.pow(1-p,3);"
    "el.textContent=pre+fmt(n*e)+post;if(p<1)requestAnimationFrame(step)}requestAnimationFrame(step)},.4);"
    'var sc=all("scrolled"),par=all("parallax"),bar=all("progress"),tick=false,y=function(){return window.pageYOffset||h.scrollTop};'
    "function frame(){tick=false;var vh=innerHeight||1;"
    'sc.forEach(function(el){el.classList.toggle("is-scrolled",y()>24)});'
    "par.forEach(function(el){var r=el.getBoundingClientRect();if(r.bottom<0||r.top>vh)return;"
    'var p=Math.max(-1,Math.min(1,(r.top+r.height/2-vh/2)/vh));el.style.translate="0 "+(p*-24).toFixed(1)+"px"});'
    "if(bar.length){var m=h.scrollHeight-vh,s=m>0?Math.min(1,y()/m):0;"
    'bar.forEach(function(el){el.style.scale=s.toFixed(4)+" 1"})}}'
    "function req(){if(!tick){tick=true;requestAnimationFrame(frame)}}"
    'if(sc.length||par.length||bar.length){addEventListener("scroll",req,{passive:true});addEventListener("resize",req);frame()}'
    'if(matchMedia("(hover:hover) and (pointer:fine)").matches)all("tilt").forEach(function(el){'
    'el.addEventListener("pointermove",function(e){var r=el.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,v=(e.clientY-r.top)/r.height-.5;'
    'el.style.setProperty("--b-ry",(x*6).toFixed(2)+"deg");el.style.setProperty("--b-rx",(-v*6).toFixed(2)+"deg")});'
    'el.addEventListener("pointerleave",function(){el.style.setProperty("--b-ry","0deg");el.style.setProperty("--b-rx","0deg")})})'
    "}catch(e){open()}})();"
)


def script_hash() -> str:
    """CSP source for the library script: 'sha256-...' of the exact text placed in the page."""
    digest = hashlib.sha256(BEHAVIOUR_JS.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def csp_meta(used: list[str]) -> str:
    """The Content-Security-Policy meta tag. Only script-src is restricted, so fonts, images and
    links behave exactly as before; the point is that no script except ours can ever run."""
    src = script_hash() if used else "'none'"
    return f'<meta http-equiv="Content-Security-Policy" content="script-src {src}; object-src \'none\'">'


def head_css(used: list[str]) -> str:
    return BEHAVIOUR_CSS if used else ""


def body_script(used: list[str]) -> str:
    return f"<script>{BEHAVIOUR_JS}</script>" if used else ""
