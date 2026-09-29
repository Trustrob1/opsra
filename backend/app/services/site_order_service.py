"""
app/services/site_order_service.py
------------------------------------
SITE-3 part 2 — the hosting checkout flow (spec §11.3, §11.4, §11.6, §11.7).

create_checkout(): the builder's confirmed choice (route, domain + backup,
legal-owner details, accepted terms — all already validated by
models.sites.CheckoutRequest) becomes a Paystack payment link plus a
`site_orders` row in `pending_payment` (spec §11.3). Price is always
RE-DERIVED server-side via pricing_service.quote() — the client never gets
to say how much its own checkout costs — mirroring spec §18 "Money: nothing
is bought without a confirmed Paystack payment" and the same
never-trust-the-client-amount rule PAY-LINK-1 already applies to CRM deal
payments.

on_payment_confirmed(): called from routers/webhooks.py's
receive_paystack_storefront_webhook, directly after
paystack_storefront_service.mark_paid(), inside its own try/except (S14).
Mirrors funnel_service.on_payment_confirmed() exactly: look up by
`payment_reference`, no-op (return False) if it isn't a site order,
idempotent claim via a conditional UPDATE (`eq("status", "pending_payment")`)
so a duplicate webhook delivery can only ever process an order once.

is_site_order_reference(): D6 — lets paystack_storefront_service.mark_paid
suppress its own generic "payment received" WhatsApp message for site
orders, since this module sends its own (spec §11.6). Mirrors
funnel_service.is_funnel_reference() exactly.

create_hosting_job(): spec §11.4 step 3 — the 6-step checklist, the SLA
clock and a task-board row. Kept as its own public, idempotent function
(not inlined into on_payment_confirmed) so the future staff "Approve order"
route (SITE-3 dashboard tabs, not built this session) can call it too, for
orgs where approval_required delays fulfilment past the payment moment.

Note: site_orders has no paid_at column (checked against the live schema
before writing this file — see 00_START_HERE.md's "before editing any
existing file" rule applied here to a new file's assumptions). sla_due_at
is computed from the moment on_payment_confirmed runs (i.e. immediately
after the webhook fires), which is what spec §11.4's "paid time + 24h"
means in practice — Paystack webhooks land within seconds of payment.

S14 boundary: create_checkout raises typed errors (SiteOrderError
subclasses, plus pricing_service/paystack_storefront_service's own typed
errors) that the router converts to a 4xx response — this IS a synchronous,
user-facing action, so it's allowed to fail loudly. Everything reachable
from the webhook (on_payment_confirmed and everything it calls) never
raises past its own boundary — each side-effect is individually
try/excepted, exactly like paystack_storefront_service.mark_paid.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SLA_HOURS = 24

# spec §11.4 step 3 — the exact 6-step checklist, in order.
_HOSTING_CHECKLIST = [
    {"key": "recheck_domain", "label": "Re-check the domain. If it's taken, use the backup.", "done": False},
    {"key": "register_domain", "label": "Register the domain at QServers in the client's name.", "done": False},
    {"key": "buy_hosting", "label": "Buy the hosting package (the configured bundle).", "done": False},
    {"key": "upload_site", "label": "Download the export zip and upload it to public_html.", "done": False},
    {"key": "enable_ssl", "label": "Turn on SSL.", "done": False},
    {"key": "paste_url", "label": "Paste the live URL into Opsra.", "done": False},
]


class SiteOrderError(Exception):
    """Base for checkout errors — routers/builder_portal.py maps to a 4xx response."""


class SiteNotFound(SiteOrderError):
    pass


class CheckoutBlocked(SiteOrderError):
    """A precondition isn't met (no linked CRM lead, Paystack storefront not connected, ...)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# create_checkout — spec §11.3
# ---------------------------------------------------------------------------

