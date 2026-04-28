"""
app/routers/commerce.py
COMM-1 — Commerce session read routes.

All routes prefixed /api/v1/commerce via main.py include_router.

Routes:
  GET /api/v1/commerce/sessions/active   — fetch open/checkout_sent session by phone

Auth: JWT required on all routes (get_current_org dependency).
S1  — org_id from JWT only, never from request body/query.
S14 — never raises; errors logged and safe response returned.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v1/commerce/sessions/active
# Returns the most recent open or checkout_sent commerce_session for the
# given phone number, scoped to the org from the JWT.
# Used by CustomerProfile.jsx to display the Active Cart section.
# S14 — never raises.
# ---------------------------------------------------------------------------

@router.get("/sessions/active")
def get_active_commerce_session(
    phone: str = Query(..., description="WhatsApp phone number of the contact"),
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    """
    Fetch the active (open or checkout_sent) commerce session for a phone number.
    Returns null data if no active session exists.
    S1  — org_id from JWT.
    S14 — DB errors return null data, never 500.
    """
    try:
        phone = (phone or "").strip()
        if not phone:
            return ok(data=None)

        result = (
            db.table("commerce_sessions")
            .select("*")
            .eq("org_id", org["org_id"])
            .eq("phone_number", phone)
            .in_("status", ["open", "checkout_sent"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data if isinstance(result.data, list) else []
        session = rows[0] if rows else None

        return ok(data=session)

    except Exception as exc:
        logger.warning(
            "get_active_commerce_session failed org=%s phone=%s: %s",
            org.get("org_id"), phone, exc,
        )
        return ok(data=None)
