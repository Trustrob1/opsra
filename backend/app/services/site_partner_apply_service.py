"""
app/services/site_partner_apply_service.py
-------------------------------------------
PARTNER-1B — apply to become a Launch Partner on the website, and sign in as one.

  start()   validate, rate-limit, email a 6-digit code  (row status pending_code)
  verify()  correct code -> status "applied" (waits for Opsra staff)
  approve() / decline()   staff decision; approve creates the partner (PARTNER-1A create_partner)
  request_login_link()    background task: sign-in link to the partner's email AND WhatsApp
  referrals()             the partner's own clients (business name, phone, website, status)

The email is proven by the code; the WhatsApp number is typed, not proven (same known limit as
builder sign-up). The sign-in link therefore goes to both channels. Reuses the builder session and
single-use link table, so a partner is signed in by the existing /builder/auth/exchange.
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.services import builder_login_service, builder_signup_service as bss, site_partner_service

logger = logging.getLogger(__name__)

CODE_MINUTES = 15
MAX_ATTEMPTS = 5
PER_IP_HOUR = 5
PER_EMAIL_HOUR = 3
PER_PHONE_HOUR = 3
LOGIN_LINK_MINUTES = 60
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")

STATUS_LABELS = {
    "brief_in_progress": "Filling the form", "brief_complete": "Brief received", "generating": "Being built",
    "preview_ready": "Preview ready", "revising": "Being revised", "hosting_checkout": "Payment started",
    "awaiting_payment": "Awaiting payment", "paid": "Paid", "publishing": "Going live", "live": "Live",
    "renewal_due": "Live", "lapsed": "Lapsed", "cancelled": "Cancelled",
}


class ApplyError(Exception):
    status_code = 422
    code = "VALIDATION_ERROR"


class ApplyRateLimited(ApplyError):
    status_code = 429
    code = "RATE_LIMITED"


class ApplyUnavailable(ApplyError):
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


def _code_hash(request_id: str, code: str) -> str:
    import hashlib
    return hashlib.sha256(f"partner-apply:{request_id}:{code}".encode("utf-8")).hexdigest()


def _base() -> str:
    return os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/")


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
    except Exception:
        logger.exception("[PARTNER-1B] email failed")
        return False


def _clean(payload: dict) -> dict:
    payload = payload or {}
    name = re.sub(r"\s+", " ", str(payload.get("full_name") or "")).strip()
    email = str(payload.get("email") or "").strip().lower()
    variants = builder_login_service.phone_variants(str(payload.get("phone") or ""))
    agency = re.sub(r"\s+", " ", str(payload.get("agency_name") or "")).strip()[:200] or None
    if not (2 <= len(name) <= 80):
        raise ApplyError("Please enter your name.")
    if not _EMAIL_RE.match(email) or len(email) > 255:
        raise ApplyError("Please enter a valid email address.")
    if not variants:
        raise ApplyError("Please enter your WhatsApp number.")
    if payload.get("accept_terms") is not True:
        raise ApplyError("Please accept the terms to continue.")
    return {"full_name": name, "email": email, "phone": variants[1], "agency_name": agency}


def _count_since(db: Any, org_id: str, column: str, value: str, since: datetime) -> int:
    rows = (db.table("site_partner_applications").select("id").eq("org_id", org_id).eq(column, value)
            .gte("created_at", _iso(since)).execute()).data or []
    return len(rows)


def start(db: Any, payload: dict, ip: str, send_login_link=None, now: Optional[datetime] = None) -> dict:
    """Returns {"request_id", "email_hint"}. Same reply whether or not the person is already a partner."""
    now = now or _now()
    if (payload or {}).get("website"):                       # honeypot
        return {"request_id": str(uuid.uuid4()), "email_hint": "***"}
    data = _clean(payload)
    org_id = bss.resolve_org(db)
    if not org_id:
        raise ApplyUnavailable("Applications aren't open right now.")

    ip_hash = bss.hash_ip("partner:" + (ip or "unknown"))
    hour = now - timedelta(hours=1)
    if (_count_since(db, org_id, "ip_hash", ip_hash, hour) >= PER_IP_HOUR
            or _count_since(db, org_id, "email", data["email"], hour) >= PER_EMAIL_HOUR
            or _count_since(db, org_id, "phone_number", data["phone"], hour) >= PER_PHONE_HOUR):
        raise ApplyRateLimited("Too many attempts. Please try again in an hour.")

    request_id = str(uuid.uuid4())
    row = {"id": request_id, "org_id": org_id, "full_name": data["full_name"], "email": data["email"],
           "phone_number": data["phone"], "agency_name": data["agency_name"], "ip_hash": ip_hash,
           "attempts": 0, "expires_at": _iso(now + timedelta(minutes=CODE_MINUTES)), "created_at": _iso(now)}
    hint = bss.mask_email(data["email"])

    partner = _one((db.table("site_partners").select("id,status").eq("org_id", org_id)
                    .in_("phone_number", [data["phone"]]).limit(1).execute()).data)
    if not partner:
        partner = _one((db.table("site_partners").select("id,status").eq("org_id", org_id)
                        .eq("email", data["email"]).limit(1).execute()).data)
    waiting = _one((db.table("site_partner_applications").select("id").eq("org_id", org_id)
                    .eq("email", data["email"]).in_("status", ["applied"]).limit(1).execute()).data)
    if partner or waiting:                                   # no code; an existing partner gets a sign-in link
        db.table("site_partner_applications").insert({**row, "code_hash": "-", "status": "blocked"}).execute()
        if partner and partner.get("status") == "active" and send_login_link:
            send_login_link(data["email"])
        return {"request_id": request_id, "email_hint": hint}

    code = f"{secrets.randbelow(1_000_000):06d}"
    first = data["full_name"].split(" ")[0]
    if not _send_email(data["email"], f"Your Opsra partner application code: {code}",
                       f"Hi {first},\n\nYour code to continue your Opsra Launch Partner application is {code}.\n"
                       f"It works for {CODE_MINUTES} minutes.\n\nIf you didn't ask for this, you can ignore this email."):
        raise ApplyUnavailable("We couldn't send your code right now. Please try again in a few minutes.")
    db.table("site_partner_applications").insert({**row, "code_hash": _code_hash(request_id, code),
                                                   "status": "pending_code"}).execute()
    return {"request_id": request_id, "email_hint": hint}


def verify(db: Any, request_id: str, code: str, now: Optional[datetime] = None) -> dict:
    now = now or _now()
    code = re.sub(r"\D", "", str(code or ""))
    bad = ApplyError("That code isn't right. Check the email and try again.")
    if len(code) != 6 or not request_id:
        raise bad
    req = _one((db.table("site_partner_applications").select("*").eq("id", str(request_id)).limit(1).execute()).data)
    if not req or req.get("status") != "pending_code":
        raise ApplyError("This code has expired. Please start again.")
    expires = bss._parse(req.get("expires_at"))
    if not expires or expires < now:
        raise ApplyError("This code has expired. Please start again.")
    attempts = int(req.get("attempts") or 0) + 1
    if not hmac.compare_digest(_code_hash(req["id"], code), req.get("code_hash") or ""):
        update = {"attempts": attempts}
        if attempts >= MAX_ATTEMPTS:
            update["status"] = "blocked"
        db.table("site_partner_applications").update(update).eq("id", req["id"]).execute()
        if attempts >= MAX_ATTEMPTS:
            raise ApplyError("Too many wrong codes. Please start again.")
        raise bad
    claim = (db.table("site_partner_applications")
             .update({"status": "applied", "verified_at": _iso(now), "attempts": attempts})
             .eq("id", req["id"]).eq("status", "pending_code").execute())
    if not claim.data:
        raise ApplyError("This code has expired. Please start again.")
    return _one(claim.data)


# ───────────────────────────── staff ─────────────────────────────

def list_applications(db: Any, org_id: str, status: Optional[str] = "applied") -> list[dict]:
    q = db.table("site_partner_applications").select("*").eq("org_id", org_id)
    if status:
        q = q.eq("status", status)
    rows = q.order("created_at", desc=True).limit(500).execute().data or []
    return [{k: v for k, v in r.items() if k not in ("code_hash", "ip_hash")} for r in rows]


def approve(db: Any, org_id: str, application_id: str, send_login_link=None) -> dict:
    app = _one((db.table("site_partner_applications").select("*").eq("id", application_id)
                .eq("org_id", org_id).limit(1).execute()).data)
    if not app:
        raise ApplyError("Application not found.")
    if app.get("status") != "applied":
        raise ApplyError("Only verified, waiting applications can be approved.")
    try:
        partner = site_partner_service.create_partner(db, org_id, app["full_name"], app["phone_number"],
                                                      app["email"], app.get("agency_name"))
    except site_partner_service.PartnerError as exc:
        raise ApplyError(str(exc))
    db.table("site_partner_applications").update(
        {"status": "approved", "decided_at": _iso(), "partner_id": partner.get("id")}
    ).eq("id", application_id).eq("org_id", org_id).execute()
    first = app["full_name"].split(" ")[0]
    _send_email(app["email"], "You're approved as an Opsra Launch Partner",
                f"Hi {first},\n\nYour Launch Partner application has been approved.\n\n"
                f"Sign in here any time with your email or WhatsApp number:\n{_base()}/partner\n\n"
                "There you'll find your personal client link and your referrals.")
    if send_login_link:
        send_login_link(app["email"])
    return partner


def decline(db: Any, org_id: str, application_id: str) -> dict:
    res = (db.table("site_partner_applications").update({"status": "declined", "decided_at": _iso()})
           .eq("id", application_id).eq("org_id", org_id).eq("status", "applied").execute())
    row = _one(res.data)
    if not row:
        raise ApplyError("Only verified, waiting applications can be declined.")
    return row


# ───────────────────────────── partner sign-in ─────────────────────────────

def find_active_partner(db: Any, identifier: str) -> Optional[dict]:
    ident = str(identifier or "").strip()
    if not ident:
        return None
    if "@" in ident:
        email = ident.lower()
        if not _EMAIL_RE.match(email):
            return None
        row = _one((db.table("site_partners").select("*").eq("email", email).eq("status", "active").limit(1).execute()).data)
    else:
        variants = builder_login_service.phone_variants(ident)
        if not variants:
            return None
        row = _one((db.table("site_partners").select("*").in_("phone_number", variants)
                    .eq("status", "active").limit(1).execute()).data)
    return row


def request_login_link(identifier: str) -> None:
    """Background task. Never raises; sends the link to the partner's own email and WhatsApp only."""
    try:
        from app.database import get_supabase
        db = get_supabase()
        partner = find_active_partner(db, identifier)
        if not partner:
            return
        builder = _one((db.table("site_builders").select("*").eq("id", partner["builder_id"])
                        .eq("org_id", partner["org_id"]).eq("status", "active").limit(1).execute()).data)
        if not builder:
            return
        raw = bss.mint_login_token(db, builder, minutes=LOGIN_LINK_MINUTES)
        url = f"{_base()}/partner/login?t={raw}"
        first = (partner.get("full_name") or "").split(" ")[0] or "there"
        text = (f"Hi {first}, here's your Opsra partner sign-in link. It works once and expires in "
                f"{LOGIN_LINK_MINUTES} minutes:\n\n{url}")
        for step in (lambda: builder_login_service._send_whatsapp(db, builder, text),
                     lambda: _send_email(partner.get("email") or builder.get("email") or "",
                                         "Your Opsra partner sign-in link", text + "\n\nIf you didn't ask for this, ignore this message.")):
            try:
                step()
            except Exception:
                logger.exception("[PARTNER-1B] link delivery step failed partner=%s", partner.get("id"))
    except Exception:
        logger.exception("[PARTNER-1B] request_login_link failed")


