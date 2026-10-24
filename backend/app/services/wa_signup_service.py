"""
app/services/wa_signup_service.py
---------------------------------
WA-AUTO-5 - public sign-up for a WhatsApp-automation-only business (page /start/whatsapp).

  1. start()  - business name, owner name, email, WhatsApp number, terms. A 6-digit code is emailed. Nothing is created yet.
  2. verify() - the code proves the email; the owner chooses a password. The business (product mode wa_automation, plans enforced),
                the owner login, the credit wallet (metering ON, so AI replies are never free), a free trial of the Automate plan
                and the optional starter credit are created. The owner then signs in on the normal login page.

Control (Superadmin card, table wa_signup_settings): sign-up is CLOSED until opened; trial days; starter credit; daily cap.
Safety: honeypot; rate limits per IP, email and phone counted from wa_signup_requests; the code is stored hashed, good for
15 minutes and 5 tries; an email that already has a login gets the same reply as a new one but no code (nothing is revealed).
S14: the trial, wallet, credit and notification steps are best effort once the business exists.
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

from app.services import builder_signup_service as bss
from app.services import org_provision_service as prov

logger = logging.getLogger(__name__)

CODE_MINUTES = 15
MAX_ATTEMPTS = 5
PER_IP_HOUR = 5
PER_EMAIL_HOUR = 3
PER_PHONE_HOUR = 3
TIER_KEY = "automate"
DEFAULTS = {"is_open": False, "trial_days": 7, "starter_credit_ngn": 0, "daily_cap": 50}
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")


class SignupError(Exception):
    status_code = 422
    code = "VALIDATION_ERROR"

    def __init__(self, message: str, status_code: int = 422, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.status_code, self.code = status_code, code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _code_hash(request_id: str, code: str) -> str:
    return hashlib.sha256(f"wa-signup:{request_id}:{code}".encode("utf-8")).hexdigest()


# -- settings (Superadmin) -------------------------------------------------------------------------------------------
def get_settings(db: Any) -> dict:
    try:
        row = _one((db.table("wa_signup_settings").select("*").eq("id", 1).limit(1).execute()).data) or {}
    except Exception as exc:
        logger.warning("wa_signup: settings unreadable: %s", exc)
        row = {}
    return {k: (row.get(k) if row.get(k) is not None else v) for k, v in DEFAULTS.items()} | {"is_open": row.get("is_open") is True}


def save_settings(db: Any, data: dict) -> dict:
    clean = {}
    for key, lo, hi in (("trial_days", 1, 30), ("starter_credit_ngn", 0, 5000), ("daily_cap", 0, 1000)):
        if key in data and data[key] is not None:
            try:
                v = int(data[key])
            except (TypeError, ValueError):
                raise SignupError(f"{key.replace('_', ' ').capitalize()} must be a whole number.")
            if not lo <= v <= hi:
                raise SignupError(f"{key.replace('_', ' ').capitalize()} must be between {lo} and {hi}.")
            clean[key] = v
    if data.get("is_open") is not None:
        clean["is_open"] = bool(data["is_open"])
    if not clean:
        return get_settings(db)
    clean["updated_at"] = _iso()
    exists = _one((db.table("wa_signup_settings").select("id").eq("id", 1).limit(1).execute()).data)
    if exists:
        db.table("wa_signup_settings").update(clean).eq("id", 1).execute()
    else:
        db.table("wa_signup_settings").insert({"id": 1, **clean}).execute()
    return get_settings(db)


def info(db: Any) -> dict:
    """What the public page may show: open or not, trial length and the plan as priced in Superadmin settings."""
    s = get_settings(db)
    plan = {"label": "Automate", "monthly_ngn": 0, "ai_messages": None}
    try:
        from app.services import account_entitlement_service as acc
        d = (acc.plan_config(db)["tiers"].get(TIER_KEY)) or {}
        plan = {"label": d.get("label") or "Automate", "monthly_ngn": int(d.get("monthly_ngn") or 0), "ai_messages": (d.get("caps") or {}).get("ai_messages")}
    except Exception as exc:
        logger.warning("wa_signup: plan info unavailable: %s", exc)
    return {"open": s["is_open"], "trial_days": s["trial_days"], "starter_credit_ngn": s["starter_credit_ngn"], "plan": plan}


# -- step 1 ------------------------------------------------------------------------------------------------------------
def _clean(payload: dict) -> dict:
    from app.services import builder_login_service
    p = payload or {}
    business = re.sub(r"\s+", " ", str(p.get("business_name") or "")).strip()
    name = re.sub(r"\s+", " ", str(p.get("full_name") or "")).strip()
    email = str(p.get("email") or "").strip().lower()
    variants = builder_login_service.phone_variants(str(p.get("phone") or ""))
    if not (2 <= len(business) <= 80):
        raise SignupError("Please enter your business name.")
    if not (2 <= len(name) <= 80):
        raise SignupError("Please enter your name.")
    if not _EMAIL_RE.match(email) or len(email) > 255:
        raise SignupError("Please enter a valid email address.")
    if not variants:
        raise SignupError("Please enter your WhatsApp number.")
    if p.get("accept_terms") is not True:
        raise SignupError("Please accept the terms to continue.")
    return {"business_name": business, "full_name": name, "email": email, "phone": variants[1]}


def _count_since(db: Any, column: str, value: str, since: datetime) -> int:
    return len(db.table("wa_signup_requests").select("id").eq(column, value).gte("created_at", _iso(since)).execute().data or [])


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
            "text": (f"Hi {first_name},\n\nYour code to create your Opsra WhatsApp account is {code}.\n"
                     f"It works for {CODE_MINUTES} minutes.\n\nIf you didn't ask for this, you can ignore this email."),
        })
        return True
    except Exception:
        logger.exception("[WA-AUTO-5] sign-up code email failed")
        return False


def start(db: Any, payload: dict, ip: str, now: Optional[datetime] = None) -> dict:
    """Returns {"request_id", "email_hint"}."""
    now = now or _now()
    if (payload or {}).get("website"):                      # honeypot
        return {"request_id": str(uuid.uuid4()), "email_hint": "***"}
    data = _clean(payload)
    settings = get_settings(db)
    if not settings["is_open"]:
        raise SignupError("Sign-ups are not open yet.", 403, "SIGNUP_CLOSED")
    ip_hash = bss.hash_ip(ip or "unknown")
    hour = now - timedelta(hours=1)
    if (_count_since(db, "ip_hash", ip_hash, hour) >= PER_IP_HOUR or _count_since(db, "email", data["email"], hour) >= PER_EMAIL_HOUR
            or _count_since(db, "phone_number", data["phone"], hour) >= PER_PHONE_HOUR):
        raise SignupError("Too many attempts. Please try again in an hour.", 429, "RATE_LIMITED")
    today = len(db.table("wa_signup_requests").select("id").eq("status", "verified").gte("verified_at", _iso(now - timedelta(hours=24))).execute().data or [])
    if today >= settings["daily_cap"]:
        raise SignupError("We're at capacity for new sign-ups today. Please try again tomorrow.", 403, "SIGNUP_CLOSED")

    request_id = str(uuid.uuid4())
    row = {"id": request_id, "business_name": data["business_name"], "full_name": data["full_name"], "email": data["email"],
           "phone_number": data["phone"], "ip_hash": ip_hash, "attempts": 0, "expires_at": _iso(now + timedelta(minutes=CODE_MINUTES)),
           "created_at": _iso(now)}
    hint = bss.mask_email(data["email"])
    try:
        taken = prov.auth_email_exists(data["email"])
    except prov.ProvisionError as exc:
        raise SignupError(str(exc), 503, "SERVICE_UNAVAILABLE")
    if taken:                                               # same reply, no code: nothing is revealed
        db.table("wa_signup_requests").insert({**row, "code_hash": "-", "status": "blocked"}).execute()
        return {"request_id": request_id, "email_hint": hint}
    code = f"{secrets.randbelow(1_000_000):06d}"
    if not _send_code_email(data["email"], data["full_name"].split(" ")[0], code):
        raise SignupError("We couldn't send your code right now. Please try again in a few minutes.", 503, "SERVICE_UNAVAILABLE")
    db.table("wa_signup_requests").insert({**row, "code_hash": _code_hash(request_id, code), "status": "pending"}).execute()
    return {"request_id": request_id, "email_hint": hint}


# -- step 2 ------------------------------------------------------------------------------------------------------------
def verify(db: Any, request_id: str, code: str, password: str, now: Optional[datetime] = None) -> dict:
    """Creates the business. Returns {"email", "org_id", "trial_days"}."""
    now = now or _now()
    code = re.sub(r"\D", "", str(code or ""))
    bad = SignupError("That code isn't right. Check the email and try again.")
    if len(code) != 6 or not request_id:
        raise bad
    if len(password or "") < 8 or len(password) > 72:
        raise SignupError("Choose a password of 8 to 72 characters.")
    req = _one((db.table("wa_signup_requests").select("*").eq("id", str(request_id)).limit(1).execute()).data)
    expired = SignupError("This code has expired. Please start again.")
    if not req or req.get("status") != "pending":
        raise expired
    exp = bss._parse(req.get("expires_at"))
    if not exp or exp < now:
        raise expired
    attempts = int(req.get("attempts") or 0) + 1
    if not hmac.compare_digest(_code_hash(req["id"], code), req.get("code_hash") or ""):
        update = {"attempts": attempts}
        if attempts >= MAX_ATTEMPTS:
            update["status"] = "blocked"
        db.table("wa_signup_requests").update(update).eq("id", req["id"]).execute()
        if attempts >= MAX_ATTEMPTS:
            raise SignupError("Too many wrong codes. Please start again.")
        raise bad
    claim = db.table("wa_signup_requests").update({"status": "verified", "verified_at": _iso(now), "attempts": attempts}) \
        .eq("id", req["id"]).eq("status", "pending").execute()
    if not claim.data:
        raise expired
    try:
        made = prov.provision_wa_org(db, business_name=req["business_name"], owner_name=req["full_name"], email=req["email"],
                                     password=password, whatsapp=req["phone_number"])
    except prov.ProvisionError as exc:
        db.table("wa_signup_requests").update({"status": "blocked"}).eq("id", req["id"]).execute()
        raise SignupError(str(exc), exc.status_code, exc.code)
    org_id = made["org_id"]
    try:
        db.table("wa_signup_requests").update({"org_id": org_id}).eq("id", req["id"]).execute()
    except Exception:
        pass
    settings = get_settings(db)
    _start_trial(db, org_id, settings["trial_days"], now)
    _open_wallet(db, org_id, settings["starter_credit_ngn"])
    _tell_platform(db, org_id, req)
    return {"email": req["email"], "org_id": org_id, "trial_days": settings["trial_days"]}


def _start_trial(db: Any, org_id: str, days: int, now: datetime) -> None:
    try:
        db.table("org_plans").insert({"org_id": org_id, "kind": "tier", "key": TIER_KEY, "status": "active", "source": "trial", "price_ngn": 0,
                                      "paid_until": _iso(now + timedelta(days=days)), "config": {}, "created_at": _iso(now), "updated_at": _iso(now)}).execute()
        from app.services import account_entitlement_service as acc
        acc._log_event(db, org_id, "system", "trial_started", {"key": TIER_KEY, "days": days})
    except Exception as exc:
        logger.error("wa_signup: trial not started org=%s: %s", org_id, exc)


def _open_wallet(db: Any, org_id: str, starter_ngn: int) -> None:
    """Metering ON from day one. The optional starter credit is idempotent (reference wa_signup_<org>)."""
    try:
        db.table("credit_wallets").upsert({"org_id": org_id, "metering_enabled": True, "meta_billing": "client_direct"}, on_conflict="org_id").execute()
    except Exception as exc:
        logger.error("wa_signup: wallet not opened org=%s: %s", org_id, exc)
    if starter_ngn and starter_ngn > 0:
        try:
            from app.services import credit_service
            credit_service.add_credit(db, org_id, int(starter_ngn) * 100, "adjust", f"wa_signup_{org_id}", {"reason": "starter credit"})
        except Exception as exc:
            logger.error("wa_signup: starter credit failed org=%s: %s", org_id, exc)


def _tell_platform(db: Any, org_id: str, req: dict) -> None:
    try:
        from app.services import platform_guard as pg
        pid = pg.platform_id(db)
        if not pid:
            return
        for u in db.table("users").select("id, roles").eq("org_id", pid).execute().data or []:
            roles = u.get("roles") if isinstance(u.get("roles"), dict) else {}
            if (roles.get("template") or "") not in ("owner", "ops_manager"):
                continue
            db.table("notifications").insert({
                "org_id": pid, "user_id": u["id"], "title": f"New WhatsApp sign-up: {req['business_name']}",
                "body": f"{req['full_name']}, {req['phone_number']}. Their free trial has started."[:1000], "type": "wa_signup",
                "resource_type": "organisation", "resource_id": org_id, "is_read": False, "created_at": _iso(),
            }).execute()
    except Exception as exc:
        logger.warning("wa_signup: platform notification failed org=%s: %s", org_id, exc)
