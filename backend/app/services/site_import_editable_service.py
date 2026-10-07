"""
backend/app/services/site_import_editable_service.py
SITE-IMPORT 2 - "Make editable": an uploaded site (Level 1) becomes a Level 2 site whose text, prices, photos and contact
links are editable in the builder editor and by WhatsApp EDIT.

Two halves, like Premium generation:
  start()  - guards (the import design exists, one run at a time, org daily cost cap). Marks the design 'running'. Cheap.
  run()    - the worker job. outline -> Claude plan -> apply_plan (markers + content read from the page) -> content validated
             -> slot manifest -> filled page compared with the original -> save. Never raises. Any failure leaves the site as
             a Level 1 import (nothing changes for the visitor) and the reasons are saved on the design.

State lives on the import design row: import_meta.level2 = {status: running|working|ready|failed, ...}. No new table.
Saved on success: import_meta.slot_skeleton (the marked page), import_meta.extracted_content (what the page said),
slot_manifest, editable=True, and the cost columns. skeleton_html (the original page) is never changed.
"""
from __future__ import annotations

import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.services import site_import_dom as dom
from app.services import site_import_prompt as prompt
from app.services import site_import_sanitiser as sanitiser
from app.services import site_import_slotting as slotting
from app.services import site_premium_generation_service as gen
from app.services import site_premium_prompt as premium_prompt
from app.services import site_premium_slots as premium_slots
from app.services.site_ops_service import NotFound, SiteOpsError, ValidationFailed

logger = logging.getLogger(__name__)

BUCKET_FILES = "site-import-files"
BUCKET_ASSETS = "site-assets"
PLAN_MAX_TOKENS = 8_000
STALE_AFTER_MINUTES = 20
MAX_ASSETS_PER_SITE = 20          # same cap as the editor's photo upload (spec 18)
MAX_ASSET_BYTES = 8 * 1024 * 1024
ACTIVE = ("running", "working")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


# ------------------------------------------------------------------ status helpers

def level2_of(design: dict) -> Optional[dict]:
    return ((design or {}).get("import_meta") or {}).get("level2") or None


def public_status(design: dict) -> dict:
    """What the panel shows for a design: {status, errors, warnings, ...} or {status: 'none'}."""
    l2 = level2_of(design)
    if not l2:
        return {"status": "none"}
    out = {"status": l2.get("status") or "none", "errors": (l2.get("errors") or [])[:10], "warnings": (l2.get("warnings") or [])[:10]}
    for k in ("finished_at", "started_at", "cost_usd", "fields", "photos"):
        if l2.get(k) is not None:
            out[k] = l2[k]
    return out


def _write_meta(db: Any, design: dict, **level2: Any) -> dict:
    """Merge into import_meta.level2 and save. Returns the new import_meta."""
    meta = dict(design.get("import_meta") or {})
    l2 = dict(meta.get("level2") or {})
    l2.update(level2)
    meta["level2"] = l2
    db.table("site_designs").update({"import_meta": meta}).eq("id", design["id"]).eq("org_id", design["org_id"]).execute()
    design["import_meta"] = meta
    return meta


def _import_design(db: Any, org_id: str, site_id: str, design_id: Optional[str]) -> Optional[dict]:
    q = (db.table("site_designs").select("*").eq("site_id", site_id).eq("org_id", org_id).eq("kind", "import").eq("status", "ready"))
    if design_id:
        q = q.eq("id", design_id)
    rows = [r for r in (q.execute().data or []) if r.get("files_prefix")]      # a Premium pasted skeleton is not an uploaded site
    if not rows:
        return None
    rows.sort(key=lambda r: int(r.get("version") or 0), reverse=True)
    return rows[0]


# ------------------------------------------------------------------ guards (request side)

