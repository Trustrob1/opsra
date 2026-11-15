"""
app/services/webchat_embed_service.py
-------------------------------------
WEBCHAT-EMBED-1 - the chat as a bubble on other websites (widget.js), and which websites may show it.

allowed_domains is a list of website names the business owns, e.g. ["royalrest.com", "shop.example.ng"].
  * an entry matches that site and every sub-domain of it (royalrest.com also covers www.royalrest.com)
  * an empty list means any website may show the bubble
  * localhost is only allowed when it is listed
The browser tells the server which site is asking (the Origin header on the widget's own request; the page the
visitor is on is passed to the chat frame by widget.js). This keeps the bubble off sites that copied the code. It is
not a lock against someone determined: the chat link itself is public by design.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

MAX_DOMAINS = 20
_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")


def clean_host(raw: Optional[str]) -> str:
    """'https://www.Example.com/shop?x=1' -> 'www.example.com'; '' when it is not a usable website name."""
    v = str(raw or "").strip().lower()
    if not v:
        return ""
    if "://" not in v:
        v = "http://" + v
    try:
        u = urlparse(v)
        u.port                                  # raises on junk such as "javascript:alert(1)"
    except ValueError:
        return ""
    host = (u.hostname or "").strip(".")
    return host if host and _HOST_RE.match(host) else ""


def sanitise_domains(raw) -> list[str]:
    if isinstance(raw, str):
        raw = re.split(r"[\s,;]+", raw)
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        h = clean_host(item)
        if h and h not in out:
            out.append(h)
        if len(out) >= MAX_DOMAINS:
            break
    return out


def origin_allowed(allowed: list, origin: Optional[str]) -> bool:
    """True when no list is set, or the website (an Origin or a page address) is on it."""
    domains = sanitise_domains(allowed or [])
    if not domains:
        return True
    host = clean_host(origin)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


# ── WEBCHAT-EMBED-2: "is it installed?" and the install email ──────────────────────────────────────────

import time

_SEEN_WRITTEN: dict = {}
SEEN_EVERY_S = 1800


def record_seen(db, org_id: str, origin: Optional[str], own_hosts: tuple = ()) -> None:
    """Remember that this website loaded the bubble. One write per business+host per 30 minutes per worker. Never raises."""
    try:
        host = clean_host(origin)
        if not host or host in own_hosts:
            return
        k = (org_id, host)
        now = time.monotonic()
        if _SEEN_WRITTEN.get(k, 0) > now - SEEN_EVERY_S:
            return
        if len(_SEEN_WRITTEN) > 2000:
            _SEEN_WRITTEN.clear()
        _SEEN_WRITTEN[k] = now
        from datetime import datetime, timezone
        iso = datetime.now(timezone.utc).isoformat()
        db.table("webchat_widget_seen").upsert({"org_id": org_id, "host": host, "last_seen_at": iso},
                                               on_conflict="org_id,host").execute()
    except Exception:
        pass


def seen_list(db, org_id: str, limit: int = 10) -> list:
    try:
        rows = (db.table("webchat_widget_seen").select("host, first_seen_at, last_seen_at").eq("org_id", org_id)
                .order("last_seen_at", desc=True).limit(limit).execute().data) or []
        return rows
    except Exception:
        return []


def script_tag(base: str, key: str) -> str:
    return f'<script src="{base.rstrip("/")}/widget.js" data-key="{key}" async></script>'


def install_email(business: str, sender_note: str, tag: str, chat_link: str) -> tuple[str, str]:
    """(subject, plain-text body) for a web person who will add the chat bubble."""
    note = f"\nA note from {business}:\n{sender_note.strip()[:500]}\n" if (sender_note or "").strip() else ""
    subject = f"Please add the {business} chat bubble to our website"
    body = (
        f"Hello,\n\n{business} would like a chat bubble on its website, so visitors can message the team. "
        "It is one line of code and takes about two minutes.\n"
        f"{note}\n"
        "WHAT TO DO\n"
        "Paste this line on every page, just before the closing </body> tag. In most website builders this is called "
        "\"custom code\", \"header and footer code\" or \"code injection\" (choose the footer / end of body, all pages):\n\n"
        f"{tag}\n\n"
        "WHAT YOU WILL SEE\n"
        "A round chat button appears in the bottom corner. It opens the chat. Nothing else on the website changes, and "
        "nothing needs installing or paying for on your side.\n\n"
        "HOW TO CHECK\n"
        f"Open the website after saving, you should see the bubble. You can also try the chat directly here: {chat_link}\n\n"
        "Platform notes: WordPress (use a header/footer code plugin such as WPCode), Wix (Settings, Custom code, body end), "
        "Shopify (theme.liquid, before </body>), Squarespace (Settings, Code injection, Footer), Webflow (Site settings, "
        "Custom code, Footer), Google Tag Manager (new Custom HTML tag, trigger: All pages).\n\n"
        f"Sent from Opsra on behalf of {business}.\n"
    )
    return subject, body
