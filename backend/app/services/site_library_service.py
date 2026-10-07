"""
backend/app/services/site_library_service.py
SITE-IMPORT 3 - library designs: build a design once (an editable import, or a ready Premium design) and reuse it for many
sites in that niche with no AI call.

  save()        copy a site's current design into site_library_designs (files copied too), after the fit checks
  list_designs  the library, by niche, with the "fewer than 3 designs" warning
  preview()     the design filled with its own sample content (sandboxed by the caller)
  attach()      give a site a copy of a library design: a new site_designs row on THAT site, the site's own content in the slots
  attach_best() the rotation: skip designs this builder just used, least used first, fall back to the next, else raise
  retire/restore

A library design is a COPY, never a link: retiring or editing one never changes a site already built from it, and a site
never depends on another site's files. Sample content is kept only for the library preview; it is never copied to a site, and a
picture slot the client has not filled shows a neutral grey box (never the sample business's photo).
Everything is scoped by org_id (S14). No network, no AI.
"""
from __future__ import annotations

import copy
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import site_import_render as import_render
from app.services import site_import_slotting as slotting
from app.services import site_premium_renderer as premium_renderer
from app.services import site_premium_slots as premium_slots
from app.services.site_ops_service import NotFound, SiteOpsError, ValidationFailed

logger = logging.getLogger(__name__)

BUCKET_FILES = "site-import-files"
MIN_PER_NICHE = 3
RECENT_FOR_ROTATION = 3
NAME_MAX = 80
NOTE_MAX = 300
FIT_ITEM_COUNTS = (1, 5, 40)
LONG_TEXT = "Long text " * 40                      # 400 characters, well over any field's normal length
_FIXED_TEXT_WARN = 12                              # this many fixed text lines: the design carries the sample's wording
_LIST_COLUMNS = ("id, org_id, name, niche, note, source_kind, source_design_id, status, uses_count, has_scripts, fingerprint, "
                 "fit, created_by, created_at, updated_at")


class LibraryError(SiteOpsError):
    status_code = 422
    code = "VALIDATION_ERROR"


class Conflict(SiteOpsError):
    status_code = 409
    code = "CONFLICT"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


# ------------------------------------------------------------------ source designs

def _source(db: Any, org_id: str, site: dict, design_id: str) -> tuple:
    """(design row, kind) where kind is 'import' (an editable uploaded site) or 'premium'. Raises LibraryError otherwise."""
    row = _one((db.table("site_designs").select("*").eq("id", design_id).eq("site_id", site["id"]).eq("org_id", org_id)
                .eq("status", "ready").limit(1).execute()).data)
    if not row:
        raise NotFound("Design not found")
    if row.get("files_prefix"):
        meta = row.get("import_meta") or {}
        if not (row.get("editable") and meta.get("slot_skeleton")):
            raise LibraryError("Make this imported design editable first. A library design needs marked slots so each site can fill it with its own content.")
        if meta.get("library"):
            raise LibraryError("This design already came from the library. Save the original library design instead.")
        return row, "import"
    if row.get("kind") == "import" and not row.get("skeleton_html"):
        raise LibraryError("This design has no page.")
    if row.get("kind") in ("generate", "redesign", "patch", "import", "library") and (row.get("skeleton_html") or "").strip():
        return row, "premium"
    raise LibraryError("This design cannot be saved to the library.")


def _strip_assets(value: Any) -> Any:
    """Sample content without photo ids (they belong to the source site)."""
    if isinstance(value, dict):
        return {k: _strip_assets(v) for k, v in value.items() if not str(k).endswith("_asset_id")}
    if isinstance(value, list):
        return [_strip_assets(v) for v in value]
    return value


# ------------------------------------------------------------------ rendering with content

def _render(kind: str, lib: dict, content: dict, assets_by_id: Optional[dict] = None, placeholder_images: bool = False,
            export: bool = False) -> str:
    """The page body for fit checks and previews (no CSP wrapping)."""
    if kind == "import":
        return slotting.fill(lib["slot_skeleton"], content, assets_by_id or {}, export=export, placeholder_images=placeholder_images)
    return premium_renderer.render_premium_page(content=content, design={
        "skeleton_html": lib["skeleton_html"], "skeleton_css": lib.get("skeleton_css") or "", "tokens": lib.get("tokens") or {},
        "art_direction": lib.get("art_direction") or {}}, assets_by_id=assets_by_id or {}, export=export)


