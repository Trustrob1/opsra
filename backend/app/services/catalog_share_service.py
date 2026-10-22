"""
app/services/catalog_share_service.py
-------------------------------------
STORE-5: the links an owner shares to bring customers to the public catalog.

  * Short link   {base}/shop/{org-slug}                 (the page opens the same catalog; the address bar then shows /catalog/...)
  * Tagged link  {base}/shop/{org-slug}?src={tag}       the tag names where the customer came from
  * QR code      the tagged link as an SVG (segno, the same library the web chat QR uses)
  * One product  {base}/shop/{org-slug}/{product-slug}[?variant={option id}&src={tag}]   (STORE-5b, "Share this product")
  * Preview link {api}/og/shop/{org-slug}/{product-slug}[?variant=..&src=..]   (STORE-5c) a tiny page with the product's photo,
    name and price for WhatsApp, Facebook and Instagram to read; people who tap it are sent on to the direct link.

The tag is carried into the web chat session when the customer first adds to the cart, so the web chat funnel
(visits, orders, paid) already shows which tag brought the sale. Tags are lowercase letters, digits, - and _, up to 30
characters (the same rule as the web chat source tag). Nothing here changes any data.
S14: helpers never touch the database beyond one slug read; failures raise ShareError with a plain message.
"""
from __future__ import annotations

import html as _html
import io
import json
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


# ── One product (STORE-5b) ──────────────────────────────────────────────────

_VARIANT_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_DEFAULT_TITLES = ("default title", "default")


def _product(db, org_id: str, item_id: str) -> Optional[dict]:
    try:
        res = (db.table("products").select("id, title, slug, price, available, catalog_visible, catalog_images, variants")
               .eq("org_id", org_id).eq("id", str(item_id or "")).limit(1).execute())
        rows = res.data
        if isinstance(rows, dict):
            rows = [rows]
        return (rows or [None])[0]
    except Exception as exc:
        logger.warning("catalog share product read failed org=%s: %s", org_id, exc)
        return None


def sizes_of(product: dict) -> list:
    """The real sizes a customer can pick: options with an id and a title that is not Shopify's placeholder."""
    out = []
    for v in product.get("variants") or []:
        vid = v.get("id") if v.get("id") is not None else v.get("variant_id")
        title = str(v.get("title") or "").strip()
        if vid is None or str(vid).strip() == "" or not title or title.lower() in _DEFAULT_TITLES:
            continue
        out.append({"id": str(vid), "label": title[:60]})
    return out


def _warnings(db, org_id: str, product: dict) -> list:
    """Reasons the link would not do what the owner hopes. The window still opens; it just says what to fix."""
    out = []
    if product.get("catalog_visible") is False:
        out.append("hidden")
    if product.get("available") is False:
        out.append("out_of_stock")
    try:
        from app.services import catalog_storefront_service as storefront
        from app.services.catalog_service import get_catalog_config
        cfg = get_catalog_config(db, org_id) or {}
        if storefront.resolve_template(db, org_id, cfg) != "storefront":
            out.append("classic_look")
        elif not storefront.shop_info(db, org_id):
            out.append("no_cart")
    except Exception as exc:
        logger.warning("catalog share warnings failed org=%s: %s", org_id, exc)
    return out


def product_share_info(db, org_id: str, item_id: str, tag: Optional[str] = None, variant: Optional[str] = None) -> dict:
    """Everything the Share this product window needs. Raises ShareError for a product or size that is not this business's."""
    info = share_info(db, org_id, tag)
    product = _product(db, org_id, item_id)
    if not product:
        raise ShareError("That product was not found.")
    slug = str(product.get("slug") or "").strip()
    if not slug:
        raise ShareError("This product has no page address yet. Open it and save it once, then try again.")
    sizes = sizes_of(product)
    chosen = str(variant or "").strip()
    if chosen and (not _VARIANT_RE.match(chosen) or chosen not in {s["id"] for s in sizes}):
        raise ShareError("That size is not one of this product's sizes.")
    params = []
    if chosen:
        params.append(f"variant={chosen}")
    if info["tag"]:
        params.append(f"src={info['tag']}")
    link = f"{info['short_link']}/{slug}" + (("?" + "&".join(params)) if params else "")
    images = product.get("catalog_images") or []
    first = images[0] if images else None
    return {
        **info,
        "share_link": f"{api_base()}/og/shop/{info['short_link'].rsplit('/', 1)[-1]}/{slug}" + (("?" + "&".join(params)) if params else ""),
        "item": {"id": str(product["id"]), "title": str(product.get("title") or "")[:120], "slug": slug,
                 "price": product.get("price"), "image": (first if isinstance(first, str) else (first or {}).get("url")) if first else None,
                 "available": product.get("available") is not False, "visible": product.get("catalog_visible") is not False},
        "sizes": sizes,
        "variant": chosen or None,
        "link": link,
        "warnings": _warnings(db, org_id, product),
    }


# ── Link preview (STORE-5c) ─────────────────────────────────────────────────

def api_base() -> str:
    """Where the preview page lives: the backend, because the front end is a static site that cannot answer crawlers."""
    return (os.getenv("PUBLIC_API_URL") or "https://opsra.onrender.com").strip().rstrip("/")


