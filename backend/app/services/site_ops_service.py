"""
app/services/site_ops_service.py
----------------------------------
SITE-3 part 3 — the staff-side actions behind the Orders, Hosting queue and
Domains & renewals dashboard tabs (spec §13, §11.4, §11.7, §11.8, §17).

Everything here is a synchronous, user-facing action taken by a signed-in
staff member, so — unlike site_order_service.on_payment_confirmed, which runs
inside a webhook — it is allowed to fail loudly with a typed SiteOpsError that
routers/sites.py turns into a 4xx. Side-effects that must never undo the main
action (WhatsApp message to the builder, manager push notification, CRM lead
conversion, task-board tidy-up) are individually try/excepted, per S14.

State changes are conditional updates (`.eq("status", expected)`, spec §6):
a double-click or two staff acting at once can only ever move an order once.
Every money-relevant action writes a `site_events` row (spec §18 Money).

Approval window (spec §6.2, L4): `approve_order` only works inside
`approval_window_start`..`approval_window_end` in `approval_timezone`
(start inclusive, end exclusive — 08:00 is in, 23:00 is out). Rejecting is not
window-gated: it buys nothing and never touches the builder's money.

Refunds (spec §11.8, L16): refund = amount paid − the service fee, decided
from the quote saved on the order. v1 refunds are made by hand in Paystack;
Opsra records the amount and the date (`record_refund`).
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_SLA_AMBER_BEFORE_HOURS = 12  # keep in step with workers/site_worker.py (spec §11.4)
_EXPIRING_DAYS = 30           # spec §13 — the Domains tab's "expiring" threshold
_PAID_KEPT_STATUSES = ("awaiting_approval", "fulfilling", "live", "needs_builder_choice")
_PAID_STATUSES = _PAID_KEPT_STATUSES + ("rejected", "refund_pending", "refunded")
_JOB_EDITABLE_STATUSES = ("queued", "in_progress", "blocked")
_IMAGE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


# ---------------------------------------------------------------------------
# Errors — routers/sites.py maps these onto HTTPException
# ---------------------------------------------------------------------------

class SiteOpsError(Exception):
    status_code = 400
    code = "INVALID_TRANSITION"


class NotFound(SiteOpsError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(SiteOpsError):
    status_code = 409
    code = "INVALID_TRANSITION"


class OutsideApprovalWindow(Conflict):
    pass


class ValidationFailed(SiteOpsError):
    status_code = 422
    code = "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _add_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + 1, day=28)


def _money(n) -> str:
    try:
        return f"₦{round(float(n)):,}"
    except (TypeError, ValueError):
        return "₦0"


def _log_event(db: Any, org_id: str, site_id: Optional[str], actor: str, event: str,
               detail: Optional[dict] = None, order_id: Optional[str] = None) -> None:
    try:
        db.table("site_events").insert({
            "org_id": org_id, "site_id": site_id, "order_id": order_id,
            "actor": actor, "event": event, "detail": detail or {}, "created_at": _iso(),
        }).execute()
    except Exception as exc:  # S14
        logger.warning("site_events insert failed event=%s: %s", event, exc)


def _message_builder(db: Any, org_id: str, order: dict, text: str) -> None:
    try:
        from app.services import site_order_service
        site_order_service._message_builder(db, org_id, order, text)
    except Exception as exc:  # S14
        logger.warning("site_ops: builder message failed order=%s: %s", order.get("id"), exc)


def _notify_managers(db: Any, org_id: str, title: str, body: str, notif_type: str) -> None:
    try:
        from app.services import funnel_service
        funnel_service.notify_managers(db, org_id, title, body, notif_type, None)
    except Exception as exc:  # S14
        logger.warning("site_ops: manager notify failed type=%s: %s", notif_type, exc)


def _complete_tasks(db: Any, org_id: str, source_record_id: str, notes: str) -> None:
    """Tidy the task board when a job/refund is finished (tasks.status 'completed')."""
    try:
        now = _iso()
        db.table("tasks").update({
            "status": "completed", "completed_at": now, "completion_notes": notes, "updated_at": now,
        }).eq("org_id", org_id).eq("source_record_id", source_record_id).neq("status", "completed").execute()
    except Exception as exc:  # S14
        logger.warning("site_ops: task completion failed record=%s: %s", source_record_id, exc)


def _get_order(db: Any, org_id: str, order_id: str) -> dict:
    row = _one((db.table("site_orders").select("*").eq("id", order_id).eq("org_id", org_id).limit(1).execute()).data)
    if not row:
        raise NotFound("Order not found")
    return row


def _get_job(db: Any, org_id: str, job_id: str) -> dict:
    row = _one((db.table("site_hosting_jobs").select("*").eq("id", job_id).eq("org_id", org_id).limit(1).execute()).data)
    if not row:
        raise NotFound("Hosting job not found")
    return row


def _service_fee(order: dict) -> float:
    try:
        return float(((order.get("quote") or {}).get("price") or {}).get("service_fee") or 0)
    except (TypeError, ValueError):
        return 0.0


def refund_amount_for(order: dict) -> float:
    """spec §11.8 / L16 — everything except Opsra's service fee."""
    return round(max(0.0, float(order.get("amount") or 0) - _service_fee(order)), 2)


# ---------------------------------------------------------------------------
# Approval window — spec §6.2 / L4
# ---------------------------------------------------------------------------

def _minutes(value, default: str) -> int:
    for raw in (value, default):
        try:
            h, m = str(raw).split(":")[:2]
            return int(h) * 60 + int(m)
        except (ValueError, TypeError):
            continue
    return 0


def in_approval_window(settings: dict, now: Optional[datetime] = None) -> bool:
    now = now or _now()
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(settings.get("approval_timezone") or "Africa/Lagos")
    except Exception:
        tz = timezone(timedelta(hours=1))  # WAT
    local = now.astimezone(tz)
    cur = local.hour * 60 + local.minute
    start = _minutes(settings.get("approval_window_start"), "08:00")
    end = _minutes(settings.get("approval_window_end"), "23:00")
    if start == end:
        return True
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end  # window wraps midnight


