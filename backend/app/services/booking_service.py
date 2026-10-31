"""
app/services/booking_service.py
--------------------------------
BOOKING-1 — native booking (Phase 1): services, weekly hours, open slots, booking links.

One calendar per organisation. A booking is still a lead_demos row, so the existing reminders,
no-show handling, nudges and recap keep working. This module adds:

  - generate_slots()      pure calculation (no database) — unit tested
  - get_open_slots()      loads rules + busy times, calls generate_slots
  - book_slot()           re-checks the slot, inserts the booking, confirms it (instantly, or leaves it
                          pending when the service needs approval)
  - cancel_booking() / reschedule_booking()
  - create_link() / resolve_link()   signed link tied to one lead (only the hash is stored)

Rules
  - All times are stored in UTC. Weekly hours are read in the organisation timezone (DST safe).
  - Double booking is blocked by the database (lead_demos_no_overlap), not only by this code.
  - org_id always comes from the caller (JWT or public path), never from a request body.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

_LIVE_STATUSES = ("pending_assignment", "confirmed")
_LINK_DAYS = 14
_MAX_RANGE_DAYS = 62
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DEFAULT_SETTINGS = {
    "native_enabled": False,
    "label": "consultation",
    "cancel_cutoff_hours": 24,
    "auto_send_link": False,
    "default_rep_id": None,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _err(code: int, name: str, message: str) -> HTTPException:
    return HTTPException(status_code=code, detail={"code": name, "message": message})


# ───────────────────────────── pure slot calculation ─────────────────────────────

def _parse_hhmm(v) -> time:
    if isinstance(v, time):
        return v.replace(second=0, microsecond=0)
    s = str(v)
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def _local_to_utc(d: date, t: time, tz: ZoneInfo) -> Optional[datetime]:
    """Local wall time -> UTC. Returns None for a local time that does not exist (DST gap)."""
    naive = datetime.combine(d, t)
    aware = naive.replace(tzinfo=tz)
    utc = aware.astimezone(timezone.utc)
    if utc.astimezone(tz).replace(tzinfo=None) != naive:
        return None
    return utc


def generate_slots(
    *,
    tz_name: str,
    rules: Iterable[dict],
    duration_minutes: int,
    buffer_minutes: int,
    busy: Iterable[tuple[datetime, datetime]],
    blocks: Iterable[tuple[datetime, datetime]],
    now: datetime,
    min_notice_hours: int,
    window_days: int,
    from_date: date,
    to_date: date,
    step_minutes: Optional[int] = None,
) -> list[datetime]:
    """
    Return open slot start times (UTC, sorted) between from_date and to_date (dates in the org timezone).

    rules: dicts with weekday (0=Mon), start_time, end_time ("HH:MM" or time). Already limited to the
    service (the caller passes service-specific rules, or the all-service rules when none exist).
    busy: (start, end) UTC pairs of existing live bookings, end already includes their buffer.
    A slot starting at s occupies [s, s + duration + buffer) and must finish its duration inside the window.
    """
    tz = ZoneInfo(tz_name)
    step = max(5, int(step_minutes or duration_minutes))
    dur = timedelta(minutes=duration_minutes)
    occupy = timedelta(minutes=duration_minutes + buffer_minutes)
    earliest = now + timedelta(hours=min_notice_hours)
    latest = now + timedelta(days=window_days)
    busy_l = sorted(busy)
    block_l = sorted(blocks)

    by_day: dict[int, list[tuple[time, time]]] = {}
    for r in rules:
        by_day.setdefault(int(r["weekday"]), []).append((_parse_hhmm(r["start_time"]), _parse_hhmm(r["end_time"])))

    out: list[datetime] = []
    d = from_date
    while d <= to_date:
        for (w_start, w_end) in sorted(by_day.get(d.weekday(), [])):
            start_utc = _local_to_utc(d, w_start, tz)
            end_utc = _local_to_utc(d, w_end, tz) if w_end != time(0, 0) else _local_to_utc(d + timedelta(days=1), time(0, 0), tz)
            if start_utc is None or end_utc is None:
                continue
            s = start_utc
            while s + dur <= end_utc:
                e = s + occupy
                if s >= earliest and s <= latest and not _overlaps(s, e, busy_l) and not _overlaps(s, s + dur, block_l):
                    out.append(s)
                s += timedelta(minutes=step)
        d += timedelta(days=1)
    return sorted(set(out))


def _overlaps(s: datetime, e: datetime, ranges: list[tuple[datetime, datetime]]) -> bool:
    for (a, b) in ranges:
        if a < e and s < b:
            return True
    return False


def hours_from_business_hours(bh: Optional[dict]) -> list[dict]:
    """Convert organisations.business_hours ({"mon":{"start":"08:00","end":"17:00"},...}) into rules."""
    rules = []
    for i, key in enumerate(_WEEKDAYS):
        d = (bh or {}).get(key)
        if isinstance(d, dict) and d.get("start") and d.get("end"):
            rules.append({"weekday": i, "start_time": d["start"], "end_time": d["end"]})
    return rules


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "service"


# ───────────────────────────── database helpers ─────────────────────────────

def _first(res):
    data = res.data
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse_dt(v) -> datetime:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)


def get_org(db, org_id: str) -> dict:
    res = db.table("organisations").select("id, name, slug, timezone, business_hours").eq("id", org_id).maybe_single().execute()
    org = _first(res)
    if not org:
        raise _err(404, "NOT_FOUND", "Organisation not found")
    return org


def get_org_by_slug(db, slug: str) -> dict:
    res = db.table("organisations").select("id, name, slug, timezone, business_hours").eq("slug", slug).limit(1).execute()
    rows = res.data or []
    if not rows:
        raise _err(404, "NOT_FOUND", "Not found")
    return rows[0]


def get_settings(db, org_id: str) -> dict:
    res = db.table("booking_settings").select("*").eq("org_id", org_id).maybe_single().execute()
    row = _first(res) or {}
    return {**DEFAULT_SETTINGS, **{k: row[k] for k in DEFAULT_SETTINGS if k in row}}


def save_settings(db, org_id: str, patch: dict) -> dict:
    allowed = {k: v for k, v in patch.items() if k in DEFAULT_SETTINGS}
    if "label" in allowed:
        allowed["label"] = (allowed["label"] or "consultation").strip()[:40] or "consultation"
    if "cancel_cutoff_hours" in allowed:
        allowed["cancel_cutoff_hours"] = max(0, min(int(allowed["cancel_cutoff_hours"]), 720))
    allowed["org_id"] = org_id
    allowed["updated_at"] = _now_iso()
    db.table("booking_settings").upsert(allowed, on_conflict="org_id").execute()
    return get_settings(db, org_id)


def list_services(db, org_id: str, active_only: bool = False) -> list[dict]:
    q = db.table("booking_services").select("*").eq("org_id", org_id).is_("deleted_at", "null").order("sort_order").order("created_at")
    if active_only:
        q = q.eq("active", True)
    return q.execute().data or []


def get_service(db, org_id: str, service_id_or_slug: str) -> dict:
    q = db.table("booking_services").select("*").eq("org_id", org_id).is_("deleted_at", "null")
    if re.fullmatch(r"[0-9a-fA-F-]{36}", service_id_or_slug or ""):
        q = q.eq("id", service_id_or_slug)
    else:
        q = q.eq("slug", service_id_or_slug)
    rows = q.limit(1).execute().data or []
    if not rows:
        raise _err(404, "NOT_FOUND", "Service not found")
    return rows[0]


def _service_fields(payload: dict) -> dict:
    f = {}
    for k in ("name", "description", "location_text"):
        if k in payload and payload[k] is not None:
            f[k] = str(payload[k]).strip()[:500]
    for k, lo, hi in (("duration_minutes", 5, 480), ("buffer_after_minutes", 0, 240),
                      ("min_notice_hours", 0, 720), ("window_days", 1, 365), ("sort_order", 0, 9999)):
        if k in payload and payload[k] is not None:
            f[k] = max(lo, min(int(payload[k]), hi))
    if payload.get("medium") in ("virtual", "in_person", "phone"):
        f["medium"] = payload["medium"]
    for k in ("requires_approval", "active"):
        if k in payload and payload[k] is not None:
            f[k] = bool(payload[k])
    return f


def create_service(db, org_id: str, payload: dict) -> dict:
    f = _service_fields(payload)
    if not f.get("name"):
        raise _err(422, "VALIDATION_ERROR", "Service name is required")
    base = slugify(payload.get("slug") or f["name"])
    existing = {s["slug"] for s in list_services(db, org_id)}
    slug, n = base, 2
    while slug in existing:
        slug, n = f"{base}-{n}", n + 1
    f.update({"org_id": org_id, "slug": slug})
    db.table("booking_services").insert(f).execute()
    return get_service(db, org_id, slug)


def update_service(db, org_id: str, service_id: str, payload: dict) -> dict:
    get_service(db, org_id, service_id)
    f = _service_fields(payload)
    f["updated_at"] = _now_iso()
    db.table("booking_services").update(f).eq("id", service_id).eq("org_id", org_id).execute()
    return get_service(db, org_id, service_id)


def delete_service(db, org_id: str, service_id: str) -> None:
    get_service(db, org_id, service_id)
    db.table("booking_services").update({"deleted_at": _now_iso(), "active": False}).eq("id", service_id).eq("org_id", org_id).execute()


def get_availability(db, org_id: str) -> list[dict]:
    return db.table("booking_availability").select("id, service_id, weekday, start_time, end_time").eq("org_id", org_id).order("weekday").order("start_time").execute().data or []


def set_availability(db, org_id: str, rows: list[dict]) -> list[dict]:
    """Replace the all-service weekly hours."""
    clean = []
    for r in rows:
        w = int(r["weekday"])
        s, e = _parse_hhmm(r["start_time"]), _parse_hhmm(r["end_time"])
        if not (0 <= w <= 6) or e <= s:
            raise _err(422, "VALIDATION_ERROR", "Each row needs a weekday (0-6) and an end time after the start time")
        clean.append({"org_id": org_id, "service_id": None, "weekday": w,
                      "start_time": s.strftime("%H:%M"), "end_time": e.strftime("%H:%M")})
    db.table("booking_availability").delete().eq("org_id", org_id).is_("service_id", "null").execute()
    if clean:
        db.table("booking_availability").insert(clean).execute()
    return get_availability(db, org_id)


def ensure_default_availability(db, org_id: str, org: Optional[dict] = None) -> list[dict]:
    """First use: copy the organisation's existing business hours so slots work out of the box."""
    rows = get_availability(db, org_id)
    if rows:
        return rows
    org = org or get_org(db, org_id)
    rules = hours_from_business_hours(org.get("business_hours"))
    if not rules:
        rules = [{"weekday": i, "start_time": "09:00", "end_time": "17:00"} for i in range(5)]
    return set_availability(db, org_id, rules)


