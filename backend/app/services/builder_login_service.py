"""
app/services/builder_login_service.py
---------------------------------------
SITE-LANDING — "send me a sign-in link" for the public builder landing page.

A builder types the phone number they registered with. If (and only if) an
ACTIVE builder owns that number, a single-use magic link (site_editor_tokens,
same hashed-token shape as EDIT on WhatsApp) is sent to the builder's OWN
channels: WhatsApp (from the org's site-builder number) and, when the builder
has an email on file, email. The link is never returned to the browser, so
knowing someone's phone number is not enough to sign in as them.

Delivery runs as a background task and the HTTP response is identical whether
or not the number is registered (no account enumeration, no timing tell).

WhatsApp only delivers free text inside Meta's 24-hour customer-service
window, so the email copy is the dependable channel for builders who haven't
messaged the bot today. Every step is S14-safe: nothing here raises.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from app.models.sites import generate_form_token
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

LOGIN_LINK_MINUTES = 60   # shorter than the 7-day WhatsApp EDIT link: this one can sit in an inbox


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def phone_variants(raw: str) -> list[str]:
    """['+E164', 'digits'] spellings of a Nigerian-default number, or [] if it can't be a phone."""
    digits = normalize_phone((raw or "").strip())
    if not digits or not digits.isdigit() or not (9 <= len(digits) <= 15):
        return []
    return [f"+{digits}", digits]


def _login_url(raw_token: str) -> str:
    base = os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/")
    return f"{base}/b/login?t={raw_token}"


def _send_whatsapp(db, builder: dict, text: str) -> None:
    number_row = _one((db.table("whatsapp_numbers").select("*").eq("org_id", builder["org_id"])
                       .eq("wa_sales_mode", "site_builder").limit(1).execute()).data)
    if not number_row:
        return
    from app.services.whatsapp_service import send_agent_text_message
    send_agent_text_message(
        db=db, org_id=builder["org_id"], phone_number=builder["phone_number"].lstrip("+"),
        lead_id=builder.get("lead_id"), message=text,
        phone_id=number_row.get("phone_id"), access_token=number_row.get("access_token"),
    )


def _send_email(to_email: str, url: str, first_name: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key or not to_email:
        return
    import resend
    resend.api_key = api_key
    resend.Emails.send({
        "from": os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io"),
        "to": [to_email],
        "subject": "Your Opsra builder sign-in link",
        "text": (f"Hi {first_name},\n\nUse this link to sign in to your Opsra builder portal. "
                 f"It works once and expires in {LOGIN_LINK_MINUTES} minutes:\n\n{url}\n\n"
                 "If you didn't ask for this, you can ignore this message."),
    })


def send_login_link(raw_phone: str) -> None:
    """Background task entry point. Never raises."""
    try:
        variants = phone_variants(raw_phone)
        if not variants:
            return
        from app.database import get_supabase
        db = get_supabase()
        builder = _one((db.table("site_builders").select("*").in_("phone_number", variants)
                        .eq("status", "active").limit(1).execute()).data)
        if not builder:
            return

        now = datetime.now(timezone.utc)
        raw_token, token_hash = generate_form_token()
        db.table("site_editor_tokens").insert({
            "org_id": builder["org_id"], "builder_id": builder["id"], "token_hash": token_hash,
            "expires_at": (now + timedelta(minutes=LOGIN_LINK_MINUTES)).isoformat(),
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
        }).execute()

        url = _login_url(raw_token)
        first = (builder.get("full_name") or "").split(" ")[0] or "there"
        text = (f"Hi {first}, here's your builder sign-in link. It works once and expires in "
                f"{LOGIN_LINK_MINUTES} minutes:\n\n{url}")
        for step in (lambda: _send_whatsapp(db, builder, text),
                     lambda: _send_email(builder.get("email") or "", url, first)):
            try:
                step()
            except Exception:
                logger.exception("[SITE-LANDING] link delivery step failed builder=%s", builder.get("id"))
    except Exception:
        logger.exception("[SITE-LANDING] send_login_link failed")
