"""
app/services/site_access_service.py
------------------------------------
SITE-ACCESS-1 — how many sites a builder may make, and the monthly builder subscription (decision D1).

Rule (Trust, 28 Sept 2026, D1):
  * A builder can have `free_sites` sites (default 3) with no subscription.
  * Past that, they need an active subscription: NGN 5,000 for 30 days, paid by Paystack link.
  * `site_builders.max_active_sites`, when set by staff, replaces the free count for that one builder
    (use a big number for a lifetime or VIP builder). `site_builders.access_paid_until` is the end of the
    paid period (null = no subscription).
  * Staff creating a site by hand (POST /sites) are never blocked. This service is for builders only.

What counts as a site: any site of the builder that is not deleted and not cancelled. Drafts count, which is
the point (it stops unlimited drafts that cost AI and storage without ever going live).

Prices live in site_builder_settings.pricing.builder_access ({free_sites, price_ngn, days}).
The payment is a site_orders row of kind 'builder_access' with site_id null; the Paystack webhook reaches
on_paid() through site_order_service.on_payment_confirmed. Nothing here raises into the payment path (S14).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULTS = {"free_sites": 3, "price_ngn": 5000, "days": 30}
KIND = "builder_access"


class AccessError(Exception):
    pass


class AccessBlocked(AccessError):
    """The builder has used their free sites and has no active subscription."""
    def __init__(self, message: str, view: dict):
        super().__init__(message)
        self.view = view


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _money(n) -> str:
    return f"₦{float(n):,.0f}"


def _int(value, default: int, low: int = 0) -> int:
    try:
        return max(low, int(value))
    except (TypeError, ValueError):
        return default


def get_config(settings: Optional[dict]) -> dict:
    """pricing.builder_access merged over the defaults; bad values fall back to the defaults."""
    raw = (((settings or {}).get("pricing") or {}).get("builder_access")) or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "free_sites": _int(raw.get("free_sites"), DEFAULTS["free_sites"], 0),
        "price_ngn": _int(raw.get("price_ngn"), DEFAULTS["price_ngn"], 0),
        "days": _int(raw.get("days"), DEFAULTS["days"], 1),
    }


def _settings(db: Any, org_id: str) -> dict:
    return _one((db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data) or {}


def count_sites(db: Any, org_id: str, builder_id: str) -> int:
    rows = (db.table("sites").select("id").eq("org_id", org_id).eq("builder_id", builder_id)
            .is_("deleted_at", "null").neq("status", "cancelled").execute()).data or []
    return len(rows)


def view(db: Any, org_id: str, builder: dict, now: Optional[datetime] = None,
         settings: Optional[dict] = None) -> dict:
    """What the builder sees: how many sites used, the cap, subscription state and whether they can start another."""
    now = now or _now()
    cfg = get_config(settings if settings is not None else _settings(db, org_id))
    cap = builder.get("max_active_sites")
    cap = _int(cap, cfg["free_sites"], 0) if cap is not None else cfg["free_sites"]
    used = count_sites(db, org_id, builder["id"])
    paid_until = _parse(builder.get("access_paid_until"))
    subscribed = bool(paid_until and paid_until > now)
    can_create = subscribed or used < cap
    return {
        "used": used, "free_sites": cap, "free_left": max(0, cap - used),
        "subscribed": subscribed, "subscribed_until": _iso(paid_until) if paid_until else None,
        "can_create": can_create, "price_ngn": cfg["price_ngn"], "days": cfg["days"],
    }


def blocked_message(v: dict) -> str:
    return (f"You've used your {v['free_sites']} free sites. Subscribe for {_money(v['price_ngn'])} "
            f"every {v['days']} days to keep building more.")


def check_can_create(db: Any, org_id: str, builder: dict, now: Optional[datetime] = None) -> dict:
    """Returns the view when the builder may start another site; raises AccessBlocked when not.
    Never blocks a builder because of a bug in this code: an unexpected error is logged and treated as allowed
    (a broken counter must not stop paying customers), but AccessBlocked always propagates."""
    try:
        v = view(db, org_id, builder, now)
    except Exception as exc:  # S14
        logger.warning("site_access: check failed builder=%s: %s", builder.get("id"), exc)
        return {"can_create": True, "error": True}
    if not v["can_create"]:
        raise AccessBlocked(blocked_message(v), v)
    return v


# ---------------------------------------------------------------------------
# CRM lead (needed for a Paystack link)
# ---------------------------------------------------------------------------

def ensure_lead(db: Any, org_id: str, builder: dict) -> Optional[str]:
    """Every builder has one CRM lead (spec 5.2). Self-registered builders may not: make it now. Best effort."""
    if builder.get("lead_id"):
        return builder["lead_id"]
    try:
        from app.models.leads import LeadCreate, LeadSource
        from app.services import lead_service
        phone = str(builder.get("phone_number") or "")
        lead = lead_service.create_lead(
            db=db, org_id=org_id, user_id=(_settings(db, org_id).get("owner_notify_user_id") or "system"),
            payload=LeadCreate(full_name=builder.get("full_name") or "Site builder", phone=phone, whatsapp=phone,
                               email=builder.get("email") or None, source=LeadSource.landing_page.value),
            entry_path="site_builder",
        )
        lead_id = (lead or {}).get("id")
        if lead_id:
            db.table("site_builders").update({"lead_id": lead_id, "updated_at": _iso()}) \
                .eq("id", builder["id"]).eq("org_id", org_id).execute()
            builder["lead_id"] = lead_id
        return lead_id
    except Exception as exc:  # S14
        logger.warning("site_access: lead creation failed builder=%s: %s", builder.get("id"), exc)
        return None


# ---------------------------------------------------------------------------
# Subscription checkout
# ---------------------------------------------------------------------------

def create_checkout(db: Any, org_id: str, builder: dict) -> dict:
    """A Paystack link for one subscription period. Reuses the builder's open link of the same price."""
    from app.services import paystack_storefront_service as paystack
    cfg = get_config(_settings(db, org_id))
    amount = cfg["price_ngn"]
    if amount <= 0:
        raise AccessError("Subscriptions aren't available right now.")
    lead_id = ensure_lead(db, org_id, builder)
    if not lead_id:
        raise AccessError("We couldn't set up your payment link yet. Please try again in a moment.")

    open_orders = [o for o in ((db.table("site_orders").select("*").eq("org_id", org_id).eq("builder_id", builder["id"])
                                .eq("kind", KIND).eq("status", "pending_payment").execute()).data or [])
                   if o.get("payment_link_id") and float(o.get("amount") or 0) == float(amount)]
    open_orders.sort(key=lambda o: str(o.get("created_at") or ""), reverse=True)
    for order in open_orders:
        link = _one((db.table("payment_links").select("checkout_url").eq("id", order["payment_link_id"])
                     .eq("org_id", org_id).limit(1).execute()).data)
        if link and link.get("checkout_url"):
            return {"checkout_url": link["checkout_url"], "amount": amount, "days": cfg["days"], "reused": True}

    try:
        link = paystack.generate_payment_link(
            db=db, org_id=org_id, lead_id=lead_id, amount=amount, payment_type="full", currency="NGN",
            trigger_stage=None, target_stage_on_paid=None, created_by=None,
        )
    except paystack.PaystackLinkError as exc:
        raise AccessError(str(exc))

    now = _iso()
    row = {
        "org_id": org_id, "site_id": None, "builder_id": builder["id"], "lead_id": lead_id,
        "kind": KIND, "route": "standard", "domain": None, "backup_domain": None,
        "quote": {"kind": KIND, "days": cfg["days"], "price": amount}, "amount": amount, "cost_snapshot": {},
        "expected_profit": amount, "payment_link_id": link.get("payment_link_id"), "payment_reference": link["reference"],
        "status": "pending_payment", "approval_required": False, "created_at": now, "updated_at": now,
    }
    db.table("site_orders").insert(row).execute()
    return {"checkout_url": link["checkout_url"], "amount": amount, "days": cfg["days"], "reused": False}


