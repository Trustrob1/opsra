"""
services/host_site_service.py
HOST-1 - "Host with Opsra": a builder who made a website outside Opsra signs in, drops the files in, sees the safety
check and a preview, and pays to put it on a domain. Everything heavy is reused:

  * the upload is read, scanned and stored by site_import_service.import_site (the same code staff use),
  * the page is shown by site_import_render (scripts run only inside a sandboxed preview),
  * hosting, domains, quotes, payment and renewal are the normal site checkout (site_order_service).

What is different from the staff import:
  * the builder can never accept an overridable finding: anything the scan refuses is simply refused,
  * a good upload is made the site's page at once (preview), so there is no extra "use this design" step,
  * limits: a cap of sites per builder (site_builder_settings.host_only_max_sites, default 25) and an upload rate limit,
  * the feature is off until site_builder_settings.host_only_enabled AND site_import_enabled are both true,
  * uploaded sites do not use the builder's free-site allowance (site_access_service.count_sites ignores tier 'imported').

A site that is already paid or live is never re-pointed by an upload. The new files are saved as a staged version and
the Opsra team publishes it from the staff Import panel.

Never raises into a caller for a lookup problem (S14); real refusals raise HostError / the import errors.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.services import site_import_render, site_import_service

logger = logging.getLogger(__name__)

DEFAULT_MAX_SITES = 25
UPLOADS_PER_HOUR = 20
NAME_MAX = 120
# A site in one of these states is already sold or published: an upload is saved but not switched on.
_LOCKED_STATUSES = ("paid", "publishing", "live", "renewal_due", "lapsed")
_upload_hits: dict = defaultdict(list)


class HostError(Exception):
    def __init__(self, message: str, status_code: int = 422, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


def rate_limited(builder_id: str, limit: int = UPLOADS_PER_HOUR, window_s: float = 3600.0) -> bool:
    now = time.monotonic()
    hits = [t for t in _upload_hits[builder_id] if now - t < window_s]
    _upload_hits[builder_id] = hits
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


def get_settings(db: Any, org_id: str) -> dict:
    return _one((db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data) or {}


def is_enabled(settings: Optional[dict]) -> bool:
    s = settings or {}
    return bool(s.get("enabled") and s.get("site_import_enabled") and s.get("host_only_enabled"))


def require_enabled(db: Any, org_id: str) -> dict:
    settings = get_settings(db, org_id)
    if not is_enabled(settings):
        raise HostError("Hosting uploads are not open yet. Please check back soon.", 403, "FORBIDDEN")
    return settings


def max_sites(settings: Optional[dict]) -> int:
    try:
        return max(1, int((settings or {}).get("host_only_max_sites") or DEFAULT_MAX_SITES))
    except (TypeError, ValueError):
        return DEFAULT_MAX_SITES


def _own_imported_sites(db: Any, builder: dict) -> list:
    return (db.table("sites").select("*").eq("org_id", builder["org_id"]).eq("builder_id", builder["id"])
            .eq("tier", "imported").is_("deleted_at", "null").order("created_at", desc=True).execute()).data or []


def config(db: Any, builder: dict) -> dict:
    settings = get_settings(db, builder["org_id"])
    cfg = site_import_service.settings_for(settings)
    used = len([s for s in _clean_rows(_own_imported_sites(db, builder)) if s.get("status") != "cancelled"]) if is_enabled(settings) else 0
    lim = site_import_service.LIMITS
    return {
        "enabled": is_enabled(settings),
        "max_upload_mb": cfg["max_mb"],
        "max_sites": max_sites(settings),
        "used": used,
        "accepts": [".zip (index.html at the top)", ".html (one file)"],
        "limits": {"files": lim["max_files"], "images_mb": lim["max_image_each"] // site_import_service.MB,
                   "scripts_mb": round(lim["max_js_total"] / site_import_service.MB, 1)},
    }


def _clean_rows(rows: list) -> list:
    return [r for r in (rows or []) if r]


def _own_site(db: Any, builder: dict, site_id: str) -> dict:
    row = _one((db.table("sites").select("*").eq("id", site_id).eq("org_id", builder["org_id"])
                .eq("builder_id", builder["id"]).is_("deleted_at", "null").limit(1).execute()).data)
    if not row:
        raise HostError("Site not found.", 404, "NOT_FOUND")
    if (row.get("tier") or "standard") != "imported":
        raise HostError("This site was not uploaded here, so files cannot be replaced from this page.")
    return row


def _placeholder_content_recipe(db: Any, org_id: str, builder: dict, name: str):
    """The sites table and the public preview link expect a content + recipe pair. An uploaded page does not use
    them, so this is the smallest valid pair on the first active template. (None, None, preset_id) if it cannot be made."""
    from app.models.sites import Recipe, SiteContentV1
    from app.services import site_design_registry, site_renderer
    preset = _one((db.table("site_presets").select("*").eq("org_id", org_id).eq("is_active", True)
                   .order("name").limit(1).execute()).data)
    if not preset:
        return None, None, None
    try:
        digits = "".join(ch for ch in str(builder.get("phone_number") or "") if ch.isdigit())
        if len(digits) < 8:
            return None, None, preset["id"]
        allowed_themes = [t for t in (preset.get("allowed_themes") or list(site_renderer.THEMES)) if t in site_renderer.THEMES]
        palette = next(iter(site_design_registry.PALETTES))
        sections = [s for s in (preset.get("sections") or list(site_renderer.SECTION_VARIANTS)) if s in site_renderer.SECTION_VARIANTS]
        recipe = {"theme": allowed_themes[0], "palette": palette, "order": sections[:3] or ["hero"]}
        content = {"business": {"name": name, "whatsapp_e164": "+" + digits[:18]},
                   "hero": {"headline": name[:140]}}
        content = SiteContentV1.model_validate(content).model_dump(mode="json")
        recipe = Recipe.model_validate(recipe).model_dump(mode="json")
        site_renderer.validate_recipe(preset, recipe)
        return content, recipe, preset["id"]
    except Exception as exc:  # S14: the site is still created; only the public /s/ preview link is missing
        logger.warning("host_site: placeholder content failed org=%s: %s", org_id, exc)
        return None, None, preset["id"]


def clean_name(raw: Optional[str], filename: str = "") -> str:
    name = " ".join(str(raw or "").split())
    if not name:
        stem = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        stem = stem.rsplit(".", 1)[0] if "." in stem else stem
        name = " ".join(stem.replace("_", " ").replace("-", " ").split())
    name = name[:NAME_MAX].strip()
    if not name or name.lower() in ("index", "site", "website", "untitled"):
        name = "My website"
    return name


def create_site(db: Any, builder: dict, name: str, settings: dict) -> dict:
    from app.models.sites import slugify_business_name
    from app.services import site_renderer
    org_id = builder["org_id"]
    existing = [s for s in _own_imported_sites(db, builder) if s.get("status") != "cancelled"]
    if len(existing) >= max_sites(settings):
        raise HostError(f"You have reached the limit of {max_sites(settings)} hosted sites. Contact us to host more.", 403, "ACCESS_LIMIT")
    content, recipe, preset_id = _placeholder_content_recipe(db, org_id, builder, name)
    if not preset_id:
        raise HostError("Hosting is not set up yet (no template is available). Please try again later.", 503, "SERVICE_UNAVAILABLE")
    slug = site_renderer.generate_slug(name)
    if (db.table("sites").select("id").eq("slug", slug).execute()).data:
        slug = f"{slugify_business_name(name)}-{site_renderer.generate_slug('')}"
    row = {
        "org_id": org_id, "builder_id": builder["id"], "preset_id": preset_id,
        "client_business_name": name, "slug": slug, "tier": "imported",
        "status": "brief_complete", "revision_count": 0, "ai_generation_count": 0, "design_rolls": 0,
        "preview_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    if content and recipe:
        row.update({"content": content, "recipe": recipe, "content_source": "manual"})
    inserted = _one((db.table("sites").insert(row).execute()).data) or row
    _log(db, org_id, inserted.get("id"), builder, "host_site_created", {"name": name})
    return inserted


def _discard(db: Any, org_id: str, site: dict) -> None:
    """Undo a site made for an upload that was refused (nothing was kept)."""
    try:
        db.table("sites").update({"deleted_at": _now_iso(), "updated_at": _now_iso()}) \
            .eq("id", site["id"]).eq("org_id", org_id).execute()
    except Exception as exc:  # S14
        logger.warning("host_site: discard failed site=%s: %s", site.get("id"), exc)


def _log(db: Any, org_id: str, site_id: Optional[str], builder: dict, event: str, detail: Optional[dict] = None) -> None:
    if not site_id:
        return
    try:
        db.table("site_events").insert({"org_id": org_id, "site_id": site_id, "actor": f"builder:{builder['id']}",
                                        "event": event, "detail": detail or {}, "created_at": _now_iso()}).execute()
    except Exception as exc:  # S14
        logger.warning("host_site: event insert failed site=%s event=%s: %s", site_id, event, exc)


def _store_render(db: Any, org_id: str, site: dict) -> None:
    try:
        from app.services import site_premium_service
        assets = (db.table("site_assets").select("id, public_url").eq("site_id", site["id"]).execute()).data or []
        html = site_premium_service.render_if_premium(db, site, {a["id"]: {"public_url": a["public_url"]} for a in assets})
        if html:
            db.table("sites").update({"rendered_html": html, "updated_at": _now_iso()}).eq("id", site["id"]).eq("org_id", org_id).execute()
    except Exception as exc:  # S14: the design is saved; the preview endpoint renders it on demand
        logger.warning("host_site: render failed site=%s: %s", site.get("id"), exc)


def plain_errors(exc: "site_import_service.ImportRejected") -> list:
    """The scan's sentences, kept short and free of paths on our side."""
    return [str(e)[:300] for e in (exc.errors or [])][:12]


