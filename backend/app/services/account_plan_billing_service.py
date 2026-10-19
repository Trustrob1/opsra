"""
app/services/account_plan_billing_service.py
----------------------------------------------
ACCOUNT-PLANS AP-2 - what an organisation pays Opsra for its OWN plan (Capture / Convert / Grow), and what happens to the
money and the dates. (Link mode: one Paystack checkout per month, with reminders. Automatic card charging comes later.)

Who pays: the organisation's owner (or an operations manager), logged in. The order is paid to OPSRA on Opsra's own
Paystack key (env PAYSTACK_SECRET_KEY, the same account the credit top-ups use). The reference starts with "ap_" so the
existing Paystack webhook can tell it apart from a credit top-up ("cr_") and from a business's own payment links.

Money rules (decisions of 19 Oct 2026)
  * Prices come from Settings > Pricing tiers on every call (one price per tier for sites and accounts). Nothing the
    browser sends can change an amount. No set-up fee. No credits are included in a plan. No VAT line. No refunds.
  * A period is billing.period_days (30). Renewal paid early keeps the unused days (the new period starts when the old one ends).
  * UPGRADE (running paid tier -> a dearer tier): pay the new price minus a credit for the unused days; starts at once.
  * DOWNGRADE (running paid tier -> a cheaper or equal tier): nothing to pay now; scheduled in config.pending_key and applied
    when the NEXT renewal is paid, at the lower price. Paying for the current plan again cancels the scheduled change.
  * Any other change (no plan yet, staff-granted, or a lapsed paid plan): a plain switch/new plan, fresh period, no credit.
  * Discount codes (scope "plans", codes held by the platform organisation) work on the very first payment only.

Lifecycle (run_cycle, daily): active -> grace at paid_until -> paused when the grace days are over. Features follow the
dates even if the worker is late (site_entitlement_service.effective_status). Owners get an email and an in-app note at the
reminder days (default 5 and 1 before the end), when the plan enters grace, and when it is paused.
For a business that has been switched on (organisations.plans_enforced) the worker also keeps organisations.subscription_status
in step (grace -> grace, paused -> read_only, paid -> active), using existing values only. A suspended business is never
touched, and a client's website workspace is never billed here.

S14: mark_paid and the worker never raise past their caller; the only thing that can fail a payment is the plan update itself,
and then the order goes back to its old state so the next webhook retry applies it.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.services import account_entitlement_service as acc
from app.services import site_addon_billing_service as sab
from app.services import site_entitlement_service as ent
from app.services import site_feature_registry as reg

logger = logging.getLogger(__name__)

PAYSTACK_API = "https://api.paystack.co"
PREFIX = "ap_"
MIN_AMOUNT_NGN = 100


class PlanBillingError(Exception):
    """User-facing failure; the router maps it to a 422."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).astimezone(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _rows(res) -> list:
    return list(getattr(res, "data", None) or [])


def _secret() -> str:
    return os.getenv("PAYSTACK_SECRET_KEY", "").strip()


def _tier_row(db: Any, org_id: str) -> Optional[dict]:
    return _one((db.table("org_plans").select("*").eq("org_id", org_id).eq("kind", "tier")
                 .neq("status", "cancelled").limit(1).execute()).data)


def _org(db: Any, org_id: str) -> dict:
    org = _one((db.table("organisations").select("id, subscription_status, plans_enforced").eq("id", org_id).limit(1).execute()).data)
    if not org:
        raise PlanBillingError("We could not find your organisation.")
    if (org.get("subscription_status") or "") == "site_workspace":
        raise PlanBillingError("A client's website workspace has no account plan. Give the site a tier instead.")
    return org


def _includes(d: dict, picks: Optional[list] = None) -> list:
    feats = list(d.get("features") or [])
    feats += [p for p in (picks or []) if p not in feats]
    return [reg.FEATURES[k]["label"] for k in feats if k in reg.FEATURES]


# ---------------------------------------------------------------------------
# quote
# ---------------------------------------------------------------------------