def create_checkout(db: Any, org_id: str, builder: dict, payload) -> dict:
    """
    payload: models.sites.CheckoutRequest (already validated: route, domain,
    backup_domain != domain, legal_owner, accepted_terms == True).

    Returns {"checkout_url", "reference", "order_id", "amount"}.
    Raises SiteOrderError / pricing_service.PricingError /
    paystack_storefront_service.PaystackLinkError — caller maps to 4xx.
    """
    from app.services import pricing_service, paystack_storefront_service

    site = _one((db.table("sites").select("*").eq("id", payload.site_id)
                 .eq("org_id", org_id).eq("builder_id", builder["id"])
                 .is_("deleted_at", "null").limit(1).execute()).data)
    if not site:
        raise SiteNotFound("Site not found")

    lead_id = builder.get("lead_id")
    if not lead_id:
        raise CheckoutBlocked("This builder has no linked CRM lead yet — checkout can't be started.")

    settings = pricing_service.get_settings(db, org_id)

    # Money: the price is always re-derived here, never trusted from the client (spec §18).
    quoted = pricing_service.quote(db, org_id, payload.domain, payload.route, "initial", settings=settings)
    amount = quoted["price"]["total"]

    # spec §11.7 — "their FIRST order is created" is decided before the insert below.
    is_first_order = not ((db.table("site_orders").select("id").eq("org_id", org_id)
                            .eq("builder_id", builder["id"]).limit(1).execute()).data or [])

    try:
        link = paystack_storefront_service.generate_payment_link(
            db=db, org_id=org_id, lead_id=lead_id, amount=amount,
            payment_type="full", currency="NGN",
            trigger_stage=None, target_stage_on_paid=None, created_by=None,
        )
    except paystack_storefront_service.PaystackLinkError as exc:
        raise CheckoutBlocked(str(exc))

    legal_owner = payload.legal_owner.model_dump(mode="json")
    now = _now_iso()
    order_row = {
        "org_id": org_id,
        "site_id": site["id"],
        "builder_id": builder["id"],
        "lead_id": lead_id,
        "kind": "initial",
        "route": payload.route,
        "domain": quoted["domain"],
        "backup_domain": payload.backup_domain.strip().lower(),
        "quote": quoted,
        "amount": amount,
        "cost_snapshot": quoted["cost"],
        "expected_profit": quoted["profit"],
        "payment_link_id": link.get("payment_link_id"),
        "payment_reference": link["reference"],
        "status": "pending_payment",
        "approval_required": bool(settings.get("approval_required")),
        "legal_owner": legal_owner,
        "created_at": now,
        "updated_at": now,
    }
    insert_res = db.table("site_orders").insert(order_row).execute()
    order = _one(insert_res.data) or order_row

    # Keep the site's own legal_owner in step — needed later for domain registration.
    try:
        db.table("sites").update({"legal_owner": legal_owner, "updated_at": now}) \
            .eq("id", site["id"]).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.warning("create_checkout: site legal_owner update failed site=%s: %s", site["id"], exc)

    # spec §11.7 — the builder's FIRST order moves their CRM lead to proposal_sent
    # (needs meeting_done switched off in the org's pipeline_stages — Trust's own
    # config, nothing to check here; move_stage validates the transition itself).
    if is_first_order:
        try:
            from app.services import lead_service
            lead_service.move_stage(db=db, org_id=org_id, lead_id=lead_id,
                                     new_stage="proposal_sent", user_id=None, bypass_payment_guard=True)
        except Exception as exc:
            logger.warning("create_checkout: lead stage move failed lead=%s: %s", lead_id, exc)

    return {
        "checkout_url": link["checkout_url"],
        "reference": link["reference"],
        "order_id": order.get("id"),
        "amount": amount,
    }


# ---------------------------------------------------------------------------
# D6 — is_site_order_reference (mirrors funnel_service.is_funnel_reference)
# ---------------------------------------------------------------------------

def is_site_order_reference(db: Any, org_id: str, reference: str) -> bool:
    try:
        res = (db.table("site_orders").select("id").eq("org_id", org_id)
               .eq("payment_reference", reference).limit(1).execute())
        return bool(res.data)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Messaging the builder — small wrapper so this module doesn't need to know
# how site-builder WhatsApp credentials are resolved (whatsapp_service falls
# back to the org's own credentials when none are passed explicitly).
# ---------------------------------------------------------------------------

def _message_builder(db: Any, org_id: str, order: dict, text: str) -> None:
    builder_row = _one((db.table("site_builders").select("phone_number").eq("id", order["builder_id"])
                         .eq("org_id", org_id).limit(1).execute()).data)
    phone = (builder_row or {}).get("phone_number")
    if not phone:
        return
    from app.services import whatsapp_service
    whatsapp_service.send_agent_text_message(
        db=db, org_id=org_id, phone_number=phone, lead_id=order.get("lead_id"), message=text,
    )


