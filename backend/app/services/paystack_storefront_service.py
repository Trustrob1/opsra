"""
app/services/paystack_storefront_service.py
PAY-LINK-1 — Stage-triggered payment links using the ORG'S OWN Paystack account.

Distinct from app/services/payment_service.py (PaystackProvider), which reads
Opsra's own subscriptions/payments tables for the owner-query revenue assistant
and uses integrations.provider='paystack'. This file uses
integrations.provider='paystack_storefront' — a completely separate credential
row, never confused with the platform-level one.

Distinct from the `payments` table (Opsra's own subscription billing — keyed to
subscription_id/customer_id, no lead_id). payment_links is keyed to lead_id and
represents payments the ORG's OWN CUSTOMERS make to the org, not to Opsra.

leads.deal_value is reused as "amount owed" — no new order_total column.
amount_paid is always computed as SUM(payment_links.amount) WHERE status='paid',
never stored redundantly, mirroring how `payments` allows multiple rows per
subscription_id with no separate running-total column either.

S14: every public function returns a safe value / raises a typed error —
callers (routes, webhook handler) decide how to surface failures. Nothing here
ever lets one failure cascade into breaking the pipeline stage machine.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException, status

load_dotenv()  # Pattern 29

logger = logging.getLogger(__name__)

_PAYSTACK_API_BASE = "https://api.paystack.co"

_VALID_PAYMENT_TYPES = {"full", "deposit", "balance"}


class PaystackLinkError(Exception):
    """Raised when a payment link cannot be generated. Caller decides response shape."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Credential lookup — provider='paystack_storefront', never 'paystack'
# ---------------------------------------------------------------------------