def list_blocks(db, org_id: str) -> list[dict]:
    return db.table("booking_blocks").select("*").eq("org_id", org_id).gte("ends_at", _now_iso()).order("starts_at").execute().data or []


def add_block(db, org_id: str, starts_at: str, ends_at: str, reason: Optional[str]) -> dict:
    s, e = _parse_dt(starts_at), _parse_dt(ends_at)
    if e <= s:
        raise _err(422, "VALIDATION_ERROR", "Block must end after it starts")
    row = {"org_id": org_id, "starts_at": s.isoformat(), "ends_at": e.isoformat(), "reason": (reason or "")[:200] or None}
    res = db.table("booking_blocks").insert(row).execute()
    return (res.data or [row])[0]


def delete_block(db, org_id: str, block_id: str) -> None:
    db.table("booking_blocks").delete().eq("id", block_id).eq("org_id", org_id).execute()


# ───────────────────────────── slots ─────────────────────────────

def _rules_for(db, org_id: str, service: dict) -> list[dict]:
    rows = get_availability(db, org_id)
    own = [r for r in rows if r.get("service_id") == service["id"]]
    return own or [r for r in rows if not r.get("service_id")]


def _busy_ranges(db, org_id: str, lo: datetime, hi: datetime) -> list[tuple[datetime, datetime]]:
    rows = (db.table("lead_demos").select("scheduled_at, slot_end, duration_minutes, status")
            .eq("org_id", org_id).in_("status", list(_LIVE_STATUSES)).is_("deleted_at", "null")
            .gte("scheduled_at", (lo - timedelta(days=1)).isoformat()).lte("scheduled_at", hi.isoformat())
            .execute().data or [])
    out = []
    for r in rows:
        if not r.get("scheduled_at"):
            continue
        s = _parse_dt(r["scheduled_at"])
        e = _parse_dt(r["slot_end"]) if r.get("slot_end") else s + timedelta(minutes=int(r.get("duration_minutes") or 30))
        out.append((s, e))
    return out