def _variants(sample: dict) -> list:
    """(label, content) pairs the design must render without error: 1, 5 and 40 items, every optional field empty, very long text."""
    out = []
    items = [i for i in (sample.get("items") or []) if isinstance(i, dict)]
    if items:
        for n in FIT_ITEM_COUNTS:
            c = copy.deepcopy(sample)
            c["items"] = [copy.deepcopy(items[k % len(items)]) for k in range(n)]
            out.append((f"{n} item(s)", c))
    minimal = {"business": {k: v for k, v in (sample.get("business") or {}).items() if k in ("name", "whatsapp_e164")},
               "hero": {"headline": (sample.get("hero") or {}).get("headline", "Headline")}}
    out.append(("only the required fields", minimal))

    def longer(v):
        if isinstance(v, str):
            return LONG_TEXT if v and not v.startswith(("+", "http")) else v
        if isinstance(v, dict):
            return {k: longer(x) for k, x in v.items()}
        if isinstance(v, list):
            return [longer(x) for x in v]
        return v
    out.append(("very long text", longer(copy.deepcopy(sample))))
    return out


def fit_check(kind: str, lib: dict, sample: dict) -> dict:
    """{"errors": [...], "warnings": [...], "fixed_text": [...], "head": {...}}. Errors block saving."""
    errors: list = []
    warnings: list = []
    skeleton = lib["slot_skeleton"] if kind == "import" else lib["skeleton_html"]
    manifest, slot_errors = premium_slots.analyse(skeleton, sample)
    errors += slot_errors
    if errors:
        return {"errors": errors, "warnings": warnings, "fixed_text": [], "head": {}}
    for label, content in _variants(sample):
        try:
            html = _render(kind, lib, content)
        except Exception as exc:  # S14: any failure here is a design that cannot be reused safely
            errors.append(f"It could not be filled with {label} ({type(exc).__name__}).")
            continue
        if "data-slot" in html or "data-repeat" in html:
            errors.append(f"Slot markers were left in the page when filled with {label}.")
    fixed: list = []
    head: dict = {}
    if kind == "import":
        fixed = slotting.fixed_text(lib["slot_skeleton"])
        head = slotting.head_text(lib["slot_skeleton"])
        if len(fixed) >= _FIXED_TEXT_WARN:
            warnings.append(f"{len(fixed)} lines of text on this page are not editable slots, so they stay exactly as written on every site "
                            f"that uses it. Check the list: they may carry the sample business's wording.")
        elif fixed:
            warnings.append(f"{len(fixed)} line(s) of fixed text stay as written on every site (listed below).")
        if head.get("title"):
            warnings.append(f"The browser tab title stays '{head['title']}' unless the site has its own SEO title.")
    return {"errors": errors, "warnings": warnings, "fixed_text": fixed, "head": head, "slots": len(manifest.get("slots") or [])}


# ------------------------------------------------------------------ files (imported designs)

def _copy_files(db: Any, files: list, src_prefix: Optional[str], dst_prefix: str, uploaded: list) -> list:
    """Download every stored file of one folder and upload it into another. Returns the new files manifest.
    `uploaded` collects the keys written so the caller can undo on failure."""
    out = []
    for f in files:
        f = dict(f)
        if f.get("stored") and f.get("storage_path"):
            data = db.storage.from_(BUCKET_FILES).download(f["storage_path"])
            key = f"{dst_prefix}/{f['path']}"
            db.storage.from_(BUCKET_FILES).upload(path=key, file=data, file_options={"content-type": f.get("mime") or "application/octet-stream",
                                                                                         "upsert": "true"})
            uploaded.append(key)
            f["storage_path"] = key
        out.append(f)
    return out


def _undo_files(db: Any, keys: list) -> None:
    try:
        if keys:
            db.storage.from_(BUCKET_FILES).remove(keys)
    except Exception as exc:  # S14
        logger.warning("site_library: file cleanup failed: %s", exc)


# ------------------------------------------------------------------ save

def _check_niche(db: Any, org_id: str, niche: str) -> None:
    ok = (db.table("site_presets").select("id").eq("org_id", org_id).eq("key", niche).limit(1).execute()).data
    if not ok:
        raise LibraryError(f"'{niche}' is not one of this account's templates (niche).")


