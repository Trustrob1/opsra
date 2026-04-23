"""
app/routers/onboarding.py
Onboarding checklist + go-live activation routes.
All routes: owner or ops_manager only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase
from app.dependencies import get_current_org
from app.services import onboarding_service

router = APIRouter()


def _require_owner_or_ops(org: dict) -> None:
    """Inline RBAC — Pattern 44."""
    template = (org.get("roles") or {}).get("template", "")
    if template not in ("owner", "ops_manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


# Static routes first — Pattern 53

@router.get("/onboarding/checklist")
def get_checklist(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_owner_or_ops(org)
    status = onboarding_service.get_checklist_status(db, org["org_id"])
    return {
        "success": True,
        "data": status,
        "message": None,
        "error": None,
    }


@router.get("/onboarding/go-live-status")
def get_go_live_status(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_owner_or_ops(org)
    status = onboarding_service.get_checklist_status(db, org["org_id"])

    gate_items_incomplete = [
        it["id"]
        for it in status["items"]
        if it["is_gate"] and not it["complete"]
    ]

    return {
        "success": True,
        "data": {
            "is_live": status["is_live"],
            "go_live_ready": status["go_live_ready"],
            "gate_items_incomplete": gate_items_incomplete,
        },
        "message": None,
        "error": None,
    }


@router.post("/onboarding/activate")
def activate_org(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_owner_or_ops(org)
    went_live_at = onboarding_service.activate_org(db, org["org_id"])
    return {
        "success": True,
        "data": {
            "activated": True,
            "went_live_at": went_live_at,
        },
        "message": "Organisation is now live",
        "error": None,
    }