def _paid_before(db: Any, org_id: str) -> bool:
    try:
        return bool(_rows(db.table("org_plan_orders").select("id").eq("org_id", org_id).eq("status", "paid").limit(1).execute()))
    except Exception as exc:
        logger.warning("account_plan: paid_before lookup failed org=%s: %s", org_id, exc)
        return True       # when unsure, treat as "not the first payment" so no code is honoured


def quote_for(db: Any, org_id: str, cfg: dict, key: str, now: datetime, row: Optional[dict] = None) -> dict:
    """What choosing `key` costs right now. kind: new | renewal | upgrade | switch | downgrade_renewal | downgrade (scheduled, no order).
    Everything comes from Settings and the plan row, never from the caller."""
    d = cfg["tiers"].get(key)
    if not d:
        raise PlanBillingError("That plan isn't available any more.")
    price = int(d["monthly_ngn"])
    if price <= 0:
        raise PlanBillingError("This plan isn't for sale yet.")
    days = cfg["billing"]["period_days"]
    credit = 0
    pending = (row.get("config") or {}).get("pending_key") if row else None
    until = ent._parse(row.get("paid_until")) if row else None
    paid_live = bool(row and row.get("source") == "paid" and until and until > now
                     and ent.effective_status(row, cfg, now) == "active")
    if row is None or row.get("status") == "pending":
        kind = "new"
    elif row["key"] == key:
        kind = "renewal" if (row.get("source") == "paid" and until) else "switch"
    elif pending == key and row.get("source") == "paid":
        kind = "downgrade_renewal"
    elif paid_live:
        old = cfg["tiers"].get(row["key"]) or {}
        old_price = int(old.get("monthly_ngn") or row.get("price_ngn") or 0)
        if price <= old_price:
            kind = "downgrade"
        else:
            kind = "upgrade"
            credit = sab._credit_for_unused(row, cfg, now)
    else:
        kind = "switch"
    first = kind == "new" and not _paid_before(db, org_id)
    return {"key": key, "label": d["label"], "price": price, "credit": credit, "total": max(price - credit, 0),
            "days": days, "kind": kind, "first": first}


def _discount(db: Any, qt: dict, code: Optional[str], now: datetime) -> Optional[dict]:
    """The discount for this quote, or None when no code was typed. A code that cannot be used raises PlanBillingError.
    The amount is always worked out here from the code row."""
    from app.services import site_discount_service as dsc
    if not dsc.normalise_code(code):
        return None
    if not qt["first"]:
        raise PlanBillingError("Codes only work on the first payment of a plan.")
    platform = acc.platform_org_id(db)
    if not platform:
        raise PlanBillingError("That code isn't valid.")
    try:
        return dsc.validate(db, platform, None, code, qt["total"], now, scope="plans")
    except dsc.DiscountError as exc:
        raise PlanBillingError(str(exc))


