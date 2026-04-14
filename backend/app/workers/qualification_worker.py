"""
app/workers/qualification_worker.py
-------------------------------------
Two Celery tasks for Module 01 qualification flow:

Task 1 — run_review_window_sender  (M01-4)
    Runs every minute. Finds whatsapp_outbox rows where:
      - status = 'scheduled'
      - send_after <= now (window has expired without rep cancellation)
    Dispatches each via _dispatch_outbox_row().
    S14: each row is processed independently — one failure never blocks others.

Task 2 — run_qualification_fallback  (M01-5)
    Runs every hour. Finds lead_qualification_sessions where:
      - stage = 'awaiting_first_message'
      - fallback_sent_at IS NULL  (not already sent)
      - created_at <= now - qualification_fallback_hours
    For each: sends a pre-approved re-engagement WhatsApp template
    OR notifies the assigned rep if no template is configured.
    Stamps fallback_sent_at to prevent duplicate sends.
    S14: each lead is processed independently.

Pattern 29: load_dotenv() called before os.getenv at module level.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

# Pattern 42: import at module level so tests can patch at source
from app.services.whatsapp_service import _dispatch_outbox_row, _call_meta_send, _normalise_data
 
from app.workers.celery_app import celery_app
 
logger = logging.getLogger(__name__)
 
 
def _get_db():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    return create_client(url, key)

# ---------------------------------------------------------------------------
# Supabase factory — Pattern 1: never module-level singleton
# ---------------------------------------------------------------------------

def _get_db():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Task 1 — Review window auto-sender  (M01-4)
# ---------------------------------------------------------------------------

@celery_app.task(name="app.workers.qualification_worker.run_review_window_sender")
def run_review_window_sender() -> dict:
    """
    Auto-send scheduled outbox messages whose review window has expired.
    Runs every minute via beat schedule.
    """
    db = _get_db()
    now_iso = datetime.now(timezone.utc).isoformat()
 
    try:
        result = (
            db.table("whatsapp_outbox")
            .select("*")
            .eq("status", "scheduled")
            .lte("send_after", now_iso)
            .execute()
        )
        rows = result.data if isinstance(result.data, list) else []
    except Exception as exc:
        logger.warning("run_review_window_sender: DB query failed: %s", exc)
        return {"sent": 0, "failed": 0, "error": str(exc)}
 
    sent = 0
    failed = 0
    for row in rows:
        try:
            dispatched = _dispatch_outbox_row(
                db=db,
                org_id=row["org_id"],
                outbox_row=row,
                actioned_by=None,
            )
            if dispatched.get("status") == "sent":
                sent += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "review_window_sender: unhandled error for outbox %s: %s",
                row.get("id"), exc,
            )
 
    logger.info("run_review_window_sender complete — sent=%d failed=%d", sent, failed)
    return {"sent": sent, "failed": failed}
 


# ---------------------------------------------------------------------------
# Task 2 — Re-engagement fallback  (M01-5)
# ---------------------------------------------------------------------------

# Re-engagement template name — must be pre-approved by Meta.
# This is the fallback for leads who submit the form but never tap Send.


_REENGAGEMENT_TEMPLATE = "lead_reengagement"
 
 
@celery_app.task(name="app.workers.qualification_worker.run_qualification_fallback")
def run_qualification_fallback() -> dict:
    """
    Find qualification sessions stuck at awaiting_first_message past the
    org's fallback window, then either:
      a) Send the pre-approved re-engagement template via WhatsApp, or
      b) Insert an in-app notification for the assigned rep directly.
 
    Stamps fallback_sent_at on the session to prevent duplicate sends.
    Runs every hour via beat schedule.
    """
    db = _get_db()
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
 
    try:
        org_result = (
            db.table("organisations")
            .select("id, whatsapp_phone_id, qualification_fallback_hours")
            .execute()
        )
        orgs = org_result.data if isinstance(org_result.data, list) else []
    except Exception as exc:
        logger.warning("run_qualification_fallback: failed to fetch orgs: %s", exc)
        return {"processed": 0, "sent": 0, "notified": 0, "failed": 0}
 
    processed = sent = notified = failed = 0
 
    for org in orgs:
        org_id = org["id"]
        phone_id = org.get("whatsapp_phone_id") or ""
        fallback_hours = int(org.get("qualification_fallback_hours") or 2)
        cutoff = (now_dt - timedelta(hours=fallback_hours)).isoformat()
 
        try:
            sess_result = (
                db.table("lead_qualification_sessions")
                .select("id, lead_id, org_id")
                .eq("org_id", org_id)
                .eq("stage", "awaiting_first_message")
                .eq("ai_active", True)
                .is_("fallback_sent_at", "null")
                .lte("created_at", cutoff)
                .execute()
            )
            sessions = sess_result.data if isinstance(sess_result.data, list) else []
        except Exception as exc:
            logger.warning(
                "run_qualification_fallback: failed to fetch sessions for org %s: %s",
                org_id, exc,
            )
            continue
 
        for session in sessions:
            processed += 1
            session_id = session["id"]
            lead_id    = session["lead_id"]
 
            try:
                lead_res = (
                    db.table("leads")
                    .select("id, full_name, whatsapp, phone, assigned_to")
                    .eq("id", lead_id)
                    .eq("org_id", org_id)
                    .is_("deleted_at", "null")
                    .maybe_single()
                    .execute()
                )
                lead = _normalise_data(lead_res.data)
                if not lead:
                    failed += 1
                    continue
 
                wa_number   = lead.get("whatsapp") or lead.get("phone")
                assigned_to = lead.get("assigned_to")
                lead_name   = lead.get("full_name") or "Lead"
                wa_sent     = False
 
                # ── Attempt WhatsApp template send ────────────────────────
                if wa_number and phone_id:
                    try:
                        meta_payload = {
                            "messaging_product": "whatsapp",
                            "to": wa_number,
                            "type": "template",
                            "template": {
                                "name": _REENGAGEMENT_TEMPLATE,
                                "language": {"code": "en"},
                            },
                        }
                        _call_meta_send(phone_id, meta_payload)
 
                        msg_row = {
                            "org_id": org_id,
                            "lead_id": lead_id,
                            "direction": "outbound",
                            "message_type": "text",
                            "content": None,
                            "template_name": _REENGAGEMENT_TEMPLATE,
                            "status": "sent",
                            "window_open": True,
                            "window_expires_at": (
                                now_dt + timedelta(hours=24)
                            ).isoformat(),
                            "sent_by": None,
                            "created_at": now_iso,
                        }
                        db.table("whatsapp_messages").insert(msg_row).execute()
                        wa_sent = True
                        sent += 1
                    except Exception as exc:
                        logger.warning(
                            "run_qualification_fallback: Meta send failed for lead %s: %s",
                            lead_id, exc,
                        )
 
                # ── Fall back to in-app notification (direct DB insert) ────
                if not wa_sent and assigned_to:
                    try:
                        notif_row = {
                            "org_id": org_id,
                            "user_id": assigned_to,
                            "type": "qualification_fallback",
                            "title": f"Follow up with {lead_name}",
                            "body": (
                                f"{lead_name} submitted the lead form but hasn't "
                                f"messaged on WhatsApp yet. Consider reaching out directly."
                            ),
                            "resource_type": "lead",
                            "resource_id": lead_id,
                            "is_read": False,
                            "created_at": now_iso,
                        }
                        db.table("notifications").insert(notif_row).execute()
                        notified += 1
                    except Exception as exc:
                        logger.warning(
                            "run_qualification_fallback: notification failed for lead %s: %s",
                            lead_id, exc,
                        )
 
                # ── Stamp fallback_sent_at regardless of send method ──────
                db.table("lead_qualification_sessions").update(
                    {"fallback_sent_at": now_iso}
                ).eq("id", session_id).execute()
 
            except Exception as exc:
                failed += 1
                logger.warning(
                    "run_qualification_fallback: unhandled error for session %s: %s",
                    session_id, exc,
                )
 
    logger.info(
        "run_qualification_fallback complete — "
        "processed=%d sent=%d notified=%d failed=%d",
        processed, sent, notified, failed,
    )
    return {"processed": processed, "sent": sent, "notified": notified, "failed": failed}
 
