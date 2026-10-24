"""
app/services/account_seat_service.py
------------------------------------
ACCOUNT-PLANS AP-7 - users and seats. Every plan includes INCLUDED_USERS (one admin and one staff member). Each user beyond
that is a SEAT, paid monthly at the price in Settings > Pricing (addons.extra_rep.monthly_ngn, N5,000 at the time of writing).

How seats are held
  * ONE add-on row per organisation (org_plans: kind 'addon', key 'extra_rep'); config.quantity is the number of paid seats.
  * Seats run on the plan's own dates: a seat row's paid_until always equals the tier's, so they lapse and renew together.
  * Buying seats part-way through a period charges only the days left (rounded up). They are on at once.
  * Renewing the plan renews the seats too (the renewal total is plan + seats). Fewer seats next time: set config.next_quantity.
  * Upgrading to a dearer plan restarts the period, so the seats are re-priced for it with the unused days credited.
  * A seat granted by staff (source 'staff') is free, is never billed, and is left alone by renewals.

Lapse (decision: block only). When seats lapse nobody is switched off. The business simply cannot add a user beyond what its
plan and live seats allow (plan_gate_service.check_can_add_user), and the Team tab tells the owner how many users are over.

Money: the amount always comes from Settings and the plan dates, never from the browser. Same Paystack account, reference
prefix and webhook as plan payments (reference starts "ap_"; order kind 'seats').
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from app.services import account_entitlement_service as acc
from app.services import account_plan_billing_service as bill
from app.services import site_addon_billing_service as sab
from app.services import site_entitlement_service as ent

logger = logging.getLogger(__name__)

INCLUDED_USERS = 2
SEAT_KEY = "extra_rep"
MAX_ADD = 50
SYSTEM_EMAIL_SUFFIX = "@system.opsra.internal"


def seat_price(cfg: dict) -> int:
    return int(((cfg.get("addons") or {}).get(SEAT_KEY) or {}).get("monthly_ngn") or 0)


def _seat_row(db: Any, org_id: str) -> Optional[dict]:
    return bill._one((db.table("org_plans").select("*").eq("org_id", org_id).eq("kind", "addon").eq("key", SEAT_KEY)
                      .neq("status", "cancelled").limit(1).execute()).data)


def _qty(row: Optional[dict], key: str = "quantity", default: int = 1) -> int:
    if not row:
        return 0
    try:
        return max(int((row.get("config") or {}).get(key, default)), 0)
    except (TypeError, ValueError):
        return default


def live_seats(db: Any, org_id: str, cfg: dict, now: datetime) -> int:
    row = _seat_row(db, org_id)
    if not row or ent.effective_status(row, cfg, now) not in acc.LIVE_STATES:
        return 0
    return _qty(row)


def included_users(db: Any, org_id: str) -> int:
    """Users the plan includes. A plan can set its own number with the users_included cap (WA-AUTO-1: 1 for the WhatsApp
    automation plan); otherwise INCLUDED_USERS. Any problem answers INCLUDED_USERS."""
    try:
        n = int((acc._compute(db, org_id, bill._now()).get("caps") or {}).get("users_included") or 0)
        return n if n > 0 else INCLUDED_USERS
    except Exception as exc:
        logger.warning("account_seat: included_users failed org=%s - using %s: %s", org_id, INCLUDED_USERS, exc)
        return INCLUDED_USERS


def allowed_users(db: Any, org_id: str, cfg: dict, now: datetime) -> int:
    return included_users(db, org_id) + live_seats(db, org_id, cfg, now)


def active_users(db: Any, org_id: str) -> int:
    rows = (db.table("users").select("id, email").eq("org_id", org_id).eq("is_active", True).execute().data) or []
    return len([r for r in rows if not (r.get("email") or "").endswith(SYSTEM_EMAIL_SUFFIX)])


def _live_paid_tier(db: Any, org_id: str, cfg: dict, now: datetime) -> Optional[dict]:
    """The running plan extra users can be bought against: paid through Paystack OR given by Opsra staff, as long as it is
    active and has an end date in the future (seats are charged for the days left and end with the plan)."""
    t = bill._tier_row(db, org_id)
    until = ent._parse(t.get("paid_until")) if t else None
    if t and t.get("source") in ("paid", "staff") and until and until > now and ent.effective_status(t, cfg, now) == "active":
        return t
    return None


# ---------------------------------------------------------------------------
# what the Team tab shows
# ---------------------------------------------------------------------------

def team(db: Any, org_id: str, now: Optional[datetime] = None) -> dict:
    now = now or bill._now()
    cfg = acc.plan_config(db)
    row = _seat_row(db, org_id)
    tier = _live_paid_tier(db, org_id, cfg, now)
    price = seat_price(cfg)
    seats = live_seats(db, org_id, cfg, now)
    used = active_users(db, org_id)
    included = included_users(db, org_id)
    allowed = included + seats
    reason = None
    if price <= 0:
        reason = "Extra users are not for sale yet."
    elif not tier:
        reason = "Extra users run on an active plan with an end date. Choose or renew a plan first."
    until = ent._parse(tier.get("paid_until")) if tier else None
    paid_seat = bool(row and row.get("source") == "paid")
    return {
        "enforced": acc.is_enforced(db, org_id), "included": included, "seats": seats, "allowed": allowed, "used": used,
        "over_by": max(used - allowed, 0), "price_ngn": price, "can_buy": reason is None, "reason": reason,
        "paid_until": tier.get("paid_until") if tier else None,
        "days_left": max(int((until - now).total_seconds() // 86400), 0) if until else 0,
        "seats_next": (_qty(row, "next_quantity", _qty(row)) if paid_seat else seats),
        "seats_lapsed": bool(row and _qty(row) > 0 and seats == 0),
        "free_seats": bool(row and row.get("source") != "paid" and seats > 0),
    }


# ---------------------------------------------------------------------------
# buying seats part-way through a period
# ---------------------------------------------------------------------------

def quote_seats(db: Any, org_id: str, add: int, now: Optional[datetime] = None) -> dict:
    now = now or bill._now()
    bill._org(db, org_id)
    if not isinstance(add, int) or isinstance(add, bool) or add < 1 or add > MAX_ADD:
        raise bill.PlanBillingError(f"Choose between 1 and {MAX_ADD} users.")
    cfg = acc.plan_config(db)
    price = seat_price(cfg)
    if price <= 0:
        raise bill.PlanBillingError("Extra users are not for sale yet.")
    tier = _live_paid_tier(db, org_id, cfg, now)
    if not tier:
        raise bill.PlanBillingError("Extra users run on an active plan with an end date. Choose or renew a plan first.")
    until = ent._parse(tier["paid_until"])
    period = cfg["billing"]["period_days"]
    remaining = min((until - now).total_seconds() / 86400.0, float(period))
    days = min(max(int(math.ceil(remaining)), 1), period)          # whole days, rounded up: the price matches the days shown
    total = max(int(math.ceil(price * add * days / period)), bill.MIN_AMOUNT_NGN)
    return {"add": add, "price": price, "days": days, "total": total, "paid_until": tier["paid_until"],
            "tier_key": tier["key"], "plan_id": tier["id"], "seats_after": live_seats(db, org_id, cfg, now) + add}


def preview_seats(db: Any, org_id: str, add: int, now: Optional[datetime] = None) -> dict:
    return quote_seats(db, org_id, add, now)


def checkout_seats(db: Any, org_id: str, *, add: int, email: str = "", user_id: Optional[str] = None,
                   callback_url: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    now = now or bill._now()
    qt = quote_seats(db, org_id, add, now)
    secret = bill._secret()
    if not secret:
        raise bill.PlanBillingError("Online payment is not available right now. Please contact support.")
    amount_kobo = int(qt["total"]) * 100

    open_orders = bill._rows(db.table("org_plan_orders").select("*").eq("org_id", org_id).eq("status", "pending")
                             .order("created_at", desc=True).execute())
    for o in open_orders:
        oq = o.get("quote") or {}
        if (o.get("change_kind") == "seats" and int(o.get("amount_kobo") or 0) == amount_kobo and int(oq.get("add") or 0) == add
                and oq.get("paid_until") == qt["paid_until"] and o.get("checkout_url")):
            return {"order_id": o["id"], "reference": o["reference"], "checkout_url": o["checkout_url"], "amount_kobo": amount_kobo, "reused": True}
    for o in open_orders:
        db.table("org_plan_orders").update({"status": "expired", "updated_at": bill._iso(now)}) \
            .eq("id", o["id"]).eq("org_id", org_id).eq("status", "pending").execute()

    reference = f"{bill.PREFIX}{org_id[:8]}_{uuid.uuid4().hex[:12]}"
    quote = {"kind": "seats", "key": qt["tier_key"], "label": "Extra users", **qt}
    email = (email or "").strip()
    try:
        order = (bill._rows(db.table("org_plan_orders").insert({
            "org_id": org_id, "plan_key": qt["tier_key"], "change_kind": "seats", "amount_kobo": amount_kobo, "quote": quote,
            "reference": reference, "status": "pending", "payer_email": email or None, "created_by": user_id,
            "created_at": bill._iso(now), "updated_at": bill._iso(now)}).execute()) or [{}])[0]
    except Exception as exc:
        logger.error("account_seats order insert failed org=%s: %s", org_id, exc)
        raise bill.PlanBillingError("Could not start your payment. Please try again.")
    body = {"email": email or f"org-{org_id[:8]}@example.com", "amount": amount_kobo, "currency": "NGN", "reference": reference,
            "metadata": {"kind": "account_seats", "org_id": org_id, "order_id": order.get("id"), "add": add}}
    if callback_url:
        body["callback_url"] = callback_url
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(f"{bill.PAYSTACK_API}/transaction/initialize", headers={"Authorization": f"Bearer {secret}"}, json=body)
        data = resp.json()
        if resp.status_code != 200 or not data.get("status"):
            raise ValueError(data.get("message") or "Paystack refused")
        url = (data.get("data") or {}).get("authorization_url")
        if not url:
            raise ValueError("no checkout url")
    except Exception as exc:
        logger.warning("account_seats checkout failed org=%s: %s", org_id, exc)
        try:
            db.table("org_plan_orders").update({"status": "failed", "updated_at": bill._iso(now)}).eq("id", order.get("id")).eq("org_id", org_id).execute()
        except Exception:
            pass
        raise bill.PlanBillingError("Could not reach Paystack right now. Please try again shortly.")
    try:
        db.table("org_plan_orders").update({"checkout_url": url}).eq("id", order.get("id")).eq("org_id", org_id).execute()
    except Exception:
        pass
    acc._log_event(db, org_id, user_id or "owner", "seats_checkout_started", {"add": add, "amount_kobo": amount_kobo})
    return {"order_id": order.get("id"), "reference": reference, "checkout_url": url, "amount_kobo": amount_kobo, "reused": False}


def apply_paid_seats(db: Any, order: dict, previous_status: str, now: datetime) -> None:
    """A paid 'seats' order: add the seats to the organisation until the plan's own end date."""
    org_id = order["org_id"]
    q = order.get("quote") or {}
    add = int(q.get("add") or 0)
    if add < 1:
        raise ValueError("seat order has no quantity")
    tier = bill._tier_row(db, org_id)
    if not tier or not tier.get("paid_until"):
        raise ValueError("no plan to attach the seats to")
    until = tier["paid_until"]
    cfg = acc.plan_config(db)
    row = _seat_row(db, org_id)
    if row:
        was_live = ent.effective_status(row, cfg, now) in acc.LIVE_STATES
        qty = (_qty(row) if was_live else 0) + add
        config = dict(row.get("config") or {})
        config["quantity"] = qty
        config.pop("next_quantity", None)
        db.table("org_plans").update({"status": "active", "source": "paid", "paid_until": until, "grace_until": None,
                                      "price_ngn": q.get("price") or 0, "config": config, "updated_at": bill._iso(now)}) \
            .eq("id", row["id"]).eq("org_id", org_id).execute()
    else:
        qty = add
        db.table("org_plans").insert({"org_id": org_id, "kind": "addon", "key": SEAT_KEY, "status": "active", "source": "paid",
                                      "price_ngn": q.get("price") or 0, "paid_until": until, "config": {"quantity": qty},
                                      "created_by": order.get("created_by"), "created_at": bill._iso(now),
                                      "updated_at": bill._iso(now)}).execute()
    acc._log_event(db, org_id, "system", "seats_paid", {"add": add, "seats": qty, "until": until, "amount_kobo": order.get("amount_kobo"),
                                                         "order_id": order.get("id")})
    bill._notify(db, org_id, "Extra users added",
                 f"Payment received. You can now have {included_users(db, org_id) + qty} users until {sab._pretty(ent._parse(until))}. Thank you.",
                 "seats_paid", order.get("payer_email"), "Your Opsra users")