def get_open_slots(db, org: dict, service: dict, from_date: date, to_date: date, now: Optional[datetime] = None,
                   exclude_demo_id: Optional[str] = None) -> list[datetime]:
    if to_date < from_date:
        raise _err(422, "VALIDATION_ERROR", "to must not be before from")
    if (to_date - from_date).days > _MAX_RANGE_DAYS:
        raise _err(422, "VALIDATION_ERROR", f"Ask for at most {_MAX_RANGE_DAYS} days at a time")
    org_id = org["id"]
    now = now or _now()
    ensure_default_availability(db, org_id, org)
    tz = ZoneInfo(org.get("timezone") or "Africa/Lagos")
    lo = datetime.combine(from_date, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
    hi = datetime.combine(to_date + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)
    busy = _busy_ranges(db, org_id, lo, hi)
    if exclude_demo_id:
        ex = (db.table("lead_demos").select("scheduled_at, slot_end, duration_minutes").eq("id", exclude_demo_id).maybe_single().execute())
        row = _first(ex)
        if row and row.get("scheduled_at"):
            s = _parse_dt(row["scheduled_at"])
            e = _parse_dt(row["slot_end"]) if row.get("slot_end") else s + timedelta(minutes=int(row.get("duration_minutes") or 30))
            busy = [b for b in busy if b != (s, e)]
    blocks = [(_parse_dt(b["starts_at"]), _parse_dt(b["ends_at"])) for b in (
        db.table("booking_blocks").select("starts_at, ends_at").eq("org_id", org_id)
        .lte("starts_at", hi.isoformat()).gte("ends_at", lo.isoformat()).execute().data or [])]
    return generate_slots(
        tz_name=org.get("timezone") or "Africa/Lagos", rules=_rules_for(db, org_id, service),
        duration_minutes=service["duration_minutes"], buffer_minutes=service.get("buffer_after_minutes") or 0,
        busy=busy, blocks=blocks, now=now, min_notice_hours=service.get("min_notice_hours") or 0,
        window_days=service.get("window_days") or 30, from_date=from_date, to_date=to_date,
    )


# ───────────────────────────── booking ─────────────────────────────

def _is_overlap_error(exc: Exception) -> bool:
    t = str(exc)
    return "lead_demos_no_overlap" in t or "23P01" in t


def pick_rep(db, org_id: str) -> Optional[str]:
    """Default rep from settings, else rotate through active owner/admin/ops_manager users."""
    cfg = db.table("booking_settings").select("default_rep_id, rr_cursor").eq("org_id", org_id).maybe_single().execute()
    row = _first(cfg) or {}
    if row.get("default_rep_id"):
        return row["default_rep_id"]
    from app.services.demo_service import _get_all_manager_ids
    ids = sorted(_get_all_manager_ids(db, org_id))
    if not ids:
        return None
    cur = int(row.get("rr_cursor") or 0)
    try:
        db.table("booking_settings").upsert({"org_id": org_id, "rr_cursor": cur + 1, "updated_at": _now_iso()}, on_conflict="org_id").execute()
    except Exception as exc:
        logger.warning("booking: rr cursor update failed - %s", exc)
    return ids[cur % len(ids)]


def _assert_slot_open(db, org: dict, service: dict, start_utc: datetime, exclude_demo_id: Optional[str] = None) -> None:
    tz = ZoneInfo(org.get("timezone") or "Africa/Lagos")
    d = start_utc.astimezone(tz).date()
    open_slots = get_open_slots(db, org, service, d, d, exclude_demo_id=exclude_demo_id)
    if start_utc not in open_slots:
        raise _err(409, "SLOT_TAKEN", "That time is no longer available. Please pick another.")


def book_slot(db, org_id: str, lead_id: str, service: dict, start_utc: datetime, source: str = "native",
              lead_timezone: Optional[str] = None, user_id: Optional[str] = None, notes: Optional[str] = None) -> dict:
    """Create a booking in a verified open slot. Instant confirm unless the service needs approval."""
    from app.services import demo_service as ds
    org = get_org(db, org_id)
    lead = ds._confirm_lead_in_org(db, org_id, lead_id)
    start_utc = start_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)
    _assert_slot_open(db, org, service, start_utc)

    live = (db.table("lead_demos").select("id").eq("org_id", org_id).eq("lead_id", lead_id)
            .in_("status", list(_LIVE_STATUSES)).is_("deleted_at", "null").gte("scheduled_at", _now_iso()).limit(1).execute().data or [])
    if live:
        raise _err(409, "ALREADY_BOOKED", "This person already has an upcoming booking. Reschedule or cancel it first.")

    dur = int(service["duration_minutes"])
    slot_end = start_utc + timedelta(minutes=dur + int(service.get("buffer_after_minutes") or 0))
    demo_id = _insert_booking_row(db, org_id, lead_id, service, start_utc, slot_end, source, lead_timezone, user_id, notes)

    if service.get("requires_approval"):
        _notify_approval_needed(db, org_id, lead, demo_id, start_utc, org)
        ds._log_timeline(db, org_id, lead_id, user_id, "booking_requested",
                         f"Booking requested for {_fmt_local(start_utc, org)} ({service['name']}). Waiting for approval.",
                         {"demo_id": demo_id, "service_id": service["id"], "source": source})
    else:
        rep = pick_rep(db, org_id)
        if not rep:
            # No one to assign: leave it pending so a manager can confirm, never lose the booking.
            _notify_approval_needed(db, org_id, lead, demo_id, start_utc, org)
        else:
            ds.confirm_demo(db, org_id, lead_id, demo_id, user_id, start_utc.isoformat(),
                            service.get("medium") or "virtual", rep, duration_minutes=dur, notes=notes)
            ds._log_timeline(db, org_id, lead_id, user_id, "booking_made",
                             f"{service['name']} booked for {_fmt_local(start_utc, org)} ({source}).",
                             {"demo_id": demo_id, "service_id": service["id"], "source": source})
    return ds._fetch_demo_by_id(db, org_id, demo_id)