def upload(db: Any, builder: dict, data: bytes, filename: str, *, name: Optional[str] = None,
           site_id: Optional[str] = None, dry_run: bool = False) -> dict:
    """Checks (dry_run) or saves an upload. Raises HostError, ImportRejected (plain refusal) or ImportFailed."""
    org_id = builder["org_id"]
    settings = require_enabled(db, org_id)
    actor = f"builder:{builder['id']}"
    if dry_run:
        r = site_import_service.import_site(db, org_id, {"id": site_id or "check-only"}, actor, data, filename, settings, dry_run=True)
        return {"saved": False, "report": r["report"]}

    created = False
    if site_id:
        site = _own_site(db, builder, site_id)
    else:
        site = create_site(db, builder, clean_name(name, filename), settings)
        created = True
    try:
        result = site_import_service.import_site(db, org_id, site, actor, data, filename, settings, accepted=None)
    except Exception:
        if created:
            _discard(db, org_id, site)
        raise

    locked = (site.get("status") in _LOCKED_STATUSES) and not created
    if not locked:
        try:
            site_import_render.activate(db, org_id, site, result["design_id"], False, actor)
        except Exception as exc:  # the files are saved; staff can switch the version on
            logger.warning("host_site: activate failed site=%s: %s", site.get("id"), exc)
            locked = True
        else:
            site["tier"], site["current_design_id"] = "imported", result["design_id"]
            if site.get("status") in (None, "brief_in_progress", "brief_complete", "generating", "revising", "preview_ready"):
                db.table("sites").update({"status": "preview_ready", "updated_at": _now_iso()}).eq("id", site["id"]).eq("org_id", org_id).execute()
                site["status"] = "preview_ready"
            _store_render(db, org_id, site)
    report = result["report"]
    _log(db, org_id, site["id"], builder, "host_site_uploaded",
         {"design_id": result["design_id"], "version": result["version"], "files": result["files"], "switched_on": not locked,
          "warnings": len(report.get("warnings") or [])})
    return {"saved": True, "site": _site_view(db, builder, site), "design_id": result["design_id"], "version": result["version"],
            "files": result["files"], "report": report, "switched_on": not locked,
            "message": ("Your site is ready to preview." if not locked else
                        "Your new files are saved. Because this site is already paid for, the Opsra team will publish the update.")}