def _image_url(first) -> str:
    raw = first if isinstance(first, str) else ((first or {}).get("url") if isinstance(first, dict) else "")
    raw = str(raw or "").strip().rstrip("?")
    return raw if raw.lower().startswith("https://") else ""


def preview_for(db, org_slug_: str, item_slug: str, variant: Optional[str] = None, src: Optional[str] = None) -> dict:
    """What the preview page says. Never raises: an unknown or hidden product gives the store's own preview and link."""
    base = base_url()
    slug = re.sub(r"[^A-Za-z0-9_-]", "", str(org_slug_ or ""))[:80]
    item_clean = re.sub(r"[^A-Za-z0-9_-]", "", str(item_slug or ""))[:120]
    out = {"title": "Online store", "description": "", "image": "", "url": f"{base}/shop/{slug}" if base and slug else base}
    try:
        org = (db.table("organisations").select("id, name, catalog_config").eq("slug", slug).limit(1).execute().data)
        if isinstance(org, dict):
            org = [org]
        org = (org or [None])[0]
        if not org:
            out["url"] = base
            return out
        name = str(org.get("name") or "").strip()
        out["title"] = name or out["title"]
        cfg = org.get("catalog_config") or {}
        res = (db.table("products").select("title, slug, price, available, catalog_description, catalog_images, extra_catalog_images")
               .eq("org_id", org["id"]).eq("slug", item_clean).eq("catalog_visible", True).limit(1).execute().data)
        if isinstance(res, dict):
            res = [res]
        item = (res or [None])[0]
        if not item:
            return out
        params = []
        v = str(variant or "").strip()
        if v and _VARIANT_RE.match(v):
            params.append(f"variant={v}")
        tag = clean_tag(src)
        if tag:
            params.append(f"src={tag}")
        out["url"] = f"{base}/shop/{slug}/{item_clean}" + (("?" + "&".join(params)) if params else "")
        title = str(item.get("title") or "").strip()
        out["title"] = f"{title} - {name}" if title and name else (title or out["title"])
        bits = []
        price = item.get("price")
        if not cfg.get("price_on_request") and price not in (None, ""):
            try:
                bits.append(str(cfg.get("price_label_template") or "\u20a6{price}").replace("{price}", f"{float(price):,.0f}"))
            except (TypeError, ValueError):
                pass
        if item.get("available") is False:
            bits.append("Out of stock")
        desc = " ".join(str(item.get("catalog_description") or "").split())[:120]
        out["description"] = " | ".join(bits + ([desc] if desc else [])) or "Tap to see this product."
        out["image"] = _image_url((item.get("catalog_images") or item.get("extra_catalog_images") or [None])[0])
    except Exception as exc:
        logger.warning("catalog preview failed org=%s item=%s: %s", org_slug_, item_slug, exc)
    return out


def preview_html(p: dict) -> str:
    """The page crawlers read. People are sent straight on to the direct link."""
    e = lambda v: _html.escape(str(v or ""), quote=True)
    url = str(p.get("url") or "")
    image = ("  <meta property=\"og:image\" content=\"%s\">\n  <meta name=\"twitter:image\" content=\"%s\">\n" % (e(p["image"]), e(p["image"]))
             if p.get("image") else "")
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n  <meta charset=\"utf-8\">\n"
        f"  <title>{e(p.get('title'))}</title>\n"
        f"  <meta property=\"og:title\" content=\"{e(p.get('title'))}\">\n"
        f"  <meta property=\"og:description\" content=\"{e(p.get('description'))}\">\n"
        f"  <meta property=\"og:url\" content=\"{e(url)}\">\n"
        "  <meta property=\"og:type\" content=\"website\">\n"
        f"{image}"
        f"  <meta name=\"twitter:card\" content=\"{'summary_large_image' if p.get('image') else 'summary'}\">\n"
        f"  <meta name=\"twitter:title\" content=\"{e(p.get('title'))}\">\n"
        f"  <meta http-equiv=\"refresh\" content=\"0;url={e(url)}\">\n"
        "</head>\n<body>\n"
        f"  <p><a href=\"{e(url)}\">Open this page</a></p>\n"
        f"  <script>window.location.replace({json.dumps(url).replace('<', chr(92) + 'u003c')});</script>\n"
        "</body>\n</html>\n"
    )


# ── Visits per tag (STORE-7) ────────────────────────────────────────────────

def record_visit(db, org_slug_: str, src: Optional[str]) -> bool:
    """Count one open of a tagged catalog link. Only tagged links are counted (an empty or unusable tag is ignored).
    Never raises; before the STORE-7 migration the insert is refused by the database and only logged."""
    tag = clean_tag(src)
    slug = re.sub(r"[^A-Za-z0-9_-]", "", str(org_slug_ or ""))[:80]
    if not tag or not slug:
        return False
    try:
        rows = db.table("organisations").select("id").eq("slug", slug).limit(1).execute().data
        if isinstance(rows, dict):
            rows = [rows]
        org = (rows or [None])[0]
        if not org:
            return False
        from app.services import webchat_service as wc
        wc.log_event(db, org["id"], None, "catalog_visit", tag)
        return True
    except Exception as exc:
        logger.warning("catalog visit not recorded slug=%s: %s", slug, exc)
        return False
