"""
app/routers/public_forms.py
-----------------------------
SITE-1B — public, unauthenticated brief-form routes. Prefix: /api/v1/forms
Spec §7.3 / §17 / §18.

No login: the token itself (hashed, spec §18) is the only credential. Mirrors
routers/public_sites.py's "no org auth, token/slug scoped" shape, not
routers/sites.py's authenticated one.

Client-version redaction (spec §7.3): this payload never includes pricing,
other sites, or live preview links for ANYONE, builder or client, so no
extra branching is needed for that. What differs by `audience` is only the
header — the client version shows the builder's own business_name instead
of "Opsra" — and the closing message after submit.

Rate limiting here (60 autosaves/min/token, 5 submits/day/token, spec §18)
is a simple in-process counter — enough to blunt a retry loop or a single
abusive client, but it resets on deploy/restart and isn't shared across
workers. A durable limiter (Redis or a DB counter) is a follow-up.
"""
from __future__ import annotations

import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.database import get_supabase
from app.models.common import ok
from app.models.sites import (
    SiteBriefFormAnswersPatch,
    SiteBriefFormSubmit,
    hash_form_token,
)
from app.services import site_design_registry, site_renderer

logger = logging.getLogger(__name__)
router = APIRouter()

_ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
_MAX_ASSET_BYTES = 8 * 1024 * 1024
_MAX_PHOTOS_PER_FORM = 20   # spec §18
_AUTOSAVE_LIMIT_PER_MIN = 60
_SUBMIT_LIMIT_PER_DAY = 5

_autosave_hits: dict[str, list[float]] = defaultdict(list)
_submit_hits: dict[str, list[float]] = defaultdict(list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _rate_limited(bucket: dict, key: str, limit: int, window_s: float) -> bool:
    now = time.time()
    hits = [t for t in bucket[key] if now - t < window_s]
    hits.append(now)
    bucket[key] = hits
    return len(hits) > limit


def _get_form_or_404(db, token: str) -> dict:
    token_hash = hash_form_token(token)
    row = _one((db.table("site_brief_forms").select("*").eq("token_hash", token_hash).limit(1).execute()).data)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "This link isn't valid."})
    if row["status"] == "revoked":
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "This link has been cancelled."})
    expires_at = row.get("expires_at")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_dt and row["status"] == "open":
                db.table("site_brief_forms").update({"status": "expired", "updated_at": _now_iso()}).eq("id", row["id"]).execute()
                row["status"] = "expired"
        except Exception:
            pass
    if row["status"] == "expired":
        raise HTTPException(status_code=410, detail={"code": "EXPIRED", "message": "This link has expired — ask for a new one."})
    return row


def _sniff_image(file_bytes: bytes, declared_mime: str) -> bool:
    sigs = {
        "image/jpeg": (b"\xff\xd8\xff",),
        "image/png": (b"\x89PNG\r\n\x1a\n",),
        "image/webp": (b"RIFF",),
    }.get(declared_mime)
    if not sigs or not any(file_bytes.startswith(s) for s in sigs):
        return False
    if declared_mime == "image/webp" and file_bytes[8:12] != b"WEBP":
        return False
    return True


# ─────────────────────────────── GET (load the form) ───────────────────────────────

@router.get("/forms/{token}")
def get_form(token: str, db=Depends(get_supabase)):
    form = _get_form_or_404(db, token)

    if not form.get("opened_at"):
        db.table("site_brief_forms").update({"opened_at": _now_iso(), "updated_at": _now_iso()}).eq("id", form["id"]).execute()

    builder = _one((db.table("site_builders").select("business_name, full_name").eq("id", form["builder_id"]).execute()).data) or {}
    settings = _one((db.table("site_builder_settings").select("brand_name").eq("org_id", form["org_id"]).execute()).data) or {}

    preset = None
    if form.get("preset_id"):
        preset = _one((db.table("site_presets").select("id, key, name, labels, brief_questions, max_items")
                       .eq("id", form["preset_id"]).execute()).data)
        if preset:  # SITE-1C-2: every form asks how the site should feel (added here, not stored per template)
            preset["brief_questions"] = site_design_registry.with_personality_question(preset.get("brief_questions"))

    presets = []
    if not preset:
        presets = (db.table("site_presets").select("id, key, name").eq("org_id", form["org_id"])
                   .eq("is_active", True).order("name").limit(10).execute()).data or []

    header_name = builder.get("business_name") if form["audience"] == "client" else (settings.get("brand_name") or "Opsra")

    return ok(data={
        "audience": form["audience"],
        "status": form["status"],
        "header_name": header_name,
        "answers": form.get("answers") or {},
        "preset": preset,
        "presets": presets,       # only sent when no preset is pinned yet — the form lets the user pick one
        "max_photos": _MAX_PHOTOS_PER_FORM,
        "expires_at": form.get("expires_at"),
    })


