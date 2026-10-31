"""
backend/app/services/booking_deposit_service.py
BOOKING-3A - OPTIONAL deposits at booking. A service with deposit_amount = 0 (the default) never touches this module.

Held booking = lead_demos.status 'pending_assignment' (already a live, slot-blocking status) + a booking_payments row 'pending'.
Methods:
  paystack - the org's own Paystack keys (Integrations > Paystack storefront). Payment is confirmed by asking Paystack
             (transaction/verify) when the customer returns and by a 2-minute sweep. Refunds go through the Paystack refund API.
  external - the org's own link (PayPal, Stripe, ...). Opsra cannot see that payment: staff tap "Mark as paid".
             Refunds are manual: the payment shows "refund_due" until staff mark it refunded.
S14: nothing here may break a booking that has no deposit.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)
_API = "https://api.paystack.co"
_OPEN = ("pending", "paid", "refund_due")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _err(status: int, code: str, msg: str):
    from app.services.booking_service import _err as e
    return e(status, code, msg)


def has_deposit(service: dict) -> bool:
    try:
        return float(service.get("deposit_amount") or 0) > 0
    except (TypeError, ValueError):
        return False


def _secret(db, org_id: str) -> str:
    try:
        from app.services.paystack_storefront_service import _get_storefront_credentials
        return (_get_storefront_credentials(db, org_id).get("secret_key") or "").strip()
    except Exception:
        return ""


def precheck(db, org_id: str, service: dict) -> None:
    """Before a slot is taken: refuse if the deposit cannot actually be collected."""
    if not has_deposit(service):
        return
    if (service.get("deposit_method") or "paystack") == "paystack":
        if not _secret(db, org_id):
            raise _err(422, "DEPOSIT_UNAVAILABLE", "Online payment is not available right now. Please contact the business.")
    elif not (service.get("deposit_external_url") or "").startswith("https://"):
        raise _err(422, "DEPOSIT_UNAVAILABLE", "Online payment is not available right now. Please contact the business.")


def public_payment(p: Optional[dict]) -> Optional[dict]:
    if not p:
        return None
    return {k: p.get(k) for k in ("status", "method", "amount", "currency", "pay_url", "hold_expires_at")}


def payment_for_demo(db, org_id: str, demo_id: str) -> Optional[dict]:
    rows = (db.table("booking_payments").select("*").eq("org_id", org_id).eq("demo_id", demo_id)
            .order("created_at", desc=True).limit(1).execute().data or [])
    return rows[0] if rows else None


def attach_status(db, org_id: str, bookings: list) -> list:
    """Calendar feed: add payment_status to each booking that has a payment row."""
    ids = [b["id"] for b in bookings if b.get("id")]
    if not ids:
        return bookings
    try:
        rows = db.table("booking_payments").select("demo_id, status, amount, currency").eq("org_id", org_id).in_("demo_id", ids).execute().data or []
        by = {r["demo_id"]: r for r in rows}
        for b in bookings:
            r = by.get(b["id"])
            if r:
                b["payment_status"], b["payment_amount"], b["payment_currency"] = r["status"], r["amount"], r["currency"]
    except Exception as exc:
        logger.warning("attach_status failed: %s", exc)
    return bookings


def create_hold(db, org_id: str, lead: dict, demo_id: str, service: dict, return_url: Optional[str] = None) -> dict:
    """Create the payment row (and the Paystack checkout) for a just-inserted booking. Raises on failure; caller releases the slot."""
    method = service.get("deposit_method") or "paystack"
    amount = round(float(service["deposit_amount"]), 2)
    currency = (service.get("deposit_currency") or "NGN").upper()
    hold = max(5, min(int(service.get("deposit_hold_minutes") or 30), 1440))
    reference, pay_url = None, None
    if method == "paystack":
        secret = _secret(db, org_id)
        if not secret:
            raise _err(422, "DEPOSIT_UNAVAILABLE", "Online payment is not available right now.")
        reference = f"bkdep_{uuid.uuid4().hex[:20]}"
        email = (lead.get("email") or "").strip() or f"lead-{str(lead['id'])[:8]}@example.com"
        body = {"email": email, "amount": int(round(amount * 100)), "currency": currency, "reference": reference,
                "metadata": {"kind": "booking_deposit", "org_id": org_id, "demo_id": demo_id}}
        if return_url:
            body["callback_url"] = return_url
        with httpx.Client(timeout=15) as c:
            r = c.post(f"{_API}/transaction/initialize", headers={"Authorization": f"Bearer {secret}"}, json=body)
        data = r.json() if r.content else {}
        if r.status_code >= 400 or not (data.get("data") or {}).get("authorization_url"):
            logger.error("deposit init failed org=%s status=%s", org_id, r.status_code)
            raise _err(502, "DEPOSIT_UNAVAILABLE", "We couldn't start the payment. Please try again.")
        pay_url = data["data"]["authorization_url"]
    else:
        pay_url = service.get("deposit_external_url")
    row = {
        "org_id": org_id, "demo_id": demo_id, "lead_id": lead["id"], "method": method, "reference": reference,
        "pay_url": pay_url, "amount": amount, "currency": currency, "status": "pending",
        "refund_rule": service.get("deposit_refund_rule") or "before_cutoff",
        "hold_expires_at": _iso(_now() + timedelta(minutes=hold)),
    }
    db.table("booking_payments").insert(row).execute()
    return payment_for_demo(db, org_id, demo_id)


def _verify_paystack(db, org_id: str, p: dict) -> bool:
    secret = _secret(db, org_id)
    if not secret or not p.get("reference"):
        return False
    try:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{_API}/transaction/verify/{p['reference']}", headers={"Authorization": f"Bearer {secret}"})
        d = (r.json() or {}).get("data") or {}
        return (d.get("status") == "success" and int(d.get("amount") or 0) >= int(round(float(p["amount"]) * 100))
                and (d.get("currency") or p["currency"]).upper() == p["currency"].upper())
    except Exception as exc:
        logger.warning("deposit verify failed ref=%s: %s", p.get("reference"), exc)
        return False


def verify(db, org_id: str, p: Optional[dict]) -> Optional[dict]:
    """Ask Paystack whether a pending deposit has been paid; settle it if so. Safe to call repeatedly."""
    if p and p["status"] == "pending" and p["method"] == "paystack" and _verify_paystack(db, org_id, p):
        settle(db, org_id, p, None)
        return payment_for_demo(db, org_id, p["demo_id"])
    return p


def settle(db, org_id: str, p: dict, user_id: Optional[str]) -> bool:
    """pending -> paid exactly once, then run the normal confirmation. Returns False if it was already settled."""
    from app.services import booking_service as bk
    from app.services import demo_service as ds
    now = bk._now_iso()
    upd = (db.table("booking_payments").update({"status": "paid", "paid_at": now, "marked_by": user_id, "updated_at": now})
           .eq("id", p["id"]).eq("org_id", org_id).eq("status", "pending").execute().data or [])
    if not upd:
        return False
    demos = db.table("lead_demos").select("*").eq("id", p["demo_id"]).eq("org_id", org_id).limit(1).execute().data or []
    demo = demos[0] if demos else None
    if not demo or demo.get("status") != "pending_assignment":
        # paid after the hold was released (or the booking was changed): the money must go back
        if not demo or demo.get("status") in ("cancelled", "rescheduled"):
            db.table("booking_payments").update({"status": "refund_due", "updated_at": now}).eq("id", p["id"]).execute()
            _tell_manager(db, org_id, demo or {"id": p["demo_id"], "lead_id": p.get("lead_id")}, "A deposit arrived after the booking was released. Refund it.")
        return True
    lead = ds._confirm_lead_in_org(db, org_id, demo["lead_id"])
    org = bk.get_org(db, org_id)
    service = bk.get_service(db, org_id, demo["service_id"]) if demo.get("service_id") else {"id": None, "name": "Booking", "duration_minutes": demo.get("duration_minutes") or 30, "medium": demo.get("medium")}
    start = bk._parse_dt(demo["scheduled_at"])
    ds._log_timeline(db, org_id, demo["lead_id"], user_id, "booking_deposit_paid",
                     f"Deposit of {p['currency']} {p['amount']:,.2f} received ({p['method']}).", {"demo_id": demo["id"]})
    bk._finish_booking(db, org_id, lead, demo["id"], service, start, demo.get("source") or "native", None, demo.get("notes"), org, rep=demo.get("assigned_to"))
    return True


def mark_paid(db, org_id: str, demo_id: str, user_id: str) -> dict:
    p = payment_for_demo(db, org_id, demo_id)
    if not p or p["status"] != "pending":
        raise _err(409, "NOT_PENDING", "There is no unpaid deposit on this booking.")
    settle(db, org_id, p, user_id)
    return payment_for_demo(db, org_id, demo_id)


def mark_refunded(db, org_id: str, demo_id: str, user_id: str) -> dict:
    p = payment_for_demo(db, org_id, demo_id)
    if not p or p["status"] not in ("refund_due", "paid"):
        raise _err(409, "NOT_REFUNDABLE", "There is no paid deposit to mark as refunded.")
    now = _iso(_now())
    db.table("booking_payments").update({"status": "refunded", "refunded_at": now, "marked_by": user_id, "updated_at": now}).eq("id", p["id"]).execute()
    return payment_for_demo(db, org_id, demo_id)


def _tell_manager(db, org_id: str, demo: dict, text: str) -> None:
    try:
        from app.services import demo_service as ds
        mgr = ds._get_manager_id(db, org_id)
        if mgr:
            ds._insert_notification(db, org_id, mgr, "booking_refund_due", "Deposit refund needed", text, demo.get("id"))
    except Exception as exc:
        logger.warning("deposit notify failed: %s", exc)


def _refund_paystack(db, org_id: str, p: dict) -> bool:
    secret = _secret(db, org_id)
    if not secret or not p.get("reference"):
        return False
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(f"{_API}/refund", headers={"Authorization": f"Bearer {secret}"}, json={"transaction": p["reference"]})
        return r.status_code < 400 and bool((r.json() or {}).get("status"))
    except Exception as exc:
        logger.warning("deposit refund failed ref=%s: %s", p.get("reference"), exc)
        return False


def on_cancel(db, org_id: str, demo: dict, by: str, cutoff_hours: int) -> Optional[str]:
    """Called when a booking is cancelled. Returns the payment's new status (or None when there was no deposit)."""
    p = payment_for_demo(db, org_id, demo["id"])
    if not p:
        return None
    now = _iso(_now())
    if p["status"] == "pending":
        db.table("booking_payments").update({"status": "cancelled", "updated_at": now}).eq("id", p["id"]).execute()
        return "cancelled"
    if p["status"] != "paid":
        return p["status"]
    rule = p.get("refund_rule") or "before_cutoff"
    refund = rule == "always" or by == "staff"
    if rule == "before_cutoff" and by != "staff":
        try:
            from app.services import booking_service as bk
            refund = bool(demo.get("scheduled_at")) and (bk._parse_dt(demo["scheduled_at"]) - _now()) >= timedelta(hours=int(cutoff_hours or 0))
        except Exception:
            refund = False
    if rule == "never" and by != "staff":
        refund = False
    if not refund:
        return "paid"
    if p["method"] == "paystack" and _refund_paystack(db, org_id, p):
        db.table("booking_payments").update({"status": "refunded", "refunded_at": now, "updated_at": now}).eq("id", p["id"]).execute()
        return "refunded"
    db.table("booking_payments").update({"status": "refund_due", "updated_at": now}).eq("id", p["id"]).execute()
    _tell_manager(db, org_id, demo, "A cancelled booking has a deposit to refund. Open the booking to mark it refunded.")
    return "refund_due"