def sweep_stale(db: Any, org_id: str, site_id: str) -> int:
    """A worker that died leaves a design 'running' forever. Anything older than STALE_AFTER_MINUTES is marked failed."""
    cutoff = _now() - timedelta(minutes=STALE_AFTER_MINUTES)
    swept = 0
    rows = (db.table("site_designs").select("id, org_id, import_meta").eq("site_id", site_id).eq("org_id", org_id)
            .eq("kind", "import").execute().data or [])
    for r in rows:
        l2 = level2_of(r)
        if not l2 or l2.get("status") not in ACTIVE:
            continue
        try:
            started = datetime.fromisoformat(str(l2.get("started_at")).replace("Z", "+00:00"))
        except Exception:  # an unreadable time counts as old
            started = cutoff - timedelta(minutes=1)
        if started < cutoff:
            _write_meta(db, r, status="failed", errors=["Making the page editable took too long and was stopped."], finished_at=_now_iso())
            swept += 1
    return swept


def _spent_today(db: Any, org_id: str) -> float:
    since = gen._today_start_iso()
    spent = sum(float(r.get("cost_usd") or 0) for r in
                (db.table("site_designs").select("cost_usd").eq("org_id", org_id).gte("created_at", since).execute().data or []))
    for r in (db.table("site_events").select("detail").eq("org_id", org_id).eq("event", "import_editable_done").gte("created_at", since).execute().data or []):
        spent += float((r.get("detail") or {}).get("cost_usd") or 0)
    return spent


def start(db: Any, org_id: str, site: dict, actor: str, design_id: Optional[str] = None) -> dict:
    """Guards, then mark the design 'running'. The caller queues the Celery task with the returned design id."""
    design = _import_design(db, org_id, site["id"], design_id)
    if not design:
        raise NotFound("Upload a site first. There is no imported design to make editable.")
    sweep_stale(db, org_id, site["id"])
    design = _import_design(db, org_id, site["id"], design["id"])
    for r in (db.table("site_designs").select("id, org_id, import_meta").eq("site_id", site["id"]).eq("org_id", org_id)
              .eq("kind", "import").execute().data or []):
        if (level2_of(r) or {}).get("status") in ACTIVE:
            raise gen.AlreadyGenerating("This site is already being made editable. It will be ready in a few minutes.")
    settings = gen.settings_for(db, org_id)
    cap = float(settings.get("site_premium_daily_cost_cap") or 20)
    if _spent_today(db, org_id) >= cap:
        raise gen.CapReached("Making pages editable is paused for today (the daily AI cost limit was reached). Please try again tomorrow.")
    _write_meta(db, design, status="running", started_at=_now_iso(), actor=actor, errors=[], warnings=[], run_id=secrets.token_hex(4))
    return {"design_id": design["id"], "version": design.get("version")}


# ------------------------------------------------------------------ the page's own pictures become site photos