def _insert_booking_row(db, org_id, lead_id, service, start_utc, slot_end, source, lead_tz, user_id, notes) -> str:
    import uuid
    demo_id = str(uuid.uuid4())
    now = _now_iso()
    try:
        db.table("lead_demos").insert({
            "id": demo_id, "org_id": org_id, "lead_id": lead_id, "status": "pending_assignment",
            "service_id": service["id"], "source": source, "medium": service.get("medium") or "virtual",
            "scheduled_at": start_utc.isoformat(), "slot_end": slot_end.isoformat(),
            "duration_minutes": int(service["duration_minutes"]), "lead_timezone": lead_tz,
            "notes": notes, "created_by": user_id, "created_at": now, "updated_at": now,
        }).execute()
    except Exception as exc:
        if _is_overlap_error(exc):
            raise _err(409, "SLOT_TAKEN", "That time was just taken. Please pick another.") from exc
        raise
    return demo_id


def _fmt_local(dt_utc: datetime, org: dict, tz_name: Optional[str] = None) -> str:
    tz = ZoneInfo(tz_name or org.get("timezone") or "Africa/Lagos")
    return dt_utc.astimezone(tz).strftime("%A, %d %b %Y at %I:%M %p")


def _notify_approval_needed(db, org_id, lead, demo_id, start_utc, org) -> None:
    from app.services import demo_service as ds
    mgr = ds._get_manager_id(db, org_id)
    if not mgr:
        return
    name = lead.get("full_name") or "Lead"
    when = _fmt_local(start_utc, org)
    ds._create_task(db, org_id, lead["id"], mgr, f"Approve booking for {name} - {when}", (_now() + timedelta(hours=4)).isoformat())
    ds._insert_notification(db, org_id, mgr, "demo_request_pending", f"Booking to approve: {name}",
                            f"{name} asked for {when}. Open the lead to confirm.", demo_id)