def approval_info(settings: dict, now: Optional[datetime] = None) -> dict:
    return {
        "required": bool(settings.get("approval_required")),
        "orders_remaining": settings.get("approval_orders_remaining"),
        "window_start": str(settings.get("approval_window_start") or "08:00")[:5],
        "window_end": str(settings.get("approval_window_end") or "23:00")[:5],
        "timezone": settings.get("approval_timezone") or "Africa/Lagos",
        "in_window": in_approval_window(settings, now),
    }


# ---------------------------------------------------------------------------
# Orders — list
# ---------------------------------------------------------------------------

def _by_id(db: Any, table: str, org_id: str, ids: list, columns: str) -> dict:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    rows = (db.table(table).select(columns).eq("org_id", org_id).in_("id", ids).execute()).data or []
    return {r["id"]: r for r in rows}


def list_orders(db: Any, org_id: str, status: Optional[str] = None, search: Optional[str] = None,
                page: int = 1, page_size: int = 50, now: Optional[datetime] = None) -> dict:
    from app.services import pricing_service
    q = db.table("site_orders").select("*").eq("org_id", org_id)
    if status:
        q = q.eq("status", status)
    rows = q.order("created_at", desc=True).execute().data or []

    sites = _by_id(db, "sites", org_id, [r.get("site_id") for r in rows], "id, client_business_name, slug, live_url")
    builders = _by_id(db, "site_builders", org_id, [r.get("builder_id") for r in rows],
                      "id, full_name, business_name, phone_number")
    jobs = _by_id(db, "site_hosting_jobs", org_id, [r.get("hosting_job_id") for r in rows],
                  "id, status, sla_due_at, domain_used")
    now = now or _now()
    out = []
    for r in rows:
        site = sites.get(r.get("site_id")) or {}
        b = builders.get(r.get("builder_id")) or {}
        job = jobs.get(r.get("hosting_job_id"))
        r = dict(r)
        r["client_business_name"] = site.get("client_business_name")
        r["site_slug"] = site.get("slug")
        r["builder_name"] = b.get("full_name")
        r["builder_business"] = b.get("business_name")
        r["builder_phone"] = b.get("phone_number")
        r["hosting_job"] = ({**job, "sla_state": _sla_state(job, now)} if job else None)
        r["service_fee"] = _service_fee(r)
        r["refund_due"] = refund_amount_for(r) if r.get("status") in ("refund_pending", "awaiting_approval", "needs_builder_choice") else None
        out.append(r)

    if search:  # Pattern 33 — Python-side filter
        s = search.lower().strip()
        out = [r for r in out if s in " ".join(str(r.get(k) or "") for k in
               ("domain", "backup_domain", "client_business_name", "builder_name", "builder_business", "payment_reference")).lower()]

    total = len(out)
    start = (page - 1) * page_size
    settings = pricing_service.get_settings(db, org_id)
    return {"items": out[start:start + page_size], "total": total, "page": page, "page_size": page_size,
            "approval": approval_info(settings, now)}


# ---------------------------------------------------------------------------
# Orders — approve / reject / record refund / resolve domain
# ---------------------------------------------------------------------------

def _register_approved_order(db: Any, org_id: str, order: dict, user_id: str) -> None:
    """spec §11.7 — a builder's FIRST approved (or live) order converts their lead
    to a customer; later orders make no stage change. Never raises (S14)."""
    try:
        builder = _one((db.table("site_builders").select("id, lead_id, approved_orders_count")
                        .eq("id", order["builder_id"]).eq("org_id", org_id).limit(1).execute()).data)
        if not builder:
            return
        prior = int(builder.get("approved_orders_count") or 0)
        db.table("site_builders").update({"approved_orders_count": prior + 1, "updated_at": _iso()}) \
            .eq("id", builder["id"]).eq("org_id", org_id).execute()
        if prior == 0 and builder.get("lead_id"):
            from app.services import lead_service
            lead_service.convert_lead(db, org_id, builder["lead_id"], user_id)
    except Exception as exc:  # S14 — includes HTTPException from convert_lead
        logger.warning("site_ops: first-order lead conversion failed order=%s: %s", order.get("id"), getattr(exc, "detail", exc))


def _use_up_approval_quota(db: Any, org_id: str, settings: dict) -> None:
    try:
        remaining = settings.get("approval_orders_remaining")
        if remaining is None or int(remaining) <= 0:
            return
        new = int(remaining) - 1
        db.table("site_builder_settings").update({"approval_orders_remaining": new, "updated_at": _iso()}) \
            .eq("org_id", org_id).execute()
        if new == 0:
            _notify_managers(db, org_id, "Approval quota reached",
                             "You've approved the planned number of orders. Switch approvals off in Sites → Settings when you're ready.",
                             "site_approval_quota")
    except Exception as exc:  # S14
        logger.warning("site_ops: approval quota update failed: %s", exc)


def approve_order(db: Any, org_id: str, order_id: str, user_id: str, now: Optional[datetime] = None) -> dict:
    from app.services import pricing_service, site_order_service
    now = now or _now()
    order = _get_order(db, org_id, order_id)
    if order["status"] != "awaiting_approval":
        raise Conflict(f"This order is '{order['status']}', not awaiting approval.")

    settings = pricing_service.get_settings(db, org_id)
    if not in_approval_window(settings, now):
        info = approval_info(settings, now)
        raise OutsideApprovalWindow(
            f"Approvals run {info['window_start']}–{info['window_end']} ({info['timezone']}). "
            "This order can be approved when the window opens.")

    claim = (db.table("site_orders").update({
        "status": "fulfilling", "approved_by": user_id, "approved_at": _iso(now), "updated_at": _iso(now),
    }).eq("id", order["id"]).eq("org_id", org_id).eq("status", "awaiting_approval").execute())
    if not claim.data:
        raise Conflict("This order was just handled by someone else.")
    order = {**order, **(_one(claim.data) or {}), "status": "fulfilling"}

    job = None
    if order.get("route") == "standard":
        try:
            job = site_order_service.create_hosting_job(db, org_id, order)
        except Exception as exc:
            # Roll the claim back so the approval can simply be retried (create_hosting_job is idempotent).
            logger.warning("site_ops: hosting job creation failed order=%s: %s", order["id"], exc)
            db.table("site_orders").update({"status": "awaiting_approval", "approved_by": None, "approved_at": None,
                                            "updated_at": _iso()}) \
                .eq("id", order["id"]).eq("org_id", org_id).eq("status", "fulfilling").execute()
            raise SiteOpsError("Couldn't start the hosting job, so the approval was rolled back. Please try again.")

    _log_event(db, org_id, order.get("site_id"), f"user:{user_id}", "order_approved",
               {"amount": order.get("amount"), "route": order.get("route"), "domain": order.get("domain")}, order["id"])
    _register_approved_order(db, org_id, order, user_id)
    _use_up_approval_quota(db, org_id, settings)
    return {"order": order, "hosting_job": job,
            "express_pending": order.get("route") == "express"}


