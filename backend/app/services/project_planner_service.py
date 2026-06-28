"""
app/services/project_planner_service.py — PROJECT-PLANNER v2 business logic.

Follows the same CRITICAL PATTERNS as whatsapp_service.py / lead_service.py:
  - Pattern 9  : _normalise_data() on every .maybe_single() result
  - S1/S2      : org_id always passed in explicitly from get_current_org —
                 every query filters .eq("org_id", org_id)
  - S14        : one record failure never silently breaks a list operation;
                 Storage/network failures surface as HTTPException, not swallowed

Storage:
  - Private bucket "project-planner-docs" (create manually in Supabase
    dashboard if it does not exist: Storage → New bucket → Private).
  - Allowed MIME types restricted to the Technical Spec §11.5 global
    allow-list: image/jpeg, image/png, image/gif, image/webp,
    application/pdf, text/csv. NOTE: .docx is NOT on the spec's allowed
    list — uploading one will return 415. If Word-doc support is wanted,
    that's a Technical Spec amendment, not something to quietly add here.
  - Max size 25MB (matches the platform-wide limit already enforced for
    WhatsApp media).
  - Documents are accessed only via 1-hour signed URLs, never public URLs.
"""
from __future__ import annotations

import logging
import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.models.common import ErrorCode
from app.models.project_planner_models import (
    PhaseCreate,
    PhaseUpdate,
    PlanCreate,
    PlanUpdate,
    StrategyCreate,
    StrategyUpdate,
    TaskCreate,
    TaskUpdate,
)
#
# NOTE: lead_service.write_audit_log() is NOT used here. Its real signature
# is write_audit_log(db, org_id, user_id, action, resource_type, resource_id=...),
# but its body hardcodes resource_type="lead" regardless of what's passed in —
# using it here would mislabel every Project Planner audit row as a lead
# event. _audit_log() below replicates the same audit_logs insert shape with
# the correct resource_type instead.

logger = logging.getLogger(__name__)

STORAGE_BUCKET = "project-planner-docs"

ALLOWED_DOCUMENT_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/csv",
}
MAX_DOCUMENT_SIZE = 25 * 1024 * 1024  # 25 MB — matches platform-wide limit (Tech Spec §11.5)

APPROVAL_ORDER = ["draft", "reviewed", "approved"]