def _get_live_booking(db, org_id: str, demo_id: str) -> dict:
    from app.services import demo_service as ds
    d = ds._fetch_demo_by_id(db, org_id, demo_id)
    if d.get("status") not in _LIVE_STATUSES:
        raise _err(400, "INVALID_TRANSITION", f"This booking is already {d.get('status')}.")
    return d


def _check_cutoff(db, org_id: str, demo: dict, enforce: bool) -> None:
    if not enforce or not demo.get("scheduled_at"):
        return
    hours = int(get_settings(db, org_id).get("cancel_cutoff_hours") or 0)
    if hours and _parse_dt(demo["scheduled_at"]) - _now() < timedelta(hours=hours):
        raise _err(403, "TOO_LATE", f"Changes are only allowed up to {hours} hours before. Please contact us directly.")


def cancel_booking(db, org_id: str, demo_id: str, by: str, reason: Optional[str] = None, user_id: Optional[str] = None) -> dict:
    """by = 'lead' (cutoff enforced) or 'staff'."""
    from app.services import demo_service as ds
    demo = _get_live_booking(db, org_id, demo_id)
    _check_cutoff(db, org_id, demo, enforce=(by == "lead"))
    now = _now_iso()
    db.table("lead_demos").update({
        "status": "cancelled", "cancelled_at": now, "cancelled_by": by,
        "cancel_reason": (reason or "")[:500] or None, "updated_at": now,
    }).eq("id", demo_id).eq("org_id", org_id).execute()
    org = get_org(db, org_id)
    lead = ds._confirm_lead_in_org(db, org_id, demo["lead_id"])
    when = _fmt_local(_parse_dt(demo["scheduled_at"]), org, demo.get("lead_timezone")) if demo.get("scheduled_at") else ""
    label = get_settings(db, org_id)["label"]
    ds._log_timeline(db, org_id, demo["lead_id"], user_id, "booking_cancelled",
                     f"Booking cancelled by {by}{(': ' + reason) if reason else ''}.", {"demo_id": demo_id})
    if demo.get("assigned_to"):
        ds._insert_notification(db, org_id, demo["assigned_to"], "demo_cancelled", f"Booking cancelled: {lead.get('full_name') or 'Lead'}",
                                f"The {label} on {when} was cancelled by {by}.", demo_id)
    ds._auto_send_wa(db, org_id, lead, (f"Your {label} on {when} has been cancelled." if when else f"Your {label} request has been cancelled.") + " Reply here any time to book a new time.")
    return ds._fetch_demo_by_id(db, org_id, demo_id)