def reject_order(db: Any, org_id: str, order_id: str, user_id: str, reason: str) -> dict:
    """awaiting_approval → refund_pending (rejected), or needs_builder_choice → refund_pending
    (builder asked for the refund). spec §6.2 / §11.8."""
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValidationFailed("A reason is required.")
    order = _get_order(db, org_id, order_id)
    from_status = order["status"]
    if from_status not in ("awaiting_approval", "needs_builder_choice"):
        raise Conflict(f"This order is '{from_status}' and can't be rejected or refunded from here.")

    refund = refund_amount_for(order)
    now = _iso()
    claim = (db.table("site_orders").update({
        "status": "refund_pending", "rejected_reason": reason[:1000], "refund_amount": refund, "updated_at": now,
    }).eq("id", order["id"]).eq("org_id", org_id).eq("status", from_status).execute())
    if not claim.data:
        raise Conflict("This order was just handled by someone else.")
    order = {**order, **(_one(claim.data) or {}), "status": "refund_pending", "refund_amount": refund}

    # Any open hosting job for this order is closed — a refunded order must not keep paging anyone.
    if order.get("hosting_job_id"):
        try:
            db.table("site_hosting_jobs").update({
                "status": "done", "completed_at": now, "updated_at": now,
                "notes": "Closed — order rejected/refunded.",
            }).eq("id", order["hosting_job_id"]).eq("org_id", org_id).neq("status", "done").execute()
            _complete_tasks(db, org_id, order["hosting_job_id"], "Order rejected/refunded")
        except Exception as exc:  # S14
            logger.warning("site_ops: closing job on reject failed order=%s: %s", order["id"], exc)

    try:
        db.table("tasks").insert({
            "org_id": org_id,
            "title": f"Refund {_money(refund)} — {order.get('domain') or order['id']}",
            "description": (f"Refund by hand in Paystack (payment reference {order.get('payment_reference')}). "
                            f"Everything except the service fee ({_money(_service_fee(order))}). "
                            "Then open Sites → Orders and click 'Record refund'."),
            "task_type": "refund", "source_module": "site_orders", "source_record_id": order["id"],
            "priority": "high", "status": "pending", "created_at": now, "updated_at": now, "created_by": None,
        }).execute()
    except Exception as exc:  # S14
        logger.warning("site_ops: refund task failed order=%s: %s", order["id"], exc)

    _message_builder(db, org_id, order,
                     f"We're sorry — we couldn't complete your order for {order.get('domain')}. "
                     f"A refund of {_money(refund)} (everything except our service fee) is on its way.")
    _log_event(db, org_id, order.get("site_id"), f"user:{user_id}",
               "order_rejected" if from_status == "awaiting_approval" else "refund_requested",
               {"reason": reason[:300], "refund_amount": refund}, order["id"])
    return order


def record_refund(db: Any, org_id: str, order_id: str, user_id: str, amount: Optional[float] = None) -> dict:
    """refund_pending → refunded. The money was already sent by hand in Paystack (v1, spec §11.8)."""
    order = _get_order(db, org_id, order_id)
    if order["status"] != "refund_pending":
        raise Conflict(f"This order is '{order['status']}', not waiting for a refund.")
    value = round(float(amount), 2) if amount is not None else float(order.get("refund_amount") or refund_amount_for(order))
    if value <= 0 or value > float(order.get("amount") or 0):
        raise ValidationFailed("The refund must be more than zero and no more than the amount paid.")

    now = _iso()
    claim = (db.table("site_orders").update({
        "status": "refunded", "refund_amount": value, "refunded_at": now, "updated_at": now,
    }).eq("id", order["id"]).eq("org_id", org_id).eq("status", "refund_pending").execute())
    if not claim.data:
        raise Conflict("This refund was just recorded by someone else.")
    order = {**order, **(_one(claim.data) or {}), "status": "refunded", "refund_amount": value, "refunded_at": now}

    _complete_tasks(db, org_id, order["id"], f"Refund of {_money(value)} recorded")
    _message_builder(db, org_id, order, f"Your refund of {_money(value)} for {order.get('domain')} has been sent.")
    _log_event(db, org_id, order.get("site_id"), f"user:{user_id}", "refund_recorded",
               {"refund_amount": value}, order["id"])
    return order