class Registrar:
    """asset_for(src): copies a stored raster file of the upload into the site's photos and returns the new site_assets id.
    The same file always gives the same id. Returns None for anything it cannot register (the plan then explains itself)."""

    def __init__(self, db: Any, site_id: str, files: list, existing: int):
        self.db, self.site_id, self.existing = db, site_id, existing
        self.by_path = {f["path"].lower(): f for f in files if f.get("stored")}
        self.done: dict = {}
        self.created: list = []        # [{"id", "storage_path"}]
        self.public: dict = {}         # id -> {"public_url"}

    @staticmethod
    def _sniff(b: bytes) -> Optional[str]:
        if b[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            return "image/webp"
        return None

    def __call__(self, src: str) -> Optional[str]:
        from urllib.parse import urlsplit
        try:
            path = sanitiser.normalise_local(urlsplit(str(src).strip()).path)
        except Exception:
            return None
        f = self.by_path.get((path or "").lower())
        if not f:
            return None
        if f["path"] in self.done:
            return self.done[f["path"]]
        if self.existing + len(self.created) >= MAX_ASSETS_PER_SITE:
            return None
        try:
            data = self.db.storage.from_(BUCKET_FILES).download(f["storage_path"])
            if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_ASSET_BYTES:
                return None
            mime = self._sniff(bytes(data))
            if not mime:
                return None
            from app.services import site_image_service
            data, mime = site_image_service.optimise(bytes(data), mime)
            stem = re.sub(r"[^a-z0-9_]", "_", f["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower())[:24].strip("_") or "image"
            slot = f"imp_{stem}"[:40]
            key = f"{self.site_id}/{slot}-{secrets.token_hex(4)}.{site_image_service.extension_for(mime)}"
            self.db.storage.from_(BUCKET_ASSETS).upload(path=key, file=data, file_options={"content-type": mime, "upsert": "true"})
            url = self.db.storage.from_(BUCKET_ASSETS).get_public_url(key)
            url = url if isinstance(url, str) else (url or {}).get("publicUrl") or (url or {}).get("publicURL")
            row = {"site_id": self.site_id, "slot": slot, "storage_path": key, "public_url": url, "mime_type": mime,
                   "bytes": len(data), "source": "editor", "created_at": _now_iso(), "updated_at": _now_iso()}
            inserted = _one(self.db.table("site_assets").insert(row).execute().data) or {}
            if not inserted.get("id"):
                self.db.storage.from_(BUCKET_ASSETS).remove([key])
                return None
            self.created.append({"id": inserted["id"], "storage_path": key})
            self.public[inserted["id"]] = {"public_url": url}
            self.done[f["path"]] = inserted["id"]
            return inserted["id"]
        except Exception as exc:  # S14: one unreadable picture must not stop the run
            logger.warning("site_import_editable: could not register %s: %s", src, exc)
            return None

    def cleanup(self) -> None:
        """Undo every photo this run registered (a failed run leaves nothing behind)."""
        for c in self.created:
            try:
                self.db.table("site_assets").delete().eq("id", c["id"]).execute()
                self.db.storage.from_(BUCKET_ASSETS).remove([c["storage_path"]])
            except Exception as exc:  # S14
                logger.warning("site_import_editable: cleanup failed asset=%s: %s", c.get("id"), exc)
        self.created, self.done, self.public = [], {}, {}


# ------------------------------------------------------------------ checks on a plan's result

def _validate_content(content: dict) -> tuple:
    """(clean content dict, errors in plain words)."""
    from pydantic import ValidationError
    from app.models.sites import SiteContentV1
    try:
        model = SiteContentV1.model_validate(content)
    except ValidationError as exc:
        errs = []
        for e in exc.errors()[:12]:
            where = ".".join(str(x) for x in e.get("loc", ()))
            if e.get("type") == "missing":
                errs.append(f"{where}: this field is required but no element was slotted for it")
            else:
                errs.append(f"{where}: {e.get('msg')}")
        return {}, errs
    return model.model_dump(mode="json"), []


def _attempt(html: str, plan: dict, registrar: Registrar) -> dict:
    """Everything after the model's answer. Returns {"ok": True, ...result} or {"ok": False, "errors": [...]}."""
    res = slotting.apply_plan(html, plan, asset_for=registrar)
    if res["errors"]:
        return {"ok": False, "errors": res["errors"]}
    content, errs = _validate_content(res["content"])
    if errs:
        return {"ok": False, "errors": errs}
    manifest, slot_errors = premium_slots.analyse(res["skeleton"], content)
    if slot_errors:
        return {"ok": False, "errors": slot_errors}
    try:
        filled = slotting.fill(res["skeleton"], content, registrar.public, export=False)
        filled_export = slotting.fill(res["skeleton"], content, {k: {"export_path": f"images/{k}.jpg"} for k in registrar.public}, export=True)
    except Exception as exc:  # S14
        return {"ok": False, "errors": [f"The marked page could not be filled ({type(exc).__name__})."]}
    diffs = slotting.compare(html, filled)
    if not diffs:
        diffs = slotting.compare(html, filled_export)
    if diffs:
        return {"ok": False, "errors": ["Proof failed: " + d for d in diffs[:5]]}
    return {"ok": True, "skeleton": res["skeleton"], "content": content, "manifest": manifest, "warnings": res["warnings"]}


# ------------------------------------------------------------------ the job

def _fail(db: Any, design: dict, usage: gen.Usage, started: float, model: str, errors: list, registrar: Optional[Registrar] = None,
          reason: Optional[str] = None) -> dict:
    if registrar:
        registrar.cleanup()
    spent = gen.cost_usd(model, usage.input_tokens, usage.output_tokens)
    _write_meta(db, design, status="failed", errors=errors[:12], warnings=[], finished_at=_now_iso(), cost_usd=spent, reason=reason)
    db.table("site_designs").update({"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "cost_usd": spent,
                                     "model": model, "prompt_version": prompt.PROMPT_VERSION,
                                     "duration_ms": int((time.monotonic() - started) * 1000)}).eq("id", design["id"]).eq("org_id", design["org_id"]).execute()
    _log_usage(db, design["org_id"], model, usage)
    gen._log_event(db, design["org_id"], design["site_id"], "system", "import_editable_failed",
                   {"design_id": design["id"], "cost_usd": spent, "errors": errors[:5]})
    return {"ok": False, "design_id": design["id"], "outcome": "level1", "cost_usd": spent, "errors": errors}


def _log_usage(db: Any, org_id: str, model: str, usage: gen.Usage) -> None:
    try:
        from app.services.ai_service import _log_claude_usage
        _log_claude_usage(db, org_id=org_id, function_name="site_import_editable", model=model,
                          input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
    except Exception as exc:  # S14
        logger.warning("site_import_editable: usage log failed: %s", exc)


def run(db: Any, design_id: str, claude: gen.ClaudeFn = gen.call_claude_checked) -> dict:
    """The worker job. Never raises."""
    started = time.monotonic()
    design = _one((db.table("site_designs").select("*").eq("id", design_id).eq("kind", "import").limit(1).execute()).data)
    if not design or not design.get("files_prefix"):
        return {"ok": False, "design_id": design_id, "outcome": "not_found"}
    if (level2_of(design) or {}).get("status") != "running":
        return {"ok": False, "design_id": design_id, "outcome": "already_running"}      # a late-acknowledged task delivered twice
    _write_meta(db, design, status="working")
    org_id, site_id = design["org_id"], design["site_id"]
    usage = gen.Usage()
    settings = gen.settings_for(db, org_id)
    model = settings.get("site_premium_model") or gen.DEFAULT_MODEL
    registrar: Optional[Registrar] = None
    try:
        html = design.get("skeleton_html") or ""
        if not html.strip():
            return _fail(db, design, usage, started, model, ["The imported page is empty."])
        existing = len((db.table("site_assets").select("id").eq("site_id", site_id).execute().data or []))
        files = (design.get("import_meta") or {}).get("files") or []
        registrar = Registrar(db, site_id, files, existing)

        root = dom.parse(html)
        dom.assign_ids(root)
        outline = slotting.outline(root)
        system = prompt.system_prompt(premium_prompt.content_vocabulary())

        problems: list = []
        plan: Any = None
        result: Optional[dict] = None
        attempts = 0
        for attempt in (1, 2):
            attempts = attempt
            user = prompt.build_user(outline, problems or None, plan if problems else None)
            text, i, o = claude(system, user, PLAN_MAX_TOKENS, model)
            usage.add(i, o)
            try:
                plan = prompt.parse_plan(text)
            except prompt.PlanParseError as exc:
                problems, plan = exc.errors, None
                continue
            outcome = _attempt(html, plan, registrar)
            if outcome["ok"]:
                result = outcome
                break
            problems = outcome["errors"]
            registrar.cleanup()          # the next attempt registers its own photos
        if not result:
            return _fail(db, design, usage, started, model, problems, registrar)
    except gen.GenerationFailed as exc:
        if exc.reason:
            gen.alert_service_problem(db, org_id, site_id, exc.reason)
        return _fail(db, design, usage, started, model, [str(exc)], registrar, reason=exc.reason)
    except Exception as exc:  # S14 - a bug must never leave the design 'working'
        logger.exception("site_import_editable: unexpected failure design=%s", design_id)
        return _fail(db, design, usage, started, model, [f"Unexpected problem ({type(exc).__name__})."], registrar)

    spent = gen.cost_usd(model, usage.input_tokens, usage.output_tokens)
    meta = dict(design.get("import_meta") or {})
    meta["slot_skeleton"] = result["skeleton"]
    meta["extracted_content"] = result["content"]
    meta["level2"] = {**(meta.get("level2") or {}), "status": "ready", "errors": [], "warnings": result["warnings"][:10],
                      "finished_at": _now_iso(), "cost_usd": spent, "attempts": attempts,
                      "fields": len(result["manifest"].get("slots") or []), "photos": [c["id"] for c in registrar.created]}
    saved = (db.table("site_designs").update({
        "import_meta": meta, "slot_manifest": result["manifest"], "editable": True,
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "cost_usd": spent, "model": model,
        "prompt_version": prompt.PROMPT_VERSION, "duration_ms": int((time.monotonic() - started) * 1000),
    }).eq("id", design_id).eq("org_id", org_id).execute()).data
    if not saved:
        registrar.cleanup()
        return {"ok": False, "design_id": design_id, "outcome": "superseded"}
    _log_usage(db, org_id, model, usage)
    gen._log_event(db, org_id, site_id, "system", "import_editable_done",
                   {"design_id": design_id, "cost_usd": spent, "attempts": attempts, "fields": meta["level2"]["fields"],
                    "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})
    return {"ok": True, "design_id": design_id, "outcome": "editable", "cost_usd": spent, "fields": meta["level2"]["fields"]}


# ------------------------------------------------------------------ using the result

def editable_design(db: Any, site: dict) -> Optional[dict]:
    """The site's current import design when it is a ready Level 2 design (marked page present), else None."""
    did = site.get("current_design_id")
    if not did or (site.get("tier") or "standard") != "imported":
        return None
    row = _one((db.table("site_designs").select("*").eq("id", did).eq("site_id", site["id"]).eq("org_id", site["org_id"])
                .eq("kind", "import").eq("status", "ready").limit(1).execute()).data)
    if not row or not row.get("files_prefix") or not row.get("editable"):
        return None
    if not (row.get("import_meta") or {}).get("slot_skeleton"):
        return None
    return row


def adopt_content(db: Any, org_id: str, site: dict, design: dict, actor: str) -> dict:
    """Make the page's own text the site's content (so the editor shows what the page says). The old content is kept as a revision
    first. Returns the new content."""
    content = (design.get("import_meta") or {}).get("extracted_content")
    if not content:
        raise ValidationFailed("This design has no extracted content. Make it editable first.")
    old = site.get("content") or {}
    if old:
        try:   # the same undo stack the editor uses, so "undo" brings the previous text back
            db.table("site_revisions").insert({"org_id": org_id, "site_id": site["id"], "content": old,
                                               "recipe": site.get("recipe"), "created_at": _now_iso()}).execute()
        except Exception as exc:  # S14: keep the old text in the event log instead, never lose it silently
            logger.warning("site_import_editable: revision snapshot failed site=%s: %s", site.get("id"), exc)
            gen._log_event(db, org_id, site["id"], actor, "import_content_replaced", {"previous_content": old})
    db.table("sites").update({"content": content, "updated_at": _now_iso()}).eq("id", site["id"]).eq("org_id", org_id).execute()
    site["content"] = content
    return content


def editor_info(db: Any, org_id: str, site: dict) -> Optional[dict]:
    """For the builder editor: None unless the site's live page is a Level 2 import. Otherwise which content groups the page shows
    (the editor hides the others and the Standard design controls). Never raises."""
    try:
        row = editable_design(db, {**site, "org_id": org_id})
        if not row:
            return None
        from app.services import site_premium_service
        return {"active": True, "design_id": row["id"], "version": row.get("version"),
                "used": site_premium_service.used_top_level(row.get("slot_manifest"))}
    except Exception as exc:  # S14
        logger.warning("site_import_editable: editor_info failed site=%s: %s", site.get("id"), exc)
        return None
