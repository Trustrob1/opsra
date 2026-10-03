"""
tests/unit/premium_gen_fixtures.py - shared fixtures for the SITE-PREMIUM P2 tests (not a test module).
A skeleton that passes EVERY strict check, the art direction that matches its palette, and a scripted fake Claude.
"""
from __future__ import annotations

import json

from tests.unit.test_site_premium_render import CONTENT

ART = {
    "concept": "A tailor's chalk line that guides the eye down the page",
    "second_read": "The footer hem is stitched with a dashed line",
    "palette_rationale": "Cotton and indigo thread: porcelain ground, ink text, cobalt accent (blue family)",
    "mode": "light", "accent_family": "blue",
    "accent_hex": "#2F4BFF", "bg_hex": "#F5F6F4", "ink_hex": "#0E1B2C",
    "hero_scale": "giant", "headline_font": "Outfit", "body_font": "Hanken Grotesk",
    "signature_moment": "scroll_reveal_words",
    "sections": [
        {"name": "hero", "layout": "fullbleed", "background": "base"},
        {"name": "items", "layout": "grid", "background": "surface"},
        {"name": "about", "layout": "quote", "background": "base"},
        {"name": "closing", "layout": "stack", "background": "deep"},
    ],
}

CSS = """
:root{--accent:#2F4BFF;--accent-ink:#F4F6FF;--bg:#F5F6F4;--ink:#0E1B2C;--surface:#E9ECEF;--deep:#0E1B2C;--muted:#4A5566;
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;--s8:64px}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font-body);line-height:1.6}
h1,h2,h3{font-family:var(--font-head);margin:0;text-wrap:balance;letter-spacing:-.02em;line-height:1}
[hidden]{display:none!important}
.wrap{padding-inline:clamp(20px,5vw,64px);max-width:1280px;margin-inline:auto}
.btn{display:inline-flex;min-height:48px;align-items:center;padding-inline:var(--s5);background:var(--accent);color:var(--accent-ink);
text-decoration:none;font-weight:700;white-space:nowrap}
.nav{display:flex;justify-content:space-between;align-items:center;min-height:64px;padding-inline:clamp(20px,5vw,64px)}
.hero{padding-block:clamp(48px,8vw,120px);overflow-x:clip}
.hero h1{font-size:clamp(2.75rem,11vw,7rem)}
.hero p{max-width:30rem;color:var(--muted)}
.items{background:var(--surface);padding-block:clamp(48px,7vw,96px)}
.grid{display:grid;gap:var(--s5);grid-template-columns:repeat(auto-fill,minmax(240px,1fr));list-style:none;padding:0}
.card img{width:100%;aspect-ratio:4/5;object-fit:cover;background:var(--surface)}
.about{padding-block:clamp(48px,7vw,96px);font-size:1.25rem}
.closing{background:var(--deep);color:var(--bg);padding-block:clamp(48px,7vw,96px)}
.wa{position:fixed;right:var(--s4);bottom:var(--s4);min-height:48px}
:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

SKELETON = """
<header data-section="nav" class="nav"><b data-slot="business.name"></b>
<a class="btn" data-slot-href="whatsapp">Order on WhatsApp</a></header>
<main>
<section class="hero" data-section="hero" data-layout="fullbleed"><div class="wrap">
<p data-role="eyebrow" data-if="business.city" data-slot="business.city"></p>
<h1 data-slot="hero.headline"></h1><p data-slot="hero.subhead"></p>
<img data-slot-img="hero.image" data-priority="high" alt="The shop"><a class="btn" data-slot-href="whatsapp">Start a chat</a></div></section>
<section class="items" data-section="items" data-layout="grid" id="shop"><div class="wrap"><h2>The collection</h2>
<ul class="grid"><li class="card" data-repeat="items"><img data-slot-img="image" alt="Item photo"><h3 data-slot="name"></h3>
<p data-if="desc" data-slot="desc"></p><span data-slot="price_ngn" data-format="price"></span>
<a class="btn" data-slot-href="whatsapp">Ask about this</a></li></ul></div></section>
<section class="about" data-section="about" data-layout="quote" data-if="about.owner"><div class="wrap">
<p data-repeat="about.body" data-slot="."></p><i data-slot="about.owner"></i></div></section>
<section class="closing" data-section="closing" data-layout="stack"><div class="wrap"><h2>Ready when you are</h2>
<a class="btn" data-slot-href="whatsapp">Message us on WhatsApp</a></div></section>
</main>
<footer data-section="footer"><div class="wrap"><a data-slot-href="instagram">Instagram</a><a data-slot-href="maps">Find us</a></div></footer>
<a class="btn wa" data-slot-href="whatsapp">WhatsApp</a>
"""


def good_build_reply() -> str:
    return f"<style>{CSS}</style>{SKELETON}"


def good_art_reply() -> str:
    return json.dumps(ART)


class ScriptedClaude:
    """A fake claude function: pops scripted replies in order and records every call."""

    def __init__(self, *replies, usage=(1000, 2000)):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.usage = usage

    def __call__(self, system, user, max_tokens, model):
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens, "model": model})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, self.usage[0], self.usage[1]


ARGS = dict(content=CONTENT, brief={"personality": "modern"}, niche="boutique", personality="modern", assets=[],
            assets_by_id={}, design_notes="", do_not_repeat=[], model="claude-sonnet-5-5")
