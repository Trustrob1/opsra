"""
app/services/catalog_storefront_service.py
------------------------------------------
STORE-1 - the "Storefront" look for the public catalog (backend only; no screen changes in this phase).

  resolve_template(db, org_id, catalog_config)   "storefront" or "classic" - what the public page should draw
  public_style(catalog_config)                   owner-typed Storefront text/colour/logo, cleaned for the browser
  shop_info(db, org_id)                          {"key": "wc_..."} when the cart can be used, else None
  chat_info(db, org_id, catalog_config)          {"key": "wc_..."} when the chat button can show (Storefront only), else None
  discount_percent(price, compare_at)            whole-number "% off", or None when there is no real discount
  save_look_image(db, org_id, data, kind)        STOREFRONT-2: upload the logo or the banner photo (re-drawn, stored, saved)
  remove_look_image(db, org_id, kind)            STOREFRONT-2: take it off again

Rules
  * Classic is the default. Storefront shows only when the owner picked it AND the plan includes catalog_storefront.
    A plan that lacks it always gets Classic (the saved choice is kept, never erased).
  * The cart is the web chat shop (webchat_shop_service). It is offered only when web chat is on, its shop switch is
    on, the plan includes it, Paystack (paystack_storefront) is connected and the business already has a chat key.
    Reading never writes: no key is created from a public page.
  * Nothing secret is returned - only the chat key, which is already public in every /c/ chat link.
  * S14: every public helper fails safe (Classic / no shop) and never raises into the router.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

FEATURE_KEY = "catalog_storefront"
TEMPLATES = ("classic", "storefront")
DEFAULT_TEMPLATE = "classic"

ANNOUNCEMENT_MAX = 120
TRUST_POINTS_MAX = 3
TRUST_POINT_CHARS = 40
LOGO_URL_MAX = 300
HERO_TITLE_MAX = 60          # STOREFRONT-2: banner headline
HERO_TEXT_MAX = 160          # STOREFRONT-2: banner line under the headline
IMAGE_MAX_BYTES = 5 * 1024 * 1024
LOOK_IMAGES = {              # kind -> (config field, longest side in px, saved as)
    "logo": ("logo_url", 600, "PNG"),
    "hero": ("hero_image_url", 1800, "JPEG"),
}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _text(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def clean_https_url(v) -> Optional[str]:
    u = str(v or "").strip()
    return u[:LOGO_URL_MAX] if u.lower().startswith("https://") and len(u) <= LOGO_URL_MAX and " " not in u else None


def public_style(catalog_config: Optional[dict]) -> dict:
    """The owner's optional Storefront text, accent colour and logo, cleaned again on the way out."""
    cfg = catalog_config if isinstance(catalog_config, dict) else {}
    points = cfg.get("trust_points")
    points = [_text(p, TRUST_POINT_CHARS) for p in points[:TRUST_POINTS_MAX]] if isinstance(points, list) else []
    accent = cfg.get("accent")
    return {
        "announcement": _text(cfg.get("announcement"), ANNOUNCEMENT_MAX) or None,
        "trust_points": [p for p in points if p],
        "accent": accent if isinstance(accent, str) and _HEX.match(accent) else None,
        "logo_url": clean_https_url(cfg.get("logo_url")),
        # STOREFRONT-2: the banner at the top of the shop (all optional; the page has its own wording when empty)
        "hero_title": _text(cfg.get("hero_title"), HERO_TITLE_MAX) or None,
        "hero_text": _text(cfg.get("hero_text"), HERO_TEXT_MAX) or None,
        "hero_image_url": clean_https_url(cfg.get("hero_image_url")),
        # STORE-1b: show the category menu / buttons (default on; the owner can turn it off)
        "show_categories": cfg.get("show_categories") is not False,
        # STOREFRONT-3: show the shop name next to the logo (default on; only matters when there is a logo)
        "show_name_with_logo": cfg.get("show_name_with_logo") is not False,
    }


def storefront_allowed(db, org_id: str) -> bool:
    """Does the business's plan include the Storefront look? (A business not switched onto plans is allowed.)"""
    from app.services import plan_gate_service as gate
    return bool(gate.allowed(db, org_id, FEATURE_KEY))


def resolve_template(db, org_id: str, catalog_config: Optional[dict]) -> str:
    try:
        cfg = catalog_config if isinstance(catalog_config, dict) else {}
        if cfg.get("template") != "storefront":
            return DEFAULT_TEMPLATE
        return "storefront" if storefront_allowed(db, org_id) else DEFAULT_TEMPLATE
    except Exception as exc:
        logger.warning("storefront resolve_template failed org=%s: %s", org_id, exc)
        return DEFAULT_TEMPLATE


def shop_info(db, org_id: str) -> Optional[dict]:
    """{'key': 'wc_...'} when a visitor can add to cart and pay on the Storefront; otherwise None."""
    try:
        from app.services import paystack_storefront_service as paystack
        from app.services import webchat_plan_service as plan
        from app.services import webchat_service as wc

        cfg = plan.apply(db, org_id, wc.get_config(db, org_id))
        if not cfg or not cfg.get("enabled") or not cfg.get("shop_enabled"):
            return None
        if not (paystack._get_storefront_credentials(db, org_id).get("secret_key") or "").strip():
            return None
        rows = (db.table("webchat_keys").select("key").eq("org_id", org_id).eq("active", True).limit(1).execute().data) or []
        key = rows[0].get("key") if rows else None
        return {"key": key} if key else None
    except Exception as exc:
        logger.warning("storefront shop_info failed org=%s: %s", org_id, exc)
        return None