def _handle_care_payment(db: Any, org_id: str, order: dict, now: datetime) -> bool:
    """Care plans and extra-edit packs have nothing to fulfil: paid means live. S14 — never raises."""
    try:
        sla_due_at = (now + timedelta(hours=_SLA_HOURS)).isoformat()    # keeps "paid time = sla_due_at - 24h" true for the KPIs
        claim = (db.table("site_orders").update({"status": "live", "sla_due_at": sla_due_at, "updated_at": now.isoformat()})
                 .eq("id", order["id"]).eq("status", "pending_payment").execute())
        if not claim.data:
            return True
        try:
            from app.services import site_care_plan_service
            site_care_plan_service.on_paid(db, org_id, order, now)
        except Exception as exc:
            logger.warning("site_order: care payment activation failed order=%s: %s", order["id"], exc)
            try:
                from app.services import funnel_service
                funnel_service.notify_managers(
                    db, org_id, "Care payment needs a hand",
                    f"A {order.get('kind')} payment (₦{float(order.get('amount') or 0):,.0f}) was received but couldn't be applied "
                    "automatically. Check the site's plan.", "site_order_late_payment", None)
            except Exception:
                pass
        try:
            from app.services import funnel_service
            funnel_service.notify_managers(
                db, org_id, "Care plan paid" if order.get("kind") == "care_plan" else "Extra edits paid",
                f"₦{float(order.get('amount') or 0):,.0f}", "site_order_paid", None)
        except Exception as exc:
            logger.warning("site_order: care manager notify failed order=%s: %s", order["id"], exc)
        return True
    except Exception as exc:
        logger.warning("site_order._handle_care_payment failed order=%s: %s", order.get("id"), exc)
        return True


def _alert_late_payment(db: Any, org_id: str, order: dict) -> None:
    """A payment landed on an order we had already expired (a newer renewal replaced it). S14."""
    try:
        from app.services import funnel_service
        funnel_service.notify_managers(
            db, org_id, f"Payment received on a closed order: {order.get('domain')}",
            "This order had been closed, but its payment link was paid. Check Paystack and "
            "either apply it by hand or refund the payment.", "site_order_late_payment", None,
        )
    except Exception as exc:
        logger.warning("site_order: late-payment alert failed order=%s: %s", order.get("id"), exc)


# ---------------------------------------------------------------------------
# on_payment_confirmed — spec §11.6, called from the Paystack storefront webhook
# ---------------------------------------------------------------------------

def on_payment_confirmed(db: Any, org_id: str, reference: str, now: Optional[datetime] = None) -> bool:
    """Returns True if the reference belonged to a site order (handled — even
    if idempotently ignored), False otherwise. S14 — never raises."""
    now = now or _now()
    try:
        order = _one((db.table("site_orders").select("*").eq("org_id", org_id)
                      .eq("payment_reference", reference).limit(1).execute()).data)
        if not order:
            return False
        if order.get("status") != "pending_payment":
            if order.get("status") == "expired":
                _alert_late_payment(db, org_id, order)
            return True  # idempotent — a prior webhook delivery already processed this

        if order.get("kind") in ("care_plan", "edit_pack"):
            return _handle_care_payment(db, org_id, order, now)

        approval_required = bool(order.get("approval_required"))
        new_status = "awaiting_approval" if approval_required else "fulfilling"
        sla_due_at = (now + timedelta(hours=_SLA_HOURS)).isoformat()

        # Claim — only one webhook delivery may move pending_payment → next status.
        claim = (db.table("site_orders").update({
            "status": new_status, "sla_due_at": sla_due_at, "updated_at": now.isoformat(),
        }).eq("id", order["id"]).eq("status", "pending_payment").execute())
        if not claim.data:
            return True  # another delivery already claimed it
        order = {**order, "status": new_status, "sla_due_at": sla_due_at}

        # spec §11.4 step 1 — this message goes out unconditionally on payment,
        # regardless of whether the order then waits for approval.
        is_renewal = order.get("kind") == "renewal"
        try:
            _message_builder(db, org_id, order,
                f"Payment received. Your renewal of {order.get('domain')} is being processed." if is_renewal
                else "Payment received. Your site is being deployed and will be live within 24 hours.")
        except Exception as exc:
            logger.warning("site_order.on_payment_confirmed: builder message failed order=%s: %s", order["id"], exc)

        try:
            from app.services import funnel_service
            funnel_service.notify_managers(
                db, org_id,
                (f"Renewal paid: {order.get('domain')}" if is_renewal else f"Site order paid: {order.get('domain')}"),
                f"NGN {float(order['amount']):,.2f} · {order.get('route')} · "
                + ("awaiting your approval" if approval_required else "fulfilling now"),
                "site_order_paid", None,
            )
        except Exception as exc:
            logger.warning("site_order.on_payment_confirmed: manager notify failed order=%s: %s", order["id"], exc)

        # Standard route, no approval gate: the hosting job starts immediately.
        # (When approval IS required, the future "Approve order" route calls
        # create_hosting_job() itself once the order moves to fulfilling.)
        if new_status == "fulfilling":
            try:
                create_hosting_job(db, org_id, order)
            except Exception as exc:
                logger.warning("site_order.on_payment_confirmed: hosting job creation failed order=%s: %s", order["id"], exc)

        return True
    except Exception as exc:
        logger.warning("site_order.on_payment_confirmed failed org=%s ref=%s: %s", org_id, reference, exc)
        return True