def preview(db: Any, org_id: str, key: str, code: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    """What the Billing screen shows before the owner presses pay. A bad code is reported, not raised."""
    now = now or _now()
    _org(db, org_id)
    cfg = acc.plan_config(db)
    row = _tier_row(db, org_id)
    qt = quote_for(db, org_id, cfg, key, now, row)
    disc, disc_err = None, None
    if qt["kind"] != "downgrade" and code and str(code).strip():
        try:
            disc = _discount(db, qt, code, now)
        except PlanBillingError as exc:
            disc_err = str(exc)
    return {**qt, "includes": _includes(cfg["tiers"][key]),
            "discount": ({"code": disc["code"], "discount": disc["discount"]} if disc else None), "discount_error": disc_err,
            "amount_due": disc["amount_due"] if disc else qt["total"], "scheduled": qt["kind"] == "downgrade",
            "applies_at": (row or {}).get("paid_until") if qt["kind"] == "downgrade" else None}


# ---------------------------------------------------------------------------
# what the Billing screen shows
# ---------------------------------------------------------------------------

def summary(db: Any, org_id: str, now: Optional[datetime] = None) -> dict:
    """Current plan, the plans for sale (with what choosing each would do) and the latest orders. Raises on a database error."""
    now = now or _now()
    org = _org(db, org_id)
    cfg = acc.plan_config(db)
    row = _tier_row(db, org_id)
    eff = ent.effective_status(row, cfg, now) if row else None
    until = ent._parse(row.get("paid_until")) if row else None
    current = None
    if row:
        d = cfg["tiers"].get(row["key"]) or {}
        pending_key = (row.get("config") or {}).get("pending_key")
        current = {
            "key": row["key"], "label": d.get("label", row["key"]), "status": eff, "source": row.get("source"),
            "paid_until": row.get("paid_until"),
            "days_left": max(int((until - now).total_seconds() // 86400), 0) if until and until > now else 0,
            "monthly_ngn": int(d.get("monthly_ngn") or 0), "includes": _includes(d, (row.get("config") or {}).get("picks")),
            "pending_change": ({"key": pending_key, "label": (cfg["tiers"].get(pending_key) or {}).get("label", pending_key)}
                               if pending_key else None),
        }
    plans = []
    for key, d in cfg["tiers"].items():
        if int(d.get("monthly_ngn") or 0) <= 0:
            continue
        try:
            qt = quote_for(db, org_id, cfg, key, now, row)
        except PlanBillingError:
            continue
        plans.append({"key": key, "label": d["label"], "monthly_ngn": int(d["monthly_ngn"]), "includes": _includes(d),
                      "caps": d.get("caps") or {}, "is_current": bool(row and row["key"] == key and eff in acc.LIVE_STATES),
                      "action": qt["kind"], "amount_due": qt["total"]})
    return {"enforced": bool(org.get("plans_enforced")), "current": current, "plans": plans,
            "billing": {"period_days": cfg["billing"]["period_days"], "grace_days": cfg["billing"]["grace_days"]},
            "orders": orders(db, org_id)}


def orders(db: Any, org_id: str, limit: int = 10) -> list:
    try:
        return _rows(db.table("org_plan_orders")
                     .select("id, plan_key, change_kind, amount_kobo, status, reference, created_at, paid_at")
                     .eq("org_id", org_id).order("created_at", desc=True).limit(limit).execute())
    except Exception as exc:
        logger.warning("account_plan.orders failed org=%s: %s", org_id, exc)
        return []


# ---------------------------------------------------------------------------
# choosing a plan -> an order and a Paystack checkout
# ---------------------------------------------------------------------------

def checkout(db: Any, org_id: str, *, key: str, email: str = "", user_id: Optional[str] = None, code: Optional[str] = None,
             callback_url: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    """Start (or reuse) the payment for choosing `key`. A downgrade only schedules the change and returns {scheduled: True}.
    Otherwise returns {order_id, reference, checkout_url, amount_kobo, reused}."""
    now = now or _now()
    _org(db, org_id)
    cfg = acc.plan_config(db)
    row = _tier_row(db, org_id)
    qt = quote_for(db, org_id, cfg, key, now, row)

    if qt["kind"] == "downgrade":
        config = dict(row.get("config") or {})
        config["pending_key"] = key
        db.table("org_plans").update({"config": config, "updated_at": _iso(now)}).eq("id", row["id"]).eq("org_id", org_id).execute()
        acc._log_event(db, org_id, user_id or "owner", "plan_downgrade_scheduled", {"to": key, "plan_id": row["id"]})
        return {"scheduled": True, "label": qt["label"], "applies_at": row.get("paid_until")}

    secret = _secret()
    if not secret:
        raise PlanBillingError("Online payment is not available right now. Please contact support.")
    disc = _discount(db, qt, code, now)
    amount_ngn = disc["amount_due"] if disc else qt["total"]
    if amount_ngn < MIN_AMOUNT_NGN:
        raise PlanBillingError("There is nothing to pay for this change yet.")
    amount_kobo = int(round(float(amount_ngn) * 100))
    code_id = (disc or {}).get("code_id")

    open_orders = _rows(db.table("org_plan_orders").select("*").eq("org_id", org_id).eq("status", "pending")
                        .order("created_at", desc=True).execute())
    for o in open_orders:
        oq = o.get("quote") or {}
        if (o.get("plan_key") == key and int(o.get("amount_kobo") or 0) == amount_kobo and o.get("change_kind") == qt["kind"]
                and (oq.get("discount") or {}).get("code_id") == code_id and o.get("checkout_url")):
            return {"order_id": o["id"], "reference": o["reference"], "checkout_url": o["checkout_url"],
                    "amount_kobo": amount_kobo, "reused": True}
    for o in open_orders:        # a different plan or amount: the old checkout must not be paid by mistake
        db.table("org_plan_orders").update({"status": "expired", "updated_at": _iso(now)}) \
            .eq("id", o["id"]).eq("org_id", org_id).eq("status", "pending").execute()

    reference = f"{PREFIX}{org_id[:8]}_{uuid.uuid4().hex[:12]}"
    quote = {"key": key, "label": qt["label"], "price": qt["price"], "credit": qt["credit"], "total": qt["total"],
             "days": qt["days"], "kind": qt["kind"], "plan_id": (row or {}).get("id"),
             **({"discount": {k: disc[k] for k in ("code_id", "code", "kind", "value", "discount")},
                 "total_before_discount": qt["total"]} if disc else {})}
    email = (email or "").strip()
    try:
        order = (_rows(db.table("org_plan_orders").insert({
            "org_id": org_id, "plan_key": key, "change_kind": qt["kind"], "amount_kobo": amount_kobo, "quote": quote,
            "reference": reference, "status": "pending", "payer_email": email or None, "created_by": user_id,
            "created_at": _iso(now), "updated_at": _iso(now)}).execute()) or [{}])[0]
    except Exception as exc:
        logger.error("account_plan order insert failed org=%s: %s", org_id, exc)
        raise PlanBillingError("Could not start your payment. Please try again.")
    body = {"email": email or f"org-{org_id[:8]}@example.com", "amount": amount_kobo, "currency": "NGN", "reference": reference,
            "metadata": {"kind": "account_plan", "org_id": org_id, "order_id": order.get("id"), "plan": key}}
    if callback_url:
        body["callback_url"] = callback_url
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(f"{PAYSTACK_API}/transaction/initialize", headers={"Authorization": f"Bearer {secret}"}, json=body)
        data = resp.json()
        if resp.status_code != 200 or not data.get("status"):
            raise ValueError(data.get("message") or "Paystack refused")
        url = (data.get("data") or {}).get("authorization_url")
        if not url:
            raise ValueError("no checkout url")
    except Exception as exc:
        logger.warning("account_plan checkout failed org=%s: %s", org_id, exc)
        try:
            db.table("org_plan_orders").update({"status": "failed", "updated_at": _iso(now)}).eq("id", order.get("id")).eq("org_id", org_id).execute()
        except Exception:
            pass
        raise PlanBillingError("Could not reach Paystack right now. Please try again shortly.")
    try:
        db.table("org_plan_orders").update({"checkout_url": url}).eq("id", order.get("id")).eq("org_id", org_id).execute()
    except Exception:
        pass
    acc._log_event(db, org_id, user_id or "owner", "plan_checkout_started", {"key": key, "kind": qt["kind"], "amount_kobo": amount_kobo})
    return {"order_id": order.get("id"), "reference": reference, "checkout_url": url, "amount_kobo": amount_kobo, "reused": False}


def clear_pending_change(db: Any, org_id: str, actor: str = "owner") -> dict:
    """Cancel a scheduled downgrade (the plan keeps renewing as it is)."""
    row = _tier_row(db, org_id)
    if not row or not (row.get("config") or {}).get("pending_key"):
        raise PlanBillingError("There is no scheduled change.")
    config = dict(row["config"])
    config.pop("pending_key", None)
    db.table("org_plans").update({"config": config, "updated_at": _iso()}).eq("id", row["id"]).eq("org_id", org_id).execute()
    acc._log_event(db, org_id, actor, "plan_downgrade_cancelled", {"plan_id": row["id"]})
    return {"cleared": True}


# ---------------------------------------------------------------------------
# payment confirmed (webhook and the return page both end here)
# ---------------------------------------------------------------------------

def mark_paid(db: Any, reference: str, paid_kobo: int, now: Optional[datetime] = None) -> dict:
    """Apply a paid order exactly once. Safe to call any number of times, from both the webhook and the return page.
    Returns {"applied": bool, "reason": str}."""
    now = now or _now()
    if not reference or not str(reference).startswith(PREFIX):
        return {"applied": False, "reason": "not_a_plan_order"}
    order = _one((db.table("org_plan_orders").select("*").eq("reference", reference).limit(1).execute()).data)
    if not order:
        return {"applied": False, "reason": "unknown_reference"}
    if order["status"] == "paid":
        return {"applied": False, "reason": "already_applied"}
    if int(paid_kobo or 0) < int(order["amount_kobo"]):
        logger.warning("account plan order %s underpaid: paid=%s expected=%s", reference, paid_kobo, order["amount_kobo"])
        return {"applied": False, "reason": "underpaid"}
    previous = order["status"]
    claimed = (db.table("org_plan_orders").update({"status": "paid", "paid_kobo": int(paid_kobo), "paid_at": _iso(now),
                                                   "updated_at": _iso(now)})
               .eq("id", order["id"]).eq("org_id", order["org_id"]).in_("status", ["pending", "expired"]).execute())
    if not claimed.data:
        return {"applied": False, "reason": "already_applied"}        # a parallel call got there first
    try:
        _apply_paid(db, order, previous, now)
    except Exception as exc:
        logger.error("account plan order %s could not be applied: %s", reference, exc)
        try:        # put the order back so the next webhook retry applies it
            db.table("org_plan_orders").update({"status": previous, "paid_at": None, "updated_at": _iso(now)}) \
                .eq("id", order["id"]).eq("org_id", order["org_id"]).execute()
        except Exception:
            pass
        return {"applied": False, "reason": "apply_failed"}
    return {"applied": True, "reason": "late_payment" if previous == "expired" else "ok"}


def _apply_paid(db: Any, order: dict, previous_status: str, now: datetime) -> None:
    org_id = order["org_id"]
    q = order.get("quote") or {}
    key = q.get("key") or order["plan_key"]
    kind = order.get("change_kind")
    days = ent._int(q.get("days"), 30, 1, 366)
    row = _tier_row(db, org_id)
    cur_until = ent._parse(row.get("paid_until")) if row else None
    running = bool(row and row.get("source") == "paid" and cur_until and cur_until > now and row.get("status") == "active")
    # An upgrade or a plain switch starts a fresh period now (an upgrade's unused days were already credited).
    # A renewal starts when the running period ends, so paying early loses no days.
    start = cur_until if (running and kind in ("renewal", "downgrade_renewal")) else now
    end = start + timedelta(days=days)

    config = dict((row or {}).get("config") or {})
    for k in ("change", "pending_key", "pending_picks", "reminded", "discount_code"):
        config.pop(k, None)
    if order.get("payer_email"):
        config["payer_email"] = order["payer_email"]
    fields = {"key": key, "status": "active", "source": "paid", "price_ngn": q.get("price") or 0, "paid_until": _iso(end),
              "grace_until": None, "next_reminder_at": None, "config": config, "updated_at": _iso(now)}
    if row:
        db.table("org_plans").update(fields).eq("id", row["id"]).eq("org_id", org_id).execute()
    else:
        try:
            db.table("org_plans").insert({"org_id": org_id, "kind": "tier", "created_by": order.get("created_by"),
                                          "created_at": _iso(now), **fields}).execute()
        except Exception:        # a plan row appeared in between (unique index): update that one instead
            row = _tier_row(db, org_id)
            if not row:
                raise
            db.table("org_plans").update(fields).eq("id", row["id"]).eq("org_id", org_id).execute()

    # Everything below is best-effort: the plan is already on, none of it may fail the payment.
    acc._log_event(db, org_id, "system", "plan_paid", {"key": key, "kind": kind, "until": _iso(end), "amount_kobo": order.get("amount_kobo"),
                                                       "order_id": order.get("id"), "late": previous_status == "expired"})
    try:
        from app.services import site_discount_service as dsc
        platform = acc.platform_org_id(db)
        if platform and (q.get("discount") or {}).get("code_id"):
            dsc.record_redemption(db, platform, {"id": order.get("id"), "quote": q, "builder_id": None})
    except Exception as exc:
        logger.warning("account_plan: redemption not recorded order=%s: %s", order.get("id"), exc)
    _sync_org_status(db, org_id, "active")
    label = q.get("label") or key
    text = f"Payment received. Your {label} plan is active until {sab._pretty(end)}. Thank you."
    _notify(db, org_id, "Plan payment received", text, "plan_paid", order.get("payer_email"), "Your Opsra plan")


# ---------------------------------------------------------------------------
# return page
# ---------------------------------------------------------------------------

def verify(db: Any, org_id: str, reference: str) -> dict:
    """The owner came back from Paystack: ask Paystack, and apply the plan if it was paid. Own-org orders only."""
    if not reference or not str(reference).startswith(PREFIX):
        raise PlanBillingError("That payment reference is not valid.")
    order = _one((db.table("org_plan_orders").select("id, status, org_id").eq("reference", reference).eq("org_id", org_id)
                  .limit(1).execute()).data)
    if not order:
        raise PlanBillingError("We could not find that payment.")
    if order["status"] == "paid":
        return {"status": "paid"}
    secret = _secret()
    if not secret:
        return {"status": order["status"]}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{PAYSTACK_API}/transaction/verify/{reference}", headers={"Authorization": f"Bearer {secret}"})
        data = (resp.json() or {}).get("data") or {}
    except Exception as exc:
        logger.warning("account_plan verify failed ref=%s: %s", reference, exc)
        return {"status": "pending"}
    if data.get("status") == "success":
        res = mark_paid(db, reference, int(data.get("amount") or 0))
        return {"status": "paid" if res["reason"] in ("ok", "late_payment", "already_applied") else "pending"}
    if data.get("status") in ("failed", "abandoned"):
        return {"status": "failed"}
    return {"status": "pending"}


# ---------------------------------------------------------------------------
# messages and the organisation status
# ---------------------------------------------------------------------------

def _notify(db: Any, org_id: str, title: str, text: str, ntype: str, email: Optional[str], subject: str) -> bool:
    """Email (if there is an address) plus an in-app note to the managers. True if at least one landed."""
    delivered = False
    if email:
        delivered = sab._send_email(email, subject, text) or delivered
    try:
        from app.services import funnel_service
        funnel_service.notify_managers(db, org_id, title, text, ntype, None)
        delivered = True
    except Exception as exc:  # S14
        logger.warning("account_plan: in-app note failed org=%s: %s", org_id, exc)
    return delivered


def _sync_org_status(db: Any, org_id: str, target: str) -> None:
    """Keep organisations.subscription_status in step for a business that has been switched on. Existing values only; a
    suspended business and a business not yet switched on are never touched."""
    try:
        org = _one((db.table("organisations").select("id, subscription_status, plans_enforced").eq("id", org_id).limit(1).execute()).data)
        if not org or org.get("plans_enforced") is not True:
            return
        cur = org.get("subscription_status")
        if cur not in ("active", "grace", "read_only") or cur == target:
            return
        db.table("organisations").update({"subscription_status": target}).eq("id", org_id).eq("subscription_status", cur).execute()
    except Exception as exc:  # S14
        logger.warning("account_plan: status sync failed org=%s: %s", org_id, exc)


# ---------------------------------------------------------------------------
# the daily sweep
# ---------------------------------------------------------------------------

def run_cycle(db: Any, now: datetime) -> dict:
    """Daily. active -> grace at paid_until -> paused when the grace days are over; reminders before the end.
    Each row is isolated (S14)."""
    result = {"checked": 0, "to_grace": 0, "paused": 0, "reminders": 0, "failed": 0}
    try:
        rows = _rows(db.table("org_plans").select("*").eq("kind", "tier").in_("status", ["active", "grace"]).eq("source", "paid").execute())
    except Exception as exc:  # S14
        logger.warning("account_plan cycle: list failed: %s", exc)
        result["failed"] += 1
        return result
    try:
        cfg = acc.plan_config(db)
    except Exception as exc:  # S14
        logger.warning("account_plan cycle: config failed: %s", exc)
        result["failed"] += 1
        return result
    for row in rows:
        result["checked"] += 1
        try:
            org = _one((db.table("organisations").select("id, subscription_status").eq("id", row["org_id"]).limit(1).execute()).data) or {}
            if (org.get("subscription_status") or "") in ("suspended", "site_workspace"):
                continue
            _process(db, row, cfg, now, result)
        except Exception as exc:  # S14
            result["failed"] += 1
            logger.warning("account_plan cycle: row failed plan=%s: %s", row.get("id"), exc)
    return result


def _process(db: Any, row: dict, cfg: dict, now: datetime, result: dict) -> None:
    org_id = row["org_id"]
    paid_until = ent._parse(row.get("paid_until"))
    if paid_until is None:
        return
    grace_end = ent._parse(row.get("grace_until")) or (paid_until + timedelta(days=cfg["billing"]["grace_days"]))
    config = dict(row.get("config") or {})
    d = cfg["tiers"].get(row["key"]) or {}
    label = d.get("label") or row["key"]
    next_key = config.get("pending_key") or row["key"]
    price = sab._money((cfg["tiers"].get(next_key) or {}).get("monthly_ngn") or row.get("price_ngn") or 0)
    email = config.get("payer_email")

    if now > grace_end:
        res = (db.table("org_plans").update({"status": "paused", "updated_at": ent._iso(now)})
               .eq("id", row["id"]).eq("org_id", org_id).in_("status", ["active", "grace"]).execute())
        if res.data:
            result["paused"] += 1
            acc._log_event(db, org_id, "system", "plan_paused_unpaid", {"plan_id": row["id"]})
            _sync_org_status(db, org_id, "read_only")
            _notify(db, org_id, "Plan paused",
                    f"Your {label} plan is paused because it wasn't renewed. Renew ({price}) in Billing to switch it back on. "
                    f"Your data is safe.", "plan_paused", email, "Your Opsra plan is paused")
        return
    if now > paid_until:
        if row.get("status") == "active":
            res = (db.table("org_plans").update({"status": "grace", "grace_until": ent._iso(grace_end), "updated_at": ent._iso(now)})
                   .eq("id", row["id"]).eq("org_id", org_id).eq("status", "active").execute())
            if res.data:
                result["to_grace"] += 1
                acc._log_event(db, org_id, "system", "plan_grace", {"plan_id": row["id"]})
                _sync_org_status(db, org_id, "grace")
                _notify(db, org_id, "Plan ended",
                        f"Your {label} plan ended on {sab._pretty(paid_until)}. Everything stays on until {sab._pretty(grace_end)}. "
                        f"Renew ({price}) in Billing to keep it.", "plan_grace", email, "Your Opsra plan has ended")
        return
    days_left = (paid_until - now).total_seconds() / 86400.0
    reminded = config.get("reminded") if isinstance(config.get("reminded"), dict) else {}
    sent = list(reminded.get("days") or []) if reminded.get("for") == ent._iso(paid_until) else []
    due = [rd for rd in sorted(cfg["billing"]["reminder_days"], reverse=True) if days_left <= rd and rd not in sent]
    if not due:
        return
    ok = _notify(db, org_id, "Plan ending soon",
                 f"Your {label} plan ends on {sab._pretty(paid_until)}. Renew for {price} in Billing to keep it going.",
                 "plan_reminder", email, "Your Opsra plan ends soon")
    if ok:
        config["reminded"] = {"for": ent._iso(paid_until), "days": sorted(set(sent + due))}
        db.table("org_plans").update({"config": config, "updated_at": ent._iso(now)}).eq("id", row["id"]).eq("org_id", org_id).execute()
        result["reminders"] += 1