def chat_info(db, org_id: str, catalog_config: Optional[dict]) -> Optional[dict]:
    """WEBCHAT-CATALOG-1: {'key': 'wc_...', 'shop': whether Chioma's own cart is on} when the Storefront can show the "Chat with Chioma" button; otherwise None.
    Needs: the owner has not switched the button off (default on), web chat on, the plan includes it, and the business
    already has an active chat key. It does NOT need the shop or Paystack. Reading never creates a key. Never raises."""
    try:
        cfg = catalog_config if isinstance(catalog_config, dict) else {}
        if cfg.get("chat_button") is False:
            return None
        from app.services import webchat_plan_service as plan
        from app.services import webchat_service as wc

        live = plan.apply(db, org_id, wc.get_config(db, org_id))
        if not live or not live.get("enabled"):
            return None
        rows = (db.table("webchat_keys").select("key").eq("org_id", org_id).eq("active", True).limit(1).execute().data) or []
        key = rows[0].get("key") if rows else None
        return {"key": key, "shop": bool(live.get("shop_enabled")), "goal": live.get("visitor_goal") or ""} if key else None   # CHIOMA-VOICE-1: goal feeds the greeting
    except Exception as exc:
        logger.warning("storefront chat_info failed org=%s: %s", org_id, exc)
        return None


def discount_percent(price, compare_at) -> Optional[int]:
    """Whole-number '% off' only when compare_at is really higher than price. Otherwise None (show nothing)."""
    try:
        p, c = float(price), float(compare_at)
    except (TypeError, ValueError):
        return None
    if p <= 0 or c <= p:
        return None
    pct = int(round((1 - p / c) * 100))
    return pct if pct >= 1 else None


def public_extras(db, org_id: str, catalog_config: Optional[dict]) -> dict:
    """The three public fields added to every public catalog response: template, shop and the owner's style."""
    template = resolve_template(db, org_id, catalog_config)
    storefront = template == "storefront"
    return {
        "template": template,
        "shop": shop_info(db, org_id) if storefront else None,
        "chat": chat_info(db, org_id, catalog_config) if storefront else None,     # WEBCHAT-CATALOG-1
        "style": public_style(catalog_config) if storefront else None,
    }


# ---------------------------------------------------------------------------
# STOREFRONT-2: logo and banner photo uploads
# ---------------------------------------------------------------------------

class LookImageError(Exception):
    """A message the owner can act on; status is the HTTP status the router returns."""
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


def clean_image(data: bytes, max_side: int, fmt: str) -> bytes:
    """Checks the bytes really are a PNG/JPEG/WebP picture and re-draws it (at most max_side px), which drops anything
    hidden in the file. PNG keeps see-through parts (logos); JPEG keeps photos small."""
    import io
    if not data or len(data) > IMAGE_MAX_BYTES:
        raise LookImageError("The picture must be under 5 MB.")
    head = data[:12]
    if not (head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff")
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")):
        raise LookImageError("Use a PNG, JPG or WebP picture.")
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 40_000_000
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGBA" if fmt == "PNG" else "RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        if fmt == "PNG":
            img.save(buf, format="PNG", optimize=True)
        else:
            img.save(buf, format="JPEG", quality=84, optimize=True, progressive=True)
        return buf.getvalue()
    except LookImageError:
        raise
    except Exception as exc:
        logger.info("storefront clean_image: unreadable picture: %s", exc)
        raise LookImageError("That picture could not be read. Try another file.")


def save_look_image(db, org_id: str, data: bytes, kind: str) -> dict:
    """Stores the logo or banner photo in the public catalog bucket and saves its link in the catalog settings.
    Returns the updated catalog config."""
    import secrets
    from app.services.catalog_service import update_catalog_config
    if kind not in LOOK_IMAGES:
        raise LookImageError("Unknown picture.", 404)
    field, side, fmt = LOOK_IMAGES[kind]
    out = clean_image(data, side, fmt)
    ext, ctype = ("png", "image/png") if fmt == "PNG" else ("jpg", "image/jpeg")
    path = f"{org_id}/catalog-look/{kind}-{secrets.token_hex(6)}.{ext}"
    try:
        db.storage.from_("catalog").upload(path=path, file=out, file_options={"content-type": ctype, "upsert": "true"})
        url = (db.storage.from_("catalog").get_public_url(path) or "").split("?")[0]
    except Exception as exc:
        logger.error("storefront save_look_image: upload failed org=%s: %s", org_id, exc)
        raise LookImageError("Could not save the picture. Please try again.", 503)
    if not clean_https_url(url):
        raise LookImageError("Could not save the picture. Please try again.", 503)
    return update_catalog_config(db, org_id, {field: url})


def remove_look_image(db, org_id: str, kind: str) -> dict:
    from app.services.catalog_service import update_catalog_config
    if kind not in LOOK_IMAGES:
        raise LookImageError("Unknown picture.", 404)
    return update_catalog_config(db, org_id, {LOOK_IMAGES[kind][0]: ""})