def save(db: Any, org_id: str, site: dict, design_id: str, actor: str, name: str, niche: str, note: str = "") -> dict:
    name, niche, note = (name or "").strip(), (niche or "").strip(), (note or "").strip()
    if not (1 <= len(name) <= NAME_MAX):
        raise LibraryError(f"Give the design a name of 1 to {NAME_MAX} characters.")
    if len(note) > NOTE_MAX:
        raise LibraryError(f"The note can be at most {NOTE_MAX} characters.")
    row, kind = _source(db, org_id, site, design_id)
    _check_niche(db, org_id, niche)
    dup = (db.table("site_library_designs").select("id").eq("org_id", org_id).eq("niche", niche).eq("name", name).execute()).data
    if dup:
        raise Conflict(f"A library design called '{name}' already exists for this niche.")

    meta = row.get("import_meta") or {}
    if kind == "import":
        sample = _strip_assets(meta.get("extracted_content") or {})
        lib_view = {"slot_skeleton": meta["slot_skeleton"]}
    else:
        sample = _strip_assets(site.get("content") or {})
        lib_view = {"skeleton_html": row["skeleton_html"], "skeleton_css": row.get("skeleton_css") or "", "tokens": row.get("tokens") or {},
                    "art_direction": row.get("art_direction") or {}}
    if not sample.get("business") or not sample.get("hero"):
        raise LibraryError("The design needs sample content (a business and a hero) to be checked and previewed.")
    fit = fit_check(kind, lib_view, sample)
    if fit["errors"]:
        raise LibraryError("The design did not pass the fit checks: " + " ".join(fit["errors"][:5]))

    lib_id = str(uuid.uuid4())
    uploaded: list = []
    try:
        record = {
            "id": lib_id, "org_id": org_id, "name": name, "niche": niche, "note": note, "source_kind": kind,
            "source_design_id": row["id"], "skeleton_html": row.get("skeleton_html") or "", "skeleton_css": row.get("skeleton_css") or "",
            "slot_skeleton": meta.get("slot_skeleton") if kind == "import" else None,
            "slot_manifest": row.get("slot_manifest") or {}, "tokens": row.get("tokens") or {}, "art_direction": row.get("art_direction") or {},
            "fingerprint": (row.get("art_direction") or {}).get("fingerprint") or {}, "sample_content": sample,
            "has_scripts": False, "files_prefix": None, "import_meta": {}, "fit": {k: fit[k] for k in ("warnings", "fixed_text", "head")},
            "status": "active", "uses_count": 0, "created_by": actor, "created_at": _now_iso(), "updated_at": _now_iso(),
        }
        if kind == "import":
            report = meta.get("report") or {}
            prefix = f"library/{org_id}/{lib_id}"
            files = _copy_files(db, meta.get("files") or [], row.get("files_prefix"), prefix, uploaded)
            record["files_prefix"] = prefix
            record["has_scripts"] = bool((report.get("scripts") or []) or (report.get("page") or {}).get("inline_scripts"))
            record["import_meta"] = {"report": report, "files": files, "filename": meta.get("filename") or name}
        inserted = _one((db.table("site_library_designs").insert(record).execute()).data) or {}
        if not inserted.get("id"):
            raise SiteOpsError("The library design could not be saved. Nothing was changed.")
    except SiteOpsError:
        _undo_files(db, uploaded)
        raise
    except Exception as exc:  # S14: storage or database problem, undo what was written
        logger.warning("site_library: save failed site=%s: %s", site.get("id"), exc)
        _undo_files(db, uploaded)
        raise SiteOpsError("The library design could not be saved (storage or database problem). Nothing was changed.")
    return {"id": lib_id, "name": name, "niche": niche, "source_kind": kind, "warnings": fit["warnings"], "fixed_text": fit["fixed_text"]}


# ------------------------------------------------------------------ list / get / retire

def get(db: Any, org_id: str, library_id: str) -> dict:
    row = _one((db.table("site_library_designs").select("*").eq("id", library_id).eq("org_id", org_id).limit(1).execute()).data)
    if not row:
        raise NotFound("Library design not found")
    return row


def list_designs(db: Any, org_id: str, niche: Optional[str] = None) -> dict:
    q = db.table("site_library_designs").select(_LIST_COLUMNS).eq("org_id", org_id)
    if niche:
        q = q.eq("niche", niche)
    rows = q.order("created_at", desc=True).execute().data or []
    counts: dict = {}
    for r in rows:
        if r.get("status") == "active":
            counts[r["niche"]] = counts.get(r["niche"], 0) + 1
    niches = sorted({r["niche"] for r in rows})
    return {"designs": rows, "niches": [{"niche": n, "active": counts.get(n, 0), "warning": counts.get(n, 0) < MIN_PER_NICHE} for n in niches]}