# ───────────────────────────── portal data ─────────────────────────────

def _phone_of(site: dict) -> Optional[str]:
    biz = ((site.get("content") or {}).get("business")) or {}
    if biz.get("phone_display") and not str(biz.get("phone_display")).startswith("0800 000"):
        return biz.get("phone_display")
    if biz.get("whatsapp_e164"):
        return biz.get("whatsapp_e164")
    brief = site.get("brief") or {}
    if isinstance(brief, dict):
        for k, v in brief.items():
            if isinstance(v, str) and re.search(r"phone|whatsapp", str(k), re.I) and v.strip():
                return v.strip()
    return None


def referrals(db: Any, partner: dict) -> list[dict]:
    rows = (db.table("sites").select("id,client_business_name,slug,status,content,brief,live_url,created_at,updated_at")
            .eq("org_id", partner["org_id"]).eq("builder_id", partner["builder_id"])
            .is_("deleted_at", "null").order("created_at", desc=True).limit(500).execute()).data or []
    out = []
    for s in rows:
        st = s.get("status") or ""
        out.append({
            "id": s["id"], "business_name": s.get("client_business_name") or "(not named yet)",
            "phone": _phone_of(s), "website": s.get("live_url") or None,
            "preview_path": f"/s/{s['slug']}" if s.get("slug") and st in ("preview_ready", "revising") else None,
            "status": st, "status_label": STATUS_LABELS.get(st, st.replace("_", " ").title()),
            "created_at": s.get("created_at"),
        })
    return out
