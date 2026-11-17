"""
app/services/chat_pause_service.py
----------------------------------
WEB-ONLY-1c - what happens when a web-chat-only business (product_mode web_chat) runs out of chat credit.

  * Paused: the wallet is metered and empty. Visitors cannot start or continue a chat and the widget is not drawn on the
    business's website until the owner subscribes or tops up. It resumes by itself on the next check (nothing to switch on).
  * Notices: when a new conversation takes the balance down to the low line, or to nothing, the owners and managers get an
    in-app note and the owner an email, saying plainly what to do. Each kind is sent at most once every 3 days.
  * Only web_chat businesses are affected. Every other kind of business keeps the old behaviour (AI falls back to the menu).

S14: nothing here raises. When the wallet or the mode cannot be read, the chat is NOT paused.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.services import credit_service as cs
from app.services import product_mode as pmode

logger = logging.getLogger(__name__)

LOW_DEFAULT_KOBO = 40_000          # N400 when Superadmin has not set a low line for the wallet
NOTICE_DAYS = 3
T_LOW, T_EMPTY = "chat_credit_low", "chat_credit_empty"

PAUSED_MESSAGE = "This chat is not available right now. Please try again later."


def status(db: Any, org_id: Optional[str]) -> dict:
    """{chat_only, balance_kobo, low_line_kobo, paused, low}. Never raises; unreadable means not paused and not low."""
    out = {"chat_only": False, "balance_kobo": 0, "low_line_kobo": LOW_DEFAULT_KOBO, "paused": False, "low": False}
    try:
        if not org_id or pmode.get_mode(db, org_id) != pmode.WEB_CHAT:
            return out
        out["chat_only"] = True
        w = cs.get_wallet(db, org_id)
        if not cs.metering_on(w):
            return out
        bal = int(w.get("balance_kobo") or 0)
        line = int(w.get("low_balance_kobo") or 0) or LOW_DEFAULT_KOBO
        out.update(balance_kobo=bal, low_line_kobo=line, paused=bal <= 0, low=0 < bal <= line)
    except Exception as exc:
        logger.warning("chat_pause.status failed org=%s: %s", org_id, exc)
    return out


def is_paused(db: Any, org_id: Optional[str]) -> bool:
    return bool(status(db, org_id)["paused"])


def _naira(kobo: int) -> str:
    return "₦" + format(int(kobo) // 100, ",")


def _plan_line(db: Any) -> str:
    """'the Chioma plan (N15,000 a month)' from Superadmin pricing; no figure when no price is set."""
    try:
        from app.services import account_entitlement_service as acc
        t = (acc.plan_config(db)["tiers"].get("chioma") or {})
        price = int(t.get("monthly_ngn") or 0)
        if price > 0:
            inc = int(t.get("included_credit_ngn") or 0)
            extra = f", which includes ₦{inc:,} of chat credit every month" if inc > 0 else ""
            return f"choose the Chioma plan (₦{price:,} a month{extra})"
    except Exception as exc:
        logger.warning("chat_pause plan line failed: %s", exc)
    return "top up in Billing"


def _recent(db: Any, org_id: str, ntype: str, now: datetime) -> bool:
    """True when this kind of note was already sent to this business within NOTICE_DAYS."""
    try:
        since = (now - timedelta(days=NOTICE_DAYS)).isoformat()
        rows = (db.table("notifications").select("id").eq("org_id", org_id).eq("type", ntype)
                .gte("created_at", since).limit(1).execute().data) or []
        return bool(rows)
    except Exception as exc:
        logger.warning("chat_pause dedupe check failed org=%s: %s", org_id, exc)
        return True       # when unsure, stay quiet rather than repeat


def _owner_emails(db: Any, org_id: str) -> list[str]:
    try:
        rows = db.table("users").select("email, roles(template)").eq("org_id", org_id).execute().data or []
        return [r["email"] for r in rows if r.get("email") and ((r.get("roles") or {}).get("template") or "").lower() == "owner"]
    except Exception as exc:
        logger.warning("chat_pause owner lookup failed org=%s: %s", org_id, exc)
        return []


def notify_after_charge(db: Any, org_id: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """Call after a conversation fee was charged. Sends the low or the empty note when due; returns which ('low'/'empty')
    or None. Never raises."""
    try:
        now = now or datetime.now(timezone.utc)
        st = status(db, org_id)
        if not st["chat_only"] or not (st["paused"] or st["low"]):
            return None
        ntype = T_EMPTY if st["paused"] else T_LOW
        if _recent(db, org_id, ntype, now):
            return None
        how = _plan_line(db)
        if st["paused"]:
            title = "Chioma has paused your web chat"
            text = (f"Your chat credit has run out, so Chioma is paused and visitors cannot start a chat on your website. "
                    f"Open Billing and {how}, or top up, and she switches back on straight away.")
            subject = "Chioma has paused your web chat"
        else:
            title = "Your chat credit is running low"
            text = (f"You have {_naira(st['balance_kobo'])} of chat credit left. When it reaches zero, Chioma pauses and visitors "
                    f"cannot start a chat. Open Billing to {how}, or top up, before that happens.")
            subject = "Your chat credit is running low"
        from app.services import funnel_service
        funnel_service.notify_managers(db, org_id, title, text, ntype, None)
        try:
            from app.services import site_addon_billing_service as sab
            for email in _owner_emails(db, org_id):
                sab._send_email(email, subject, text)
        except Exception as exc:
            logger.warning("chat_pause email failed org=%s: %s", org_id, exc)
        return "empty" if st["paused"] else "low"
    except Exception as exc:
        logger.warning("chat_pause.notify_after_charge failed org=%s: %s", org_id, exc)
        return None