# ─────────────────────────────── PATCH (autosave) ───────────────────────────────

@router.patch("/forms/{token}")
def autosave_form(token: str, payload: SiteBriefFormAnswersPatch, db=Depends(get_supabase)):
    form = _get_form_or_404(db, token)
    if form["status"] != "open":
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "This form is no longer open for editing."})

    if _rate_limited(_autosave_hits, form["token_hash"], _AUTOSAVE_LIMIT_PER_MIN, 60.0):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Saving too fast — please slow down."})

    if (payload.website or "").strip():
        # Honeypot tripped — pretend success, save nothing. Spec §18.
        logger.info("[SITE-1B] honeypot tripped on autosave token_hash=%s", form["token_hash"][:8])
        return ok(data={"saved": True})

    merged = dict(form.get("answers") or {})
    # `_photos` is server-owned (the upload route stores full file records there). The page only keeps
    # picture URLs for display, and merging those back used to overwrite the records, so photos were
    # lost at submit. Never accept it from the client.
    merged.update({k: v for k, v in (payload.answers or {}).items() if k != "_photos"})
    updates = {"answers": merged, "last_saved_at": _now_iso(), "updated_at": _now_iso()}
    if payload.preset_id and not form.get("preset_id"):
        updates["preset_id"] = payload.preset_id
    db.table("site_brief_forms").update(updates).eq("id", form["id"]).execute()
    return ok(data={"saved": True})


# ─────────────────────────────── Photo upload ───────────────────────────────

@router.post("/forms/{token}/assets", status_code=status.HTTP_201_CREATED)
async def upload_form_asset(
    token: str,
    slot: str = Query(..., max_length=40),
    file: UploadFile = File(...),
    db=Depends(get_supabase),
):
    form = _get_form_or_404(db, token)
    if form["status"] != "open":
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "This form is no longer open for editing."})

    photos = dict((form.get("answers") or {}).get("_photos") or {})
    existing_count = sum(len(v) for v in photos.values())
    if existing_count >= _MAX_PHOTOS_PER_FORM:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": f"A form can have at most {_MAX_PHOTOS_PER_FORM} photos"})

    if file.content_type not in _ALLOWED_IMAGE_MIME:
        raise HTTPException(status_code=400, detail="Unsupported file type. Allowed: JPEG, PNG, WebP.")
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_ASSET_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds the 8 MB limit.")
    if not _sniff_image(file_bytes, file.content_type):
        raise HTTPException(status_code=400, detail="File content doesn't match its declared type.")

    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[file.content_type]
    storage_path = f"forms/{form['token_hash'][:16]}/{slot}-{secrets.token_hex(4)}.{ext}"
    db.storage.from_("site-assets").upload(path=storage_path, file=file_bytes,
                                            file_options={"content-type": file.content_type, "upsert": "true"})
    public_url = db.storage.from_("site-assets").get_public_url(storage_path)

    photos.setdefault(slot, []).append({"storage_path": storage_path, "public_url": public_url, "mime_type": file.content_type, "bytes": len(file_bytes)})
    answers = dict(form.get("answers") or {})
    answers["_photos"] = photos
    db.table("site_brief_forms").update({"answers": answers, "last_saved_at": _now_iso(), "updated_at": _now_iso()}).eq("id", form["id"]).execute()
    return ok(data={"slot": slot, "public_url": public_url}, message="Photo uploaded")


def _photo_record(entry) -> Optional[dict]:
    """A stored photo record, or one rebuilt from a bare public URL (forms autosaved before the `_photos`
    fix hold URLs instead of records). None if it can't be read."""
    if isinstance(entry, dict) and entry.get("storage_path") and entry.get("public_url"):
        return entry
    if isinstance(entry, str) and "/site-assets/" in entry:
        path = entry.split("/site-assets/", 1)[1].split("?", 1)[0]
        ext = path.rsplit(".", 1)[-1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext)
        if path and mime:
            return {"storage_path": path, "public_url": entry, "mime_type": mime, "bytes": 0}
    return None


# ─────────────────────────────── Submit ───────────────────────────────

