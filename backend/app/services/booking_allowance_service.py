"""
booking_allowance_service.py - BOOKING-ALLOWANCE-1

Each plan (and the Booking add-on) includes a number of bookings a month (the "bookings" cap in Settings).
Bookings past that number are NEVER blocked: each one costs a small fee taken from the business's prepaid credit
(automation_fee_rules, event_type 'booking_overage', flat_kobo). The fee covers the WhatsApp confirmations and
reminders that every extra booking sends.

Rules:
  - Nothing happens until the business's plan is enforced (same as every other allowance).
  - A booking is counted when it is secured (_finish_booking): customer bookings, WhatsApp bookings and staff bookings
    made through book_slot, including a deposit booking once its deposit is paid.
  - Never raises: a problem here must not lose a booking (S14).
  - The fee is taken once per booking (ledger ref fee:booking:<demo_id>), so a retry cannot charge twice.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import account_entitlement_service as acc
from app.services import credit_service as cs
from app.services import site_entitlement_service as ent

logger = logging.getLogger(__name__)

CAP_KEY = "bookings"
FEE_EVENT = "booking_overage"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _one(data):
    return data[0] if isinstance(data, list) and data else None


def _bump(db: Any, org_id: str, now: datetime) -> Optional[int]:
    """Add one to this month's counter and return the new total. None if it could not be counted."""
    ps = ent.period_start(now).isoformat()
    for _ in range(4):
        row = _one((db.table("org_usage_counters").select("*").eq("org_id", org_id).eq("cap_key", CAP_KEY)
                    .eq("period_start", ps).limit(1).execute()).data)
        if row is None:
            try:
                db.table("org_usage_counters").insert({"org_id": org_id, "cap_key": CAP_KEY, "period_start": ps,
                                                       "used": 0, "updated_at": now.isoformat()}).execute()
            except Exception:       # a parallel request created it first
                pass
            continue
        used = int(row.get("used") or 0)
        res = (db.table("org_usage_counters").update({"used": used + 1, "updated_at": now.isoformat()})
               .eq("id", row["id"]).eq("used", used).execute())
        if res.data:
            return used + 1
    return None


def overage_fee_kobo(db: Any, org_id: str) -> int:
    rule = cs.find_fee_rule(db, org_id, FEE_EVENT)
    return cs._fee_amount(rule, 0, 0) if rule else 0


def record_booking(db: Any, org_id: str, demo_id: str, now: Optional[datetime] = None) -> dict:
    """Count one booking and charge the overage fee if this one is past the allowance.
    Returns {counted, used, cap, over, charged_kobo}. Never raises."""
    out = {"counted": False, "used": 0, "cap": 0, "over": False, "charged_kobo": 0}
    try:
        now = now or _now()
        if not org_id or not demo_id or not acc.is_enforced(db, org_id):
            return out
        cap = int(acc._compute(db, org_id, now)["caps"].get(CAP_KEY, 0))
        if cap <= 0:
            return out                      # this plan has no booking allowance to count
        used = _bump(db, org_id, now)
        if used is None:
            logger.warning("booking_allowance: could not count booking org=%s demo=%s", org_id, demo_id)
            return out
        out.update({"counted": True, "used": used, "cap": cap, "over": used > cap})
        if used <= cap:
            return out
        wallet = cs.get_wallet(db, org_id)
        if not cs.metering_on(wallet):
            return out
        fee = overage_fee_kobo(db, org_id)
        if fee > 0:
            res = cs._debit(db, org_id, fee, "fee", f"fee:booking:{demo_id}", f"fee:{FEE_EVENT}",
                            {"demo_id": demo_id, "used": used, "cap": cap})
            out["charged_kobo"] = int(res["charged_kobo"]) if res else 0
    except Exception as exc:  # S14
        logger.warning("booking_allowance.record_booking failed org=%s demo=%s: %s", org_id, demo_id, exc)
    return out
