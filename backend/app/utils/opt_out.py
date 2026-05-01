"""
app/utils/opt_out.py
---------------------
9E-I — I1: WhatsApp opt-out / opt-in keyword handling.

Extracted into its own module so it can be unit-tested independently of
webhooks.py and imported cleanly from there.

Called by:
  app/routers/webhooks.py  — _handle_inbound_message()
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services.whatsapp_service import _get_org_wa_credentials, _call_meta_send

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

OPT_OUT_KEYWORDS: frozenset = frozenset({
    "stop", "unsubscribe", "optout", "opt out", "opt-out",
    "cancel", "quit", "remove me",
})

OPT_IN_KEYWORDS: frozenset = frozenset({
    "start", "subscribe", "optin", "opt in",
})

OPT_OUT_REPLY = (
    "You've been unsubscribed from our WhatsApp messages. "
    "Reply START at any time to opt back in. "
    "No further messages will be sent to you."
)

OPT_IN_REPLY = (
    "Welcome back! You're now subscribed to receive messages from us again. "
    "Reply STOP at any time to unsubscribe."
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handle_opt_keywords(
    db,
    content: str,
    sender_phone: str,
    org_id: str,
    customer_id: Optional[str],
    lead_id: Optional[str],
) -> bool:
    """
    Check whether the inbound message is an opt-out or opt-in keyword.

    If matched:
      - Set whatsapp_opted_out on the lead or customer record
      - Send one reply via Meta API
      - Return True  (message fully consumed — caller must return immediately)

    Returns False if the message is not a recognised keyword.

    S14 — never raises; all failures are logged as warnings so normal
    inbound processing continues unaffected.
    """
    normalised = content.strip().lower()
    is_opt_out = normalised in OPT_OUT_KEYWORDS
    is_opt_in  = normalised in OPT_IN_KEYWORDS

    if not is_opt_out and not is_opt_in:
        return False

    try:
        opted_out_flag = is_opt_out          # True → opted out; False → opted in
        reply_msg      = OPT_OUT_REPLY if is_opt_out else OPT_IN_REPLY

        # ── Update the correct record ─────────────────────────────────────
        if customer_id:
            db.table("customers").update(
                {"whatsapp_opted_out": opted_out_flag}
            ).eq("id", customer_id).eq("org_id", org_id).execute()
            logger.info(
                "handle_opt_keywords: customer %s whatsapp_opted_out=%s",
                customer_id, opted_out_flag,
            )
        elif lead_id:
            db.table("leads").update(
                {"whatsapp_opted_out": opted_out_flag}
            ).eq("id", lead_id).eq("org_id", org_id).execute()
            logger.info(
                "handle_opt_keywords: lead %s whatsapp_opted_out=%s",
                lead_id, opted_out_flag,
            )
        else:
            # Unknown contact — no record to update, still confirm the opt-out.
            logger.info(
                "handle_opt_keywords: opt-%s from unknown contact %s (no record found)",
                "out" if is_opt_out else "in", sender_phone,
            )

        # ── Send one reply via Meta API ───────────────────────────────────
        try:
            phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
            if phone_id and access_token:
                _call_meta_send(phone_id, {
                    "messaging_product": "whatsapp",
                    "to":   sender_phone,
                    "type": "text",
                    "text": {"body": reply_msg},
                }, token=access_token)
        except Exception as send_exc:
            logger.warning(
                "handle_opt_keywords: failed to send reply to %s: %s",
                sender_phone, send_exc,
            )

        return True

    except Exception as exc:
        logger.warning(
            "handle_opt_keywords: error processing keyword from %s: %s",
            sender_phone, exc,
        )
        return False