def resolve_domain_choice(db: Any, org_id: str, order_id: str, user_id: str, domain: str) -> dict:
    """needs_builder_choice → fulfilling with a new domain (spec §6.2). The new domain must end the
    same way as the original — a different ending changes the price, which needs a refund and re-order."""
    from app.services import domain_check_service, pricing_service
    order = _get_order(db, org_id, order_id)
    if order["status"] != "needs_builder_choice":
        raise Conflict(f"This order is '{order['status']}', not waiting for a domain choice.")

    settings = pricing_service.get_settings(db, org_id)
    tlds = domain_check_service._supported_tlds(settings)
    try:
        _, old_tld = domain_check_service._split_label_tld(order.get("domain") or "", tlds)
        normalised, available = domain_check_service.check_availability_fresh(db, org_id, domain)
        _, new_tld = domain_check_service._split_label_tld(normalised, tlds)
    except domain_check_service.DomainCheckError as exc:
        raise ValidationFailed(str(exc))
    if new_tld != old_tld:
        raise ValidationFailed(f"The new domain must end in {old_tld} like the original — a different ending changes the price.")
    if available is not True:
        raise ValidationFailed(f"{normalised} isn't confirmed available right now." if available is None
                               else f"{normalised} is taken.")

    now = _iso()
    claim = (db.table("site_orders").update({"domain": normalised, "status": "fulfilling", "updated_at": now})
             .eq("id", order["id"]).eq("org_id", org_id).eq("status", "needs_builder_choice").execute())
    if not claim.data:
        raise Conflict("This order was just handled by someone else.")
    order = {**order, "domain": normalised, "status": "fulfilling"}

    if order.get("hosting_job_id"):
        job = _get_job(db, org_id, order["hosting_job_id"])
        checklist = _tick(job.get("checklist"), "recheck_domain", True)
        db.table("site_hosting_jobs").update({
            "status": "queued", "domain_used": normalised, "domain_rechecked_at": now,
            "checklist": checklist, "updated_at": now,
        }).eq("id", job["id"]).eq("org_id", org_id).execute()
    _log_event(db, org_id, order.get("site_id"), f"user:{user_id}", "domain_choice_resolved",
               {"domain": normalised}, order["id"])
    return order


# ---------------------------------------------------------------------------
# Hosting queue
# ---------------------------------------------------------------------------

def _sla_state(job: dict, now: datetime) -> str:
    if job.get("status") == "done":
        return "done"
    due = _parse_iso(job.get("sla_due_at"))
    if not due:
        return "none"
    if now >= due:
        return "red"
    if (due - now) <= timedelta(hours=_SLA_AMBER_BEFORE_HOURS):
        return "amber"
    return "green"


def _tick(checklist, key: str, done: bool) -> list:
    out, found = [], False
    for item in (checklist or []):
        item = dict(item)
        if item.get("key") == key:
            found = True
            item["done"] = bool(done)
            item["done_at"] = _iso() if done else None
        out.append(item)
    if not found:
        raise ValidationFailed(f"Unknown checklist step '{key}'.")
    return out


def _enrich_jobs(db: Any, org_id: str, jobs: list, now: datetime) -> list:
    orders = _by_id(db, "site_orders", org_id, [j.get("order_id") for j in jobs],
                    "id, domain, backup_domain, route, amount, status, builder_id, kind")
    sites = _by_id(db, "sites", org_id, [j.get("site_id") for j in jobs], "id, client_business_name, slug, live_url")
    users = _by_id(db, "users", org_id, [j.get("assigned_to") for j in jobs], "id, full_name")
    out = []
    for j in jobs:
        o = orders.get(j.get("order_id")) or {}
        s = sites.get(j.get("site_id")) or {}
        due = _parse_iso(j.get("sla_due_at"))
        j = dict(j)
        j.update({
            "domain": o.get("domain"), "backup_domain": o.get("backup_domain"), "route": o.get("route"),
            "order_status": o.get("status"), "order_amount": o.get("amount"), "order_kind": o.get("kind") or "initial",
            "client_business_name": s.get("client_business_name"), "site_slug": s.get("slug"),
            "live_url": s.get("live_url"),
            "assigned_name": (users.get(j.get("assigned_to")) or {}).get("full_name"),
            "sla_state": _sla_state(j, now),
            "seconds_to_sla": int((due - now).total_seconds()) if due and j.get("status") != "done" else None,
        })
        out.append(j)
    return out


def list_hosting_jobs(db: Any, org_id: str, assigned_to: Optional[str] = None, include_done: bool = False,
                      now: Optional[datetime] = None) -> list:
    now = now or _now()
    q = db.table("site_hosting_jobs").select("*").eq("org_id", org_id)
    if not include_done:
        q = q.neq("status", "done")
    if assigned_to:
        q = q.eq("assigned_to", assigned_to)
    rows = q.order("sla_due_at").limit(200).execute().data or []
    return _enrich_jobs(db, org_id, rows, now)


def _job_view(db: Any, org_id: str, job_id: str) -> dict:
    return _enrich_jobs(db, org_id, [_get_job(db, org_id, job_id)], _now())[0]


def patch_hosting_job(db: Any, org_id: str, job_id: str, user_id: str, fields: dict) -> dict:
    """fields (only the keys the caller sent): assigned_to (user id | None), status, notes,
    step (checklist key) + step_done."""
    job = _get_job(db, org_id, job_id)
    if job["status"] == "done":
        raise Conflict("This job is already done.")
    updates: dict = {}
    detail: dict = {}

    if "assigned_to" in fields:
        uid = fields["assigned_to"]
        if uid:
            user = _one((db.table("users").select("id").eq("id", uid).eq("org_id", org_id)
                         .eq("is_active", True).limit(1).execute()).data)
            if not user:
                raise ValidationFailed("That person isn't an active member of this organisation.")
        updates["assigned_to"] = uid or None
        detail["assigned_to"] = uid or None
        try:  # keep the board task in step
            db.table("tasks").update({"assigned_to": uid or None, "updated_at": _iso()}) \
                .eq("org_id", org_id).eq("source_record_id", job["id"]).neq("status", "completed").execute()
        except Exception as exc:  # S14
            logger.warning("site_ops: task reassignment failed job=%s: %s", job["id"], exc)

    if fields.get("status") is not None:
        if fields["status"] not in _JOB_EDITABLE_STATUSES:
            raise ValidationFailed("Use 'Mark live' to finish a job.")
        updates["status"] = fields["status"]
        detail["status"] = fields["status"]

    if "notes" in fields:
        updates["notes"] = (fields["notes"] or "")[:5000]

    if fields.get("step"):
        updates["checklist"] = _tick(job.get("checklist"), fields["step"], bool(fields.get("step_done", True)))
        detail["step"] = {fields["step"]: bool(fields.get("step_done", True))}
        if "status" not in updates and job["status"] == "queued":
            updates["status"] = "in_progress"

    if updates.get("assigned_to") and "status" not in updates and job["status"] == "queued":
        updates["status"] = "in_progress"
    if not updates:
        return _job_view(db, org_id, job_id)

    updates["updated_at"] = _iso()
    res = (db.table("site_hosting_jobs").update(updates).eq("id", job["id"]).eq("org_id", org_id)
           .neq("status", "done").execute())
    if not res.data:
        raise Conflict("This job was just finished by someone else.")
    _log_event(db, org_id, job.get("site_id"), f"user:{user_id}", "hosting_job_updated", detail, job.get("order_id"))
    return _job_view(db, org_id, job_id)