@router.post("/forms/{token}/submit")
def submit_form(token: str, payload: SiteBriefFormSubmit, db=Depends(get_supabase)):
    form = _get_form_or_404(db, token)
    if form["status"] != "open":
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "This form has already been submitted."})

    if (payload.website or "").strip():
        # Honeypot tripped — pretend success, create nothing. Spec §18.
        logger.info("[SITE-1B] honeypot tripped on submit token_hash=%s", form["token_hash"][:8])
        return ok(data={"submitted": True})

    if _rate_limited(_submit_hits, form["token_hash"], _SUBMIT_LIMIT_PER_DAY, 86400.0):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many submission attempts."})

    if not form.get("preset_id"):
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Please choose a business type before submitting."})
    preset = _one((db.table("site_presets").select("*").eq("id", form["preset_id"]).execute()).data)
    if not preset:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "That business type is no longer available."})

    merged_answers = dict(form.get("answers") or {})
    merged_answers.update({k: v for k, v in (payload.answers or {}).items() if k != "_photos"})  # see autosave
    photos = merged_answers.pop("_photos", {})

    slug = site_renderer.generate_slug(payload.client_business_name)
    if (db.table("sites").select("id").eq("slug", slug).execute()).data:
        slug = site_renderer.generate_slug(payload.client_business_name)

    site_row = {
        "org_id": form["org_id"], "builder_id": form["builder_id"], "preset_id": form["preset_id"],
        "client_business_name": payload.client_business_name, "slug": slug,
        "status": "brief_complete", "brief": merged_answers, "content_source": "builder_words",
        "revision_count": 0, "ai_generation_count": 0, "design_rolls": 0,
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    site_res = db.table("sites").insert(site_row).execute()
    site = _one(site_res.data) or site_row

    for slot, uploads in (photos or {}).items():
        for u in uploads:
            u = _photo_record(u)
            if not u:
                logger.warning("[SITE-1B] submit_form: skipped an unreadable photo entry site=%s slot=%s", site["id"], slot)
                continue
            try:
                db.table("site_assets").insert({
                    "site_id": site["id"], "slot": slot, "storage_path": u["storage_path"],
                    "public_url": u["public_url"], "mime_type": u["mime_type"], "bytes": u["bytes"],
                    "source": "brief_form", "created_at": _now_iso(), "updated_at": _now_iso(),
                }).execute()
            except Exception:
                logger.exception("[SITE-1B] submit_form: asset copy failed site=%s slot=%s", site["id"], slot)

    # SITE-2: generate content/recipe from the brief now that photos are attached.
    # Never allowed to fail the submission — falls back to builder_words internally.
    try:
        from app.services import site_copy_service
        full_site = _one((db.table("sites").select("*").eq("id", site["id"]).execute()).data) or site
        content, recipe, source = site_copy_service.generate_content_and_recipe(db, full_site, preset, form["org_id"])
        site_copy_service.apply_generated_content(db, site["id"], content, recipe, source)
    except Exception:
        logger.exception("[SITE-2] content generation failed site=%s", site.get("id"))

    db.table("site_brief_forms").update({
        "site_id": site["id"], "status": "submitted", "answers": merged_answers,
        "submitted_at": _now_iso(), "submit_count": (form.get("submit_count") or 0) + 1,
        "updated_at": _now_iso(),
    }).eq("id", form["id"]).execute()

    _notify_builder_of_submission(db, form)

    if form["audience"] == "client":
        builder = _one((db.table("site_builders").select("business_name").eq("id", form["builder_id"]).execute()).data) or {}
        thanks = f"Thank you — {builder.get('business_name') or 'we'} will be in touch."
        return ok(data={"submitted": True, "message": thanks})
    return ok(data={"submitted": True, "message": "Thanks! We're building your preview now — we'll message you on WhatsApp shortly."})


def _notify_builder_of_submission(db, form: dict) -> None:
    """Spec §7.3: if the builder messaged in the last 24h, a plain text reply is fine;
    outside that window Meta requires a pre-approved template, which isn't wired up
    yet (still pending Meta approval per Decisions_Summary) — so for now this always
    tries the plain-text route and relies on send_agent_text_message's own S14 safety
    net to no-op quietly if WhatsApp rejects it as outside the 24h window."""
    try:
        builder = _one((db.table("site_builders").select("*").eq("id", form["builder_id"]).execute()).data)
        if not builder:
            return
        number_row = _one((db.table("whatsapp_numbers").select("*").eq("org_id", form["org_id"])
                            .eq("wa_sales_mode", "site_builder").limit(1).execute()).data)
        if not number_row:
            return
        if form["audience"] == "client":
            label = form.get("client_label") or "Your client"
            text = f"{label}'s details are in. Building the preview now — we'll send it here shortly."
        else:
            text = "Your details are in. Building your preview now — we'll send it here shortly."
        from app.services.whatsapp_service import send_agent_text_message
        send_agent_text_message(
            db=db, org_id=form["org_id"], phone_number=builder["phone_number"], lead_id=builder.get("lead_id"),
            message=text, phone_id=number_row.get("phone_id"), access_token=number_row.get("access_token"),
        )
    except Exception:
        logger.exception("[SITE-1B] _notify_builder_of_submission failed form=%s", form.get("id"))