def sweep(db, limit: int = 100) -> dict:
    """Worker: confirm Paystack deposits that were paid, release holds that ran out."""
    from app.services import booking_service as bk
    from app.services import demo_service as ds
    out = {"settled": 0, "expired": 0}
    rows = (db.table("booking_payments").select("*").eq("status", "pending").order("hold_expires_at").limit(limit).execute().data or [])
    now = _now()
    for p in rows:
        try:
            org_id = p["org_id"]
            if p["method"] == "paystack" and _verify_paystack(db, org_id, p):
                if settle(db, org_id, p, None):
                    out["settled"] += 1
                continue
            if bk._parse_dt(p["hold_expires_at"]) > now:
                continue
            demos = db.table("lead_demos").select("*").eq("id", p["demo_id"]).eq("org_id", org_id).limit(1).execute().data or []
            demo = demos[0] if demos else None
            stamp = bk._now_iso()
            if demo and demo.get("status") == "confirmed":     # a manager confirmed it by hand
                db.table("booking_payments").update({"status": "waived", "updated_at": stamp}).eq("id", p["id"]).eq("status", "pending").execute()
                continue
            got = db.table("booking_payments").update({"status": "expired", "updated_at": stamp}).eq("id", p["id"]).eq("status", "pending").execute().data or []
            if not got:
                continue
            if demo and demo.get("status") == "pending_assignment":
                db.table("lead_demos").update({"status": "cancelled", "cancelled_at": stamp, "cancelled_by": "system",
                                               "cancel_reason": "Deposit not paid in time", "updated_at": stamp}).eq("id", demo["id"]).execute()
                lead = ds._confirm_lead_in_org(db, org_id, demo["lead_id"])
                ds._log_timeline(db, org_id, demo["lead_id"], None, "booking_cancelled", "Booking released: deposit was not paid in time.", {"demo_id": demo["id"]})
                ds._auto_send_wa(db, org_id, lead, "We released your booking because the deposit wasn't paid in time. Reply here any time to book again.")
            out["expired"] += 1
        except Exception as exc:
            logger.warning("deposit sweep item failed id=%s: %s", p.get("id"), exc)
    return out
