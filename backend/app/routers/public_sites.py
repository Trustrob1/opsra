"""
app/routers/public_sites.py
-----------------------------
SITE-1A — the public preview route. NO auth dependency.

  GET /s/{slug}   -> the rendered site, or 404 (unknown slug) / 410 (expired/cancelled)

Security (spec §8.5, §18):
  - Never returns org_id, builder_id, lead data, or anything beyond the rendered page.
  - A strict, page-specific CSP — this route sets its own Content-Security-Policy header;
    main.py's SecurityHeadersMiddleware must NOT overwrite a CSP a route already set
    (see SITE-1A_Edits.md §main.py — this is a one-line guard, not yet in main.py).
  - X-Robots-Tag: noindex, nofollow / Referrer-Policy: no-referrer, in addition to the
    <meta robots> tag the renderer already emits.
  - Rate limit: 60 requests/minute/IP (same in-process pattern as public_catalog.py).
  - Register in main.py with prefix="" (like public_catalog_og / public_funnels).
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.database import get_supabase
from app.services import site_premium_service, site_renderer

logger = logging.getLogger(__name__)
router = APIRouter()

_rate_store: dict[str, list[float]] = {}
_RATE_LIMIT = 60
_RATE_WINDOW = 60.0

_LIVE_STATUSES = {
    "brief_in_progress", "brief_complete", "generating", "preview_ready", "revising",
    "hosting_checkout", "awaiting_payment", "paid", "publishing", "live", "renewal_due",
}


def _check_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    calls = [t for t in _rate_store.get(ip, []) if t > now - _RATE_WINDOW]
    if len(calls) >= _RATE_LIMIT:
        _rate_store[ip] = calls
        raise HTTPException(status_code=429, detail="Too many requests")
    calls.append(now)
    _rate_store[ip] = calls
    if len(_rate_store) > 10_000:
        _rate_store.clear()


_PREVIEW_CSP = (
    "default-src 'none'; "
    "img-src https://*.supabase.co data:; "
    "style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def _preview_headers() -> dict:
    return {
        "Content-Security-Policy": _PREVIEW_CSP,
        "X-Robots-Tag": "noindex, nofollow",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }


@router.get("/s/{slug}", include_in_schema=False)
def preview_site(slug: str, request: Request, db=Depends(get_supabase)):
    _check_rate_limit(request)

    site_r = (
        db.table("sites")
        .select("id, org_id, preset_id, status, content, recipe, preview_expires_at, deleted_at, tier, current_design_id")
        .eq("slug", slug)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    site = site_r.data
    if isinstance(site, list):
        site = site[0] if site else None
    if not site:
        raise HTTPException(status_code=404, detail="Not found")

    if site["status"] == "cancelled":
        raise HTTPException(status_code=410, detail="This preview is no longer available")

    if site["status"] not in _LIVE_STATUSES and site["status"] != "live":
        # Defensive — any status not in the known live/preview set is treated as gone,
        # never rendered, so a future status value can't accidentally leak a page.
        raise HTTPException(status_code=410, detail="This preview is no longer available")

    expires_at = site.get("preview_expires_at")
    if expires_at and site["status"] != "live":
        from datetime import datetime, timezone
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry < datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail="This preview has expired")
        except (ValueError, AttributeError):
            pass

    if not site.get("content") or not site.get("recipe"):
        raise HTTPException(status_code=404, detail="Not found")

    preset_r = (
        db.table("site_presets").select("*").eq("id", site["preset_id"]).maybe_single().execute()
    )
    preset = preset_r.data
    if isinstance(preset, list):
        preset = preset[0] if preset else None
    if not preset:
        logger.error("preview_site: preset %s missing for site %s", site["preset_id"], site["id"])
        raise HTTPException(status_code=404, detail="Not found")

    assets_r = (
        db.table("site_assets").select("id, public_url").eq("site_id", site["id"]).execute()
    )
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in (assets_r.data or [])}

    try:
        html = site_premium_service.render_if_premium(db, site, assets_by_id)   # SITE-PREMIUM P1
        if html is None:
            html = site_renderer.render_page(site["content"], site["recipe"], preset, assets_by_id)
    except Exception as exc:
        logger.error("preview_site: render failed for slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="This preview couldn't be rendered right now")

    headers = _preview_headers()
    if (site.get("tier") or "standard") == "imported":      # SITE-IMPORT 1b: scripts run, but in a sandbox
        from app.services import site_import_render
        base = None
        try:
            d = site_import_render._current_design(db, site)
            base = site_import_render.public_base(db, d) if d else None
            from urllib.parse import urlsplit
            origin = "{u.scheme}://{u.netloc}".format(u=urlsplit(base)) if base else None
            headers = site_import_render.preview_headers(site_import_render._allowed_hosts(db, site["org_id"]), origin)
        except Exception as exc:  # S14: keep the strict script-free headers
            logger.warning("preview_site: imported headers failed slug=%s: %s", slug, exc)
    return HTMLResponse(content=html, status_code=200, headers=headers)