def reschedule_booking(db, org_id: str, demo_id: str, new_start_utc: datetime, by: str, user_id: Optional[str] = None) -> dict:
    from app.services import demo_service as ds
    demo = _get_live_booking(db, org_id, demo_id)
    _check_cutoff(db, org_id, demo, enforce=(by == "lead"))
    org = get_org(db, org_id)
    service = get_service(db, org_id, demo["service_id"]) if demo.get("service_id") else {
        "id": None, "duration_minutes": demo.get("duration_minutes") or 30, "buffer_after_minutes": 0,
        "min_notice_hours": 2, "window_days": 30, "medium": demo.get("medium"), "name": "Booking"}
    new_start = new_start_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)
    _assert_slot_open(db, org, service, new_start, exclude_demo_id=demo_id)
    slot_end = new_start + timedelta(minutes=int(service["duration_minutes"]) + int(service.get("buffer_after_minutes") or 0))
    try:
        db.table("lead_demos").update({
            "scheduled_at": new_start.isoformat(), "slot_end": slot_end.isoformat(),
            "reminder_24h_sent": False, "reminder_1h_sent": False, "noshow_task_created": False,
            "rep_nudge_sent_at": None, "manager_nudge_sent_at": None,
            "reschedule_count": int(demo.get("reschedule_count") or 0) + 1, "updated_at": _now_iso(),
        }).eq("id", demo_id).eq("org_id", org_id).execute()
    except Exception as exc:
        if _is_overlap_error(exc):
            raise _err(409, "SLOT_TAKEN", "That time was just taken. Please pick another.") from exc
        raise
    lead = ds._confirm_lead_in_org(db, org_id, demo["lead_id"])
    when = _fmt_local(new_start, org, demo.get("lead_timezone"))
    ds._log_timeline(db, org_id, demo["lead_id"], user_id, "booking_rescheduled",
                     f"Booking moved to {when} by {by}.", {"demo_id": demo_id})
    if demo.get("assigned_to"):
        ds._insert_notification(db, org_id, demo["assigned_to"], "demo_confirmed", f"Booking moved: {lead.get('full_name') or 'Lead'}",
                                f"Now {when}.", demo_id)
    ds._auto_send_wa(db, org_id, lead, f"Your {get_settings(db, org_id)['label']} has been moved to {when}. See you then.")
    return ds._fetch_demo_by_id(db, org_id, demo_id)


