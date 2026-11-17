"""
app/services/chat_signup_service.py
-----------------------------------
WEB-ONLY-1a - public sign-up for a web-chat-only business (page /start/chat): Chioma on the website, no WhatsApp.

  1. start()  - business name, owner name, email, WhatsApp number (to reach the owner; the product does not use it), terms.
                A 6-digit code is emailed. Nothing is created yet.
  2. verify() - the code proves the email; the owner chooses a password. The business (product mode web_chat, plans enforced),
                the owner login, a credit wallet (metering ON, so every chat is paid from credit), a FREE Chioma plan (no end
                date, no card) and the starter credit are created. The owner then signs in on the normal login page.

Free period: the plan row has source 'free' and no end date, so web chat is on for as long as there is credit. When the credit
runs out the chat pauses (WEB-ONLY-1c) until the owner subscribes or tops up. Paying converts the same row to a paid Chioma plan
(account_plan_billing_service), and only then does the plan's monthly included credit start (plan_credit_worker skips 'free' rows).

Control (Superadmin card, table chat_signup_settings): sign-up is CLOSED until opened; starter credit; daily cap. This switch is
separate from the WhatsApp sign-up switch (wa_signup_settings).
Safety: same as the WhatsApp sign-up - honeypot; rate limits per IP, email and phone counted from chat_signup_requests; the code is
stored hashed, good for 15 minutes and 5 tries; an email that already has a login gets the same reply as a new one but no code.
S14: the plan, wallet, credit and notification steps are best effort once the business exists.
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
from app.services.wa_signup_service import (
    CODE_MINUTES, MAX_ATTEMPTS, PER_EMAIL_HOUR, PER_IP_HOUR, PER_PHONE_HOUR, SignupError, _clean, _iso, _now, _one,
)

logger = logging.getLogger(__name__)

TIER_KEY = "chioma"
DEFAULTS = {"is_open": False, "starter_credit_ngn": 2000, "daily_cap": 50}   # Trust, 17 Nov 2026: N2,000 free credit, no card, no time limit


def _code_hash(request_id: str, code: str) -> str:
    return hashlib.sha256(f"chat-signup:{request_id}:{code}".encode("utf-8")).hexdigest()


# -- settings (Superadmin) -------------------------------------------------------------------------------------------
def get_settings(db: Any) -> dict:
    try:
        row = _one((db.table("chat_signup_settings").select("*").eq("id", 1).limit(1).execute()).data) or {}
    except Exception as exc:
        logger.warning("chat_signup: settings unreadable: %s", exc)
        row = {}
    return {k: (row.get(k) if row.get(k) is not None else v) for k, v in DEFAULTS.items()} | {"is_open": row.get("is_open") is True}


def save_settings(db: Any, data: dict) -> dict:
    clean = {}
    for key, lo, hi in (("starter_credit_ngn", 0, 5000), ("daily_cap", 0, 1000)):
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
    exists = _one((db.table("chat_signup_settings").select("id").eq("id", 1).limit(1).execute()).data)
    if exists:
        db.table("chat_signup_settings").update(clean).eq("id", 1).execute()
    else:
        db.table("chat_signup_settings").insert({"id": 1, **clean}).execute()
    return get_settings(db)


def info(db: Any) -> dict:
    """What the public page may show: open or not, the starter credit and the plan as priced in Superadmin settings."""
    s = get_settings(db)
    plan = {"label": "Chioma", "monthly_ngn": 0, "ai_messages": None, "included_credit_ngn": 0}
    try:
        from app.services import account_entitlement_service as acc
        d = (acc.plan_config(db)["tiers"].get(TIER_KEY)) or {}
        plan = {"label": d.get("label") or "Chioma", "monthly_ngn": int(d.get("monthly_ngn") or 0),
                "ai_messages": (d.get("caps") or {}).get("ai_messages"), "included_credit_ngn": int(d.get("included_credit_ngn") or 0)}
    except Exception as exc:
        logger.warning("chat_signup: plan info unavailable: %s", exc)
    return {"open": s["is_open"], "starter_credit_ngn": s["starter_credit_ngn"], "plan": plan}


# -- step 1 ------------------------------------------------------------------------------------------------------------
def _count_since(db: Any, column: str, value: str, since: datetime) -> int:
    return len(db.table("chat_signup_requests").select("id").eq(column, value).gte("created_at", _iso(since)).execute().data or [])


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
            "text": (f"Hi {first_name},\n\nYour code to create your Chioma web chat account is {code}.\n"
                     f"It works for {CODE_MINUTES} minutes.\n\nIf you didn't ask for this, you can ignore this email."),
        })
        return True
    except Exception:
        logger.exception("[WEB-ONLY-1a] sign-up code email failed")
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
    today = len(db.table("chat_signup_requests").select("id").eq("status", "verified").gte("verified_at", _iso(now - timedelta(hours=24))).execute().data or [])
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
        db.table("chat_signup_requests").insert({**row, "code_hash": "-", "status": "blocked"}).execute()
        return {"request_id": request_id, "email_hint": hint}
    code = f"{secrets.randbelow(1_000_000):06d}"
    if not _send_code_email(data["email"], data["full_name"].split(" ")[0], code):
        raise SignupError("We couldn't send your code right now. Please try again in a few minutes.", 503, "SERVICE_UNAVAILABLE")
    db.table("chat_signup_requests").insert({**row, "code_hash": _code_hash(request_id, code), "status": "pending"}).execute()
    return {"request_id": request_id, "email_hint": hint}


# -- step 2 ------------------------------------------------------------------------------------------------------------
def verify(db: Any, request_id: str, code: str, password: str, now: Optional[datetime] = None) -> dict:
    """Creates the business. Returns {"email", "org_id", "starter_credit_ngn"}."""
    now = now or _now()
    code = re.sub(r"\D", "", str(code or ""))
    bad = SignupError("That code isn't right. Check the email and try again.")
    if len(code) != 6 or not request_id:
        raise bad
    if len(password or "") < 8 or len(password) > 72:
        raise SignupError("Choose a password of 8 to 72 characters.")
    req = _one((db.table("chat_signup_requests").select("*").eq("id", str(request_id)).limit(1).execute()).data)
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
        db.table("chat_signup_requests").update(update).eq("id", req["id"]).execute()
        if attempts >= MAX_ATTEMPTS:
            raise SignupError("Too many wrong codes. Please start again.")
        raise bad
    claim = db.table("chat_signup_requests").update({"status": "verified", "verified_at": _iso(now), "attempts": attempts}) \
        .eq("id", req["id"]).eq("status", "pending").execute()
    if not claim.data:
        raise expired
    try:
        made = prov.provision_wa_org(db, business_name=req["business_name"], owner_name=req["full_name"], email=req["email"],
                                     password=password, whatsapp=req["phone_number"], product_mode="web_chat")
    except prov.ProvisionError as exc:
        db.table("chat_signup_requests").update({"status": "blocked"}).eq("id", req["id"]).execute()
        raise SignupError(str(exc), exc.status_code, exc.code)
    org_id = made["org_id"]
    try:
        db.table("chat_signup_requests").update({"org_id": org_id}).eq("id", req["id"]).execute()
    except Exception:
        pass
    settings = get_settings(db)
    _start_free_plan(db, org_id, now)
    _turn_on_ai(db, org_id, req.get("phone_number"))
    _open_wallet(db, org_id, settings["starter_credit_ngn"])
    _tell_platform(db, org_id, req)
    return {"email": req["email"], "org_id": org_id, "starter_credit_ngn": settings["starter_credit_ngn"]}


def _start_free_plan(db: Any, org_id: str, now: datetime) -> None:
    """A Chioma plan row with source 'free' and no end date: web chat is on while there is credit (see the module note)."""
    try:
        db.table("org_plans").insert({"org_id": org_id, "kind": "tier", "key": TIER_KEY, "status": "active", "source": "free", "price_ngn": 0,
                                      "paid_until": None, "config": {}, "created_at": _iso(now), "updated_at": _iso(now)}).execute()
        from app.services import account_entitlement_service as acc
        acc._log_event(db, org_id, "system", "free_plan_started", {"key": TIER_KEY})
    except Exception as exc:
        logger.error("chat_signup: free plan not started org=%s: %s", org_id, exc)


def _turn_on_ai(db: Any, org_id: str, phone: Any = None) -> None:
    """Chioma's AI answers are the point of this product, so they start ON (the web chat default is off), and she may read the product list. The owner can switch
    them off in Admin > Web Chat. Existing settings in the web chat config are kept."""
    try:
        rows = (db.table("organisations").select("webchat_config").eq("id", org_id).limit(1).execute().data) or []
        cfg = dict((rows[0].get("webchat_config") if rows else None) or {})
        cfg["ai_enabled"] = True
        cfg["answer_first"] = True            # she answers first and asks for details after the first answer
        cfg["products_read"] = True           # ONLY-1c-PRODUCTS: she answers price and stock questions from the Products tab (no cards or cart)
        number = _call_number(phone)
        if number:                            # ONLY-1c-DOWN: the phone icon and Call us work from day one, on the owner's own number (editable)
            cfg.setdefault("call_enabled", True)
            cfg.setdefault("call_number", number)
        db.table("organisations").update({"webchat_config": cfg}).eq("id", org_id).execute()
    except Exception as exc:
        logger.error("chat_signup: AI not switched on org=%s: %s", org_id, exc)


def _call_number(phone: Any) -> str:
    try:
        from app.services import webchat_service as wc
        return wc.normalise_phone(str(phone or "")) or ""
    except Exception:
        return ""


def _open_wallet(db: Any, org_id: str, starter_ngn: int) -> None:
    """Metering ON from day one, so every chat is paid from credit. The starter credit is idempotent (reference chat_signup_<org>)
    and does not expire. No Meta billing line: this business has no WhatsApp."""
    try:
        db.table("credit_wallets").upsert({"org_id": org_id, "metering_enabled": True}, on_conflict="org_id").execute()
    except Exception as exc:
        logger.error("chat_signup: wallet not opened org=%s: %s", org_id, exc)
    if starter_ngn and starter_ngn > 0:
        try:
            from app.services import credit_service
            credit_service.add_credit(db, org_id, int(starter_ngn) * 100, "adjust", f"chat_signup_{org_id}", {"reason": "starter credit"})
        except Exception as exc:
            logger.error("chat_signup: starter credit failed org=%s: %s", org_id, exc)


def _tell_platform(db: Any, org_id: str, req: dict) -> None:
    try:
        from app.services import platform_guard as pg
        pid = pg.platform_id(db)
        if not pid:
            return
        for u in db.table("users").select("id, roles(template)").eq("org_id", pid).execute().data or []:
            roles = u.get("roles") if isinstance(u.get("roles"), dict) else {}
            if (roles.get("template") or "") not in ("owner", "ops_manager"):
                continue
            db.table("notifications").insert({
                "org_id": pid, "user_id": u["id"], "title": f"New Chioma sign-up: {req['business_name']}",
                "body": f"{req['full_name']}, {req['phone_number']}. Their free Chioma account has started."[:1000], "type": "chat_signup",
                "resource_type": "organisation", "resource_id": org_id, "is_read": False, "created_at": _iso(),
            }).execute()
    except Exception as exc:
        logger.warning("chat_signup: platform notification failed org=%s: %s", org_id, exc)