def set_status(db: Any, org_id: str, library_id: str, status: str) -> dict:
    if status not in ("active", "retired"):
        raise LibraryError("Unknown status.")
    row = get(db, org_id, library_id)
    db.table("site_library_designs").update({"status": status, "updated_at": _now_iso()}).eq("id", library_id).eq("org_id", org_id).execute()
    return {"id": row["id"], "status": status}


# ------------------------------------------------------------------ preview

def preview(db: Any, org_id: str, library_id: str) -> str:
    """The design filled with its own sample content. Imported designs come back wrapped like an imported page (CSP meta, files
    from the library folder); the caller shows it in a sandboxed iframe."""
    lib = get(db, org_id, library_id)
    sample = lib.get("sample_content") or {}
    if lib["source_kind"] == "import":
        design = {"skeleton_html": lib["skeleton_html"], "files_prefix": lib["files_prefix"], "editable": True,
                  "import_meta": {**(lib.get("import_meta") or {}), "slot_skeleton": lib["slot_skeleton"]}}
        try:
            return import_render.render_imported_page(db, design, import_render._allowed_hosts(db, org_id), export=False,
                                                      content=sample, assets_by_id={})
        except import_render.ImportRenderError as exc:
            raise LibraryError(str(exc))
    return _render("premium", lib, sample)


# ------------------------------------------------------------------ attach

def _missing_content(content: dict) -> list:
    biz, hero = (content or {}).get("business") or {}, (content or {}).get("hero") or {}
    out = []
    if not str(biz.get("name") or "").strip():
        out.append("the business name")
    if not str(biz.get("whatsapp_e164") or "").strip():
        out.append("the WhatsApp number")
    if not str(hero.get("headline") or "").strip():
        out.append("the hero headline")
    return out


def attach(db: Any, org_id: str, site: dict, library_id: str, actor: str) -> dict:
    """A copy of the library design becomes this site's current design. Raises LibraryError (nothing changed) when the site's
    content cannot fill it. The site's own content goes in the slots; the sample content is never used."""
    lib = get(db, org_id, library_id)
    if lib.get("status") != "active":
        raise LibraryError("This library design is retired.")
    content = site.get("content") or {}
    missing = _missing_content(content)
    if missing:
        raise LibraryError("This site cannot use the design yet. It is missing " + ", ".join(missing) + ".")
    kind = lib["source_kind"]
    assets = (db.table("site_assets").select("id, public_url").eq("site_id", site["id"]).execute().data or [])
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in assets}
    # the fit checks run again with THIS site's content
    try:
        if kind == "import":
            _manifest, slot_errors = premium_slots.analyse(lib["slot_skeleton"], content)
            if slot_errors:
                raise LibraryError("This site's content does not fit the design: " + "; ".join(slot_errors[:3]))
        _render(kind, lib, content, assets_by_id, placeholder_images=True)
    except LibraryError:
        raise
    except Exception as exc:  # S14
        raise LibraryError(f"This site's content could not be placed in the design ({type(exc).__name__}).")

    existing = (db.table("site_designs").select("id, version").eq("site_id", site["id"]).eq("org_id", org_id).execute().data or [])
    version = max((int(r["version"]) for r in existing), default=0) + 1
    uploaded: list = []
    try:
        base = {
            "org_id": org_id, "site_id": site["id"], "version": version, "kind": "import", "parent_id": site.get("current_design_id"),
            "skeleton_html": lib["skeleton_html"], "skeleton_css": lib.get("skeleton_css") or "", "slot_manifest": lib.get("slot_manifest") or {},
            "art_direction": lib.get("art_direction") or {}, "tokens": lib.get("tokens") or {}, "status": "ready", "staged": False,
            "created_by": actor, "created_at": _now_iso(),
        }
        if kind == "import":
            prefix = f"{org_id}/{site['id']}/{secrets.token_hex(6)}/v{version}"
            files = _copy_files(db, (lib.get("import_meta") or {}).get("files") or [], lib.get("files_prefix"), prefix, uploaded)
            row = {**base, "editable": True, "files_prefix": prefix, "source_path": None,
                   "checks": {"library": {"id": lib["id"], "name": lib["name"]}},
                   "import_meta": {"report": (lib.get("import_meta") or {}).get("report") or {}, "files": files,
                                   "filename": f"Library: {lib['name']}", "slot_skeleton": lib["slot_skeleton"],
                                   "extracted_content": lib.get("sample_content") or {},
                                   "library": {"id": lib["id"], "name": lib["name"], "fingerprint": lib.get("fingerprint") or {}},
                                   "level2": {"status": "ready", "errors": [], "warnings": [], "finished_at": _now_iso(), "cost_usd": 0,
                                              "fields": len((lib.get("slot_manifest") or {}).get("slots") or []), "photos": []}}}
            tier = "imported"
        else:
            row = {**base, "editable": False, "files_prefix": None,
                   "checks": {"library": {"id": lib["id"], "name": lib["name"], "fingerprint": lib.get("fingerprint") or {}}, "outcome": "premium"},
                   "import_meta": {}}
            tier = "premium"
        inserted = _one((db.table("site_designs").insert(row).execute()).data) or {}
        if not inserted.get("id"):
            raise SiteOpsError("The design could not be attached. Nothing was changed.")
    except SiteOpsError:
        _undo_files(db, uploaded)
        raise
    except Exception as exc:  # S14
        logger.warning("site_library: attach failed site=%s: %s", site.get("id"), exc)
        _undo_files(db, uploaded)
        raise SiteOpsError("The design could not be attached (storage or database problem). Nothing was changed.")
    db.table("sites").update({"tier": tier, "current_design_id": inserted["id"], "updated_at": _now_iso()}) \
        .eq("id", site["id"]).eq("org_id", org_id).execute()
    db.table("site_library_designs").update({"uses_count": int(lib.get("uses_count") or 0) + 1, "updated_at": _now_iso()}) \
        .eq("id", lib["id"]).eq("org_id", org_id).execute()
    if kind == "premium":
        from app.services import site_premium_service
        site_premium_service._prune(db, org_id, site["id"], keep_id=inserted["id"])
    site["tier"], site["current_design_id"] = tier, inserted["id"]
    return {"design_id": inserted["id"], "version": version, "tier": tier, "library_id": lib["id"], "name": lib["name"]}


