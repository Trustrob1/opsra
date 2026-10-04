"""
app/services/builder_signup_service.py
---------------------------------------
SITE-WEB-1 - sign up for the Site Builder on the web, with no WhatsApp message needed.

Who: anyone (a web developer building for clients, or a business owner building their own site). The account is a
`site_builders` row, never an Opsra user, so a web sign-up can never reach a staff screen: builder sessions use a
separate token secret and audience (see builder_auth_service).

Flow:
  1. start()  - name, email, WhatsApp number, account type. A 6-digit code is emailed. Nothing is created yet.
  2. verify() - the code proves the email address. The builder (status active, source web_signup) and their CRM
                lead are created and a builder session is returned, so they land in the portal at once.

Safety:
  * Open only while the owner has "Who can start building" switched to open sign-up (members_only false).
  * Durable rate limits kept in site_signup_requests: per IP, per email, per phone, and a daily cap on verified
    sign-ups. A code is good for 15 minutes and 5 tries.
  * An existing phone number never reveals itself: the reply is the same and the owner of that number is sent a
    normal sign-in link instead.
  * The 3-free-sites cap and the builder subscription (site_access_service) bound what a new account can cost.

Known limit: the phone number is typed in, not proven (WhatsApp can't send a code outside its 24-hour window
without an approved template). The email is proven. A sign-in link goes to both channels.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

CODE_MINUTES = 15
MAX_ATTEMPTS = 5
PER_IP_HOUR = 5
PER_EMAIL_HOUR = 3
PER_PHONE_HOUR = 3
DEFAULT_DAILY_CAP = 150
ACCOUNT_TYPES = ("builder", "owner")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")


class SignupError(Exception):
    status_code = 422
    code = "VALIDATION_ERROR"


class SignupClosed(SignupError):
    status_code = 403
    code = "SIGNUP_CLOSED"


class SignupRateLimited(SignupError):
    status_code = 429
    code = "RATE_LIMITED"


class SignupUnavailable(SignupError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def hash_ip(ip: str) -> str:
    return hashlib.sha256(f"builder-signup:{ip}".encode("utf-8")).hexdigest()


def _code_hash(request_id: str, code: str) -> str:
    return hashlib.sha256(f"{request_id}:{code}".encode("utf-8")).hexdigest()


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return (local[:1] + "***@" + domain) if local else email


# ---------------------------------------------------------------------------
# Which org, and is sign-up open
# ---------------------------------------------------------------------------

def resolve_org(db: Any) -> Optional[str]:
    """The org that runs the Site Builder: the one with a site_builder WhatsApp number, else the only enabled one."""
    number = _one((db.table("whatsapp_numbers").select("org_id").eq("wa_sales_mode", "site_builder").limit(1).execute()).data)
    if number and number.get("org_id"):
        return number["org_id"]
    rows = (db.table("site_builder_settings").select("org_id").eq("enabled", True).limit(2).execute()).data or []
    return rows[0]["org_id"] if len(rows) == 1 else None


def _settings(db: Any, org_id: str) -> dict:
    return _one((db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data) or {}


def _daily_cap(settings: dict) -> int:
    raw = (((settings.get("pricing") or {}).get("builder_access")) or {}).get("signup_daily_cap")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_CAP


def is_open(settings: dict) -> bool:
    """Same switch as the WhatsApp bot: members_only false means anyone may start."""
    return bool(settings.get("enabled")) and not settings.get("members_only", True)


# ---------------------------------------------------------------------------
# Rate limits (durable: counted from site_signup_requests)
# ---------------------------------------------------------------------------

def _count_since(db: Any, org_id: str, column: str, value: str, since: datetime) -> int:
    rows = (db.table("site_signup_requests").select("id").eq("org_id", org_id).eq(column, value)
            .gte("created_at", _iso(since)).execute()).data or []
    return len(rows)


def _check_rate_limits(db: Any, org_id: str, ip_hash: str, email: str, phone: str, now: datetime) -> None:
    hour = now - timedelta(hours=1)
    if (_count_since(db, org_id, "ip_hash", ip_hash, hour) >= PER_IP_HOUR
            or _count_since(db, org_id, "email", email, hour) >= PER_EMAIL_HOUR
            or _count_since(db, org_id, "phone_number", phone, hour) >= PER_PHONE_HOUR):
        raise SignupRateLimited("Too many attempts. Please try again in an hour.")


def _verified_today(db: Any, org_id: str, now: datetime) -> int:
    rows = (db.table("site_signup_requests").select("id").eq("org_id", org_id).eq("status", "verified")
            .gte("verified_at", _iso(now - timedelta(hours=24))).execute()).data or []
    return len(rows)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _send_code_email(email: str, first_name: str, code: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        return False
    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            "from": os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io"),
            "to": [email],
            "subject": f"Your Opsra sign-up code: {code}",
            "text": (f"Hi {first_name},\n\nYour code to create your Opsra builder account is {code}.\n"
                     f"It works for {CODE_MINUTES} minutes.\n\nIf you didn't ask for this, you can ignore this email."),
        })
        return True
    except Exception:
        logger.exception("[SITE-WEB-1] sign-up code email failed")
        return False


# ---------------------------------------------------------------------------
# Step 1 - start
# ---------------------------------------------------------------------------

def _clean(payload: dict) -> dict:
    from app.services import builder_login_service
    payload = payload or {}
    name = re.sub(r"\s+", " ", str(payload.get("full_name") or "")).strip()
    email = str(payload.get("email") or "").strip().lower()
    variants = builder_login_service.phone_variants(str(payload.get("phone") or ""))
    account_type = payload.get("account_type") or "builder"
    if not (2 <= len(name) <= 80):
        raise SignupError("Please enter your name.")
    if not _EMAIL_RE.match(email) or len(email) > 255:
        raise SignupError("Please enter a valid email address.")
    if not variants:
        raise SignupError("Please enter your WhatsApp number.")
    if account_type not in ACCOUNT_TYPES:
        raise SignupError("Please choose how you'll use Opsra.")
    if payload.get("accept_terms") is not True:
        raise SignupError("Please accept the terms to continue.")
    return {"full_name": name, "email": email, "phone": variants[1], "account_type": account_type}


def start(db: Any, payload: dict, ip: str, send_login_link=None, now: Optional[datetime] = None) -> dict:
    """Validate, rate-limit, and email a code. Returns {"request_id", "email_hint"}.
    `send_login_link` is called with the phone when the number already has an account (it is the sign-in link sender)."""
    now = now or _now()
    if (payload or {}).get("website"):                      # honeypot: pretend success, create nothing
        return {"request_id": str(uuid.uuid4()), "email_hint": "***"}
    data = _clean(payload)

    org_id = resolve_org(db)
    settings = _settings(db, org_id) if org_id else {}
    if not org_id or not is_open(settings):
        raise SignupClosed("Sign-ups aren't open right now.")

    ip_hash = hash_ip(ip or "unknown")
    _check_rate_limits(db, org_id, ip_hash, data["email"], data["phone"], now)

    existing = _one((db.table("site_builders").select("id, status").eq("org_id", org_id)
                     .in_("phone_number", [data["phone"], "+" + data["phone"]]).limit(1).execute()).data)
    if existing and existing.get("status") == "pending":
        existing = None                                      # an unclaimed bot placeholder: verify() takes it over
    request_id = str(uuid.uuid4())
    # Log the attempt either way (the rate limit counts it); an existing number gets a sign-in link, not a code.
    row = {
        "id": request_id, "org_id": org_id, "full_name": data["full_name"], "email": data["email"],
        "phone_number": data["phone"], "account_type": data["account_type"], "ip_hash": ip_hash,
        "attempts": 0, "expires_at": _iso(now + timedelta(minutes=CODE_MINUTES)), "created_at": _iso(now),
    }
    if existing:
        db.table("site_signup_requests").insert({**row, "code_hash": "-", "status": "blocked"}).execute()
        if send_login_link and existing.get("status") == "active":
            send_login_link(data["phone"])
        return {"request_id": request_id, "email_hint": mask_email(data["email"])}

    if _verified_today(db, org_id, now) >= _daily_cap(settings):
        raise SignupClosed("We're at capacity for new sign-ups today. Please try again tomorrow.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    if not _send_code_email(data["email"], data["full_name"].split(" ")[0], code):
        raise SignupUnavailable("We couldn't send your code right now. Please try again in a few minutes.")
    db.table("site_signup_requests").insert({**row, "code_hash": _code_hash(request_id, code), "status": "pending"}).execute()
    return {"request_id": request_id, "email_hint": mask_email(data["email"])}


# ---------------------------------------------------------------------------
# Step 2 - verify and create the account
# ---------------------------------------------------------------------------

def verify(db: Any, request_id: str, code: str, now: Optional[datetime] = None) -> dict:
    """Returns the new builder row. Raises SignupError for a wrong, expired or used code."""
    now = now or _now()
    code = re.sub(r"\D", "", str(code or ""))
    bad = SignupError("That code isn't right. Check the email and try again.")
    if len(code) != 6 or not request_id:
        raise bad
    req = _one((db.table("site_signup_requests").select("*").eq("id", str(request_id)).limit(1).execute()).data)
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
        db.table("site_signup_requests").update(update).eq("id", req["id"]).execute()
        if attempts >= MAX_ATTEMPTS:
            raise SignupError("Too many wrong codes. Please start again.")
        raise bad

    org_id = req["org_id"]
    claim = (db.table("site_signup_requests").update({"status": "verified", "verified_at": _iso(now), "attempts": attempts})
             .eq("id", req["id"]).eq("status", "pending").execute())
    if not claim.data:                                       # someone else used it a moment ago
        raise SignupError("This code has expired. Please start again.")

    taken = _one((db.table("site_builders").select("id, status").eq("org_id", org_id)
                  .in_("phone_number", [req["phone_number"], "+" + req["phone_number"]]).limit(1).execute()).data)
    if taken and taken.get("status") != "pending":
        raise SignupError("This number already has an account. Please sign in instead.")

    builder = {
        "org_id": org_id, "phone_number": req["phone_number"], "full_name": req["full_name"], "email": req["email"],
        "status": "active", "source": "web_signup", "account_type": req["account_type"],
        "approved_orders_count": 0, "joined_at": _iso(now),
    }
    if taken:                                                # claim the bot's pending placeholder
        updated = _one(db.table("site_builders").update({**builder, "updated_at": _iso(now)})
                       .eq("id", taken["id"]).eq("org_id", org_id).execute().data)
        created = updated or {**builder, "id": taken["id"]}
    else:
        created = _one(db.table("site_builders").insert(builder).execute().data) or builder
    try:
        from app.services import site_access_service
        site_access_service.ensure_lead(db, org_id, created)
    except Exception:  # S14 - the account exists either way
        logger.exception("[SITE-WEB-1] lead creation failed builder=%s", created.get("id"))
    try:
        db.table("site_events").insert({
            "org_id": org_id, "site_id": None, "actor": "system", "event": "builder_signed_up",
            "detail": {"builder_id": created.get("id"), "account_type": req["account_type"], "source": "web_signup"},
            "created_at": _iso(now),
        }).execute()
    except Exception:  # S14
        logger.exception("[SITE-WEB-1] event log failed")
    return created


def mint_login_token(db: Any, builder: dict, minutes: int = 10, now: Optional[datetime] = None) -> str:
    """A single-use portal sign-in token (same table and shape as the WhatsApp EDIT link). The sign-up page hands it
    to /b/login?t=..., so the portal's session token is only ever created by /auth/exchange and never stored."""
    from app.models.sites import generate_form_token
    now = now or _now()
    raw_token, token_hash = generate_form_token()
    db.table("site_editor_tokens").insert({
        "org_id": builder["org_id"], "builder_id": builder["id"], "token_hash": token_hash,
        "expires_at": _iso(now + timedelta(minutes=minutes)), "created_at": _iso(now), "updated_at": _iso(now),
    }).execute()
    return raw_token