def _job_and_order(db: Any, org_id: str, job_id: str) -> tuple:
    job = _get_job(db, org_id, job_id)
    if job["status"] == "done":
        raise Conflict("This job is already done.")
    order = _get_order(db, org_id, job["order_id"])
    if order["status"] != "fulfilling" and not (order["status"] == "needs_builder_choice"):
        raise Conflict(f"The order is '{order['status']}', so this job can't be worked on right now.")
    return job, order


def _step_done(job: dict, key: str) -> bool:
    return any(i.get("key") == key and i.get("done") for i in (job.get("checklist") or []))


def recheck_domain(db: Any, org_id: str, job_id: str, user_id: str) -> dict:
    """spec §11.4 step 3.1 — a fresh (uncached) registry check of the domain in use."""
    from app.services import domain_check_service
    job, order = _job_and_order(db, org_id, job_id)
    if order["status"] != "fulfilling":
        raise Conflict("This order is waiting for the builder to choose a domain.")
    if _step_done(job, "register_domain"):
        raise Conflict("The domain is already registered, so there's nothing to re-check.")
    current = job.get("domain_used") or order.get("domain")
    try:
        normalised, available = domain_check_service.check_availability_fresh(db, org_id, current)
    except domain_check_service.DomainCheckError as exc:
        raise ValidationFailed(str(exc))

    now = _iso()
    if available is None:
        message = f"Couldn't confirm {normalised} right now — try again in a minute."
    elif available:
        db.table("site_hosting_jobs").update({
            "domain_used": normalised, "domain_rechecked_at": now,
            "checklist": _tick(job.get("checklist"), "recheck_domain", True),
            "status": "in_progress" if job["status"] == "queued" else job["status"], "updated_at": now,
        }).eq("id", job["id"]).eq("org_id", org_id).execute()
        message = f"{normalised} is still available."
        if domain_check_service.is_unconfirmed_tld(normalised):
            message += " (DNS check only — the registrar gives the final answer when you register it.)"
    else:
        db.table("site_hosting_jobs").update({"domain_rechecked_at": now, "updated_at": now}) \
            .eq("id", job["id"]).eq("org_id", org_id).execute()
        message = f"{normalised} has been taken." + (" Use the backup domain." if order.get("backup_domain") else "")
    _log_event(db, org_id, job.get("site_id"), f"user:{user_id}", "domain_rechecked",
               {"domain": normalised, "available": available}, order["id"])
    return {"job": _job_view(db, org_id, job_id), "domain": normalised, "available": available, "message": message}


def use_backup_domain(db: Any, org_id: str, job_id: str, user_id: str) -> dict:
    """spec §11.4 step 3.1 — switch to the backup; if that's gone too the order moves to
    needs_builder_choice (spec §6.2) and the builder is told."""
    from app.services import domain_check_service
    job, order = _job_and_order(db, org_id, job_id)
    if order["status"] != "fulfilling":
        raise Conflict("This order is waiting for the builder to choose a domain.")
    backup = (order.get("backup_domain") or "").strip().lower()
    if not backup:
        raise ValidationFailed("This order has no backup domain.")
    if job.get("domain_used") == backup:
        raise Conflict("The backup domain is already the one in use.")
    if _step_done(job, "register_domain"):
        raise Conflict("The domain is already registered — it's too late to switch.")
    try:
        normalised, available = domain_check_service.check_availability_fresh(db, org_id, backup)
    except domain_check_service.DomainCheckError as exc:
        raise ValidationFailed(str(exc))

    now = _iso()
    if available is None:
        raise Conflict(f"Couldn't confirm {normalised} right now — try again in a minute.")

    if available:
        db.table("site_hosting_jobs").update({
            "domain_used": normalised, "domain_rechecked_at": now,
            "checklist": _tick(job.get("checklist"), "recheck_domain", True),
            "status": "in_progress" if job["status"] == "queued" else job["status"], "updated_at": now,
        }).eq("id", job["id"]).eq("org_id", org_id).execute()
        _log_event(db, org_id, job.get("site_id"), f"user:{user_id}", "domain_backup_used",
                   {"domain": normalised}, order["id"])
        return {"job": _job_view(db, org_id, job_id), "domain": normalised, "available": True,
                "order_status": "fulfilling", "message": f"Now using the backup, {normalised}."}

    # Both domains are gone.
    claim = (db.table("site_orders").update({"status": "needs_builder_choice", "updated_at": now})
             .eq("id", order["id"]).eq("org_id", org_id).eq("status", "fulfilling").execute())
    if claim.data:
        db.table("site_hosting_jobs").update({
            "status": "blocked", "domain_rechecked_at": now, "updated_at": now,
            "notes": f"Both {order.get('domain')} and {normalised} were taken — waiting for the builder.",
        }).eq("id", job["id"]).eq("org_id", org_id).execute()
        _message_builder(db, org_id, order,
                         f"Both of your chosen domains ({order.get('domain')} and {normalised}) were taken before we could register them. "
                         f"Reply here to choose a new domain, or to ask for a refund ({_money(refund_amount_for(order))} — everything except our service fee).")
        _notify_managers(db, org_id, "Order needs a new domain",
                         f"{order.get('domain')} and its backup are both taken.", "site_order_needs_choice")
        _log_event(db, org_id, job.get("site_id"), f"user:{user_id}", "order_needs_builder_choice",
                   {"domain": order.get("domain"), "backup": normalised}, order["id"])
    return {"job": _job_view(db, org_id, job_id), "domain": normalised, "available": False,
            "order_status": "needs_builder_choice",
            "message": "The backup is taken too. The order now waits for the builder to choose a new domain."}


