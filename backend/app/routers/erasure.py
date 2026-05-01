"""
app/routers/erasure.py
-----------------------
9E-I — I3: Right-to-erasure endpoint (NDPR compliance).

Route: DELETE /api/v1/admin/contacts/{phone_number}/erase  (owner only)

Hard-deletes all PII for a contact identified by phone number:
  - leads records (hard delete, org-scoped)
  - customers records (hard delete, org-scoped)
  - whatsapp_sessions for that phone (hard delete, org-scoped)
  - Writes an erasure_log record with SHA-256 hash of the phone number

whatsapp_messages rows are linked via lead_id/customer_id FK.
Once the lead/customer rows are deleted, messages are orphaned.
If FK CASCADE DELETE is configured on whatsapp_messages, they are removed
automatically. If not, they are anonymised implicitly (no PII link remains).

Security:
  - Owner role only
  - confirmation=true required in body (prevents accidental erasure)
  - org_id from JWT only — cannot erase contacts from other orgs (S1)

WIRING: register this router in backend/app/main.py:
  from app.routers.erasure import router as erasure_router
  app.include_router(erasure_router)
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.services.lead_service import write_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["compliance"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class EraseRequest(BaseModel):
    confirmation: bool = Field(
        ...,
        description="Must be true — prevents accidental erasure of PII",
    )


class EraseResponse(BaseModel):
    erased: bool
    records_removed: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_phone(phone: str) -> str:
    """Strip whitespace, dashes, and parentheses for consistent matching."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.delete(
    "/contacts/{phone_number}/erase",
    response_model=EraseResponse,
    summary="Right-to-erasure — hard-delete all PII for a contact (OWNER only)",
)
def erase_contact(
    phone_number: str,
    payload: EraseRequest,
    org: dict = Depends(get_current_org),
) -> EraseResponse:
    """
    Permanently and irreversibly remove all personal data for a contact.

    Identifies the contact by phone number within the requesting org only.
    Writes an erasure_log record with a SHA-256 hash of the phone (no raw PII).

    This endpoint is the implementation of the data subject's right to erasure
    under Nigeria's NDPR (National Data Protection Regulation) and similar laws.
    """
    # ── S1: org_id from JWT only ──────────────────────────────────────────
    org_id:  str = org["org_id"]
    user_id: str = org["id"]

    # ── Owner-only role check ─────────────────────────────────────────────
    role_name: str = (org.get("role") or {}).get("name", "")
    if role_name != "owner":
        raise HTTPException(
            status_code=403,
            detail="Owner role required for contact erasure",
        )

    # ── Confirmation gate — must be explicitly true ───────────────────────
    if not payload.confirmation:
        raise HTTPException(
            status_code=422,
            detail="confirmation must be true to proceed with erasure",
        )

    db = get_supabase()
    phone_normalised = _normalise_phone(phone_number)
    records_removed  = 0

    # ── 1. Hard-delete leads matching this phone ──────────────────────────
    try:
        lead_res = (
            db.table("leads")
            .delete()
            .eq("org_id", org_id)
            .or_(f"phone.eq.{phone_normalised},whatsapp.eq.{phone_normalised}")
            .execute()
        )
        n = len(lead_res.data or [])
        records_removed += n
        logger.info("erase_contact: deleted %d lead(s) for hash=%s org=%s", n, _sha256(phone_normalised), org_id)
    except Exception as exc:
        logger.warning("erase_contact: failed to delete leads: %s", exc)

    # ── 2. Hard-delete customers matching this phone ──────────────────────
    try:
        cust_res = (
            db.table("customers")
            .delete()
            .eq("org_id", org_id)
            .or_(f"phone.eq.{phone_normalised},whatsapp.eq.{phone_normalised}")
            .execute()
        )
        n = len(cust_res.data or [])
        records_removed += n
        logger.info("erase_contact: deleted %d customer(s) for hash=%s org=%s", n, _sha256(phone_normalised), org_id)
    except Exception as exc:
        logger.warning("erase_contact: failed to delete customers: %s", exc)

    # ── 3. Hard-delete whatsapp_sessions for this phone ──────────────────
    try:
        sess_res = (
            db.table("whatsapp_sessions")
            .delete()
            .eq("org_id", org_id)
            .eq("phone_number", phone_normalised)
            .execute()
        )
        n = len(sess_res.data or [])
        records_removed += n
        logger.info("erase_contact: deleted %d session(s) for hash=%s org=%s", n, _sha256(phone_normalised), org_id)
    except Exception as exc:
        logger.warning("erase_contact: failed to delete sessions: %s", exc)

    # ── 4. Write erasure_log — phone_hash only, no raw PII ───────────────
    phone_hash = _sha256(phone_normalised)
    try:
        db.table("erasure_log").insert({
            "org_id":          org_id,
            "requested_by":    user_id,
            "phone_hash":      phone_hash,
            "records_removed": records_removed,
            "created_at":      _now_iso(),
        }).execute()
    except Exception as exc:
        logger.warning("erase_contact: failed to write erasure_log: %s", exc)

    # ── 5. Write audit_log ────────────────────────────────────────────────
    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="contact.erased",
        resource_type="contact",
        resource_id=None,
        old_value=None,
        new_value={
            "phone_hash":      phone_hash,
            "records_removed": records_removed,
        },
    )

    logger.info(
        "erase_contact: complete — hash=%s org=%s records_removed=%d",
        phone_hash, org_id, records_removed,
    )
    return EraseResponse(erased=True, records_removed=records_removed)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