def _get_storefront_credentials(db: Any, org_id: str) -> dict:
    """
    Returns {'secret_key': ..., 'public_key': ...} or {} if not connected.
    S14: never raises.
    """
    try:
        result = (
            db.table("integrations")
            .select("credentials")
            .eq("org_id", org_id)
            .eq("provider", "paystack_storefront")
            .eq("status", "connected")
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        return (data or {}).get("credentials") or {}
    except Exception as exc:
        logger.warning("_get_storefront_credentials failed org=%s: %s", org_id, exc)
        return {}


# ---------------------------------------------------------------------------
# Lead lookup — minimal fields needed for a payment link
# ---------------------------------------------------------------------------

def _get_lead_for_payment(db: Any, org_id: str, lead_id: str) -> dict:
    result = (
        db.table("leads")
        .select("id, org_id, full_name, whatsapp, phone, email, deal_value, assigned_to, stage")
        .eq("id", lead_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Lead not found"},
        )
    return data


# ---------------------------------------------------------------------------
# generate_payment_link
# ---------------------------------------------------------------------------

def generate_payment_link(
    db: Any,
    org_id: str,
    lead_id: str,
    amount: float,
    payment_type: str = "full",
    currency: str = "NGN",
    trigger_stage: Optional[str] = None,
    target_stage_on_paid: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    """
    Generates a Paystack Initialize Transaction link using the org's OWN
    paystack_storefront credentials, and inserts a payment_links row.

    Returns {"checkout_url": str, "reference": str, "payment_link_id": str}.
    Raises PaystackLinkError if credentials are missing or the API call fails —
    caller (route) converts this into a user-facing error response.
    """
    if payment_type not in _VALID_PAYMENT_TYPES:
        raise PaystackLinkError(f"Invalid payment_type '{payment_type}'")

    creds = _get_storefront_credentials(db, org_id)
    secret_key = (creds.get("secret_key") or "").strip()
    if not secret_key:
        raise PaystackLinkError(
            "Paystack storefront is not connected for this organisation."
        )

    lead = _get_lead_for_payment(db, org_id, lead_id)
    email = (lead.get("email") or "").strip() or f"{lead_id[:8]}@opsra.placeholder"
    reference = f"opsra_{org_id[:8]}_{lead_id[:8]}_{uuid.uuid4().hex[:8]}"

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{_PAYSTACK_API_BASE}/transaction/initialize",
                headers={"Authorization": f"Bearer {secret_key}"},
                json={
                    "email": email,
                    "amount": int(round(amount * 100)),  # kobo
                    "currency": currency,
                    "reference": reference,
                },
            )
        body = resp.json()
        if resp.status_code != 200 or not body.get("status"):
            logger.warning(
                "generate_payment_link: Paystack initialize failed org=%s lead=%s status=%s body=%s",
                org_id, lead_id, resp.status_code, body,
            )
            raise PaystackLinkError(
                body.get("message") or "Paystack could not initialize this transaction."
            )
        checkout_url = (body.get("data") or {}).get("authorization_url")
    except PaystackLinkError:
        raise
    except Exception as exc:
        logger.warning("generate_payment_link: Paystack call failed org=%s lead=%s: %s", org_id, lead_id, exc)
        raise PaystackLinkError("Could not reach Paystack right now. Try again shortly.")

    now = _now_iso()
    insert_result = (
        db.table("payment_links")
        .insert({
            "org_id": org_id,
            "lead_id": lead_id,
            "payment_type": payment_type,
            "amount": amount,
            "currency": currency,
            "reference": reference,
            "checkout_url": checkout_url,
            "status": "pending",
            "trigger_stage": trigger_stage,
            "target_stage_on_paid": target_stage_on_paid,
            "sent_at": now,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        })
        .execute()
    )
    row = insert_result.data[0] if insert_result.data else None

    return {
        "checkout_url": checkout_url,
        "reference": reference,
        "payment_link_id": (row or {}).get("id"),
        "lead": lead,
    }


# ---------------------------------------------------------------------------
# get_lead_payment_progress
# ---------------------------------------------------------------------------

def get_lead_payment_progress(db: Any, org_id: str, lead_id: str) -> dict:
    """
    Returns {
      "deal_value": float | None,
      "amount_paid": float,
      "balance_due": float | None,   # None if deal_value not set
      "payment_links": [ {id, payment_type, amount, status, reference, ...}, ... ]
    }
    amount_paid sums ONLY status='paid' rows. Pending/failed/expired/cancelled
    rows are returned in payment_links for visibility but excluded from the sum.
    S14: on any DB failure, returns a safe empty-progress shape rather than raising.
    """
    try:
        lead_r = (
            db.table("leads")
            .select("deal_value")
            .eq("id", lead_id)
            .eq("org_id", org_id)
            .maybe_single()
            .execute()
        )
        lead_d = lead_r.data
        if isinstance(lead_d, list):
            lead_d = lead_d[0] if lead_d else None
        deal_value = (lead_d or {}).get("deal_value")

        links_r = (
            db.table("payment_links")
            .select("id, payment_type, amount, currency, status, reference, checkout_url, "
                    "sent_at, paid_at, created_at")
            .eq("org_id", org_id)
            .eq("lead_id", lead_id)
            .order("created_at", desc=True)
            .execute()
        )
        links = links_r.data or []
        amount_paid = sum(float(l["amount"]) for l in links if l.get("status") == "paid")
        balance_due = (float(deal_value) - amount_paid) if deal_value is not None else None

        return {
            "deal_value": float(deal_value) if deal_value is not None else None,
            "amount_paid": amount_paid,
            "balance_due": balance_due,
            "payment_links": links,
        }
    except Exception as exc:
        logger.warning("get_lead_payment_progress failed org=%s lead=%s: %s", org_id, lead_id, exc)
        return {"deal_value": None, "amount_paid": 0.0, "balance_due": None, "payment_links": []}


# ---------------------------------------------------------------------------
# verify_transaction — fallback reconciliation
# ---------------------------------------------------------------------------

def verify_transaction(db: Any, org_id: str, reference: str) -> dict:
    """
    GET /transaction/verify/{reference} against the org's own Paystack account.
    S14: returns {'verified': False} on any failure, never raises.
    """
    creds = _get_storefront_credentials(db, org_id)
    secret_key = (creds.get("secret_key") or "").strip()
    if not secret_key:
        return {"verified": False, "reason": "not_connected"}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{_PAYSTACK_API_BASE}/transaction/verify/{reference}",
                headers={"Authorization": f"Bearer {secret_key}"},
            )
        body = resp.json()
        if resp.status_code == 200 and body.get("status"):
            data = body.get("data") or {}
            return {"verified": True, "status": data.get("status"), "data": data}
        return {"verified": False, "reason": "not_found_or_failed"}
    except Exception as exc:
        logger.warning("verify_transaction failed org=%s ref=%s: %s", org_id, reference, exc)
        return {"verified": False, "reason": "error"}


# ---------------------------------------------------------------------------
# mark_paid — called ONLY from the paystack-storefront webhook handler
# ---------------------------------------------------------------------------

def mark_paid(db: Any, org_id: str, reference: str) -> None:
    """
    Idempotent. Marks the payment_links row paid, then decides whether to move
    the lead's pipeline stage:
      - amount_paid (after this payment) >= leads.deal_value → move to
        this row's target_stage_on_paid (if set)
      - else if payment_type == 'deposit' and org's payment_link_config has
        deposit_ack_stage set → move there instead
      - else no stage move

    Each side-effect (stage move, WhatsApp send, rep notification) is wrapped
    individually — S14 — one failing never rolls back the payment status update.
    """
    link_r = (
        db.table("payment_links")
        .select("*")
        .eq("org_id", org_id)
        .eq("reference", reference)
        .maybe_single()
        .execute()
    )
    link = link_r.data
    if isinstance(link, list):
        link = link[0] if link else None
    if not link:
        logger.warning("mark_paid: no payment_links row for org=%s ref=%s", org_id, reference)
        return

    if link.get("status") == "paid":
        return  # idempotent — already processed

    now = _now_iso()
    db.table("payment_links").update({
        "status": "paid",
        "paid_at": now,
        "updated_at": now,
    }).eq("id", link["id"]).execute()

    lead_id = link["lead_id"]
    progress = get_lead_payment_progress(db, org_id, lead_id)
    amount_paid = progress["amount_paid"]
    deal_value = progress["deal_value"]

    fully_paid = deal_value is not None and amount_paid >= deal_value

    # ── Decide stage move ────────────────────────────────────────────────
    try:
        target_stage = link.get("target_stage_on_paid")
        stage_to_move = None
        if fully_paid and target_stage:
            stage_to_move = target_stage
        elif link.get("payment_type") == "deposit":
            org_r = (
                db.table("organisations")
                .select("payment_link_config")
                .eq("id", org_id)
                .maybe_single()
                .execute()
            )
            org_d = org_r.data
            if isinstance(org_d, list):
                org_d = org_d[0] if org_d else None
            cfg = (org_d or {}).get("payment_link_config") or {}
            deposit_ack_stage = cfg.get("deposit_ack_stage")
            if deposit_ack_stage:
                stage_to_move = deposit_ack_stage

        if stage_to_move:
            from app.services import lead_service
            lead_service.move_stage(
                db=db, org_id=org_id, lead_id=lead_id,
                new_stage=stage_to_move, user_id=None,
                bypass_payment_guard=True,  # this IS the real Paystack payment path —
                                             # not a manual override, so use the bypass
                                             # (confirm_full_payment would incorrectly
                                             # log a deposit-only move as an override)
            )
    except Exception as exc:
        logger.warning("mark_paid: stage move failed org=%s lead=%s: %s", org_id, lead_id, exc)

    # ── WhatsApp confirmation to customer ──────────────────────────────────
    try:
        lead_r = (
            db.table("leads").select("full_name, whatsapp, phone, assigned_to")
            .eq("id", lead_id).eq("org_id", org_id).maybe_single().execute()
        )
        lead_d = lead_r.data
        if isinstance(lead_d, list):
            lead_d = lead_d[0] if lead_d else None
        lead_d = lead_d or {}
        phone_number = (lead_d.get("whatsapp") or lead_d.get("phone") or "").strip()
        if phone_number:
            from app.services import whatsapp_service
            balance_due = progress["balance_due"] or 0
            whatsapp_service.send_payment_received_message(
                db=db, org_id=org_id, phone_number=phone_number,
                amount=float(link["amount"]), currency=link.get("currency") or "NGN",
                balance_due=max(balance_due, 0),
            )
    except Exception as exc:
        logger.warning("mark_paid: WhatsApp confirmation failed org=%s lead=%s: %s", org_id, lead_id, exc)

    # ── Notify assigned rep ─────────────────────────────────────────────────
    try:
        assigned_to = (lead_d or {}).get("assigned_to")
        if assigned_to:
            label = "Full payment" if fully_paid else "Deposit"
            db.table("notifications").insert({
                "org_id": org_id,
                "user_id": assigned_to,
                "title": f"{label} received: {(lead_d or {}).get('full_name', 'Lead')}",
                "body": f"{link.get('currency', 'NGN')} {float(link['amount']):,.2f} received via Paystack.",
                "type": "payment_received",
                "resource_type": "lead",
                "resource_id": lead_id,
            }).execute()
    except Exception as exc:
        logger.warning("mark_paid: rep notification failed org=%s lead=%s: %s", org_id, lead_id, exc)
