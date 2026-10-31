"""
app/routers/booking.py
-----------------------
BOOKING-1 — native booking API.

Public (no login), prefix /api/v1 :
  GET  /public/booking/link/{token}                      who the link is for, service(s), any existing booking
  GET  /public/booking/link/{token}/slots?from=&to=&service=   open slots (UTC) + org timezone
  POST /public/booking/link/{token}/book                 pick a slot
  POST /public/booking/link/{token}/reschedule           move the existing booking
  POST /public/booking/link/{token}/cancel               cancel (cut-off enforced)

Staff (login), prefix /api/v1 :
  BOOKING-2B people: GET /booking/staff, PUT /booking/staff/{user_id}, GET/PUT /booking/staff/{user_id}/hours,
                     GET/POST /booking/staff/{user_id}/blocks, DELETE /booking/staff/blocks/{id},
                     PUT /booking/services/{id}/staff, POST /booking/bookings/{demo_id}/assign
  GET/PATCH /booking/settings
  GET/POST /booking/services, PATCH/DELETE /booking/services/{id}
  GET/PUT  /booking/availability
  GET/POST /booking/blocks, DELETE /booking/blocks/{id}
  GET  /booking/slots?service=&from=&to=                 open slots for staff booking
  GET  /booking/bookings?from=&to=                       calendar feed
  POST /booking/leads/{lead_id}/book                     staff books a lead into a real slot
  POST /booking/leads/{lead_id}/link                     make a booking link (returns the URL)
  POST /booking/bookings/{demo_id}/cancel, /reschedule

The org always comes from the JWT (staff) or from the link token (public). Plan feature: selling_booking.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org, require_admin
from app.models.common import ok
from app.services import booking_service as bk
from app.services import plan_gate_service as plan_gate
from app.services import webchat_service as wc
from app.services.site_capture_service import ip_hash

logger = logging.getLogger(__name__)
router = APIRouter()          # public (no login)
staff = APIRouter()           # staff (login); registered with the crm_only guard


# ───────────────────────────── helpers ─────────────────────────────

def _nostore(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _limit(request: Request, bucket: str, limit: int, window: int) -> None:
    if wc.rate_limited(f"bk:{bucket}:{ip_hash(_client_ip(request))}", limit, window):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many requests. Please try again shortly."})


def _gate(db, org_id: str) -> None:
    if not plan_gate.allowed(db, org_id, "selling_booking"):
        raise plan_gate.http_error()


def _parse_day(v: Optional[str], default: date) -> date:
    if not v:
        return default
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Dates must look like 2026-11-30"})


def _parse_start(v: str) -> datetime:
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Invalid start time"})
    if d.tzinfo is None:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Start time needs a timezone (use UTC, e.g. 2026-11-30T09:00:00Z)"})
    return d


def _slots_payload(org: dict, service: dict, slots: list[datetime]) -> dict:
    return {
        "timezone": org.get("timezone") or "Africa/Lagos",
        "service": {k: service.get(k) for k in ("id", "name", "slug", "duration_minutes", "medium", "location_text", "requires_approval")},
        "slots": [s.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") for s in slots],
    }


def _public_booking(d: Optional[dict]) -> Optional[dict]:
    if not d:
        return None
    return {k: d.get(k) for k in ("id", "status", "scheduled_at", "duration_minutes", "medium", "service_id")}


def _link_context(db, token: str) -> tuple[dict, dict, dict]:
    link = bk.resolve_link(db, token)
    org = bk.get_org(db, link["org_id"])
    _gate(db, org["id"])
    cfg = bk.get_settings(db, org["id"])
    if not cfg["native_enabled"]:
        raise HTTPException(status_code=404, detail={"code": "NOT_AVAILABLE", "message": "Online booking is not available right now."})
    return link, org, cfg


def _current_booking(db, link: dict) -> Optional[dict]:
    if link.get("demo_id"):
        rows = db.table("lead_demos").select("*").eq("id", link["demo_id"]).eq("org_id", link["org_id"]).limit(1).execute().data or []
        if rows and rows[0].get("status") in ("pending_assignment", "confirmed"):
            return rows[0]
    return None


def _link_service(db, link: dict) -> dict:
    services = bk.list_services(db, link["org_id"], active_only=True)
    if link.get("service_id"):
        for s in services:
            if s["id"] == link["service_id"]:
                return s
    if not services:
        raise HTTPException(status_code=404, detail={"code": "NOT_AVAILABLE", "message": "Online booking is not available right now."})
    return services[0]


# ───────────────────────────── public ─────────────────────────────

@router.get("/public/booking/link/{token}")
def public_link(token: str, request: Request, response: Response, db=Depends(get_supabase)):
    _nostore(response)
    _limit(request, "link", 120, 60)
    link, org, cfg = _link_context(db, token)
    lead = db.table("leads").select("full_name").eq("id", link["lead_id"]).eq("org_id", org["id"]).limit(1).execute().data
    if isinstance(lead, list):
        lead = lead[0] if lead else None
    first = ((lead or {}).get("full_name") or "").split(" ")[0]
    service = _link_service(db, link)
    people = []
    if cfg.get("calendar_mode") == "per_staff" and cfg.get("let_leads_choose_person"):
        ids = set(bk.eligible_staff_ids(db, org["id"], service))
        people = [{"id": u["id"], "name": u.get("full_name") or "Team member"} for u in bk._org_users(db, org["id"]) if u["id"] in ids]
    return ok({
        "staff": people,
        "business": org.get("name"), "first_name": first, "label": cfg["label"],
        "cancel_cutoff_hours": cfg["cancel_cutoff_hours"], "timezone": org.get("timezone") or "Africa/Lagos",
        "service": {k: service.get(k) for k in ("id", "name", "description", "duration_minutes", "medium", "location_text", "requires_approval")},
        "booking": _public_booking(_current_booking(db, link)),
    })


@router.get("/public/booking/link/{token}/slots")
def public_slots(token: str, request: Request, response: Response, db=Depends(get_supabase),
                 from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                 staff_id: Optional[str] = Query(None, alias="staff", max_length=64)):
    _nostore(response)
    _limit(request, "slots", 120, 60)
    link, org, cfg = _link_context(db, token)
    service = _link_service(db, link)
    start = _parse_day(from_, datetime.now(timezone.utc).date())
    end = _parse_day(to, start + timedelta(days=13))
    current = _current_booking(db, link)
    pick = staff_id if (staff_id and cfg.get("let_leads_choose_person")) else None
    slots = bk.get_open_slots(db, org, service, start, end, exclude_demo_id=current["id"] if current else None, rep_id=pick)
    return ok(_slots_payload(org, service, slots))


class BookBody(BaseModel):
    start: str = Field(..., max_length=40)
    timezone: Optional[str] = Field(default=None, max_length=60)
    note: Optional[str] = Field(default=None, max_length=1000)
    website: Optional[str] = Field(default=None, max_length=200)   # honeypot
    staff_id: Optional[str] = Field(default=None, max_length=64)   # BOOKING-2D: only used when the business lets leads choose


@router.post("/public/booking/link/{token}/book")
def public_book(token: str, body: BookBody, request: Request, response: Response, db=Depends(get_supabase)):
    _nostore(response)
    _limit(request, "book", 10, 3600)
    if body.website:
        return ok({"booked": True})   # honeypot: pretend success
    link, org, cfg = _link_context(db, token)
    if _current_booking(db, link):
        raise HTTPException(status_code=409, detail={"code": "ALREADY_BOOKED", "message": "You already have a booking. Use reschedule or cancel."})
    service = _link_service(db, link)
    demo = bk.book_slot(db, org["id"], link["lead_id"], service, _parse_start(body.start), source="native",
                        lead_timezone=body.timezone, notes=body.note,
                        rep_id=body.staff_id if (body.staff_id and cfg.get("let_leads_choose_person")) else None)
    bk.link_attach_booking(db, link["id"], demo["id"])
    return ok({"booking": _public_booking(demo)}, message="Booked")


class RescheduleBody(BaseModel):
    start: str = Field(..., max_length=40)


@router.post("/public/booking/link/{token}/reschedule")
def public_reschedule(token: str, body: RescheduleBody, request: Request, response: Response, db=Depends(get_supabase)):
    _nostore(response)
    _limit(request, "resched", 10, 3600)
    link, org, _ = _link_context(db, token)
    current = _current_booking(db, link)
    if not current:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "No active booking on this link."})
    demo = bk.reschedule_booking(db, org["id"], current["id"], _parse_start(body.start), by="lead")
    return ok({"booking": _public_booking(demo)}, message="Moved")


class CancelBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


@router.post("/public/booking/link/{token}/cancel")
def public_cancel(token: str, body: CancelBody, request: Request, response: Response, db=Depends(get_supabase)):
    _nostore(response)
    _limit(request, "cancel", 10, 3600)
    link, org, _ = _link_context(db, token)
    current = _current_booking(db, link)
    if not current:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "No active booking on this link."})
    demo = bk.cancel_booking(db, org["id"], current["id"], by="lead", reason=body.reason)
    return ok({"booking": _public_booking(demo)}, message="Cancelled")


# ───────────────────────────── staff: settings ─────────────────────────────

class SettingsBody(BaseModel):
    native_enabled: Optional[bool] = None
    label: Optional[str] = Field(default=None, max_length=40)
    cancel_cutoff_hours: Optional[int] = Field(default=None, ge=0, le=720)
    auto_send_link: Optional[bool] = None
    default_rep_id: Optional[str] = None
    calendar_mode: Optional[Literal["single", "per_staff"]] = None
    auto_send_mode: Optional[Literal["link", "picker"]] = None
    template_buttons: Optional[bool] = None
    let_leads_choose_person: Optional[bool] = None
    auto_send_trigger: Optional[Literal["qualified", "stage"]] = None
    auto_send_stage: Optional[str] = Field(default=None, max_length=60)


@staff.get("/booking/settings")
def get_settings(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.get_settings(db, org["org_id"]))


@staff.patch("/booking/settings")
def patch_settings(body: SettingsBody, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    patch = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
    out = bk.save_settings(db, org["org_id"], patch)
    if out["native_enabled"]:
        bk.ensure_default_availability(db, org["org_id"])
        if not bk.list_services(db, org["org_id"]):
            bk.create_service(db, org["org_id"], {"name": out["label"].capitalize(), "duration_minutes": 30})
    return ok(out)


# ───────────────────────────── staff: services / hours / blocks ─────────────────────────────

class ServiceBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    buffer_after_minutes: Optional[int] = Field(default=None, ge=0, le=240)
    medium: Optional[Literal["virtual", "in_person", "phone"]] = None
    location_text: Optional[str] = Field(default=None, max_length=300)
    requires_approval: Optional[bool] = None
    min_notice_hours: Optional[int] = Field(default=None, ge=0, le=720)
    window_days: Optional[int] = Field(default=None, ge=1, le=365)
    active: Optional[bool] = None
    sort_order: Optional[int] = Field(default=None, ge=0, le=9999)
    assignment_mode: Optional[Literal["anyone", "specific", "lead_owner_first"]] = None


def _dump(body) -> dict:
    return body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)


@staff.get("/booking/services")
def list_services(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.list_services(db, org["org_id"]))


@staff.post("/booking/services", status_code=201)
def create_service(body: ServiceBody, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.create_service(db, org["org_id"], _dump(body)))


@staff.patch("/booking/services/{service_id}")
def update_service(service_id: str, body: ServiceBody, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.update_service(db, org["org_id"], service_id, _dump(body)))


@staff.delete("/booking/services/{service_id}")
def delete_service(service_id: str, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    bk.delete_service(db, org["org_id"], service_id)
    return ok(message="Deleted")


class HoursRow(BaseModel):
    weekday: int = Field(..., ge=0, le=6)
    start_time: str = Field(..., pattern=r"^\d{1,2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{1,2}:\d{2}$")


class HoursBody(BaseModel):
    rows: list[HoursRow] = Field(default_factory=list, max_length=70)


@staff.get("/booking/availability")
def get_availability(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.ensure_default_availability(db, org["org_id"]))


@staff.put("/booking/availability")
def put_availability(body: HoursBody, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    rows = [r.model_dump() if hasattr(r, "model_dump") else r.dict() for r in body.rows]
    return ok(bk.set_availability(db, org["org_id"], rows))


class BlockBody(BaseModel):
    starts_at: str = Field(..., max_length=40)
    ends_at: str = Field(..., max_length=40)
    reason: Optional[str] = Field(default=None, max_length=200)


@staff.get("/booking/blocks")
def list_blocks(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.list_blocks(db, org["org_id"]))


@staff.post("/booking/blocks", status_code=201)
def add_block(body: BlockBody, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.add_block(db, org["org_id"], body.starts_at, body.ends_at, body.reason))


@staff.delete("/booking/blocks/{block_id}")
def delete_block(block_id: str, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    bk.delete_block(db, org["org_id"], block_id)
    return ok(message="Deleted")


# ───────────────────────────── staff: slots, calendar, booking ─────────────────────────────

@staff.get("/booking/slots")
def staff_slots(service: str, org: dict = Depends(get_current_org), db=Depends(get_supabase),
                from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None):
    _gate(db, org["org_id"])
    o = bk.get_org(db, org["org_id"])
    svc = bk.get_service(db, org["org_id"], service)
    start = _parse_day(from_, datetime.now(timezone.utc).date())
    end = _parse_day(to, start + timedelta(days=13))
    return ok(_slots_payload(o, svc, bk.get_open_slots(db, o, svc, start, end)))


@staff.get("/booking/bookings")
def calendar_feed(org: dict = Depends(get_current_org), db=Depends(get_supabase),
                  from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None):
    _gate(db, org["org_id"])
    start = _parse_day(from_, datetime.now(timezone.utc).date())
    end = _parse_day(to, start + timedelta(days=7))
    lo = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    return ok(bk.list_bookings(db, org["org_id"], lo, hi))


class StaffBookBody(BaseModel):
    service: str = Field(..., max_length=60)
    start: str = Field(..., max_length=40)
    notes: Optional[str] = Field(default=None, max_length=2000)


@staff.post("/booking/leads/{lead_id}/book", status_code=201)
def staff_book(lead_id: str, body: StaffBookBody, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    svc = bk.get_service(db, org["org_id"], body.service)
    demo = bk.book_slot(db, org["org_id"], lead_id, svc, _parse_start(body.start), source="manual",
                        user_id=org["id"], notes=body.notes)
    return ok(demo, message="Booked")


class LinkBody(BaseModel):
    service: Optional[str] = Field(default=None, max_length=60)
    send_whatsapp: bool = False


def _public_base() -> str:
    return (os.environ.get("FRONTEND_URL") or os.environ.get("PUBLIC_APP_URL") or "https://opsra-frontend.onrender.com").rstrip("/")


@staff.post("/booking/leads/{lead_id}/link", status_code=201)
def make_link(lead_id: str, body: LinkBody, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    cfg = bk.get_settings(db, org["org_id"])
    if not cfg["native_enabled"]:
        raise HTTPException(status_code=400, detail={"code": "NOT_ENABLED", "message": "Turn on online booking in settings first."})
    service_id = bk.get_service(db, org["org_id"], body.service)["id"] if body.service else None
    token = bk.create_link(db, org["org_id"], lead_id, service_id, org["id"])
    url = f"{_public_base()}/b/{token}"
    result = {"sent": False, "via": None, "reason": None}
    if body.send_whatsapp:
        from app.services import demo_service as ds
        lead = ds._confirm_lead_in_org(db, org["org_id"], lead_id)
        first = (lead.get("full_name") or "").split(" ")[0] or "there"
        result = ds._auto_send_wa(
            db, org["org_id"], lead,
            f"Hi {first}, you can pick a time for your {cfg['label']} here: {url}",
            template_name=bk.BOOKING_LINK_TEMPLATE, template_vars=[first, cfg["label"], url],
        )
    return ok({"url": url, "sent_whatsapp": bool(result.get("sent")), "whatsapp_via": result.get("via"), "whatsapp_reason": result.get("reason")})


class StaffCancelBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


@staff.post("/booking/bookings/{demo_id}/cancel")
def staff_cancel(demo_id: str, body: StaffCancelBody, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.cancel_booking(db, org["org_id"], demo_id, by="staff", reason=body.reason, user_id=org["id"]))


@staff.post("/booking/bookings/{demo_id}/reschedule")
def staff_reschedule(demo_id: str, body: RescheduleBody, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.reschedule_booking(db, org["org_id"], demo_id, _parse_start(body.start), by="staff", user_id=org["id"]))


# ───────────────────────────── BOOKING-2B: people (per-staff calendars) ─────────────────────────────

def _role(org: dict) -> tuple[str, dict]:
    role = org.get("roles") or {}
    return role.get("template", ""), (role.get("permissions") or {})


def _is_admin(org: dict) -> bool:
    tpl, perms = _role(org)
    return tpl == "owner" or perms.get("is_admin") is True


def _is_manager(org: dict) -> bool:
    tpl, _ = _role(org)
    return _is_admin(org) or tpl in ("ops_manager", "admin")


def _admin_or_self(org: dict, user_id: str) -> None:
    if not (_is_admin(org) or org["id"] == user_id):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "You can only change your own hours and time off."})


class StaffBody(BaseModel):
    accepts_bookings: Optional[bool] = None
    uses_org_hours: Optional[bool] = None


class StaffHoursBody(BaseModel):
    rows: list[HoursRow] = Field(default_factory=list, max_length=70)


class ServiceStaffBody(BaseModel):
    user_ids: list[str] = Field(default_factory=list, max_length=100)


class AssignBody(BaseModel):
    user_id: str = Field(..., max_length=64)


@staff.get("/booking/staff")
def list_staff(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.list_staff(db, org["org_id"]))


@staff.put("/booking/staff/{user_id}")
def put_staff(user_id: str, body: StaffBody, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.set_staff(db, org["org_id"], user_id, body.accepts_bookings, body.uses_org_hours))


@staff.put("/booking/staff/{user_id}/hours")
def put_staff_hours(user_id: str, body: StaffHoursBody, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    _admin_or_self(org, user_id)
    rows = [r.model_dump() if hasattr(r, "model_dump") else r.dict() for r in body.rows]
    return ok(bk.set_staff_hours(db, org["org_id"], user_id, rows))


@staff.put("/booking/staff/{user_id}/use-business-hours")
def put_staff_use_org_hours(user_id: str, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    _admin_or_self(org, user_id)
    return ok(bk.set_staff(db, org["org_id"], user_id, uses_org_hours=True))


@staff.get("/booking/staff/{user_id}/blocks")
def list_staff_blocks(user_id: str, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok(bk.list_staff_blocks(db, org["org_id"], user_id))


@staff.post("/booking/staff/{user_id}/blocks", status_code=201)
def post_staff_block(user_id: str, body: BlockBody, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    _admin_or_self(org, user_id)
    return ok(bk.add_staff_block(db, org["org_id"], user_id, body.starts_at, body.ends_at, body.reason))


@staff.delete("/booking/staff/blocks/{block_id}")
def delete_staff_block(block_id: str, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    rows = db.table("booking_staff_blocks").select("user_id").eq("id", block_id).eq("org_id", org["org_id"]).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Not found"})
    _admin_or_self(org, rows[0]["user_id"])
    bk.delete_staff_block(db, org["org_id"], block_id)
    return ok({"deleted": True})


@staff.put("/booking/services/{service_id}/staff")
def put_service_staff(service_id: str, body: ServiceStaffBody, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    return ok({"user_ids": bk.set_service_staff(db, org["org_id"], service_id, body.user_ids)})


@staff.post("/booking/bookings/{demo_id}/assign")
def assign_booking(demo_id: str, body: AssignBody, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _gate(db, org["org_id"])
    if not _is_manager(org):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Only a manager or admin can reassign a booking."})
    return ok(bk.reassign_booking(db, org["org_id"], demo_id, body.user_id, org["id"]))


# ───────────────────────────── BOOKING-2C: WhatsApp slot picker ─────────────────────────────

class PickerBody(BaseModel):
    service: Optional[str] = Field(default=None, max_length=64)


@staff.post("/booking/leads/{lead_id}/wa-picker")
def start_wa_picker(lead_id: str, body: PickerBody, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    """Send the lead a day list on WhatsApp. If the 24h window is closed, the booking-link template is sent instead."""
    _gate(db, org["org_id"])
    from app.services import booking_wa_service as bwa
    service_id = bk.get_service(db, org["org_id"], body.service)["id"] if body.service else None
    return ok(bwa.start_picker(db, org["org_id"], lead_id, service_id=service_id, user_id=org["id"]))

