"""
app/services/site_premium_service.py
-------------------------------------
SITE-PREMIUM P1 - Premium design versions: staff import of a hand-written skeleton (proves the
whole path with no Claude), listing, switching a site back to Standard, and the one function the
render call sites use: render_if_premium().

Rules (spec sections 3, 5, 6):
  * Everything is scoped by org_id (S14). A design row is only ever read through its site's org.
  * An imported skeleton goes through the sanitiser, the CSS variable contract, the slot checks and
    a trial render BEFORE anything is saved. A failure saves nothing.
  * Every change writes a site_events row (done by the router via _log_event).
  * The last 10 versions per site are kept; the current one is never pruned.
  * render_if_premium() never raises: any problem logs a warning and returns None, so the caller
    falls back to the Standard render and a bad design can never take a site offline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import site_premium_checks as checks
from app.services import site_premium_fonts as fonts
from app.services import site_premium_renderer as renderer
from app.services import site_premium_slots as slots
from app.services.site_ops_service import NotFound, SiteOpsError, ValidationFailed
from app.services.site_premium_sanitiser import SanitiseError, sanitise_skeleton

logger = logging.getLogger(__name__)

KEEP_VERSIONS = 10
_LIST_COLUMNS = "id, version, kind, status, staged, created_by, created_at, cost_usd, model, prompt_version, checks"


class PremiumNotEnabled(SiteOpsError):
    status_code = 403
    code = "FORBIDDEN"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def require_enabled(settings_row: Optional[dict]) -> None:
    if not (settings_row or {}).get("premium_enabled"):
        raise PremiumNotEnabled("Premium sites are not switched on for this account yet.")


def _problems(errors: list[str]) -> ValidationFailed:
    return ValidationFailed("Skeleton not accepted: " + "; ".join(errors))


def validate_skeleton(raw_html: str, content: dict, headline_font: str, body_font: str,
                      assets_by_id: Optional[dict] = None) -> dict:
    """Runs every P1 check. Returns the parts to store, or raises ValidationFailed with the reasons."""
    try:
        fonts.validate_fonts(headline_font, body_font)
    except fonts.FontError as exc:
        raise _problems([str(exc)])
    try:
        clean = sanitise_skeleton(raw_html)
    except SanitiseError as exc:
        raise _problems(exc.errors)
    errors = renderer.css_contract_errors(clean.css)
    manifest, slot_errors = slots.analyse(clean.html, content)
    errors += slot_errors
    static = checks.run_static_checks(clean.html, clean.css, headline_font, body_font)
    errors += static["errors"]
    if errors:
        raise _problems(errors)
    tokens = renderer.extract_root_tokens(clean.css)
    design = {"skeleton_html": clean.html, "skeleton_css": clean.css, "tokens": tokens,
              "art_direction": {"headline_font": headline_font, "body_font": body_font}}
    try:   # a trial render with the real content proves the design fills without error
        renderer.render_premium_page(content=content, design=design, assets_by_id=assets_by_id or {}, export=False)
    except Exception as exc:  # S14
        raise _problems([f"The design could not be rendered with this site's content ({exc})"])
    return {**design, "slot_manifest": manifest, "removed": clean.removed, "static_warnings": static["warnings"]}


def import_skeleton(db: Any, org_id: str, site: dict, actor: str, raw_html: str,
                    headline_font: Optional[str] = None, body_font: Optional[str] = None,
                    assets_by_id: Optional[dict] = None) -> dict:
    """Staff import. Saves a new site_designs version and makes it the site's current design."""
    content = site.get("content") or {}
    if not content:
        raise ValidationFailed("This site has no content yet. Generate or enter its content first.")
    if not headline_font or not body_font:
        d_head, d_body = fonts.default_pair()
        headline_font, body_font = headline_font or d_head, body_font or d_body
    parts = validate_skeleton(raw_html, content, headline_font, body_font, assets_by_id)

    existing = (db.table("site_designs").select("id, version").eq("site_id", site["id"]).eq("org_id", org_id)
                .execute()).data or []          # at most KEEP_VERSIONS + 1 rows, so the max is taken here
    version = max((int(r["version"]) for r in existing), default=0) + 1
    row = {
        "org_id": org_id, "site_id": site["id"], "version": version, "kind": "import",
        "parent_id": site.get("current_design_id"),
        "skeleton_html": parts["skeleton_html"], "skeleton_css": parts["skeleton_css"],
        "slot_manifest": parts["slot_manifest"], "art_direction": parts["art_direction"],
        "tokens": parts["tokens"], "status": "ready", "staged": False,
        "checks": {"sanitiser": "ok", "contract": "ok", "slots": "ok", "static": {"errors": [], "warnings": parts["static_warnings"]},
                   "removed": parts["removed"]},
        "created_by": actor, "created_at": _now_iso(),
    }
    inserted = _one((db.table("site_designs").insert(row).execute()).data) or {}
    design_id = inserted.get("id")
    if not design_id:
        raise SiteOpsError("The design could not be saved. Nothing was changed.")
    db.table("sites").update({"tier": "premium", "current_design_id": design_id, "updated_at": _now_iso()}) \
        .eq("id", site["id"]).eq("org_id", org_id).execute()
    _prune(db, org_id, site["id"], keep_id=design_id)
    return {"id": design_id, "version": version, "removed": parts["removed"], "slot_manifest": parts["slot_manifest"],
            "warnings": parts["static_warnings"]}


