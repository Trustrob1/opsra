"""
app/routers/tickets.py
Module 03 — Support routes.
Registered in main.py with prefix="/api/v1".

Routes (Technical Spec §5.4):
  GET  POST         /api/v1/tickets
  GET  PATCH        /api/v1/tickets/{ticket_id}
  POST              /api/v1/tickets/{ticket_id}/messages
  POST              /api/v1/tickets/{ticket_id}/resolve
  POST              /api/v1/tickets/{ticket_id}/close
  POST              /api/v1/tickets/{ticket_id}/reopen
  POST              /api/v1/tickets/{ticket_id}/escalate
  GET  POST         /api/v1/tickets/{ticket_id}/attachments
  GET  POST         /api/v1/knowledge-base
  GET  PATCH DELETE /api/v1/knowledge-base/{article_id}
  POST GET          /api/v1/interaction-logs
"""
from __future__ import annotations

import logging
import re
import uuid as _uuid_mod
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import filetype as _filetype  # S16: magic byte MIME verification (pip install filetype)
    _FILETYPE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _filetype = None  # type: ignore[assignment]
    _FILETYPE_AVAILABLE = False

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok, paginated
from app.models.tickets import (
    ALLOWED_ATTACHMENT_TYPES,
    MAX_ATTACHMENT_BYTES,
    AddMessageRequest,
    InteractionLogCreate,
    KBArticleCreate,
    KBArticleUpdate,
    ResolveRequest,
    TicketCreate,
    TicketUpdate,
)
from app.services import ticket_service
from app.utils.rbac import get_role_template, is_scoped_role, require_permission_key

router = APIRouter()

# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