def _summary_of(designs: list) -> Optional[dict]:
    if not designs:
        return None
    d = designs[0]
    return {"id": d["id"], "version": d["version"], "filename": d.get("filename"), "created_at": d.get("created_at"),
            "files": (d.get("counts") or {}).get("files"), "scripts": d.get("scripts", 0), "warnings": d.get("warnings", 0),
            "external_unknown": d.get("external_unknown", 0), "missing_files": d.get("missing_files", 0),
            "active": bool(d.get("active")), "staged": bool(d.get("staged"))}


def _site_view(db: Any, builder: dict, site: dict, designs: Optional[list] = None) -> dict:
    if designs is None:
        try:
            designs = site_import_render.designs(db, builder["org_id"], site)
        except Exception as exc:  # S14
            logger.warning("host_site: designs failed site=%s: %s", site.get("id"), exc)
            designs = []
    return {"id": site["id"], "client_business_name": site.get("client_business_name"), "slug": site.get("slug"),
            "status": site.get("status"), "live_url": site.get("live_url"), "created_at": site.get("created_at"),
            "has_preview_link": bool(site.get("content") and site.get("recipe")),
            "design": _summary_of(designs)}


def list_sites(db: Any, builder: dict) -> list:
    org_id = builder["org_id"]
    rows = _own_imported_sites(db, builder)
    domains = {}
    try:
        for d in (db.table("site_domains").select("site_id, renews_on, hosting_renews_on, status").eq("org_id", org_id).execute()).data or []:
            domains[d["site_id"]] = d
    except Exception as exc:  # S14
        logger.warning("host_site: domains lookup failed: %s", exc)
    out = []
    for r in rows:
        v = _site_view(db, builder, r)
        d = domains.get(r["id"])
        v["hosting_status"] = d["status"] if d else None
        v["renews_on"] = d["renews_on"] if d else None
        out.append(v)
    return out