# ---------------------------------------------------------------------------
# seats inside a plan renewal or upgrade
# ---------------------------------------------------------------------------

def renewal_seats(db: Any, org_id: str, cfg: dict, tier_row: Optional[dict], now: datetime, kind: str) -> tuple:
    """(seats, price, credit) to add to a quote. Only PAID seats are billed. A renewal uses next_quantity when the owner set
    one. An upgrade keeps today's seats and credits their unused days (the new period starts now)."""
    row = _seat_row(db, org_id)
    price = seat_price(cfg)
    if not row or row.get("source") != "paid" or price <= 0:
        return 0, price, 0
    if kind == "upgrade":
        if ent.effective_status(row, cfg, now) not in acc.LIVE_STATES:
            return 0, price, 0
        qty = _qty(row)
        until = ent._parse(row.get("paid_until"))
        credit = 0
        if until and until > now and ent.effective_status(row, cfg, now) == "active":
            period = cfg["billing"]["period_days"]
            remaining = min((until - now).total_seconds() / 86400.0, float(period))
            credit = max(int(price * qty * remaining / period), 0)
        return qty, price, credit
    return _qty(row, "next_quantity", _qty(row)), price, 0


def apply_renewal(db: Any, org_id: str, kind: str, quote: dict, end_iso: str, now: datetime) -> None:
    """After the plan row has been updated by a paid renewal / downgrade renewal / upgrade: line the paid seats up with it."""
    if kind not in ("renewal", "downgrade_renewal", "upgrade"):
        return
    row = _seat_row(db, org_id)
    if not row or row.get("source") != "paid":
        return
    seats = int(quote.get("seats") or 0)
    if seats < 1:
        db.table("org_plans").update({"status": "cancelled", "updated_at": bill._iso(now)}).eq("id", row["id"]).eq("org_id", org_id).execute()
        acc._log_event(db, org_id, "system", "seats_ended", {"reason": "not renewed"})
        return
    config = dict(row.get("config") or {})
    config["quantity"] = seats
    config.pop("next_quantity", None)
    db.table("org_plans").update({"status": "active", "paid_until": end_iso, "grace_until": None,
                                  "price_ngn": quote.get("seat_price") or row.get("price_ngn") or 0,
                                  "config": config, "updated_at": bill._iso(now)}).eq("id", row["id"]).eq("org_id", org_id).execute()


