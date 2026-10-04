"""
app/services/site_premium_billing_service.py
---------------------------------------------
SITE-PREMIUM P5 - what a builder pays for a Premium site, and what happens to that money.

Prices (all editable in Settings -> Pricing -> Premium, stored in site_builder_settings.pricing["premium"]):
  design_fee_ngn   paid BEFORE the design is made (default 20,000). Covers the first design and the included
                   redesigns. It is its own order (kind 'premium_design'), not part of the go-live order.
  total_fee_ngn    the whole Premium price (default 30,000). What is still unpaid of it is added to the go-live
                   order as one line, 'Premium design balance' (total minus the design fee already paid).
  redesign_fee_ngn one extra new design after the included ones are used, or after go-live (default 30,000).
                   Its own order (kind 'premium_redesign'); each payment gives one credit.

Money rules
  * Pay first. Payment starts the design at once (a worker makes it, as for staff).
  * A failed attempt costs the builder nothing: they can try again free, up to MAX_ATTEMPTS failed designs.
    Failures on our side (no AI credit, queue down) never count toward that.
  * If every attempt fails, the design fee is refunded. The refund follows the existing Opsra way: a task for staff
    to refund by hand in Paystack, then 'Record refund' (site_ops_service.record_refund). It is opened
    automatically after the last failed attempt, or by the builder pressing 'Get my money back'.
  * Not refundable once a design has passed the checks and been made (a ready design exists).
  * A Premium site with no design-fee order has no balance at go-live (nothing was prepaid), unless staff switch
    sites.premium_charge_at_golive on: then the whole Premium price (total_fee_ngn) is added at go-live.

Nothing here trusts the browser for money: prices are read from settings on the server every time.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import site_premium_generation_service as gen
from app.services.site_ops_service import Conflict, NotFound, SiteOpsError, ValidationFailed

logger = logging.getLogger(__name__)

KIND_DESIGN = "premium_design"
KIND_REDESIGN = "premium_redesign"
PREMIUM_KINDS = (KIND_DESIGN, KIND_REDESIGN)
PAID = "live"                      # same word the care-plan orders use once paid and applied
DEFAULTS = {"design_fee_ngn": 20000, "total_fee_ngn": 30000, "redesign_fee_ngn": 30000}
MAX_ATTEMPTS = 3
LIVE_STATUSES = ("live", "renewal_due", "lapsed")
CREDIT_USED_EVENT = "premium_redesign_used"


class PremiumBillingBlocked(SiteOpsError):
    status_code = 422
    code = "VALIDATION_ERROR"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(data):
    return (data or [None])[0] if isinstance(data, list) else data


def _money(n) -> str:
    return f"₦{float(n):,.0f}"


def get_config(settings: Optional[dict]) -> dict:
    raw = (((settings or {}).get("pricing") or {}).get("premium")) or {}
    cfg = dict(DEFAULTS)
    for key in DEFAULTS:
        try:
            if raw.get(key) is not None and float(raw[key]) >= 0:
                cfg[key] = int(float(raw[key]))
        except (TypeError, ValueError):
            pass
    cfg["total_fee_ngn"] = max(cfg["total_fee_ngn"], cfg["design_fee_ngn"])   # the whole price is never less than the first part
    return cfg


def _settings(db: Any, org_id: str) -> dict:
    return gen.settings_for(db, org_id)


# ------------------------------------------------------------------ orders and events

def _orders(db: Any, org_id: str, site_id: str, kind: str, status: Optional[str] = None) -> list[dict]:
    q = db.table("site_orders").select("*").eq("org_id", org_id).eq("site_id", site_id).eq("kind", kind)
    if status:
        q = q.eq("status", status)
    rows = q.execute().data or []
    return sorted(rows, key=lambda o: str(o.get("created_at") or ""), reverse=True)


def paid_design_order(db: Any, org_id: str, site_id: str) -> Optional[dict]:
    rows = _orders(db, org_id, site_id, KIND_DESIGN, PAID)
    return rows[0] if rows else None


def design_fee_paid(db: Any, org_id: str, site_id: str) -> int:
    return int(sum(float(o.get("amount") or 0) for o in _orders(db, org_id, site_id, KIND_DESIGN, PAID)))


def go_live_balance(db: Any, org_id: str, site_id: str) -> dict:
    """What is still owed of the Premium price, to add to the go-live order.
    A design fee paid here -> the total minus what was paid. No fee paid -> 0, unless staff switched 'charge at go-live'
    on for a Premium site that was made before payment existed: then the whole Premium price is owed."""
    paid = design_fee_paid(db, org_id, site_id)
    total = get_config(_settings(db, org_id))["total_fee_ngn"]
    if paid > 0:
        return {"balance": max(total - paid, 0), "paid": paid, "total": total}
    site = _one(db.table("sites").select("id, tier, premium_charge_at_golive").eq("id", site_id).eq("org_id", org_id)
                .limit(1).execute().data)
    if site and site.get("premium_charge_at_golive") and (site.get("tier") or "standard") == "premium":
        return {"balance": total, "paid": 0, "total": total}
    return {"balance": 0, "paid": 0, "total": 0}


def set_charge_at_golive(db: Any, org_id: str, site: dict, enabled: bool, actor: str) -> dict:
    """Staff switch for a Premium site made before payment existed: charge the whole Premium price at go-live."""
    if (site.get("tier") or "standard") != "premium":
        raise ValidationFailed("Only a site with a Premium design can be charged for Premium.")
    if enabled and design_fee_paid(db, org_id, site["id"]) > 0:
        raise ValidationFailed("This site already paid a Premium design fee, so its balance is charged automatically.")
    db.table("sites").update({"premium_charge_at_golive": bool(enabled), "updated_at": _now_iso()}) \
        .eq("id", site["id"]).eq("org_id", org_id).execute()
    _event(db, org_id, site["id"], "premium_charge_at_golive_on" if enabled else "premium_charge_at_golive_off", {}, None, actor=actor)
    return {"charge_at_golive": bool(enabled), **go_live_balance(db, org_id, site["id"])}


def _event(db: Any, org_id: str, site_id: str, event: str, detail: Optional[dict] = None, order_id: Optional[str] = None,
           actor: str = "system") -> None:
    try:
        db.table("site_events").insert({"org_id": org_id, "site_id": site_id, "order_id": order_id, "actor": actor,
                                        "event": event, "detail": detail or {}, "created_at": _now_iso()}).execute()
    except Exception as exc:  # S14
        logger.warning("site_premium_billing: event insert failed %s: %s", event, exc)


def _tell_builder(db: Any, org_id: str, order: dict, text: str) -> None:
    try:
        from app.services import site_order_service
        site_order_service._message_builder(db, org_id, order, text)
    except Exception as exc:  # S14
        logger.warning("site_premium_billing: builder message failed order=%s: %s", order.get("id"), exc)


def _tell_managers(db: Any, org_id: str, title: str, body: str, event: str) -> None:
    try:
        from app.services import funnel_service
        funnel_service.notify_managers(db, org_id, title, body, event, None)
    except Exception as exc:  # S14
        logger.warning("site_premium_billing: manager notify failed: %s", exc)


def _load_site(db: Any, org_id: str, site_id: str, builder_id: Optional[str] = None) -> dict:
    q = db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).is_("deleted_at", "null")
    if builder_id:
        q = q.eq("builder_id", builder_id)
    site = _one(q.limit(1).execute().data)
    if not site:
        raise NotFound("Site not found")
    return site


# ------------------------------------------------------------------ attempts

def _design_rows(db: Any, org_id: str, site_id: str) -> list[dict]:
    return db.table("site_designs").select("id, kind, status, staged, checks, created_at").eq("org_id", org_id) \
        .eq("site_id", site_id).execute().data or []


def failed_attempts(db: Any, org_id: str, site_id: str, since: Optional[str]) -> int:
    """Failed first-design attempts since the fee was paid. Failures on our side (stage 'service') are not counted."""
    n = 0
    for r in _design_rows(db, org_id, site_id):
        if r.get("kind") != "generate" or r.get("status") != "failed":
            continue
        if since and str(r.get("created_at") or "") < str(since):
            continue
        if ((r.get("checks") or {}).get("stage")) == "service":
            continue
        n += 1
    return n


def _has_made_design(db: Any, org_id: str, site_id: str) -> bool:
    return any(r.get("status") == "ready" for r in _design_rows(db, org_id, site_id))


def _in_flight(db: Any, org_id: str, site_id: str) -> bool:
    return any(r.get("status") in ("generating", "checking") for r in _design_rows(db, org_id, site_id))


# ------------------------------------------------------------------ what the builder sees

def offer(db: Any, org_id: str, site: dict) -> dict:
    """The 'Make it Premium' card for a Standard site before go-live. Never raises for a normal site."""
    settings = _settings(db, org_id)
    cfg = get_config(settings)
    base = {"available": False, "state": "unavailable", "design_fee": cfg["design_fee_ngn"], "total": cfg["total_fee_ngn"],
            "golive_balance": max(cfg["total_fee_ngn"] - cfg["design_fee_ngn"], 0), "redesigns_included": None}
    if not settings.get("premium_enabled") or cfg["design_fee_ngn"] <= 0:
        return base
    if (site.get("tier") or "standard") == "premium":
        return {**base, "state": "premium"}
    if (site.get("status") or "") in LIVE_STATUSES:
        return {**base, "state": "live", "reason": "Premium is chosen before your site goes live."}
    if not (site.get("content") or {}):
        return {**base, "state": "no_content", "reason": "Finish your Standard preview first. Premium is designed from it."}
    gen.sweep_stale(db, org_id, site["id"])
    inc = settings.get("site_premium_redesigns_included")
    base = {**base, "available": True, "redesigns_included": 2 if inc is None else int(inc)}
    refunds = _orders(db, org_id, site["id"], KIND_DESIGN, "refund_pending")
    paid = paid_design_order(db, org_id, site["id"])
    if refunds and not paid:
        return {**base, "state": "refund_pending", "refund_amount": float(refunds[0].get("refund_amount") or refunds[0].get("amount") or 0)}
    if paid:
        if _in_flight(db, org_id, site["id"]):
            return {**base, "state": "designing"}
        n = failed_attempts(db, org_id, site["id"], paid.get("created_at"))
        return {**base, "state": "failed", "attempts": n, "retries_left": max(MAX_ATTEMPTS - n, 0),
                "can_retry": n < MAX_ATTEMPTS, "can_refund": not _has_made_design(db, org_id, site["id"]),
                "refund_amount": float(paid.get("amount") or 0)}
    pending = [o for o in _orders(db, org_id, site["id"], KIND_DESIGN, "pending_payment") if o.get("payment_link_id")]
    url = None
    if pending:
        link = _one(db.table("payment_links").select("checkout_url").eq("id", pending[0]["payment_link_id"]).eq("org_id", org_id)
                    .limit(1).execute().data)
        url = (link or {}).get("checkout_url")
    return {**base, "state": "awaiting_payment" if url else "can_buy", "checkout_url": url}


# ------------------------------------------------------------------ buying

def create_checkout(db: Any, org_id: str, builder: dict, site_id: str, what: str) -> dict:
    """what: 'design' | 'redesign'. Returns {checkout_url, amount, kind, reused}. Raises PremiumBillingBlocked."""
    from app.services import paystack_storefront_service
    if what not in ("design", "redesign"):
        raise PremiumBillingBlocked("Unknown purchase.")
    site = _load_site(db, org_id, site_id, builder.get("id"))
    if not builder.get("lead_id"):
        raise PremiumBillingBlocked("This builder has no linked CRM lead yet, so a payment link can't be created.")
    cfg = get_config(_settings(db, org_id))
    if what == "design":
        view = offer(db, org_id, site)
        if not view["available"] or view["state"] not in ("can_buy", "awaiting_payment"):
            raise PremiumBillingBlocked(view.get("reason") or "Premium is not available for this site right now.")
        kind, amount = KIND_DESIGN, cfg["design_fee_ngn"]
    else:
        if (site.get("tier") or "standard") != "premium":
            raise PremiumBillingBlocked("A new design can be bought for a site that already has a Premium design.")
        from app.services import site_premium_history as hist
        status = hist.redesign_status(db, org_id, site)
        if status["allowed"]:
            raise PremiumBillingBlocked("You can still make a new design without paying.")
        kind, amount = KIND_REDESIGN, cfg["redesign_fee_ngn"]
    if amount <= 0:
        raise PremiumBillingBlocked("This isn't available right now.")

    for o in _orders(db, org_id, site["id"], kind, "pending_payment"):          # reuse an open link for the same price
        if o.get("payment_link_id") and float(o.get("amount") or 0) == float(amount):
            link = _one(db.table("payment_links").select("checkout_url").eq("id", o["payment_link_id"]).eq("org_id", org_id)
                        .limit(1).execute().data)
            if link and link.get("checkout_url"):
                return {"checkout_url": link["checkout_url"], "amount": amount, "kind": kind, "reused": True, "order": o}
    try:
        link = paystack_storefront_service.generate_payment_link(
            db=db, org_id=org_id, lead_id=builder["lead_id"], amount=amount, payment_type="full", currency="NGN",
            trigger_stage=None, target_stage_on_paid=None, created_by=None)
    except paystack_storefront_service.PaystackLinkError as exc:
        raise PremiumBillingBlocked(str(exc))
    try:                                                    # rough profit: price minus the gateway's cut
        from app.services import pricing_service
        gw = (_settings(db, org_id).get("pricing") or {}).get("gateway") or {}
        profit = round(amount - float(pricing_service._gateway_fee(amount, gw)), 2)
    except Exception:
        profit = float(amount)
    now = _now_iso()
    row = {"org_id": org_id, "site_id": site["id"], "builder_id": builder["id"], "lead_id": builder["lead_id"],
           "kind": kind, "route": "standard", "domain": None, "backup_domain": None,
           "quote": {"kind": kind, "price": amount, "total_fee": cfg["total_fee_ngn"]}, "amount": amount, "cost_snapshot": {},
           "expected_profit": profit, "payment_link_id": link.get("payment_link_id"), "payment_reference": link["reference"],
           "status": "pending_payment", "approval_required": False, "created_at": now, "updated_at": now}
    order = _one(db.table("site_orders").insert(row).execute().data) or row
    _event(db, org_id, site["id"], f"{kind}_order_created", {"amount": amount}, order.get("id"), actor=f"builder:{builder['id']}")
    return {"checkout_url": link["checkout_url"], "amount": amount, "kind": kind, "reused": False, "order": order}


# ------------------------------------------------------------------ starting the design

def _queue(db: Any, org_id: str, row: dict) -> None:
    try:
        from app.workers.site_premium_worker import run_premium_generation
        run_premium_generation.apply_async(args=[row["id"]], retry=False)
    except Exception as exc:  # S14 - the queue is down: never leave the site blocked, and never count it as an attempt
        logger.warning("site_premium_billing: could not queue design=%s: %s", row["id"], exc)
        db.table("site_designs").update({"status": "failed", "checks": {"stage": "service", "outcome": "fallback_standard",
                                         "errors": ["The design could not be queued."]}}).eq("id", row["id"]).eq("org_id", org_id).execute()
        raise PremiumBillingBlocked("The design service is busy. Please try again in a few minutes.")


def _begin(db: Any, org_id: str, site: dict, builder_id: str) -> dict:
    """Start and queue one design. Raises SiteOpsError subclasses with a plain message."""
    try:
        row = gen.start_generation(db, org_id, site, f"builder:{builder_id}")
    except gen.CapReached as exc:
        if "paused" in str(exc):
            gen.alert_cost_cap(db, org_id, site["id"])
        raise PremiumBillingBlocked(str(exc))
    _queue(db, org_id, row)
    _event(db, org_id, site["id"], "premium_generation_started", {"design_id": row["id"], "version": row["version"], "paid": True},
           actor=f"builder:{builder_id}")
    return row


def retry(db: Any, org_id: str, builder: dict, site_id: str) -> dict:
    site = _load_site(db, org_id, site_id, builder.get("id"))
    paid = paid_design_order(db, org_id, site_id)
    if not paid or (site.get("tier") or "standard") == "premium":
        raise PremiumBillingBlocked("There is nothing to try again.")
    n = failed_attempts(db, org_id, site_id, paid.get("created_at"))
    if n >= MAX_ATTEMPTS:
        raise PremiumBillingBlocked("The design could not be made after several tries. You can get your money back instead.")
    return _begin(db, org_id, site, builder["id"])


# ------------------------------------------------------------------ payment confirmed (called from site_order_service)

def on_paid(db: Any, org_id: str, order: dict, now: Optional[datetime] = None) -> None:
    """Apply a paid Premium order. S14: the caller wraps this, and the payment is already recorded either way."""
    site_id = order.get("site_id")
    if order.get("kind") == KIND_REDESIGN:
        _event(db, org_id, site_id, "premium_redesign_paid", {"amount": order.get("amount")}, order.get("id"))
        _tell_builder(db, org_id, order, "Payment received. You can now press 'Try another design' on your site.")
        return
    try:
        site = _load_site(db, org_id, site_id)
        _begin(db, org_id, site, order["builder_id"])
        _tell_builder(db, org_id, order, "Payment received. Your Premium design is being made now. It takes a few minutes, "
                                          "and you can follow it on your site page.")
    except Exception as exc:  # S14 - paid, but the design could not start right now: staff are told, the builder can press retry
        logger.warning("site_premium_billing: could not start design after payment order=%s: %s", order.get("id"), exc)
        _event(db, org_id, site_id, "premium_start_failed", {"reason": str(exc)[:300]}, order.get("id"))
        _tell_managers(db, org_id, "Premium design paid but not started",
                       f"{_money(order.get('amount') or 0)} was received but the design could not start ({str(exc)[:120]}). "
                       "The builder can press Try again on their site page.", "premium_start_failed")
        _tell_builder(db, org_id, order, "Payment received. Your Premium design will start shortly. If it hasn't started "
                                          "in a few minutes, open your site page and press Try again.")


# ------------------------------------------------------------------ refunds

def _open_refund(db: Any, org_id: str, order: dict, reason: str, actor: str) -> dict:
    now = _now_iso()
    claim = (db.table("site_orders").update({"status": "refund_pending", "refund_amount": float(order.get("amount") or 0),
                                             "rejected_reason": reason[:1000], "updated_at": now})
             .eq("id", order["id"]).eq("org_id", org_id).eq("status", PAID).execute())
    if not claim.data:
        raise Conflict("A refund is already being handled for this order.")
    order = {**order, **(_one(claim.data) or {}), "status": "refund_pending", "refund_amount": float(order.get("amount") or 0)}
    amount = float(order["refund_amount"])
    try:
        db.table("tasks").insert({
            "org_id": org_id, "title": f"Refund {_money(amount)} — Premium design fee",
            "description": (f"Refund by hand in Paystack (payment reference {order.get('payment_reference')}). "
                            "The Premium design could not be made. Then open Sites → Orders and click 'Record refund'."),
            "task_type": "refund", "source_module": "site_orders", "source_record_id": order["id"],
            "priority": "high", "status": "pending", "created_at": now, "updated_at": now, "created_by": None}).execute()
    except Exception as exc:  # S14
        logger.warning("site_premium_billing: refund task failed order=%s: %s", order["id"], exc)
    _event(db, org_id, order.get("site_id"), "premium_fee_refund_requested", {"refund_amount": amount, "reason": reason[:200]},
           order["id"], actor=actor)
    _tell_builder(db, org_id, order, f"We're sorry we couldn't make your Premium design. A refund of {_money(amount)} is on its way.")
    _tell_managers(db, org_id, f"Refund needed: {_money(amount)} Premium design fee", reason[:200], "premium_fee_refund")
    return order


def request_refund(db: Any, org_id: str, builder: dict, site_id: str) -> dict:
    """The builder asks for the design fee back. Only while no design has been made."""
    site = _load_site(db, org_id, site_id, builder.get("id"))
    paid = paid_design_order(db, org_id, site_id)
    if not paid or (site.get("tier") or "standard") == "premium":
        raise PremiumBillingBlocked("There is no design fee to return for this site.")
    if _has_made_design(db, org_id, site_id):
        raise PremiumBillingBlocked("A design has already been made for you, so the fee can't be returned.")
    if _in_flight(db, org_id, site_id):
        raise PremiumBillingBlocked("Your design is being made right now. Please wait for it to finish.")
    return _open_refund(db, org_id, paid, "The builder asked for the fee back after the design could not be made.",
                        f"builder:{builder['id']}")


def after_failure(db: Any, org_id: str, design: dict) -> None:
    """Called when a first design fails. When the allowed attempts are used up, open the refund. S14: never raises."""
    try:
        if design.get("kind") != "generate" or ((design.get("checks") or {}).get("stage")) == "service":
            return
        site_id = design["site_id"]
        paid = paid_design_order(db, org_id, site_id)
        if not paid or _has_made_design(db, org_id, site_id):
            return
        if failed_attempts(db, org_id, site_id, paid.get("created_at")) >= MAX_ATTEMPTS:
            _open_refund(db, org_id, paid, f"All {MAX_ATTEMPTS} design attempts failed.", "system")
    except Exception as exc:  # S14
        logger.warning("site_premium_billing: after_failure failed design=%s: %s", design.get("id"), exc)


# ------------------------------------------------------------------ paid redesign credits

def redesign_credits(db: Any, org_id: str, site_id: str) -> dict:
    paid = len(_orders(db, org_id, site_id, KIND_REDESIGN, PAID))
    events = db.table("site_events").select("id, detail").eq("org_id", org_id).eq("site_id", site_id) \
        .eq("event", CREDIT_USED_EVENT).execute().data or []
    used = sum(1 for e in events if (e.get("detail") or {}).get("paid_credit"))
    return {"paid": paid, "used": used, "available": max(paid - used, 0)}


def uses_paid_credit(db: Any, org_id: str, site: dict) -> bool:
    """True when the redesign being finished is covered by a paid credit rather than a free included one."""
    from app.services import site_premium_history as hist
    free_ok = hist.free_available(db, org_id, site, _settings(db, org_id))["free_ok"]
    return (not free_ok) and redesign_credits(db, org_id, site["id"])["available"] > 0