def _default_http_get(url: str):
    import httpx
    return httpx.get(url, follow_redirects=True, timeout=10.0)


def mark_live(db: Any, org_id: str, job_id: str, user_id: str, live_url: str,
              http_get: Optional[Callable[[str], Any]] = None, now: Optional[datetime] = None) -> dict:
    """spec §11.4 step 5 — the URL must be https, on the chosen domain, and answer HTTP 200. Then the
    order and site go live, a site_domains row records the renewal dates, and the builder is told."""
    now = now or _now()
    job, order = _job_and_order(db, org_id, job_id)
    if order["status"] != "fulfilling":
        raise Conflict("This order is waiting for the builder to choose a domain.")

    domain = (job.get("domain_used") or order.get("domain") or "").lower()
    url = (live_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValidationFailed("The live URL must start with https://")
    host = parsed.hostname.lower()
    if host not in (domain, f"www.{domain}"):
        raise ValidationFailed(f"The live URL must be on the client's domain ({domain}).")
    try:
        resp = (http_get or _default_http_get)(url)
    except Exception:
        raise ValidationFailed(f"Couldn't reach {url}. Check the site is up and SSL is on, then try again.")
    if getattr(resp, "status_code", None) != 200:
        raise ValidationFailed(f"{url} answered with HTTP {getattr(resp, 'status_code', '?')}, not 200.")

    ts = _iso(now)
    claim = (db.table("site_orders").update({"status": "live", "updated_at": ts})
             .eq("id", order["id"]).eq("org_id", org_id).eq("status", "fulfilling").execute())
    if not claim.data:
        raise Conflict("This order was just handled by someone else.")

    db.table("site_hosting_jobs").update({
        "status": "done", "completed_at": ts, "domain_used": domain,
        "checklist": _tick(job.get("checklist"), "paste_url", True), "updated_at": ts,
    }).eq("id", job["id"]).eq("org_id", org_id).execute()
    db.table("sites").update({"status": "live", "live_url": url, "published_at": ts, "updated_at": ts}) \
        .eq("id", order["site_id"]).eq("org_id", org_id).execute()

    domain_row = _record_domain(db, org_id, order, domain, now)
    _complete_tasks(db, org_id, job["id"], f"Live at {url}")
    _message_builder(db, org_id, order, f"Your client's website is live: {url}")
    if not order.get("approved_at"):  # approvals were off — this is the "goes live" moment (spec §11.7)
        _register_approved_order(db, org_id, order, user_id)
    _log_event(db, org_id, order.get("site_id"), f"user:{user_id}", "site_published",
               {"url": url, "domain": domain}, order["id"])
    return {"order_status": "live", "live_url": url, "site_domain": domain_row, "job": _job_view(db, org_id, job_id)}


def _record_domain(db: Any, org_id: str, order: dict, domain: str, now: datetime) -> Optional[dict]:
    """One site_domains row per (site, domain), with renewal dates a year out (spec §5.3)."""
    try:
        existing = _one((db.table("site_domains").select("*").eq("org_id", org_id).eq("site_id", order["site_id"])
                         .eq("domain", domain).limit(1).execute()).data)
        if existing:
            return existing
        domain_cost = hosting_cost = None
        try:
            from app.services import pricing_service
            q = pricing_service.quote(db, org_id, domain, order.get("route") or "standard", "renewal")
            domain_cost, hosting_cost = q["cost"]["domain"], q["cost"]["hosting"]
        except Exception as exc:
            logger.warning("site_ops: renewal cost lookup failed domain=%s: %s", domain, exc)
        renews = _add_year(now.date()).isoformat()
        row = {
            "org_id": org_id, "site_id": order["site_id"], "domain": domain,
            "registrar": "hostinger" if order.get("route") == "express" else "qservers",
            "route": order.get("route") or "standard", "registered_at": _iso(now),
            "renews_on": renews, "registrar_cost_renewal": domain_cost, "registrar_cost_currency": "NGN",
            "hosting_renews_on": renews, "hosting_cost_renewal": hosting_cost, "status": "active",
            "created_at": _iso(now), "updated_at": _iso(now),
        }
        return _one(db.table("site_domains").insert(row).execute().data) or row
    except Exception as exc:  # S14 — the site is already live; a missing register row is recoverable by hand
        logger.warning("site_ops: site_domains insert failed order=%s: %s", order.get("id"), exc)
        return None


def _close_other_renewal_orders(db: Any, org_id: str, order: dict, domain: str) -> int:
    """After a renewal is done, any other unpaid renewal order for the same domain is stale."""
    closed = 0
    try:
        rows = (db.table("site_orders").select("id, domain").eq("org_id", org_id).eq("site_id", order["site_id"])
                .eq("kind", "renewal").eq("status", "pending_payment").execute()).data or []
        for r in rows:
            if r["id"] != order["id"] and (r.get("domain") or "").lower() == domain:
                db.table("site_orders").update({"status": "expired", "updated_at": _iso()}) \
                    .eq("id", r["id"]).eq("org_id", org_id).eq("status", "pending_payment").execute()
                closed += 1
    except Exception as exc:  # S14
        logger.warning("site_ops: closing stale renewal orders failed order=%s: %s", order.get("id"), exc)
    return closed


def mark_renewed(db: Any, org_id: str, job_id: str, user_id: str, now: Optional[datetime] = None) -> dict:
    """SITE-4 — finishes a renewal job. Both registrar steps must be ticked; the renewal dates move a year
    on from whichever is later, today or the current date, so an early renewal never loses paid time."""
    from app.services import pricing_service
    now = now or _now()
    job, order = _job_and_order(db, org_id, job_id)
    if order.get("kind") != "renewal":
        raise Conflict("This is not a renewal job — use Mark live.")
    if order["status"] != "fulfilling":
        raise Conflict(f"The order is '{order['status']}', so it can't be marked renewed.")
    if not (_step_done(job, "renew_domain") and _step_done(job, "renew_hosting")):
        raise ValidationFailed("Tick both 'Renew the domain' and 'Renew the hosting package' first.")

    domain = (order.get("domain") or "").lower()
    domain_row = _one((db.table("site_domains").select("*").eq("org_id", org_id).eq("site_id", order["site_id"])
                       .eq("domain", domain).limit(1).execute()).data)
    if not domain_row:
        raise NotFound("The domain register has no entry for this domain.")

    today = now.date()
    new_domain_date = _add_year(max(_parse_date(domain_row.get("renews_on")) or today, today))
    new_hosting_date = _add_year(max(_parse_date(domain_row.get("hosting_renews_on")) or today, today))

    ts = _iso(now)
    claim = (db.table("site_orders").update({"status": "live", "updated_at": ts})
             .eq("id", order["id"]).eq("org_id", org_id).eq("status", "fulfilling").execute())
    if not claim.data:
        raise Conflict("This order was just handled by someone else.")

    updates = {"renews_on": new_domain_date.isoformat(), "hosting_renews_on": new_hosting_date.isoformat(),
               "status": "active", "updated_at": ts}
    try:
        q = pricing_service.quote(db, org_id, domain, order.get("route") or "standard", "renewal")
        updates["registrar_cost_renewal"] = q["cost"]["domain"]
        updates["hosting_cost_renewal"] = q["cost"]["hosting"]
    except Exception as exc:  # S14 — keep the old cost figures
        logger.warning("site_ops: renewal cost refresh failed domain=%s: %s", domain, exc)
    db.table("site_domains").update(updates).eq("id", domain_row["id"]).eq("org_id", org_id).execute()

    db.table("site_hosting_jobs").update({
        "status": "done", "completed_at": ts, "checklist": _tick(job.get("checklist"), "confirm_site", True),
        "updated_at": ts,
    }).eq("id", job["id"]).eq("org_id", org_id).execute()
    try:
        db.table("sites").update({"status": "live", "updated_at": ts}).eq("id", order["site_id"]) \
            .eq("org_id", org_id).in_("status", ["live", "renewal_due", "lapsed"]).execute()
    except Exception as exc:  # S14
        logger.warning("site_ops: site status reset failed site=%s: %s", order.get("site_id"), exc)

    _close_other_renewal_orders(db, org_id, order, domain)
    _complete_tasks(db, org_id, job["id"], f"Renewed until {new_domain_date.isoformat()}")
    _message_builder(db, org_id, order, f"{domain} is renewed until {new_domain_date.day} {new_domain_date.strftime('%b %Y')}.")
    _log_event(db, org_id, order.get("site_id"), f"user:{user_id}", "renewal_completed",
               {"domain": domain, "renews_on": new_domain_date.isoformat(),
                "hosting_renews_on": new_hosting_date.isoformat()}, order["id"])
    return {"order_status": "live", "renews_on": new_domain_date.isoformat(),
            "hosting_renews_on": new_hosting_date.isoformat(), "job": _job_view(db, org_id, job_id)}


def send_renewal_link(db: Any, org_id: str, domain_id: str, user_id: str) -> dict:
    """Staff button in the Domains tab: (re)creates the renewal link and WhatsApps it to the builder."""
    from app.services import site_renewal_service as renewal
    domain_row = _one((db.table("site_domains").select("*").eq("id", domain_id).eq("org_id", org_id).limit(1).execute()).data)
    if not domain_row:
        raise NotFound("Domain not found")
    try:
        link = renewal.get_or_create_renewal_link(db, org_id, domain_row)
        site, builder = renewal._load_site_and_builder(db, org_id, domain_row)
    except renewal.RenewalNotFound as exc:
        raise NotFound(str(exc))
    except renewal.RenewalBlocked as exc:
        raise Conflict(str(exc))
    except pricing_errors() as exc:
        raise ValidationFailed(str(exc))
    days = renewal.days_left(domain_row, renewal.lagos_today()) or 0
    sent = renewal.send_builder_reminder(db, org_id, builder, site, domain_row, link["checkout_url"], link["amount"], days)
    _log_event(db, org_id, site["id"], f"user:{user_id}", "renewal_link_sent",
               {"domain": domain_row.get("domain"), "sent": bool(sent)}, (link["order"] or {}).get("id"))
    return {"checkout_url": link["checkout_url"], "amount": link["amount"], "sent": bool(sent), "reused": link["reused"]}


def pricing_errors():
    from app.services import pricing_service
    return pricing_service.PricingError


# ---------------------------------------------------------------------------
# Export zip — spec §8.6
# ---------------------------------------------------------------------------

def build_export_zip(db: Any, org_id: str, site_id: str) -> tuple:
    """Returns (bytes, filename). Built in memory, never stored (spec §8.6)."""
    from app.services import site_renderer
    site = _one((db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id)
                 .is_("deleted_at", "null").limit(1).execute()).data)
    if not site:
        raise NotFound("Site not found")
    preset = _one((db.table("site_presets").select("*").eq("id", site["preset_id"]).eq("org_id", org_id)
                   .limit(1).execute()).data)
    if not preset:
        raise NotFound("This site's template no longer exists")
    assets = (db.table("site_assets").select("id, slot, storage_path, mime_type").eq("site_id", site["id"])
              .execute()).data or []

    order = _one((db.table("site_orders").select("domain").eq("org_id", org_id).eq("site_id", site["id"])
                  .neq("status", "expired").order("created_at", desc=True).limit(1).execute()).data)
    domain = (order or {}).get("domain")

    buf = io.BytesIO()
    used: set = set()
    assets_by_id: dict = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for a in assets:
            try:
                data = db.storage.from_("site-assets").download(a["storage_path"])
            except Exception as exc:
                logger.warning("site_ops: export asset download failed asset=%s: %s", a.get("id"), exc)
                continue
            ext = _IMAGE_EXT.get(a.get("mime_type") or "", "jpg")
            slot = re.sub(r"[^a-z0-9_-]", "-", str(a.get("slot") or "image").lower())
            name = f"images/{slot}.{ext}"
            if name in used:
                name = f"images/{slot}-{str(a['id'])[:6]}.{ext}"
            used.add(name)
            zf.writestr(name, data)
            assets_by_id[a["id"]] = {"export_path": name}
        try:
            html = site_renderer.render_export(site["content"], site["recipe"], preset, assets_by_id)
        except ValueError as exc:
            raise ValidationFailed(str(exc))
        zf.writestr("index.html", html)
        origin = f"https://{domain}" if domain else None
        zf.writestr("robots.txt", "User-agent: *\nAllow: /\n" + (f"Sitemap: {origin}/sitemap.xml\n" if origin else ""))
        if origin:
            zf.writestr("sitemap.xml",
                        '<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        f"<url><loc>{origin}/</loc></url></urlset>\n")
    return buf.getvalue(), f"{site['slug']}-export.zip"


# ---------------------------------------------------------------------------
# Domains & renewals
# ---------------------------------------------------------------------------

def list_domains(db: Any, org_id: str, expiring_within: Optional[int] = None, status: Optional[str] = None,
                 search: Optional[str] = None, now: Optional[datetime] = None) -> list:
    today = (now or _now()).date()
    rows = (db.table("site_domains").select("*").eq("org_id", org_id).order("renews_on").execute()).data or []
    sites = _by_id(db, "sites", org_id, [r.get("site_id") for r in rows], "id, client_business_name, slug, builder_id, live_url")
    builders = _by_id(db, "site_builders", org_id, [s.get("builder_id") for s in sites.values()],
                      "id, full_name, business_name, phone_number")
    out = []
    for r in rows:
        site = sites.get(r.get("site_id")) or {}
        b = builders.get(site.get("builder_id")) or {}
        dates = [d for d in (_parse_date(r.get("renews_on")), _parse_date(r.get("hosting_renews_on"))) if d]
        days = (min(dates) - today).days if dates else None
        stored = r.get("status")
        effective = stored
        if stored in ("active", "expiring") and days is not None:
            effective = "lapsed" if days < 0 else ("expiring" if days <= _EXPIRING_DAYS else "active")
        parts = [r.get("registrar_cost_renewal"), r.get("hosting_cost_renewal")]
        cost = sum(float(p) for p in parts if p is not None) if any(p is not None for p in parts) else None
        r = dict(r)
        r.update({
            "client_business_name": site.get("client_business_name"), "site_slug": site.get("slug"),
            "live_url": site.get("live_url"), "builder_name": b.get("full_name"),
            "builder_business": b.get("business_name"), "builder_phone": b.get("phone_number"),
            "days_to_renewal": days, "effective_status": effective, "cost_at_renewal": cost,
        })
        out.append(r)

    if status:
        out = [r for r in out if r["effective_status"] == status]
    if expiring_within is not None:
        out = [r for r in out if r["days_to_renewal"] is not None and r["days_to_renewal"] <= expiring_within
               and r["effective_status"] != "transferred"]
    if search:
        s = search.lower().strip()
        out = [r for r in out if s in " ".join(str(r.get(k) or "") for k in
               ("domain", "client_business_name", "builder_name", "builder_business")).lower()]
    out.sort(key=lambda r: (r["days_to_renewal"] is None, r["days_to_renewal"] if r["days_to_renewal"] is not None else 0))
    return out


# ---------------------------------------------------------------------------
# Overview KPIs — spec §13 Overview tab
# ---------------------------------------------------------------------------

def order_kpis(db: Any, org_id: str, sites_total: int, now: Optional[datetime] = None) -> dict:
    now = now or _now()
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Lagos")
    except Exception:
        tz = timezone(timedelta(hours=1))
    local_now = now.astimezone(tz)
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    orders = (db.table("site_orders").select("id, kind, status, amount, expected_profit, refund_amount, sla_due_at, created_at")
              .eq("org_id", org_id).execute()).data or []
    paid = [o for o in orders if o.get("status") in _PAID_STATUSES]

    def paid_at(o):  # site_orders has no paid_at — sla_due_at is paid time + 24h (site_order_service)
        due = _parse_iso(o.get("sla_due_at"))
        return (due - timedelta(hours=24)) if due else _parse_iso(o.get("created_at"))

    def revenue(o):  # a refunded order keeps only what wasn't refunded (the service fee)
        amount = float(o.get("amount") or 0)
        if o.get("status") == "refunded":
            return amount - float(o.get("refund_amount") or 0)
        if o.get("status") in ("rejected", "refund_pending"):
            return 0.0
        return amount

    def profit(o):
        return float(o.get("expected_profit") or 0) if o.get("status") in _PAID_KEPT_STATUSES else 0.0

    def totals(rows):
        return {"revenue": round(sum(revenue(o) for o in rows), 2), "expected_profit": round(sum(profit(o) for o in rows), 2)}

    this_month = [o for o in paid if (paid_at(o) or now).astimezone(tz) >= month_start]
    initial_paid = [o for o in paid if o.get("kind") == "initial"]

    today = now.date()
    renewals = 0
    for d in (db.table("site_domains").select("renews_on, hosting_renews_on, status").eq("org_id", org_id).execute()).data or []:
        if d.get("status") == "transferred":
            continue
        dates = [x for x in (_parse_date(d.get("renews_on")), _parse_date(d.get("hosting_renews_on"))) if x]
        if dates and (min(dates) - today).days <= _EXPIRING_DAYS:
            renewals += 1

    open_jobs = (db.table("site_hosting_jobs").select("id, status, sla_due_at").eq("org_id", org_id)
                 .neq("status", "done").execute()).data or []
    overdue = sum(1 for j in open_jobs if _sla_state(j, now) == "red")

    return {
        "orders_paid": len(paid),
        "orders_awaiting_approval": sum(1 for o in orders if o.get("status") == "awaiting_approval"),
        "orders_refund_pending": sum(1 for o in orders if o.get("status") == "refund_pending"),
        "conversion_rate": round(len({o["id"] for o in initial_paid}) / sites_total * 100, 1) if sites_total else None,
        "this_month": totals(this_month),
        "all_time": totals(paid),
        "renewals_due_30d": renewals,
        "hosting_jobs_open": len(open_jobs),
        "hosting_jobs_overdue": overdue,
    }