def set_next_seats(db: Any, org_id: str, quantity: int, actor: str = "owner") -> dict:
    """Fewer seats at the next renewal (never more: more users are bought now)."""
    row = _seat_row(db, org_id)
    if not row or row.get("source") != "paid":
        raise bill.PlanBillingError("You have no paid extra users to change.")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
        raise bill.PlanBillingError("Choose a number of users that is zero or more.")
    current = _qty(row)
    if quantity > current:
        raise bill.PlanBillingError("To add users, buy them above. This setting is only for having fewer at your next renewal.")
    config = dict(row.get("config") or {})
    if quantity == current:
        config.pop("next_quantity", None)
    else:
        config["next_quantity"] = quantity
    db.table("org_plans").update({"config": config, "updated_at": bill._iso()}).eq("id", row["id"]).eq("org_id", org_id).execute()
    acc._log_event(db, org_id, actor, "seats_next_set", {"quantity": quantity, "current": current})
    return {"seats_next": quantity}


def renewal_note(db: Any, org_id: str, cfg: dict, now: datetime) -> int:
    """Naira the seats add to the next renewal (for reminder texts). 0 on any problem."""
    try:
        qty, price, _ = renewal_seats(db, org_id, cfg, None, now, "renewal")
        return int(qty * price)
    except Exception:
        return 0
