"""
app/services/site_chat_button.py
--------------------------------
WEBCHAT-SITE-1 - a "Chat with us" button on websites built in Opsra.

The site engine is script-free on purpose (no <script> in a page, strict security policies), so this is NOT the chat bubble
(widget.js). It is one plain link, styled inline, that opens the business's full-screen chat page in a new tab. Nothing runs
on the page, and no policy needs loosening.

  * the chat that opens is the web chat of the account the site belongs to (sites.org_id)
  * shown only on a site whose own switch is on (Sites > open the site > Chat button; off by default, so a business that
    builds sites for clients never puts its own chat on them), and only when the account's web chat is on and its plan allows it
  * the link is tagged ?s=site so the chat stats show these visitors
Pure string work plus one config lookup. Never raises: any problem leaves the page exactly as it was (S14).
"""
from __future__ import annotations

import logging
import re
from html import escape
from typing import Any, Optional

logger = logging.getLogger(__name__)

MARK = "data-opsra-chat-link"
_BODY_END = re.compile(r"</body\s*>", re.I)
_BRAND = re.compile(r"^#[0-9a-fA-F]{6}$")
_ICON = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
         'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex:none"><path d="M4 5.5h16v11H9.5L5 20v-3.5H4z"/></svg>')


def button_html(link: str, color: str = "#028090", side: str = "right", label: str = "Chat with us") -> str:
    c = color if _BRAND.match(color or "") else "#028090"
    pos = "left:16px" if side == "left" else "right:16px"
    style = (f"position:fixed;bottom:16px;{pos};z-index:2147483000;display:inline-flex;align-items:center;gap:8px;"
             f"min-height:48px;padding:0 20px;border-radius:999px;background:{c};color:#ffffff;text-decoration:none;"
             "font:600 16px/1 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;box-shadow:0 6px 20px rgba(20,34,43,.28)")
    return (f'<a {MARK} href="{escape(link, quote=True)}" target="_blank" rel="noopener" '
            f'aria-label="{escape(label, quote=True)} (opens in a new tab)" style="{style}">{_ICON}{escape(label)}</a>')


def inject(html: str, button: str) -> str:
    """Put the button just before the last </body>; at the end when the page has none. Once only."""
    if not button or not isinstance(html, str) or MARK in html:
        return html
    last = None
    for last in _BODY_END.finditer(html):
        pass
    if last:
        return html[:last.start()] + button + html[last.start():]
    return html + button


def account_chat(db: Any, org_id: str) -> Optional[dict]:
    """{'link','color','side'} when this account's web chat is on, set up and allowed by its plan, else None.
    (Whether a particular SITE shows the button is the site's own switch: see resolve.)"""
    try:
        from app.services import webchat_plan_service as plan
        from app.services import webchat_service as wc
        row = (db.table("webchat_keys").select("key").eq("org_id", org_id).eq("active", True).limit(1).execute().data or [None])[0]
        if not row:
            return None
        cfg = wc.get_config(db, org_id)
        if not cfg.get("enabled"):
            return None
        cfg = plan.apply(db, org_id, cfg)
        if cfg is None:
            return None
        return {"link": f"{wc.public_base()}/c/{row['key']}?s=site", "color": cfg.get("brand_color"), "side": cfg.get("widget_side", "right")}
    except Exception as exc:  # S14
        logger.warning("site chat button: lookup failed org=%s: %s", org_id, exc)
        return None


def site_switched_on(db: Any, org_id: str, site_id: Optional[str]) -> bool:
    """The site's own switch (sites.chat_button, off by default). Anything unclear = off."""
    if not site_id:
        return False
    try:
        rows = (db.table("sites").select("chat_button").eq("id", site_id).eq("org_id", org_id).limit(1).execute().data) or []
        return bool(rows and rows[0].get("chat_button") is True)
    except Exception as exc:  # S14
        logger.warning("site chat button: site flag failed site=%s: %s", site_id, exc)
        return False


def resolve(db: Any, org_id: str, site_id: Optional[str] = None) -> Optional[dict]:
    """The button for ONE site: only when that site's switch is on AND the account's chat is on, set up and allowed."""
    if not site_switched_on(db, org_id, site_id):
        return None
    return account_chat(db, org_id)


def add(db: Any, site: dict, html: Any) -> Any:
    """html with the button added when it applies, else html unchanged."""
    try:
        if not isinstance(html, str):
            return html
        info = resolve(db, site["org_id"], site.get("id"))
        return inject(html, button_html(info["link"], info["color"], info["side"])) if info else html
    except Exception as exc:  # S14
        logger.warning("site chat button: add failed: %s", exc)
        return html


def add_to_files(db: Any, site: dict, files: list) -> list:
    """The export / publish file list with the button added to every .html page."""
    try:
        info = resolve(db, site["org_id"], site.get("id"))
        if not info:
            return files
        btn = button_html(info["link"], info["color"], info["side"])
        out = []
        for name, data in files:
            if str(name).lower().endswith((".html", ".htm")):
                if isinstance(data, bytes):
                    try:
                        data = inject(data.decode("utf-8"), btn).encode("utf-8")
                    except UnicodeDecodeError:
                        pass
                elif isinstance(data, str):
                    data = inject(data, btn)
            out.append((name, data))
        return out
    except Exception as exc:  # S14
        logger.warning("site chat button: files failed: %s", exc)
        return files