@router.get("/tickets")
async def list_tickets(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    urgency: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    sla_breached: Optional[bool] = Query(None),
    customer_id: Optional[str] = Query(None),
    lead_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]

    # Phase 9B: resolve scope for sales_agent / affiliate_partner
    scope_customer_ids = None
    scope_lead_ids     = None
    if is_scoped_role(org):
        _cust = db.table("customers").select("id") \
            .eq("org_id", org_id).eq("assigned_to", org["id"]).execute()
        scope_customer_ids = [r["id"] for r in (_cust.data or [])]
        _lead = db.table("leads").select("id") \
            .eq("org_id", org_id).eq("assigned_to", org["id"]) \
            .is_("deleted_at", "null").execute()
        scope_lead_ids = [r["id"] for r in (_lead.data or [])]

    result = ticket_service.list_tickets(
        db=db,
        org_id=org_id,
        status=status,
        category=category,
        urgency=urgency,
        assigned_to=assigned_to,
        sla_breached=sla_breached,
        customer_id=customer_id,
        lead_id=lead_id,
        page=page,
        page_size=page_size,
        scope_customer_ids=scope_customer_ids,
        scope_lead_ids=scope_lead_ids,
     )
 
    return paginated(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/tickets", status_code=201)
async def create_ticket(
    data: TicketCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    ticket = ticket_service.create_ticket(
        db=db, org_id=org_id, user_id=user_id, data=data
    )
    return ok(data=ticket, message="Ticket created")


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    ticket = ticket_service.get_ticket(db=db, ticket_id=ticket_id, org_id=org_id)
    return ok(data=ticket)


@router.patch("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: str,
    data: TicketUpdate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    # C7: Optimistic concurrency — reject stale updates
    if data.updated_at:
        existing = ticket_service.get_ticket(db=db, ticket_id=ticket_id, org_id=org_id)
        db_ts = existing.get("updated_at") or ""
        if db_ts and db_ts > data.updated_at:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CONCURRENT_MODIFICATION",
                    "message": "Record modified by another user. Reload to see changes.",
                },
            )
    ticket = ticket_service.update_ticket(
        db=db, ticket_id=ticket_id, org_id=org_id, user_id=user_id, data=data
    )
    return ok(data=ticket, message="Ticket updated")


# ---------------------------------------------------------------------------
# Ticket messages
# ---------------------------------------------------------------------------


@router.post("/tickets/{ticket_id}/messages", status_code=201)
async def add_message(
    ticket_id: str,
    data: AddMessageRequest,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    message = ticket_service.add_message(
        db=db,
        ticket_id=ticket_id,
        org_id=org_id,
        user_id=user_id,
        data=data,
    )
    return ok(data=message, message="Message added")


# ---------------------------------------------------------------------------
# Ticket status transitions
# ---------------------------------------------------------------------------


@router.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: str,
    data: ResolveRequest,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    ticket = ticket_service.resolve_ticket(
        db=db,
        ticket_id=ticket_id,
        org_id=org_id,
        user_id=user_id,
        resolution_notes=data.resolution_notes,
    )
    return ok(data=ticket, message="Ticket resolved")


@router.post("/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    ticket = ticket_service.close_ticket(
        db=db, ticket_id=ticket_id, org_id=org_id, user_id=user_id
    )
    return ok(data=ticket, message="Ticket closed")


@router.post("/tickets/{ticket_id}/reopen")
async def reopen_ticket(
    ticket_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    user_id: str = org["id"]

    # S17 / §4.2: closed → open requires supervisor or above.
    # get_current_org returns roles as a joined row — the role is at
    # roles.template, never at a flat "role" key. Matches require_admin
    # pattern in dependencies.py: owner by template, admin by is_admin perm.
    _roles    = org.get("roles") or {}
    _template = (_roles.get("template") or "").lower() if isinstance(_roles, dict) else ""
    _perms    = (_roles.get("permissions") or {}) if isinstance(_roles, dict) else {}
    _can_reopen = (
        _template == "owner"
        or _perms.get("is_admin") is True
        or _template in ("supervisor", "ops_manager")
        or _perms.get("manage_tickets") is True
    )
    if not _can_reopen:
        raise HTTPException(
            status_code=403,
            detail="Supervisor or above required to reopen closed tickets.",
        )

    ticket = ticket_service.reopen_ticket(
        db=db, ticket_id=ticket_id, org_id=org_id, user_id=user_id
    )
    return ok(data=ticket, message="Ticket reopened")


@router.post("/tickets/{ticket_id}/escalate")
async def escalate_ticket(
    ticket_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    ticket = ticket_service.escalate_ticket(
        db=db, ticket_id=ticket_id, org_id=org_id, user_id=user_id
    )
    return ok(data=ticket, message="Ticket escalated")


# ---------------------------------------------------------------------------
# Ticket attachments
# ---------------------------------------------------------------------------


@router.get("/tickets/{ticket_id}/attachments")
async def list_attachments(
    ticket_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    attachments = ticket_service.list_attachments(
        db=db, ticket_id=ticket_id, org_id=org_id
    )
    return ok(data=attachments)


@router.post("/tickets/{ticket_id}/attachments", status_code=201)
async def upload_attachment(
    ticket_id: str,
    file: UploadFile = File(...),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Multipart upload.  Validates MIME type and size, builds storage_path,
    then inserts the attachment metadata row.
    Actual byte upload to Supabase Storage is stubbed (TODO: Phase integration).
    Technical Spec §11.5.
    """
    org_id: str = org["org_id"]
    user_id: str = org["id"]

    # Validate MIME type at the router layer before reading body
    if file.content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}",
        )

    contents = await file.read()
    file_size = len(contents)
    if file_size > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")

    # S16: verify actual file bytes against the magic byte signature.
    # The Content-Type header is client-supplied and trivially spoofable —
    # this check uses the real bytes to confirm the declared type matches.
    if _FILETYPE_AVAILABLE:
        guessed = _filetype.guess(contents)
        guessed_mime = guessed.mime if guessed else None
        if guessed_mime not in ALLOWED_ATTACHMENT_TYPES:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"File content does not match an allowed type. "
                    f"Detected: {guessed_mime or 'unknown'}."
                ),
            )
    else:
        # filetype not installed — fall back to header-only check (logged as warning)
        import logging as _logging  # noqa: PLC0415
        _logging.getLogger(__name__).warning(
            "S16: filetype package not installed — magic byte check skipped. "
            "Install with: pip install filetype"
        )

    # Sanitise file name — strip path separators, UUID-prefix (§11.5)
    raw_name = file.filename or "upload"
    safe_name = re.sub(r"[^\w.\-]", "_", raw_name)
    storage_path = (
        f"tickets/{org_id}/{ticket_id}/{_uuid_mod.uuid4()}_{safe_name}"
    )

    # Upload bytes to Supabase Storage — Phase 9E (was stubbed TODO).
    # Bucket: "ticket-attachments" — must exist in Supabase Storage dashboard.
    # Upload happens BEFORE the DB row insert so a storage failure never
    # leaves an orphaned metadata row with no backing bytes.
    # Tech Spec §11.5 — storage_path is already sanitised above.
    try:
        db.storage.from_("ticket-attachments").upload(
            path=storage_path,
            file=contents,
            file_options={"content-type": file.content_type},
        )
        logger.info("Attachment uploaded to storage: %s (%d bytes)", storage_path, file_size)
    except Exception as exc:
        logger.error("Supabase Storage upload failed for %s: %s", storage_path, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="File upload to storage failed. Please try again.",
        )

    attachment = ticket_service.create_attachment(
        db=db,
        ticket_id=ticket_id,
        org_id=org_id,
        user_id=user_id,
        file_name=safe_name,
        file_type=file.content_type,
        storage_path=storage_path,
        file_size_bytes=file_size,
    )
    return ok(data=attachment, message="Attachment uploaded")


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


@router.get("/knowledge-base")
async def list_kb_articles(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    result = ticket_service.list_kb_articles(
        db=db, org_id=org_id, category=category, page=page, page_size=page_size
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/knowledge-base", status_code=201)
async def create_kb_article(
    data: KBArticleCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    require_permission_key(
        org, "manage_kb",
        "KB management requires owner, admin, support agent, or the manage_kb permission",
    )
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    article = ticket_service.create_kb_article(
        db=db, org_id=org_id, user_id=user_id, data=data
    )
    return ok(data=article, message="KB article created")


@router.get("/knowledge-base/{article_id}")
async def get_kb_article(
    article_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    article = ticket_service.get_kb_article(
        db=db, article_id=article_id, org_id=org_id
    )
    return ok(data=article)


@router.patch("/knowledge-base/{article_id}")
async def update_kb_article(
    article_id: str,
    data: KBArticleUpdate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    require_permission_key(
        org, "manage_kb",
        "KB management requires owner, admin, support agent, or the manage_kb permission",
    )
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    article = ticket_service.update_kb_article(
        db=db,
        article_id=article_id,
        org_id=org_id,
        user_id=user_id,
        data=data,
    )
    return ok(data=article, message="KB article updated")


@router.delete("/knowledge-base/{article_id}")
async def unpublish_kb_article(
    article_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Admin-only: sets is_published=False (soft delete).
    Role check: owner template required (§4.2 — 'Manage knowledge base' for CEO/owner).
    """
    org_id: str = org["org_id"]
    user_id: str = org["id"]

    # Role guard — owner or ops_manager only
    role_template = (org.get("roles") or {}).get("template", "")
    if role_template not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=403,
            detail="Admin role required to unpublish KB articles",
        )

    article = ticket_service.unpublish_kb_article(
        db=db, article_id=article_id, org_id=org_id, user_id=user_id
    )
    return ok(data=article, message="KB article unpublished")


@router.post("/knowledge-base/bulk-import", status_code=201)
async def bulk_import_kb_articles(
    file: UploadFile = File(...),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Bulk-import KB articles from a CSV file — avoids typing articles one by
    one in the UI. Expected columns: category, title, content (required),
    tags (optional, semicolon-separated within the cell — commas are the CSV
    delimiter so can't be used inside a field), is_published (true/false,
    default true), action_type (informational|action_required, default
    informational), action_label (optional).

    Each row is validated and created individually via the SAME
    ticket_service.create_kb_article() the single-article endpoint uses —
    inherits identical validation, category checking, and versioning. One
    bad row is reported in the errors list and never blocks the rest of
    the batch.

    RBAC: same as single create (manage_kb permission).
    """
    require_permission_key(
        org, "manage_kb",
        "KB management requires owner, admin, support agent, or the manage_kb permission",
    )
    org_id: str = org["org_id"]
    user_id: str = org["id"]

    raw_bytes = await file.read()
    if len(raw_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (5MB max)")

    import csv
    import io

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="File must be UTF-8 encoded CSV")

    reader = csv.DictReader(io.StringIO(text))
    required_cols = {"category", "title", "content"}
    field_names_lower = {c.strip().lower() for c in (reader.fieldnames or [])}
    if not required_cols.issubset(field_names_lower):
        raise HTTPException(
            status_code=422,
            detail=(
                f"CSV must include columns: {', '.join(sorted(required_cols))} "
                "(tags, is_published, action_type, action_label are optional)"
            ),
        )

    created = []
    errors = []
    for i, raw_row in enumerate(reader, start=2):  # row 1 is the header
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
        try:
            tags_raw = row.get("tags", "")
            tags = [t.strip() for t in tags_raw.split(";") if t.strip()] or None

            is_published_raw = (row.get("is_published") or "true").lower()
            is_published = is_published_raw in ("true", "1", "yes")

            data = KBArticleCreate(
                category=row["category"],
                title=row["title"],
                content=row["content"],
                tags=tags,
                is_published=is_published,
                action_type=row.get("action_type") or "informational",
                action_label=row.get("action_label") or None,
            )
            article = ticket_service.create_kb_article(
                db=db, org_id=org_id, user_id=user_id, data=data
            )
            created.append({"row": i, "title": data.title, "id": article.get("id")})
        except Exception as exc:
            errors.append({"row": i, "title": row.get("title", ""), "error": str(exc)})

    return ok(
        data={"created": created, "errors": errors, "total_rows": len(created) + len(errors)},
        message=f"{len(created)} article(s) created, {len(errors)} error(s)",
    )


@router.post("/tickets/{ticket_id}/suggest-kb-article")
async def suggest_kb_article(
    ticket_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Generate a KB article draft from a resolved ticket with knowledge_gap_flagged=True.
    Returns {title, category, content, tags} for the agent to review and publish.
    Human supervision required — this does not auto-publish.
    """
    org_id: str = org["org_id"]
    suggestion = ticket_service.suggest_kb_article_from_ticket(
        db=db, ticket_id=ticket_id, org_id=org_id
    )
    return ok(data=suggestion, message="KB article draft generated")


# ---------------------------------------------------------------------------
# Interaction logs
# ---------------------------------------------------------------------------


@router.post("/interaction-logs", status_code=201)
async def create_interaction_log(
    data: InteractionLogCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    log = ticket_service.create_interaction_log(
        db=db, org_id=org_id, user_id=user_id, data=data
    )
    return ok(data=log, message="Interaction log created")


@router.get("/interaction-logs")
async def list_interaction_logs(
    customer_id: Optional[str] = Query(None),
    lead_id: Optional[str] = Query(None),
    logged_by: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id: str = org["org_id"]
    result = ticket_service.list_interaction_logs(
        db=db,
        org_id=org_id,
        customer_id=customer_id,
        lead_id=lead_id,
        logged_by=logged_by,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )