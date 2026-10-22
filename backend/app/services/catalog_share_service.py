"""
app/services/catalog_share_service.py
-------------------------------------
STORE-5: the links an owner shares to bring customers to the public catalog.

  * Short link   {base}/shop/{org-slug}                 (the page opens the same catalog; the address bar then shows /catalog/...)
  * Tagged link  {base}/shop/{org-slug}?src={tag}       the tag names where the customer came from
  * QR code      the tagged link as an SVG (segno, the same library the web chat QR uses)

The tag is carried into the web chat session when the customer first adds to the cart, so the web chat funnel
(visits, orders, paid) already shows which tag brought the sale. Tags are lowercase letters, digits, - and _, up to 30
characters (the same rule as the web chat source tag). Nothing here changes any data.
S14: helpers never touch the database beyond one slug read; failures raise ShareError with a plain message.
"""
from __future__ import annotations

import io
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

TAG_MAX = 30
PRESETS = [
    ("instagram", "Instagram"),
    ("whatsapp", "WhatsApp status"),
    ("facebook", "Facebook"),
    ("flyer", "Flyer or poster"),
    ("shop", "Shop sign or counter"),
]


class ShareError(ValueError):
    """A problem the owner can understand; the router turns it into a 422."""


def clean_tag(value) -> str:
    """Lowercase letters, digits, - and _ only, at most 30 characters. Empty when nothing usable is left."""
    return re.sub(r"[^a-z0-9_-]", "", str(value or "").lower())[:TAG_MAX]


def base_url() -> str:
    base = (os.getenv("CATALOG_BASE_URL") or os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    if not base:
        try:
            from app.config import settings
            base = (getattr(settings, "FRONTEND_URL", "") or "").strip().rstrip("/")
        except Exception:
            base = ""
    return base


def org_slug(db, org_id: str) -> str:
    try:
        res = db.table("organisations").select("slug").eq("id", org_id).limit(1).execute()
        rows = res.data
        if isinstance(rows, dict):
            rows = [rows]
        return str(((rows or [{}])[0] or {}).get("slug") or "").strip()
    except Exception as exc:
        logger.warning("catalog share slug read failed org=%s: %s", org_id, exc)
        return ""


def tagged(link: str, tag: Optional[str]) -> str:
    return f"{link}?src={tag}" if tag else link


def share_info(db, org_id: str, tag: Optional[str] = None) -> dict:
    """Links for the owner's Share panel. `tag` is cleaned; an empty one gives the plain short link."""
    slug = org_slug(db, org_id)
    base = base_url()
    if not slug or not base:
        raise ShareError("Your store address is not ready yet. Please contact support.")
    short = f"{base}/shop/{slug}"
    clean = clean_tag(tag)
    return {
        "short_link": short,
        "catalog_link": f"{base}/catalog/{slug}",
        "tag": clean or None,
        "tagged_link": tagged(short, clean),
        "presets": [{"tag": t, "label": label, "link": tagged(short, t)} for t, label in PRESETS],
    }


def qr_svg(link: str) -> bytes:
    """The link as an SVG QR code (dark ink on white, with a quiet border so phones scan it from a flyer)."""
    import segno
    buf = io.BytesIO()
    segno.make(link, error="m").save(buf, kind="svg", scale=10, border=2, dark="#14181B", xmldecl=False)
    return buf.getvalue()
