"""
app/routers/funnels.py
-----------------------
FUNNEL-1 — internal Event Funnel routes. Prefix: /api/v1/funnels

S1/S2: org_id from get_current_org only (Pattern 28). Pattern 37: org["roles"]["template"].
Read: owner, admin, ops_manager. Write: owner, ops_manager (same as WhatsApp numbers).
Pattern 53: static routes before parameterised ones.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.models.funnels import FunnelCreate, FunnelUpdate, GrantEarly, ManualPaid, RegistrationPatch
from app.services import funnel_service

logger = logging.getLogger(__name__)
router = APIRouter()

_READ_ROLES = ("owner", "admin", "ops_manager")
_WRITE_ROLES = ("owner", "ops_manager")


def _role(org: dict) -> str:
    return ((org.get("roles") or {}).get("template") or "").lower()


def _require(org: dict, roles: tuple) -> None:
    if _role(org) not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"code": "FORBIDDEN", "message": "You don't have access to event funnels."})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_funnel(db, org_id: str, funnel_id: str) -> dict:
    row = funnel_service._one((db.table("event_funnels").select("*").eq("id", funnel_id)
                               .eq("org_id", org_id).limit(1).execute()).data)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Funnel not found"})
    return row


def _get_reg(db, org_id: str, funnel_id: str, reg_id: str) -> dict:
    row = funnel_service._one((db.table("funnel_registrations").select("*").eq("id", reg_id)
                               .eq("funnel_id", funnel_id).eq("org_id", org_id).limit(1).execute()).data)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Registration not found"})
    return row


def _serialise(payload) -> dict:
    data = payload.model_dump(exclude_unset=True, mode="json")
    return data


def _validate_activation(db, org_id: str, funnel: dict) -> None:
    """A funnel can only go active with an event_funnel number of THIS org and no other active funnel on it."""
    nid = funnel.get("whatsapp_number_id")
    if not nid:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Choose a WhatsApp number first."})
    num = funnel_service._number_row_by_id(db, org_id, nid)
    if not num:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "WhatsApp number not found."})
    if num.get("wa_sales_mode") != "event_funnel":
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR",
                                         "message": "Set this WhatsApp number to Event Funnel mode first."})
    others = (db.table("event_funnels").select("id").eq("org_id", org_id).eq("whatsapp_number_id", nid)
              .eq("status", "active").execute()).data or []
    if any(o["id"] != funnel.get("id") for o in others):
        raise HTTPException(409, detail={"code": "CONFLICT",
                                         "message": "Another active funnel already uses this number."})
    if funnel.get("pricing_mode") == "deadline" and not funnel.get("early_deadline_at"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Deadline mode needs an early-price deadline."})


# ── Static routes ─────────────────────────────────────────────────────────

@router.get("/funnels")
def list_funnels(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    rows = (db.table("event_funnels").select(
        "id, name, status, event_title, event_starts_at, registration_closes_at, pricing_mode, "
        "early_price, regular_price, whatsapp_number_id, created_at")
        .eq("org_id", org["org_id"]).order("created_at", desc=True).execute()).data or []
    return ok(data=rows)


@router.get("/funnels/defaults")
def funnel_defaults(org=Depends(get_current_org)):
    _require(org, _READ_ROLES)
    return ok(data={
        "messages": funnel_service.DEFAULT_MESSAGES,
        "sequence_window": funnel_service.DEFAULT_SEQUENCE_WINDOW,
        "sequence_deadline": funnel_service.DEFAULT_SEQUENCE_DEADLINE,
        "settings": funnel_service.DEFAULT_SETTINGS,
    })


@router.post("/funnels", status_code=status.HTTP_201_CREATED)
def create_funnel(payload: FunnelCreate, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    data = _serialise(payload)
    data.update({"org_id": org["org_id"], "status": data.get("status") or "draft",
                 "created_at": _now_iso(), "updated_at": _now_iso()})
    if data["status"] == "active":
        _validate_activation(db, org["org_id"], data)
    res = db.table("event_funnels").insert(data).execute()
    return ok(data=funnel_service._one(res.data) or data, message="Funnel created")


# ── Parameterised routes ─────────────────────────────────────────────────

@router.get("/funnels/{funnel_id}")
def get_funnel(funnel_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    f["effective_messages"] = funnel_service.funnel_messages(f)
    f["effective_sequence"] = funnel_service.funnel_sequence(f)
    f["effective_settings"] = funnel_service.funnel_settings(f)
    return ok(data=f)


@router.patch("/funnels/{funnel_id}")
def update_funnel(funnel_id: str, payload: FunnelUpdate, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    current = _get_funnel(db, org["org_id"], funnel_id)
    updates = _serialise(payload)
    if not updates:
        return ok(data=current)
    merged = dict(current)
    merged.update(updates)
    if merged.get("status") == "active":
        _validate_activation(db, org["org_id"], merged)
    rc, es = funnel_service._dt(merged.get("registration_closes_at")), funnel_service._dt(merged.get("event_starts_at"))
    if rc and es and rc > es:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Registration must close before the event starts."})
    updates["updated_at"] = _now_iso()
    db.table("event_funnels").update(updates).eq("id", funnel_id).eq("org_id", org["org_id"]).execute()
    merged.update(updates)
    return ok(data=merged, message="Funnel updated")


@router.get("/funnels/{funnel_id}/stats")
def funnel_stats(funnel_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    return ok(data=funnel_service.get_funnel_stats(db, org["org_id"], f))


@router.get("/funnels/{funnel_id}/registrations")
def list_registrations(
    funnel_id: str,
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(new|paid|closed_unpaid|opted_out)$"),
    ad_code: Optional[str] = Query(None, max_length=12),
    needs_human: Optional[bool] = None,
    search: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org=Depends(get_current_org), db=Depends(get_supabase),
):
    _require(org, _READ_ROLES)
    _get_funnel(db, org["org_id"], funnel_id)

    def build():
        q = (db.table("funnel_registrations").select(
            "id, lead_id, phone, name, email, ad_code, status, seats, amount_paid, paid_at, "
            "first_message_at, last_inbound_at, needs_human, ref_code, referred_by_id, early_override_until, "
            "price_tier_paid, created_at")
            .eq("org_id", org["org_id"]).eq("funnel_id", funnel_id))
        if status_filter:
            q = q.eq("status", status_filter)
        if ad_code:
            q = q.eq("ad_code", ad_code.upper())
        if needs_human is not None:
            q = q.eq("needs_human", needs_human)
        return q.order("created_at", desc=True)

    rows = funnel_service._fetch_all(build)
    if search:  # Pattern 33 — Python-side filter
        s = search.lower().strip()
        rows = [r for r in rows if s in (r.get("name") or "").lower() or s in (r.get("phone") or "")
                or s in (r.get("email") or "").lower() or s in (r.get("ref_code") or "").lower()]
    total = len(rows)
    start = (page - 1) * page_size
    return ok(data={"items": rows[start:start + page_size], "total": total, "page": page, "page_size": page_size})


@router.get("/funnels/{funnel_id}/export.csv")
def export_registrations(funnel_id: str, paid_only: bool = True,
                         org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)

    def build():
        q = (db.table("funnel_registrations").select(
            "name, phone, email, seats, amount_paid, paid_at, ad_code, ref_code, status")
            .eq("org_id", org["org_id"]).eq("funnel_id", funnel_id))
        if paid_only:
            q = q.eq("status", "paid")
        return q.order("created_at")

    rows = funnel_service._fetch_all(build)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "phone", "email", "seats", "amount_paid", "paid_at", "ad_code", "ref_code", "status"])
    for r in rows:
        # CSV-injection guard: prefix cells that start with a formula character
        w.writerow([("'" + str(v)) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v
                    for v in (r.get("name"), r.get("phone"), r.get("email"), r.get("seats"), r.get("amount_paid"),
                              r.get("paid_at"), r.get("ad_code"), r.get("ref_code"), r.get("status"))])
    fname = "".join(c for c in (f.get("name") or "funnel") if c.isalnum() or c in "-_ ")[:40].strip() or "funnel"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})


@router.post("/funnels/{funnel_id}/registrations/{reg_id}/grant-early")
def grant_early(funnel_id: str, reg_id: str, payload: GrantEarly,
                org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    reg = _get_reg(db, org["org_id"], funnel_id, reg_id)
    until = datetime.now(timezone.utc) + timedelta(hours=payload.hours)
    reg = funnel_service._update_reg(db, reg, {"early_override_until": until.isoformat()})
    funnel_service.log_event(db, org["org_id"], funnel_id, reg_id, "override_granted",
                             detail={"hours": payload.hours, "by": org["id"]})
    return ok(data={"early_override_until": reg["early_override_until"]},
              message=f"Early price re-opened for {payload.hours}h — use Resend link to tell them.")


@router.post("/funnels/{funnel_id}/registrations/{reg_id}/resend-link")
def resend_link(funnel_id: str, reg_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    reg = _get_reg(db, org["org_id"], funnel_id, reg_id)
    number_row = funnel_service._number_row_by_id(db, org["org_id"], f.get("whatsapp_number_id"))
    if not number_row:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Funnel has no WhatsApp number."})
    sent = funnel_service.send_pay_message(db, f, number_row, reg, "pay_link_resend")
    if not sent:
        raise HTTPException(503, detail={"code": "INTEGRATION_ERROR",
                                         "message": "WhatsApp didn't accept the message (outside the 24-hour window?)."})
    return ok(message="Payment link sent")


@router.post("/funnels/{funnel_id}/registrations/{reg_id}/mark-paid")
def mark_paid_manually(funnel_id: str, reg_id: str, payload: ManualPaid,
                       org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    reg = _get_reg(db, org["org_id"], funnel_id, reg_id)
    reg = funnel_service.mark_paid_manually(db, org["org_id"], f, reg, payload.amount, payload.seats,
                                            payload.note, org["id"])
    return ok(data=reg, message="Marked as paid")


@router.patch("/funnels/{funnel_id}/registrations/{reg_id}")
def patch_registration(funnel_id: str, reg_id: str, payload: RegistrationPatch,
                       org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _get_funnel(db, org["org_id"], funnel_id)
    reg = _get_reg(db, org["org_id"], funnel_id, reg_id)
    updates = payload.model_dump(exclude_unset=True)
    if "email" in updates and updates["email"]:
        email = funnel_service.parse_email(updates["email"])
        if not email:
            raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Not a valid email."})
        updates["email"] = email
    reg = funnel_service._update_reg(db, reg, updates)
    return ok(data=reg)
