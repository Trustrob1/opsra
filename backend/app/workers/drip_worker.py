"""
app/workers/drip_worker.py
---------------------------
Celery task:

  run_drip_scheduler  — Daily 08:00 WAT (07:00 UTC)
    Fetch pending drip_sends where scheduled_for <= today.
    Apply pause rules before sending.
    Queue outbound message in whatsapp_messages.
    Update drip_sends.status to sent / paused / skipped / failed.

Pause rules (evaluated in order):
  1. Customer status != 'active'             → status = 'skipped'
  2. Customer has an open/in-progress ticket → status = 'paused'
  3. drip_message row not found              → status = 'failed'
  4. drip_message.business_types is non-empty
     AND customer.business_type does not match → status = 'skipped'
     (CONFIG-2: match is case-insensitive; also resolves labels to keys
      using the org's drip_business_types config so legacy free-text
      entries like "Pharmacy" still match the key "pharmacy")

On success:
  • INSERT into whatsapp_messages (status = 'queued')
  • UPDATE drip_sends SET status = 'sent', sent_at = now()

NOTE: whatsapp_messages column names (direction, body, message_type) are
      expected to match Phase 3A schema. Verify during smoke test.

Pattern 29: load_dotenv() at module level.
Pattern 1:  get_supabase() called inside task body.
Pattern 33: Python-side date comparison — no server-side date filter.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase  # noqa: E402
from app.services.whatsapp_service import (  # noqa: E402
    _get_org_wa_credentials,
    _call_meta_send,
    _build_template_components,
    _first_name,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _normalise(data) -> Optional[dict]:
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _build_key_set(org_biz_types: list[dict]) -> dict[str, str]:
    """
    CONFIG-2: Build a lookup from every known label and key → canonical key.

    Given org_biz_types = [{"key": "pharmacy", "label": "Pharmacy"}, ...]
    returns:
      {
        "pharmacy":         "pharmacy",   # key  → key
        "Pharmacy":         "pharmacy",   # label → key (original case)
        "pharmacy":         "pharmacy",   # already lower
        ...
      }
    This lets us resolve legacy free-text values like "Pharmacy" or "PHARMACY"
    to the canonical slug "pharmacy" for comparison.
    """
    mapping: dict[str, str] = {}
    for entry in org_biz_types or []:
        key   = (entry.get("key")   or "").strip()
        label = (entry.get("label") or "").strip()
        if key:
            mapping[key.lower()]   = key
            mapping[key]           = key
        if label:
            mapping[label.lower()] = key
            mapping[label]         = key
    return mapping


def _business_type_matches(
    customer_biz_type: Optional[str],
    message_biz_types: list[str],
    label_to_key: dict[str, str],
) -> bool:
    """
    CONFIG-2: Return True if the customer's business_type matches any entry
    in message_biz_types, or if message_biz_types is empty (= send to all).

    Matching strategy (in order):
      1. Empty message_biz_types → always matches.
      2. No customer business_type → does not match a restricted message.
      3. Resolve customer value through label_to_key map (handles legacy labels).
      4. Case-insensitive direct comparison as final fallback.
    """
    if not message_biz_types:
        return True  # empty = send to all types

    if not customer_biz_type:
        return False  # message is restricted but customer has no type set

    customer_lower = customer_biz_type.strip().lower()

    # Resolve customer value to canonical key if possible
    resolved_customer = label_to_key.get(customer_biz_type.strip()) \
        or label_to_key.get(customer_lower) \
        or customer_lower

    for msg_type in message_biz_types:
        msg_lower   = (msg_type or "").strip().lower()
        resolved_msg = label_to_key.get(msg_type.strip()) \
            or label_to_key.get(msg_lower) \
            or msg_lower

        if resolved_customer == resolved_msg:
            return True
        # Fallback: raw case-insensitive match (handles configs with no org types)
        if customer_lower == msg_lower:
            return True

    return False


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def run_drip_scheduler(self):
    """
    Daily 08:00 WAT — Process all pending drip sends due today or earlier.
    Applies pause/skip rules. Queues approved sends to whatsapp_messages.
    """
    logger.info("drip_worker: run_drip_scheduler starting.")
    db = get_supabase()  # Pattern 1
    processed = 0
    skipped = 0

    try:
        today = _today_iso()
        orgs = (db.table("organisations").select("id, drip_business_types").execute().data or [])

        for org_row in orgs:
            org_id: str = org_row["id"]

            # CONFIG-2: build label→key map once per org
            org_biz_types = org_row.get("drip_business_types") or []
            label_to_key  = _build_key_set(org_biz_types)

            try:
                all_pending = (
                    db.table("drip_sends")
                    .select("id, customer_id, drip_message_id, scheduled_for, status")
                    .eq("org_id", org_id)
                    .eq("status", "pending")
                    .execute()
                    .data or []
                )

                # Python-side filter: scheduled_for <= today (Pattern 33)
                due = [
                    s
                    for s in all_pending
                    if (s.get("scheduled_for") or "")[:10] <= today
                ]

                for send in due:
                    send_id: str = send["id"]
                    customer_id: str = send["customer_id"]
                    message_id: Optional[str] = send.get("drip_message_id")

                    try:
                        # ── Pause rule 1: customer not active → skip ────────
                        customer = _normalise(
                            db.table("customers")
                            .select("id, status, whatsapp, phone, full_name, business_type")
                            .eq("id", customer_id)
                            .execute()
                            .data
                        )

                        if not customer or customer.get("status") != "active":
                            _set_status(db, send_id, "skipped")
                            skipped += 1
                            continue

                        # ── Pause rule 2: open ticket → pause ───────────────
                        open_tickets = (
                            db.table("tickets")
                            .select("id")
                            .eq("org_id", org_id)
                            .eq("customer_id", customer_id)
                            .in_("status", ["open", "in_progress"])
                            .execute()
                            .data or []
                        )
                        if open_tickets:
                            _set_status(db, send_id, "paused")
                            skipped += 1
                            continue

                        # ── Fetch drip message content ──────────────────────
                        if not message_id:
                            _set_status(db, send_id, "failed")
                            logger.warning(
                                "drip_worker: send %s has no drip_message_id", send_id
                            )
                            continue

                        message = _normalise(
                            db.table("drip_messages")
                            .select("id, body, message_type, business_types")
                            .eq("id", message_id)
                            .execute()
                            .data
                        )
                        if not message:
                            _set_status(db, send_id, "failed")
                            logger.warning(
                                "drip_worker: drip_message %s not found", message_id
                            )
                            continue

                        # ── Pause rule 3 (CONFIG-2): business_type mismatch → skip
                        msg_biz_types = message.get("business_types") or []
                        customer_biz  = customer.get("business_type")
                        if not _business_type_matches(
                            customer_biz, msg_biz_types, label_to_key
                        ):
                            _set_status(db, send_id, "skipped")
                            logger.info(
                                "drip_worker: send %s skipped — customer type '%s' "
                                "not in message types %s",
                                send_id, customer_biz, msg_biz_types,
                            )
                            skipped += 1
                            continue

                        # ── Resolve org WhatsApp credentials ────────────
                        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
                        if not phone_id or not access_token:
                            logger.warning(
                                "drip_worker: org %s has no WhatsApp credentials — "
                                "skipping send %s", org_id, send_id,
                            )
                            _set_status(db, send_id, "failed")
                            skipped += 1
                            continue

                        # ── Resolve template name from template_id ───────────
                        template_id = message.get("template_id")
                        if not template_id:
                            logger.warning(
                                "drip_worker: drip_message %s has no template_id", message_id
                            )
                            _set_status(db, send_id, "failed")
                            continue

                        tmpl = _normalise(
                            db.table("whatsapp_templates")
                            .select("name, meta_status")
                            .eq("id", template_id)
                            .eq("org_id", org_id)
                            .execute()
                            .data
                        )
                        if not tmpl or tmpl.get("meta_status") != "approved":
                            logger.warning(
                                "drip_worker: template %s not approved for org %s "
                                "— skipping send %s", template_id, org_id, send_id,
                            )
                            _set_status(db, send_id, "skipped")
                            skipped += 1
                            continue

                        template_name = tmpl["name"]

                        # ── Build Meta payload with recipient name as {{1}} ──
                        to_number = customer.get("whatsapp") or customer.get("phone")
                        if not to_number:
                            logger.warning(
                                "drip_worker: customer %s has no WhatsApp number", customer_id
                            )
                            _set_status(db, send_id, "failed")
                            continue

                        components = _build_template_components(
                            variables=None,
                            recipient_name=customer.get("full_name"),
                        )
                        template_dict: dict = {
                            "name": template_name,
                            "language": {"code": "en"},
                        }
                        if components:
                            template_dict["components"] = components

                        meta_payload = {
                            "messaging_product": "whatsapp",
                            "to": to_number,
                            "type": "template",
                            "template": template_dict,
                        }

                        # ── Call Meta Cloud API ──────────────────────────────
                        try:
                            meta_resp = _call_meta_send(phone_id, meta_payload, token=access_token)
                            meta_msgs = meta_resp.get("messages")
                            meta_message_id = None
                            if isinstance(meta_msgs, list) and meta_msgs:
                                meta_message_id = meta_msgs[0].get("id")
                        except Exception as meta_exc:
                            logger.warning(
                                "drip_worker: Meta API failed for send %s: %s", send_id, meta_exc
                            )
                            _set_status(db, send_id, "failed")
                            continue

                        # ── Record in whatsapp_messages ──────────────────────
                        window_expires = (
                            datetime.now(timezone.utc) + timedelta(hours=24)
                        ).isoformat()
                        try:
                            db.table("whatsapp_messages").insert({
                                "org_id": org_id,
                                "customer_id": customer_id,
                                "direction": "outbound",
                                "message_type": "template",
                                "template_name": template_name,
                                "status": "sent",
                                "meta_message_id": meta_message_id,
                                "window_open": True,
                                "window_expires_at": window_expires,
                                "sent_by": None,
                                "created_at": _now_iso(),
                            }).execute()
                        except Exception as db_exc:
                            logger.warning(
                                "drip_worker: failed to record whatsapp_message for "
                                "send %s: %s", send_id, db_exc,
                            )

                        # ── Mark drip_send as sent ───────────────────────────
                        db.table("drip_sends").update(
                            {"status": "sent", "sent_at": _now_iso()}
                        ).eq("id", send_id).execute()
                        processed += 1

                    except Exception as exc:
                        logger.warning(
                            "drip_worker: send %s failed — %s", send_id, exc
                        )
                        _set_status(db, send_id, "failed")

            except Exception as exc:
                logger.error(
                    "drip_worker: drip scheduler failed for org %s — %s", org_id, exc
                )

        logger.info(
            "drip_worker: run_drip_scheduler done. Sent: %d, Skipped/Paused: %d.",
            processed,
            skipped,
        )

    except Exception as exc:
        logger.error("drip_worker: run_drip_scheduler fatal — %s", exc)
        raise self.retry(exc=exc, countdown=30)


def _set_status(db, send_id: str, status: str) -> None:
    """Update drip_sends.status, swallowing any DB error."""
    try:
        db.table("drip_sends").update({"status": status}).eq("id", send_id).execute()
    except Exception as exc:
        logger.warning(
            "drip_worker: failed to set status=%s for send %s — %s",
            status,
            send_id,
            exc,
        )