# ---------------------------------------------------------------------------
# create_hosting_job — spec §11.4 step 3
# ---------------------------------------------------------------------------

def create_hosting_job(db: Any, org_id: str, order: dict) -> dict:
    """
    Creates the hosting job (checklist + SLA clock) and a matching task-board
    row (`tasks`, source_module="site_hosting"). Idempotent: if a job already
    exists for this order, returns it instead of creating a second one — a
    retried approve action, or on_payment_confirmed firing more than once at
    the edges, must never double-queue the same job.

    sla_due_at is carried over from the order (already set in
    on_payment_confirmed — "paid time" + 24h) rather than recomputed here, so
    an approval delay never silently extends the SLA the builder was promised.
    """
    existing = _one((db.table("site_hosting_jobs").select("*").eq("org_id", org_id)
                     .eq("order_id", order["id"]).limit(1).execute()).data)
    if existing:
        return existing

    now = _now_iso()
    is_renewal = order.get("kind") == "renewal"
    sla_due_at = order.get("sla_due_at") or (_now() + timedelta(hours=_SLA_HOURS)).isoformat()
    if is_renewal:
        # Renewals get 72h from payment (the order keeps its 24h clock for the KPI maths).
        base = _parse_iso(sla_due_at) or _now()
        sla_due_at = (base + timedelta(hours=48)).isoformat()
    if is_renewal:
        from app.services.site_renewal_service import RENEWAL_CHECKLIST
        checklist = [dict(item) for item in RENEWAL_CHECKLIST]
    else:
        checklist = [dict(item) for item in _HOSTING_CHECKLIST]
    job_row = {
        "org_id": org_id,
        "order_id": order["id"],
        "site_id": order["site_id"],
        "status": "queued",
        "checklist": checklist,
        "sla_due_at": sla_due_at,
        "alerted_12h": False,
        "alerted_overdue": False,
        "created_at": now,
        "updated_at": now,
    }
    insert_res = db.table("site_hosting_jobs").insert(job_row).execute()
    job = _one(insert_res.data) or job_row

    try:
        db.table("site_orders").update({"hosting_job_id": job.get("id"), "updated_at": now}) \
            .eq("id", order["id"]).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.warning("create_hosting_job: order link-back failed order=%s: %s", order["id"], exc)

    # A task on the board (spec §11.4 step 3 — "a task on the board"), unassigned
    # until a staff member claims it from the Hosting queue tab.
    try:
        db.table("tasks").insert({
            "org_id": org_id,
            "title": (f"Renew hosting: {order.get('domain') or order['site_id']}" if is_renewal
                      else f"Deploy hosting: {order.get('domain') or order['site_id']}"),
            "description": ("Renewal job — renew the domain and the hosting package, confirm the site loads, "
                            "then click Mark renewed in Opsra." if is_renewal else
                            "Standard hosting job — re-check the domain, register it, buy hosting, "
                            "upload the export, turn on SSL, then paste the live URL into Opsra."),
            "task_type": "hosting_job",
            "source_module": "site_hosting",
            "source_record_id": job.get("id"),
            "priority": "high",
            "status": "pending",
            "due_at": sla_due_at,
            "created_at": now,
            "updated_at": now,
            "created_by": None,  # system-generated
        }).execute()
    except Exception as exc:
        logger.warning("create_hosting_job: task row failed order=%s: %s", order["id"], exc)

    # Push notification at creation (spec §11.4 step 4).
    try:
        from app.services import funnel_service
        funnel_service.notify_managers(
            db, org_id, "New renewal job queued" if is_renewal else "New hosting job queued",
            f"{order.get('domain')} · due {sla_due_at}", "hosting_job_created", None,
        )
    except Exception as exc:
        logger.warning("create_hosting_job: notify failed order=%s: %s", order["id"], exc)

    return job