def list_bookings(db, org_id: str, from_dt: datetime, to_dt: datetime) -> list[dict]:
    rows = (db.table("lead_demos")
            .select("id, lead_id, status, scheduled_at, slot_end, duration_minutes, medium, service_id, assigned_to, source, leads(full_name, whatsapp)")
            .eq("org_id", org_id).is_("deleted_at", "null").not_.is_("scheduled_at", "null")
            .gte("scheduled_at", from_dt.isoformat()).lte("scheduled_at", to_dt.isoformat())
            .order("scheduled_at").execute().data or [])
    return rows


# ───────────────────────────── links ─────────────────────────────

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_link(db, org_id: str, lead_id: str, service_id: Optional[str], user_id: Optional[str]) -> str:
    """Returns the plain token (shown once). Only the hash is stored."""
    from app.services import demo_service as ds
    ds._confirm_lead_in_org(db, org_id, lead_id)
    token = secrets.token_urlsafe(24)
    db.table("booking_links").insert({
        "org_id": org_id, "lead_id": lead_id, "service_id": service_id, "token_hash": _hash(token),
        "expires_at": (_now() + timedelta(days=_LINK_DAYS)).isoformat(), "created_by": user_id,
    }).execute()
    return token


def resolve_link(db, token: str) -> dict:
    rows = db.table("booking_links").select("*").eq("token_hash", _hash(token or "")).limit(1).execute().data or []
    if not rows or _parse_dt(rows[0]["expires_at"]) < _now():
        raise _err(404, "LINK_INVALID", "This link has expired. Please ask for a new one.")
    return rows[0]


def link_attach_booking(db, link_id: str, demo_id: str) -> None:
    db.table("booking_links").update({"demo_id": demo_id, "used_at": _now_iso()}).eq("id", link_id).execute()