# Default execution-plan template applied to every new strategy —
# mirrors genericPlanFor() from the original standalone tool.
DEFAULT_PHASES = [
    {
        "title": "Immediate", "sub_label": "Week 1",
        "tasks": [
            {"title_suffix": "Assign an owner for {title}", "description": "Name one person accountable for getting this strategy off the ground."},
            {"title_suffix": "Confirm budget and resources", "description": "Lock in the spend and people needed before any work starts."},
        ],
    },
    {
        "title": "Setup & foundation", "sub_label": "Weeks 2-4",
        "tasks": [
            {"title_suffix": "Define scope and requirements", "description": "Spell out exactly what this strategy includes, who it's for, and who's involved."},
            {"title_suffix": "Select vendors, partners or tools", "description": "Lock in any external suppliers, platforms or partners needed to execute."},
            {"title_suffix": "Produce core assets and materials", "description": "Creative, copy, or physical materials needed before launch."},
        ],
    },
    {
        "title": "Launch & rollout", "sub_label": "Weeks 5-8",
        "tasks": [
            {"title_suffix": "Launch {title}", "description": "Go live and start execution."},
            {"title_suffix": "Monitor early results and fix friction points", "description": "Watch the first few weeks closely and resolve issues as they surface."},
        ],
    },
    {
        "title": "Review & decision", "sub_label": "Weeks 9-12",
        "tasks": [
            {"title_suffix": "Review performance against goals", "description": "Compare actual results to what was expected when this strategy was approved."},
            {"title_suffix": "Decide to scale, adjust, or stop", "description": "Make the call on next steps based on results, not on the original assumption."},
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_log(db, org_id: str, user_id: Optional[str], action: str, resource_type: str, resource_id: Optional[str] = None) -> None:
    """
    Writes directly to audit_logs — same column shape as
    lead_service.write_audit_log(), but with the correct resource_type
    (that function hardcodes "lead" internally, so it can't be reused here).
    S14: audit logging failure must never block the actual mutation.
    """
    try:
        db.table("audit_logs").insert({
            "org_id": org_id,
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "old_value": None,
            "new_value": None,
        }).execute()
    except Exception as exc:
        logger.warning("_audit_log: failed to write audit row action=%s resource_type=%s: %s", action, resource_type, exc)


def _normalise_data(result_data):
    """Pattern 9 — normalise list vs dict from .maybe_single()."""
    data = result_data
    if isinstance(data, list):
        data = data[0] if data else None
    return data


def _plan_or_404(db, org_id: str, plan_id: str) -> dict:
    result = (
        db.table("project_plans")
        .select("*")
        .eq("id", plan_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    plan = _normalise_data(result.data)
    if not plan:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)
    return plan


def _strategy_or_404(db, org_id: str, strategy_id: str) -> dict:
    result = (
        db.table("project_strategies")
        .select("*")
        .eq("id", strategy_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    strategy = _normalise_data(result.data)
    if not strategy:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)
    return strategy


def _phase_or_404(db, org_id: str, phase_id: str) -> dict:
    result = (
        db.table("project_strategy_phases")
        .select("*")
        .eq("id", phase_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    phase = _normalise_data(result.data)
    if not phase:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)
    return phase


def _task_or_404(db, org_id: str, task_id: str) -> dict:
    result = (
        db.table("project_tasks")
        .select("*")
        .eq("id", task_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    task = _normalise_data(result.data)
    if not task:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)
    return task


def _seed_default_phases(db, org_id: str, strategy_id: str, title: str) -> None:
    """Create the default 4-phase execution-plan template for a new strategy."""
    for phase_idx, phase_tpl in enumerate(DEFAULT_PHASES):
        phase_row = (
            db.table("project_strategy_phases")
            .insert({
                "org_id": org_id,
                "strategy_id": strategy_id,
                "title": phase_tpl["title"],
                "sub_label": phase_tpl["sub_label"],
                "position": phase_idx,
            })
            .execute()
        )
        phase_data = _normalise_data(phase_row.data)
        phase_id = (phase_data or {}).get("id")
        if not phase_id:
            # S14 — one phase failing to seed shouldn't abort strategy creation;
            # log and move on rather than raising mid-loop.
            logger.warning(
                "_seed_default_phases: phase insert returned no id for strategy=%s",
                strategy_id,
            )
            continue

        task_rows = [
            {
                "org_id": org_id,
                "phase_id": phase_id,
                "title": t["title_suffix"].format(title=title),
                "description": t["description"],
                "status": "not_started",
                "position": task_idx,
            }
            for task_idx, t in enumerate(phase_tpl["tasks"])
        ]
        if task_rows:
            db.table("project_tasks").insert(task_rows).execute()


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def list_plans(db, org_id: str) -> list:
    result = (
        db.table("project_plans")
        .select("*")
        .eq("org_id", org_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def create_plan(db, org_id: str, user_id: str, payload: PlanCreate) -> dict:
    row = (
        db.table("project_plans")
        .insert({
            "org_id": org_id,
            "name": payload.name,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
        .execute()
    )
    plan = _normalise_data(row.data)
    _audit_log(db, org_id, user_id, "project_plan_created", "project_plan", plan["id"])
    return plan


def update_plan(db, org_id: str, user_id: str, plan_id: str, payload: PlanUpdate) -> dict:
    _plan_or_404(db, org_id, plan_id)
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        return _plan_or_404(db, org_id, plan_id)
    updates["updated_at"] = _now_iso()
    row = (
        db.table("project_plans")
        .update(updates)
        .eq("id", plan_id)
        .eq("org_id", org_id)
        .execute()
    )
    result = _normalise_data(row.data) or _plan_or_404(db, org_id, plan_id)
    _audit_log(db, org_id, user_id, "project_plan_updated", "project_plan", plan_id)
    return result


def delete_plan(db, org_id: str, user_id: str, plan_id: str) -> None:
    _plan_or_404(db, org_id, plan_id)
    db.table("project_plans").delete().eq("id", plan_id).eq("org_id", org_id).execute()
    _audit_log(db, org_id, user_id, "project_plan_deleted", "project_plan", plan_id)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def list_strategies(db, org_id: str, plan_id: str) -> list:
    """Returns strategies for a plan, each nested with its phases and tasks."""
    strategies_result = (
        db.table("project_strategies")
        .select("*")
        .eq("org_id", org_id)
        .eq("plan_id", plan_id)
        .order("phase", desc=False)
        .order("position", desc=False)
        .execute()
    )
    strategies = strategies_result.data or []
    if not strategies:
        return []

    strategy_ids = [s["id"] for s in strategies]

    phases_result = (
        db.table("project_strategy_phases")
        .select("*")
        .eq("org_id", org_id)
        .in_("strategy_id", strategy_ids)
        .order("position", desc=False)
        .execute()
    )
    phases_by_strategy: dict = {}
    for p in (phases_result.data or []):
        phases_by_strategy.setdefault(p["strategy_id"], []).append(p)

    phase_ids = [p["id"] for plist in phases_by_strategy.values() for p in plist]
    tasks_by_phase: dict = {}
    if phase_ids:
        tasks_result = (
            db.table("project_tasks")
            .select("*")
            .eq("org_id", org_id)
            .in_("phase_id", phase_ids)
            .order("position", desc=False)
            .execute()
        )
        for t in (tasks_result.data or []):
            tasks_by_phase.setdefault(t["phase_id"], []).append(t)

    docs_result = (
        db.table("project_strategy_documents")
        .select("id, strategy_id, file_name, external_link, uploaded_at")
        .eq("org_id", org_id)
        .in_("strategy_id", strategy_ids)
        .execute()
    )
    docs_by_strategy: dict = {}
    for d in (docs_result.data or []):
        docs_by_strategy.setdefault(d["strategy_id"], []).append(d)

    for s in strategies:
        s_phases = phases_by_strategy.get(s["id"], [])
        for p in s_phases:
            p["tasks"] = tasks_by_phase.get(p["id"], [])
        s["phases"] = s_phases
        s["documents"] = docs_by_strategy.get(s["id"], [])

    return strategies


def create_strategy(db, org_id: str, user_id: str, payload: StrategyCreate) -> dict:
    _plan_or_404(db, org_id, payload.plan_id)

    row = (
        db.table("project_strategies")
        .insert({
            "org_id": org_id,
            "plan_id": payload.plan_id,
            "phase": payload.phase,
            "channel": payload.channel,
            "title": payload.title,
            "description": payload.description,
            "included": True,
            "approval_status": "draft",
            "position": 0,
            "created_by": user_id,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
        .execute()
    )
    strategy = _normalise_data(row.data)
    if not strategy:
        raise HTTPException(status_code=503, detail="Failed to create strategy — please try again")

    _seed_default_phases(db, org_id, strategy["id"], payload.title)
    _audit_log(db, org_id, user_id, "project_strategy_created", "project_strategy", strategy["id"])

    # Return the fully nested version (with its freshly seeded default
    # phases/tasks) rather than the bare insert result, so the frontend has
    # the starter template immediately without a second round-trip.
    nested = list_strategies(db, org_id, payload.plan_id)
    return next((s for s in nested if s["id"] == strategy["id"]), strategy)


def update_strategy(db, org_id: str, user_id: str, strategy_id: str, payload: StrategyUpdate) -> dict:
    _strategy_or_404(db, org_id, strategy_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _strategy_or_404(db, org_id, strategy_id)
    updates["updated_at"] = _now_iso()
    db.table("project_strategies").update(updates).eq("id", strategy_id).eq("org_id", org_id).execute()
    _audit_log(db, org_id, user_id, "project_strategy_updated", "project_strategy", strategy_id)
    return _strategy_or_404(db, org_id, strategy_id)


def delete_strategy(db, org_id: str, user_id: str, strategy_id: str) -> None:
    _strategy_or_404(db, org_id, strategy_id)
    db.table("project_strategies").delete().eq("id", strategy_id).eq("org_id", org_id).execute()
    _audit_log(db, org_id, user_id, "project_strategy_deleted", "project_strategy", strategy_id)


def approve_strategy(db, org_id: str, strategy_id: str, user_id: str) -> dict:
    """Advances approval_status one step: draft -> reviewed -> approved."""
    strategy = _strategy_or_404(db, org_id, strategy_id)
    current = strategy.get("approval_status", "draft")
    idx = APPROVAL_ORDER.index(current) if current in APPROVAL_ORDER else 0
    if idx >= len(APPROVAL_ORDER) - 1:
        raise HTTPException(status_code=400, detail="Strategy is already fully approved")
    next_status = APPROVAL_ORDER[idx + 1]

    updates = {"approval_status": next_status, "updated_at": _now_iso()}
    if next_status == "approved":
        updates["approved_by"] = user_id
        updates["approved_at"] = _now_iso()

    db.table("project_strategies").update(updates).eq("id", strategy_id).eq("org_id", org_id).execute()
    _audit_log(db, org_id, user_id, f"project_strategy_{next_status}", "project_strategy", strategy_id)
    return _strategy_or_404(db, org_id, strategy_id)


def revert_strategy(db, org_id: str, strategy_id: str, user_id: str) -> dict:
    """Steps approval_status back one stage: approved -> reviewed -> draft."""
    strategy = _strategy_or_404(db, org_id, strategy_id)
    current = strategy.get("approval_status", "draft")
    idx = APPROVAL_ORDER.index(current) if current in APPROVAL_ORDER else 0
    if idx <= 0:
        raise HTTPException(status_code=400, detail="Strategy is already in draft")
    prev_status = APPROVAL_ORDER[idx - 1]

    updates = {"approval_status": prev_status, "updated_at": _now_iso()}
    if prev_status != "approved":
        updates["approved_by"] = None
        updates["approved_at"] = None

    db.table("project_strategies").update(updates).eq("id", strategy_id).eq("org_id", org_id).execute()
    _audit_log(db, org_id, user_id, f"project_strategy_reverted_to_{prev_status}", "project_strategy", strategy_id)
    return _strategy_or_404(db, org_id, strategy_id)


# ---------------------------------------------------------------------------
# Phases & Tasks
# ---------------------------------------------------------------------------

def create_phase(db, org_id: str, strategy_id: str, payload: PhaseCreate) -> dict:
    _strategy_or_404(db, org_id, strategy_id)
    row = (
        db.table("project_strategy_phases")
        .insert({
            "org_id": org_id,
            "strategy_id": strategy_id,
            "title": payload.title,
            "sub_label": payload.sub_label,
            "position": payload.position,
        })
        .execute()
    )
    return _normalise_data(row.data)


def update_phase(db, org_id: str, phase_id: str, payload: PhaseUpdate) -> dict:
    _phase_or_404(db, org_id, phase_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _phase_or_404(db, org_id, phase_id)
    db.table("project_strategy_phases").update(updates).eq("id", phase_id).eq("org_id", org_id).execute()
    return _phase_or_404(db, org_id, phase_id)


def create_task(db, org_id: str, phase_id: str, payload: TaskCreate) -> dict:
    _phase_or_404(db, org_id, phase_id)
    row = (
        db.table("project_tasks")
        .insert({
            "org_id": org_id,
            "phase_id": phase_id,
            "title": payload.title,
            "description": payload.description,
            "owner_user_id": payload.owner_user_id,
            "owner_label": payload.owner_label,
            "due_date": payload.due_date,
            "status": "not_started",
            "position": 0,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
        .execute()
    )
    return _normalise_data(row.data)


def update_task(db, org_id: str, task_id: str, payload: TaskUpdate) -> dict:
    _task_or_404(db, org_id, task_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _task_or_404(db, org_id, task_id)
    updates["updated_at"] = _now_iso()
    db.table("project_tasks").update(updates).eq("id", task_id).eq("org_id", org_id).execute()
    return _task_or_404(db, org_id, task_id)


def delete_task(db, org_id: str, task_id: str) -> None:
    _task_or_404(db, org_id, task_id)
    db.table("project_tasks").delete().eq("id", task_id).eq("org_id", org_id).execute()


# ---------------------------------------------------------------------------
# Strategy documents — Storage upload + external link
# (mirrors send_whatsapp_media_message()'s Storage pattern exactly)
# ---------------------------------------------------------------------------

def upload_strategy_document(
    db,
    org_id: str,
    user_id: str,
    strategy_id: str,
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> dict:
    """
    Uploads a document to the private "project-planner-docs" bucket and
    records it against the strategy.

    Raises:
      HTTPException 413 — file exceeds 25 MB
      HTTPException 415 — unsupported content_type (Tech Spec §11.5 allow-list)
      HTTPException 503 — Supabase Storage failure
    """
    _strategy_or_404(db, org_id, strategy_id)

    if len(file_bytes) > MAX_DOCUMENT_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds maximum size of 25 MB")

    if content_type not in ALLOWED_DOCUMENT_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{content_type}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_DOCUMENT_CONTENT_TYPES))}"
            ),
        )

    safe_filename = filename.replace("/", "_").replace("\\", "_").replace("'", "").replace('"', "")
    storage_path = f"{STORAGE_BUCKET}/{org_id}/{strategy_id}/{_uuid_mod.uuid4()}_{safe_filename}"

    try:
        db.storage.from_(STORAGE_BUCKET).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type},
        )
    except Exception as exc:
        logger.warning(
            "upload_strategy_document: Supabase Storage upload failed org=%s path=%s: %s",
            org_id, storage_path, exc,
        )
        raise HTTPException(status_code=503, detail="Failed to upload file to storage — please try again")

    row = (
        db.table("project_strategy_documents")
        .insert({
            "org_id": org_id,
            "strategy_id": strategy_id,
            "file_name": safe_filename,
            "mime_type": content_type,
            "storage_path": storage_path,
            "uploaded_by": user_id,
            "uploaded_at": _now_iso(),
        })
        .execute()
    )
    document = _normalise_data(row.data)
    _audit_log(db, org_id, user_id, "project_strategy_document_uploaded", "project_strategy_document", document["id"])
    return document


def set_strategy_document_link(db, org_id: str, user_id: str, strategy_id: str, external_link: str) -> dict:
    _strategy_or_404(db, org_id, strategy_id)
    row = (
        db.table("project_strategy_documents")
        .insert({
            "org_id": org_id,
            "strategy_id": strategy_id,
            "external_link": external_link,
            "uploaded_by": user_id,
            "uploaded_at": _now_iso(),
        })
        .execute()
    )
    return _normalise_data(row.data)


def get_document_download_url(db, org_id: str, document_id: str) -> str:
    """
    Returns a fresh 1-hour signed URL, re-signed on demand from storage_path
    (same approach as whatsapp.py's /messages/{id}/download-url).
    """
    result = (
        db.table("project_strategy_documents")
        .select("id, storage_path, external_link")
        .eq("id", document_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    doc = _normalise_data(result.data)
    if not doc:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)

    if doc.get("external_link"):
        return doc["external_link"]

    storage_path = doc.get("storage_path")
    if not storage_path:
        raise HTTPException(status_code=404, detail="This document has no stored file or link")

    try:
        signed = db.storage.from_(STORAGE_BUCKET).create_signed_url(path=storage_path, expires_in=3600)
        if hasattr(signed, "data"):
            d = signed.data or {}
            signed_url = d.get("signedUrl") or d.get("signedURL")
        elif isinstance(signed, dict):
            signed_url = (
                signed.get("signedUrl")
                or signed.get("signedURL")
                or (signed.get("data") or {}).get("signedUrl")
            )
        else:
            signed_url = None
    except Exception as exc:
        logger.warning(
            "get_document_download_url: signed URL creation failed org=%s path=%s: %s",
            org_id, storage_path, exc,
        )
        signed_url = None

    if not signed_url:
        raise HTTPException(status_code=503, detail="Failed to generate download URL — please try again")
    return signed_url


def delete_document(db, org_id: str, document_id: str) -> None:
    result = (
        db.table("project_strategy_documents")
        .select("id, storage_path")
        .eq("id", document_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    doc = _normalise_data(result.data)
    if not doc:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)

    storage_path = doc.get("storage_path")
    if storage_path:
        try:
            db.storage.from_(STORAGE_BUCKET).remove([storage_path])
        except Exception as exc:
            # S14 — failing to delete the underlying file shouldn't block
            # removing the DB record the user asked to delete.
            logger.warning(
                "delete_document: Storage remove failed org=%s path=%s: %s",
                org_id, storage_path, exc,
            )

    db.table("project_strategy_documents").delete().eq("id", document_id).eq("org_id", org_id).execute()