def on_paid(db: Any, org_id: str, order: dict, now: Optional[datetime] = None) -> None:
    """Payment confirmed: push access_paid_until forward one period. If a period is still running the new one
    starts when it ends, so paying early never loses days."""
    now = now or _now()
    days = _int(((order.get("quote") or {}).get("days")), DEFAULTS["days"], 1)
    builder = _one((db.table("site_builders").select("*").eq("id", order["builder_id"]).eq("org_id", org_id)
                    .limit(1).execute()).data)
    if not builder:
        raise AccessError("builder not found for access payment")
    current = _parse(builder.get("access_paid_until"))
    start = current if (current and current > now) else now
    end = start + timedelta(days=days)
    db.table("site_builders").update({"access_paid_until": _iso(end), "updated_at": _iso(now)}) \
        .eq("id", builder["id"]).eq("org_id", org_id).execute()
    try:
        db.table("site_events").insert({
            "org_id": org_id, "site_id": None, "order_id": order.get("id"), "actor": "system",
            "event": "builder_access_paid", "detail": {"builder_id": builder["id"], "until": _iso(end)},
            "created_at": _iso(now),
        }).execute()
    except Exception as exc:  # S14
        logger.warning("site_access: event log failed order=%s: %s", order.get("id"), exc)
    try:
        from app.services import site_order_service
        site_order_service._message_builder(
            db, org_id, order,
            f"Your Site Builder subscription is active until {end.astimezone(timezone(timedelta(hours=1))).strftime('%d %b %Y')}. "
            "You can start as many sites as you like until then.")
    except Exception as exc:  # S14
        logger.warning("site_access: builder message failed order=%s: %s", order.get("id"), exc)
