"""
app/services/billing_pay_link_service.py
----------------------------------------
BILL-4 - an invoice-style link to a business's Billing: shows the plan, the credit left and lets the person holding it
renew the plan or top up credit through Paystack. Nothing else: no team, no payment history, no settings, no plan switching.

Rules
  * One active link per business: making a new one ends the old one. The token is shown once; only its SHA-256 is stored.
  * Valid for 7 days (max 30). Revocable at any time. Every use bumps use_count / last_used_at.
  * The business always comes from the token, never from the request. Amounts are never accepted from the browser except a
    custom top-up amount, which goes through the same limits as a logged-in top-up.
  * Anyone holding the link can see the plan and balance and pay; treat it like an invoice link.
  * S14: reads never raise past their caller except LinkError (rendered as one generic message).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 7
MAX_DAYS = 30
GENERIC = "This link is not valid any more. Please ask the business for a new one."


class LinkError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _rows(res) -> list:
    data = getattr(res, "data", None)
    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) and data else []


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def _live(row: dict, now: datetime) -> bool:
    if not row or row.get("revoked_at"):
        return False
    try:
        exp = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    except Exception:
        return False
    return exp > now


def create(db: Any, org_id: str, *, user_id: Optional[str], label: str, email: str, days: int = DEFAULT_DAYS,
           now: Optional[datetime] = None) -> dict:
    now = now or _now()
    days = max(1, min(int(days or DEFAULT_DAYS), MAX_DAYS))
    revoke(db, org_id, now)
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(days=days)
    row = {"org_id": org_id, "token_hash": hash_token(token), "payer_email": (email or "").strip() or None,
           "created_by": user_id, "created_by_label": (label or "")[:120] or None, "expires_at": _iso(expires)}
    try:
        db.table("billing_pay_links").insert(row).execute()
    except Exception as exc:
        logger.error("pay link insert failed org=%s: %s", org_id, exc)
        raise LinkError("Could not create the link. Please try again.")
    return {"token": token, "expires_at": _iso(expires)}


def status(db: Any, org_id: str, now: Optional[datetime] = None) -> Optional[dict]:
    """The business's current link (never the token), or None."""
    now = now or _now()
    try:
        rows = _rows(db.table("billing_pay_links").select("id, expires_at, revoked_at, use_count, last_used_at, created_at, created_by_label")
                     .eq("org_id", org_id).order("created_at", desc=True).limit(1).execute())
    except Exception as exc:
        logger.warning("pay link status failed org=%s: %s", org_id, exc)
        return None
    if not rows or not _live(rows[0], now):
        return None
    r = rows[0]
    return {k: r.get(k) for k in ("expires_at", "use_count", "last_used_at", "created_at", "created_by_label")}


def revoke(db: Any, org_id: str, now: Optional[datetime] = None) -> int:
    now = now or _now()
    try:
        rows = _rows(db.table("billing_pay_links").select("id, expires_at, revoked_at").eq("org_id", org_id).is_("revoked_at", "null").execute())
        n = 0
        for r in rows:
            db.table("billing_pay_links").update({"revoked_at": _iso(now)}).eq("id", r["id"]).eq("org_id", org_id).execute()
            n += 1
        return n
    except Exception as exc:
        logger.warning("pay link revoke failed org=%s: %s", org_id, exc)
        return 0


def resolve(db: Any, token: str, now: Optional[datetime] = None, touch: bool = True) -> dict:
    """The live link row for this token. Raises LinkError(GENERIC) for anything wrong (unknown, expired, revoked)."""
    now = now or _now()
    if not token or len(token) < 20 or len(token) > 80:
        raise LinkError(GENERIC)
    try:
        rows = _rows(db.table("billing_pay_links").select("*").eq("token_hash", hash_token(token)).limit(1).execute())
    except Exception as exc:
        logger.warning("pay link resolve failed: %s", exc)
        raise LinkError(GENERIC)
    if not rows or not _live(rows[0], now):
        raise LinkError(GENERIC)
    row = rows[0]
    if touch:
        try:
            db.table("billing_pay_links").update({"use_count": int(row.get("use_count") or 0) + 1, "last_used_at": _iso(now)}) \
                .eq("id", row["id"]).eq("org_id", row["org_id"]).execute()
        except Exception as exc:
            logger.warning("pay link touch failed: %s", exc)
    return row


def public_view(db: Any, link: dict, now: Optional[datetime] = None) -> dict:
    """What the page shows. Deliberately small: business name, plan, credit, what renewing costs, the top-up packs."""
    from app.services import account_plan_billing_service as plans
    from app.services import credit_order_service as cos
    now = now or _now()
    org_id = link["org_id"]
    org = _rows(db.table("organisations").select("name").eq("id", org_id).limit(1).execute())
    try:
        s = plans.summary(db, org_id, now)
    except Exception as exc:
        logger.warning("pay link summary failed org=%s: %s", org_id, exc)
        s = {"current": None, "plans": [], "credit": None}
    cur = s.get("current")
    renew = None
    if cur:
        item = next((p for p in s.get("plans", []) if p.get("key") == cur["key"]), None)
        if item and item.get("for_sale"):
            yearly = cur.get("interval") == "year" and item.get("yearly_amount_due")
            renew = {"amount_ngn": int(item["yearly_amount_due"] if yearly else item["amount_due"]), "interval": "year" if yearly else "month"}
    plan = None
    if cur:
        plan = {k: cur.get(k) for k in ("label", "status", "paid_until", "days_left", "monthly_ngn", "interval")}
    try:
        packs = [{"id": p["id"], "price_kobo": p["price_kobo"], "credit_kobo": p["credit_kobo"]} for p in cos.list_packs(db)]
    except Exception:
        packs = []
    return {"business": (org[0].get("name") if org else None), "expires_at": link.get("expires_at"), "plan": plan,
            "credit": s.get("credit"), "renew": renew, "packs": packs,
            "min_custom_kobo": cos.MIN_CUSTOM_KOBO, "max_order_kobo": cos.MAX_ORDER_KOBO}


def renew(db: Any, link: dict, callback_url: str) -> dict:
    """Pay for the plan the business is already on (same plan, same period). Never changes plan."""
    from app.services import account_plan_billing_service as plans
    org_id = link["org_id"]
    row = plans._tier_row(db, org_id)
    if not row:
        raise plans.PlanBillingError("This business has no plan to renew yet.")
    interval = "year" if (row.get("config") or {}).get("interval") == "year" else "month"
    res = plans.checkout(db, org_id, key=row["key"], email=link.get("payer_email") or "", user_id=None,
                         callback_url=callback_url, interval=interval)
    if res.get("scheduled"):
        raise plans.PlanBillingError("There is nothing to pay for this plan right now.")
    return {"checkout_url": res["checkout_url"], "reference": res["reference"]}


def verify(db: Any, link: dict, reference: str) -> dict:
    """After Paystack: confirm a payment that belongs to THIS business only (plan: ap_, credit: cr_)."""
    from app.services import account_plan_billing_service as plans
    from app.services import credit_order_service as cos
    ref = str(reference or "")
    if ref.startswith("cr_"):
        return cos.verify(db, link["org_id"], ref)
    return plans.verify(db, link["org_id"], ref)
