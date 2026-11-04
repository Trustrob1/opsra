"""
app/services/wa_budget_alert_service.py
---------------------------------------
WA-BUDGET-3 — tell the owner (in the app and by email) when the monthly WhatsApp budget reaches 80% and 100%.

Called after a WhatsApp message is metered. One alert per threshold per month per business: the in-app
notification itself is the record (type wa_budget_80 / wa_budget_100, created this month), so there is no new table.
Goes to the owner and operations managers. S14: never raises.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from app.services import credit_service

logger = logging.getLogger(__name__)

THRESHOLDS = ((100, "wa_budget_100"), (80, "wa_budget_80"))
MANAGER_ROLES = ("owner", "ops_manager")


def _naira(kobo: int) -> str:
    return f"₦{kobo / 100:,.0f}"


def level_reached(spent: int, budget: int) -> Optional[tuple[int, str]]:
    if budget <= 0:
        return None
    for pct, kind in THRESHOLDS:
        if spent * 100 >= budget * pct:
            return pct, kind
    return None


def _message(pct: int, spent: int, budget: int, action: str) -> tuple[str, str]:
    if pct >= 100:
        what = ("Customers who message you on WhatsApp now get a link to your web chat, and marketing messages are paused."
                if action == "chat" else "Messages keep going and use your credit.")
        return ("Your WhatsApp budget is used up",
                f"You have spent {_naira(spent)} of your {_naira(budget)} WhatsApp budget this month. {what} "
                "You can raise the budget any time in Billing > Credits.")
    what = ("When it runs out, customers will be sent to your web chat."
            if action == "chat" else "When it runs out, messages will keep going and use your credit.")
    return ("You have used 80% of your WhatsApp budget",
            f"You have spent {_naira(spent)} of your {_naira(budget)} WhatsApp budget this month. {what}")


def _already_sent(db, org_id: str, kind: str) -> bool:
    rows = (db.table("notifications").select("id").eq("org_id", org_id).eq("type", kind)
            .gte("created_at", credit_service._month_start()).limit(1).execute()).data or []
    return bool(rows)


def _recipients(db, org_id: str) -> list[dict]:
    rows = db.table("users").select("id, email, roles(template)").eq("org_id", org_id).execute().data or []
    out = []
    for u in rows:
        role = str(((u.get("roles") or {}).get("template")) or "").lower()
        if role in MANAGER_ROLES:
            out.append(u)
    return out


def _send_email(to_email: str, subject: str, text: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key or not to_email:
        return False
    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({"from": os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io"),
                            "to": [to_email], "subject": subject, "text": text})
        return True
    except Exception as exc:
        logger.warning("wa_budget email failed: %s", exc)
        return False


def check_and_alert(db, org_id: Optional[str]) -> bool:
    """True when an alert went out on this call."""
    try:
        if not org_id:
            return False
        wallet = credit_service.get_wallet(db, org_id)
        if not credit_service.metering_on(wallet):
            return False
        budget = int((wallet or {}).get("wa_monthly_budget_kobo") or 0)
        if budget <= 0:
            return False
        spent = credit_service.month_wa_spend_kobo(db, org_id)
        hit = level_reached(spent, budget)
        if not hit:
            return False
        pct, kind = hit
        if _already_sent(db, org_id, kind):
            return False
        action = (wallet or {}).get("wa_over_budget_action") or "chat"
        title, body = _message(pct, spent, budget, action)
        now = datetime.now(timezone.utc).isoformat()
        users = _recipients(db, org_id)
        for u in users:
            try:
                db.table("notifications").insert({
                    "org_id": org_id, "user_id": u["id"], "type": kind, "title": title, "body": body,
                    "resource_type": "credits", "resource_id": None, "is_read": False, "created_at": now,
                }).execute()
            except Exception as exc:
                logger.warning("wa_budget notification failed org=%s: %s", org_id, exc)
            if u.get("email"):
                link = os.environ.get("FRONTEND_URL", "https://opsra.com.ng").rstrip("/")
                _send_email(u["email"], title, f"{body}\n\nOpen Billing: {link}\n")
        return bool(users)
    except Exception as exc:
        logger.warning("wa_budget check_and_alert failed org=%s: %s", org_id, exc)
        return False
