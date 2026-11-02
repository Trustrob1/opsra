"""
app/services/wa_setup_queue_service.py
--------------------------------------
WA-AUTO-6 - the queue of "please connect my WhatsApp" requests: an email to Trust's alert address when one arrives,
a list for Superadmin, and "Mark connected". The bell notification (wa_onboarding_service) stays as well.
S14: sending the email never fails the request.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)
DEFAULT_ALERT_EMAIL = "trustrobert34@gmail.com"


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def alert_email(db: Any) -> str:
    try:
        row = _one(db.table("wa_signup_settings").select("alert_email").eq("id", 1).limit(1).execute().data) or {}
        return (row.get("alert_email") or "").strip()
    except Exception as exc:
        logger.warning("wa_setup_queue: alert address unreadable: %s", exc)
        return DEFAULT_ALERT_EMAIL


def send_alert(db: Any, org_id: str, phone: str, note: str) -> bool:
    """Emails the alert address about a new request. False when there is no address, no mail key, or the send failed."""
    to = alert_email(db)
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not to or not api_key:
        return False
    try:
        org = _one(db.table("organisations").select("name").eq("id", org_id).limit(1).execute().data) or {}
        name = org.get("name") or "A business"
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            "from": os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io"),
            "to": [to],
            "subject": f"Connect WhatsApp request: {name}",
            "text": (f"{name} asked Opsra to connect their WhatsApp number.\n\nNumber: {phone}\nNote: {note or '(none)'}\n\n"
                     f"Open Superadmin > Plans > Setup requests to see the list and mark it connected when done."),
        })
        return True
    except Exception:
        logger.exception("wa_setup_queue: alert email failed org=%s", org_id)
        return False


def list_requests(db: Any) -> list:
    """Every request, waiting ones first, newest first."""
    rows = db.table("wa_onboarding").select("org_id, setup_requested_at, setup_phone, setup_note, setup_done_at").limit(1000).execute().data or []
    rows = [r for r in rows if r.get("setup_requested_at")]
    names = {}
    ids = [r["org_id"] for r in rows]
    if ids:
        for o in db.table("organisations").select("id, name, whatsapp_phone_id").in_("id", ids).execute().data or []:
            names[o["id"]] = o
    out = []
    for r in rows:
        o = names.get(r["org_id"]) or {}
        done = bool(r.get("setup_done_at"))
        out.append({"org_id": r["org_id"], "business": o.get("name") or "(deleted business)", "phone": r.get("setup_phone"), "note": r.get("setup_note"),
                    "requested_at": r.get("setup_requested_at"), "done_at": r.get("setup_done_at"), "done": done,
                    "number_linked": bool(o.get("whatsapp_phone_id"))})
    out.sort(key=lambda x: str(x["requested_at"] or ""), reverse=True)
    out.sort(key=lambda x: x["done"])
    return out


def mark_done(db: Any, org_id: str, now: Optional[datetime] = None) -> dict:
    rows = db.table("wa_onboarding").select("org_id, setup_requested_at").eq("org_id", org_id).limit(1).execute().data or []
    if not rows or not rows[0].get("setup_requested_at"):
        return {"found": False}
    db.table("wa_onboarding").update({"setup_done_at": (now or datetime.now(timezone.utc)).isoformat()}).eq("org_id", org_id).execute()
    return {"found": True}