def _prune(db: Any, org_id: str, site_id: str, keep_id: str) -> None:
    try:
        rows = (db.table("site_designs").select("id, version").eq("site_id", site_id).eq("org_id", org_id)
                .execute()).data or []
        rows.sort(key=lambda r: int(r["version"]), reverse=True)
        for old in rows[KEEP_VERSIONS:]:
            if old["id"] != keep_id:
                db.table("site_designs").delete().eq("id", old["id"]).eq("org_id", org_id).execute()
    except Exception as exc:  # S14 - pruning is housekeeping, never blocks an import
        logger.warning("site_premium: prune failed site=%s: %s", site_id, exc)


def list_designs(db: Any, org_id: str, site_id: str) -> list:
    return (db.table("site_designs").select(_LIST_COLUMNS).eq("site_id", site_id).eq("org_id", org_id)
            .order("version", desc=True).execute()).data or []


def force_standard(db: Any, org_id: str, site: dict) -> None:
    """Switch a site back to the Standard render. The design versions are kept so it can be switched on again."""
    db.table("sites").update({"tier": "standard", "updated_at": _now_iso()}) \
        .eq("id", site["id"]).eq("org_id", org_id).execute()


def use_design(db: Any, org_id: str, site: dict, design_id: str) -> dict:
    """Make an existing version current again (undo). Premium tier on."""
    row = _one((db.table("site_designs").select("id, version").eq("id", design_id).eq("site_id", site["id"])
                .eq("org_id", org_id).eq("status", "ready").limit(1).execute()).data)
    if not row:
        raise NotFound("Design version not found")
    db.table("sites").update({"tier": "premium", "current_design_id": row["id"], "updated_at": _now_iso()}) \
        .eq("id", site["id"]).eq("org_id", org_id).execute()
    return row


def render_if_premium(db: Any, site: dict, assets_by_id: dict, export: bool = False,
                      canonical_domain: Optional[str] = None) -> Optional[str]:
    """The Premium page for this site, or None when the site is Standard / has no usable design.
    Never raises - a problem is logged and the caller renders Standard instead."""
    if (site.get("tier") or "standard") != "premium" or not site.get("current_design_id"):
        return None
    try:
        design = _one((db.table("site_designs").select("*").eq("id", site["current_design_id"])
                       .eq("org_id", site["org_id"]).eq("status", "ready").limit(1).execute()).data)
        if not design:
            logger.warning("site_premium: design %s missing for site %s - rendering Standard",
                           site["current_design_id"], site.get("id"))
            return None
        return renderer.render_premium_page(content=site.get("content") or {}, design=design,
                                            assets_by_id=assets_by_id, export=export,
                                            canonical_domain=canonical_domain)
    except Exception as exc:  # S14
        logger.warning("site_premium: premium render failed site=%s - rendering Standard: %s", site.get("id"), exc)
        return None