def latest_design_id(db: Any, builder: dict, site: dict) -> Optional[str]:
    designs = site_import_render.designs(db, builder["org_id"], site)
    if site.get("current_design_id") and any(d["id"] == site["current_design_id"] for d in designs):
        return site["current_design_id"]
    return designs[0]["id"] if designs else None


def preview_html(db: Any, builder: dict, site_id: str, design_id: Optional[str] = None) -> str:
    """The page for the sandboxed preview frame (scripts on, no access to the portal)."""
    site = _own_site(db, builder, site_id)
    did = design_id or latest_design_id(db, builder, site)
    if not did:
        raise HostError("Nothing has been uploaded to this site yet.", 404, "NOT_FOUND")
    assets = (db.table("site_assets").select("id, public_url").eq("site_id", site_id).execute()).data or []
    try:
        return site_import_render.preview_design(db, builder["org_id"], site, did, {a["id"]: {"public_url": a["public_url"]} for a in assets})
    except site_import_render.ImportRenderError as exc:
        raise HostError(str(exc), 404, "NOT_FOUND")


def report_for(db: Any, builder: dict, site_id: str) -> dict:
    _own_site(db, builder, site_id)
    rep = site_import_service.latest_report(db, builder["org_id"], site_id)
    if not rep:
        raise HostError("Nothing has been uploaded to this site yet.", 404, "NOT_FOUND")
    return rep