# ------------------------------------------------------------------ rotation

def _niche_of(db: Any, org_id: str, site: dict) -> Optional[str]:
    if not site.get("preset_id"):
        return None
    row = _one((db.table("site_presets").select("key").eq("id", site["preset_id"]).eq("org_id", org_id).limit(1).execute()).data)
    return (row or {}).get("key")


def _recently_used(db: Any, org_id: str, site: dict) -> list:
    """Library ids this builder's latest sites used (newest first, at most RECENT_FOR_ROTATION)."""
    builder_id = site.get("builder_id")
    if not builder_id:
        return []
    ids = [r["id"] for r in (db.table("sites").select("id").eq("org_id", org_id).eq("builder_id", builder_id).execute().data or [])]
    if not ids:
        return []
    rows = (db.table("site_designs").select("import_meta, checks, created_at").eq("org_id", org_id).in_("site_id", ids)
            .order("created_at", desc=True).limit(60).execute().data or [])
    used: list = []
    for r in rows:
        lib_id = ((r.get("import_meta") or {}).get("library") or (r.get("checks") or {}).get("library") or {}).get("id")
        if lib_id and lib_id not in used:
            used.append(lib_id)
        if len(used) >= RECENT_FOR_ROTATION:
            break
    return used


def candidates(db: Any, org_id: str, site: dict, niche: Optional[str] = None) -> list:
    """Active designs for the niche in the order attach_best tries them: not recently used by this builder first, then least used."""
    niche = niche or _niche_of(db, org_id, site)
    if not niche:
        return []
    rows = (db.table("site_library_designs").select(_LIST_COLUMNS).eq("org_id", org_id).eq("niche", niche).eq("status", "active")
            .execute().data or [])
    recent = _recently_used(db, org_id, site)
    return sorted(rows, key=lambda r: (r["id"] in recent, int(r.get("uses_count") or 0), r.get("created_at") or ""))


def attach_best(db: Any, org_id: str, site: dict, actor: str, niche: Optional[str] = None) -> dict:
    """Try the candidates in order; the first that fits wins. When none fits, raises LibraryError with every reason (the site stays as it is)."""
    cands = candidates(db, org_id, site, niche)
    if not cands:
        raise LibraryError("There is no active library design for this site's niche yet.")
    reasons = []
    for c in cands:
        try:
            return attach(db, org_id, site, c["id"], actor)
        except LibraryError as exc:
            reasons.append(f"{c['name']}: {exc}")
    raise LibraryError("No library design fits this site. " + " | ".join(reasons[:4]))
