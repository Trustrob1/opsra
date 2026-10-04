"""
app/services/builder_phone_service.py
---------------------------------------
SITE-WEB-2 - a signed-in builder changes their own WhatsApp number.

  1. start()  - the new number is checked, then a 6-digit code is emailed to the address ALREADY on the account.
                That email, not the new number, is what proves the person asking owns the account.
  2. verify() - a correct code moves the account to the new number.

Rules:
  * The builder must be signed in (the route enforces it) and must have an email on file.
  * A number that belongs to any other builder in the org can't be taken.
  * 3 requests per builder per hour (counted from site_phone_changes), a code lasts 15 minutes and 5 tries.
  * Numbers are stored digits-only (2348...), the same spelling web sign-up uses, so the WhatsApp bot finds them.
Nothing here is shown to anyone but the signed-in builder.
"""
from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from app.services.builder_login_service import phone_variants
from app.services.builder_signup_service import (
    CODE_MINUTES, MAX_ATTEMPTS, SignupError, SignupRateLimited, SignupUnavailable,
    _code_hash, _iso, _now, _one, _parse, mask_email,
)

logger = logging.getLogger(__name__)

PER_BUILDER_HOUR = 3


def _digits(raw: str) -> str:
    v = phone_variants(raw)
    return v[1] if v else ""


def _send_code_email(email: str, first_name: str, code: str, new_phone: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key or not email:
        return False
    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            "from": os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io"),
            "to": [email],
            "subject": f"Your Opsra code: {code}",
            "text": (f"Hi {first_name},\n\nYour code to change your WhatsApp number to +{new_phone} is {code}.\n"
                     f"It works for {CODE_MINUTES} minutes.\n\n"
                     "If you didn't ask for this, ignore this email and your number stays as it is."),
        })
        return True
    except Exception:
        logger.exception("[SITE-WEB-2] phone-change code email failed")
        return False


def _taken(db: Any, org_id: str, new_digits: str, builder_id: str) -> bool:
    rows = (db.table("site_builders").select("id").eq("org_id", org_id)
            .in_("phone_number", [new_digits, "+" + new_digits]).limit(5).execute()).data or []
    return any(r.get("id") != builder_id for r in rows)


def start(db: Any, builder: dict, raw_phone: str, now: Optional[datetime] = None) -> dict:
    now = now or _now()
    new_digits = _digits(raw_phone)
    if not new_digits:
        raise SignupError("Please enter a valid WhatsApp number.")
    if new_digits == _digits(builder.get("phone_number") or ""):
        raise SignupError("That is already your number.")
    email = (builder.get("email") or "").strip()
    if not email:
        raise SignupError("Add your email under Account and save it first. We send the confirmation code there.")

    hour = now - timedelta(hours=1)
    recent = (db.table("site_phone_changes").select("id").eq("builder_id", builder["id"])
              .gte("created_at", _iso(hour)).execute()).data or []
    if len(recent) >= PER_BUILDER_HOUR:
        raise SignupRateLimited("Too many requests. Please try again in an hour.")
    if _taken(db, builder["org_id"], new_digits, builder["id"]):
        raise SignupError("That number is already used by another account. Check it, or contact support.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    first = (builder.get("full_name") or "").split(" ")[0] or "there"
    if not _send_code_email(email, first, code, new_digits):
        raise SignupUnavailable("We couldn't send your code right now. Please try again in a few minutes.")
    request_id = str(uuid.uuid4())
    db.table("site_phone_changes").insert({
        "id": request_id, "org_id": builder["org_id"], "builder_id": builder["id"], "new_phone": new_digits,
        "code_hash": _code_hash(request_id, code), "status": "pending", "attempts": 0,
        "expires_at": _iso(now + timedelta(minutes=CODE_MINUTES)), "created_at": _iso(now),
    }).execute()
    return {"request_id": request_id, "email_hint": mask_email(email)}


def verify(db: Any, builder: dict, request_id: str, code: str, now: Optional[datetime] = None) -> dict:
    """Returns the updated builder row."""
    import hmac
    import re
    now = now or _now()
    code = re.sub(r"\D", "", str(code or ""))
    bad = SignupError("That code isn't right. Check the email and try again.")
    if len(code) != 6 or not request_id:
        raise bad
    req = _one((db.table("site_phone_changes").select("*").eq("id", str(request_id))
                .eq("builder_id", builder["id"]).limit(1).execute()).data)
    if not req or req.get("status") != "pending":
        raise SignupError("This code has expired. Please start again.")
    expires = _parse(req.get("expires_at"))
    if not expires or expires < now:
        raise SignupError("This code has expired. Please start again.")

    attempts = int(req.get("attempts") or 0) + 1
    if not hmac.compare_digest(_code_hash(req["id"], code), req.get("code_hash") or ""):
        update = {"attempts": attempts}
        if attempts >= MAX_ATTEMPTS:
            update["status"] = "blocked"
        db.table("site_phone_changes").update(update).eq("id", req["id"]).execute()
        if attempts >= MAX_ATTEMPTS:
            raise SignupError("Too many wrong codes. Please start again.")
        raise bad

    claim = (db.table("site_phone_changes").update({"status": "verified", "verified_at": _iso(now), "attempts": attempts})
             .eq("id", req["id"]).eq("status", "pending").execute())
    if not claim.data:
        raise SignupError("This code has expired. Please start again.")
    if _taken(db, builder["org_id"], req["new_phone"], builder["id"]):
        raise SignupError("That number is already used by another account.")

    db.table("site_builders").update({"phone_number": req["new_phone"], "updated_at": _iso(now)}) \
        .eq("id", builder["id"]).eq("org_id", builder["org_id"]).execute()
    return _one((db.table("site_builders").select("*").eq("id", builder["id"]).execute()).data) or {
        **builder, "phone_number": req["new_phone"]}
