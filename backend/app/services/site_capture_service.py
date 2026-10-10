"""
app/services/site_capture_service.py
--------------------------------------
SITE-ADDONS A1-1 - lead capture from a client's site (the Capture tier).

A site has a public KEY (it sits in the page; it never reveals an org or site id). The enquiry form and the tracked
WhatsApp link use it. Behind the key:

  key -> site -> entitlement check (site_entitlement_service.has_feature, in the SITE's own org)
      -> the client's WORKSPACE (a separate organisation that holds only that client's leads; decision D1)
      -> a lead created through lead_service.create_lead, tagged with the site, source and consent
      -> an instant reply to the visitor and an alert to the owner, each only when its feature is on.

Workspace organisations are created with subscription_status "site_workspace", so every org-wide worker that gates on
active/grace skips them; they have no real users, only one hidden system user the leads are assigned to.

S14: nothing in the messaging part raises. The lead is saved before any message is attempted.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote, urlparse

from app.services import site_entitlement_service as ent

logger = logging.getLogger(__name__)

REPLY_TEMPLATE_ENV = "SITE_LEAD_REPLY_TEMPLATE"     # approved WhatsApp template: {{1}} visitor name, {{2}} business
ALERT_TEMPLATE_ENV = "SITE_LEAD_ALERT_TEMPLATE"     # approved WhatsApp template: {{1}} business, {{2}} name, {{3}} link
REMINDER_MINUTES = 15                               # E3 (proposed): nudge the owner this long after the alert
CONSENT_VERSION = "v1"
MAX_MESSAGE = 2000
SUBMIT_PER_IP_PER_HOUR = 10
SUBMIT_PER_KEY_PER_HOUR = 120
LINK_PER_IP_PER_HOUR = 300
LINK_PER_KEY_PER_HOUR = 20000

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
_SRC_RE = re.compile(r"[^a-zA-Z0-9 _\-./:]")
_hits: dict[str, list[float]] = {}


class CaptureError(ValueError):
    """Plain-language problem the caller can show."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def public_base() -> str:
    return os.environ.get("PUBLIC_API_URL", "https://opsra.onrender.com").rstrip("/")


def form_action_url(key: str) -> str:
    return f"{public_base()}/api/v1/public/site-leads/{key}"


def wa_link_url(key: str) -> str:
    return f"{public_base()}/sl/{key}/wa"


# ---------------------------------------------------------------------------
# rate limiting (in-process, like the other public pages) and the hashed IP
# ---------------------------------------------------------------------------

def rate_limited(bucket: str, limit: int, window_s: float = 3600.0, now: Optional[float] = None) -> bool:
    import time
    now = now if now is not None else time.monotonic()
    calls = [t for t in _hits.get(bucket, []) if t > now - window_s]
    calls.append(now)
    _hits[bucket] = calls
    if len(_hits) > 20_000:
        _hits.clear()
    return len(calls) > limit


def ip_hash(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return None
    salt = os.environ.get("SITE_IP_SALT", "opsra-site-capture")
    return hashlib.sha256(f"{salt}:{ip}".encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# the site key
# ---------------------------------------------------------------------------

def _new_key() -> str:
    return "sk_" + secrets.token_urlsafe(18)


def get_or_create_key(db: Any, org_id: str, site_id: str) -> dict:
    row = _one((db.table("site_keys").select("*").eq("site_id", site_id).eq("org_id", org_id).eq("active", True)
                .limit(1).execute()).data)
    if row:
        return row
    try:
        ins = db.table("site_keys").insert({"org_id": org_id, "site_id": site_id, "key": _new_key(), "active": True}).execute()
        return ins.data[0]
    except Exception:       # another request created it first
        row = _one((db.table("site_keys").select("*").eq("site_id", site_id).eq("org_id", org_id).eq("active", True)
                    .limit(1).execute()).data)
        if row:
            return row
        raise


def rotate_key(db: Any, org_id: str, site_id: str) -> dict:
    """Switch the old key off and make a new one. Pages that still carry the old key stop capturing until republished."""
    old = _one((db.table("site_keys").select("*").eq("site_id", site_id).eq("org_id", org_id).eq("active", True)
                .limit(1).execute()).data)
    if old:
        db.table("site_keys").update({"active": False, "rotated_at": _iso(_now())}).eq("id", old["id"]).execute()
    ins = db.table("site_keys").insert({"org_id": org_id, "site_id": site_id, "key": _new_key(), "active": True}).execute()
    return ins.data[0]


def resolve_key(db: Any, key: str) -> Optional[dict]:
    """Active key -> {key_row, site}. None for anything unknown, switched off, or a deleted site."""
    if not isinstance(key, str) or not key.startswith("sk_") or len(key) > 60:
        return None
    k = _one((db.table("site_keys").select("*").eq("key", key).eq("active", True).limit(1).execute()).data)
    if not k:
        return None
    site = _one((db.table("sites").select("*").eq("id", k["site_id"]).eq("org_id", k["org_id"]).is_("deleted_at", "null")
                 .limit(1).execute()).data)
    if not site:
        return None
    return {"key": k, "site": site}


# ---------------------------------------------------------------------------
# the client workspace (decision D1)
# ---------------------------------------------------------------------------

def get_workspace(db: Any, site_id: str) -> Optional[dict]:
    return _one((db.table("site_workspaces").select("*").eq("site_id", site_id).limit(1).execute()).data)


def ensure_workspace(db: Any, org_id: str, site: dict) -> dict:
    """The client's own workspace: an organisation (never counted as a live customer), the standard roles and one
    hidden system user. Created once per site; a second call (or a parallel one) returns the same row."""
    existing = get_workspace(db, site["id"])
    if existing:
        return existing
    from app.routers.superadmin import ROLE_TEMPLATES
    slug = "site-" + secrets.token_hex(4)
    name = (site.get("client_business_name") or "Client site")[:200]
    ws_org = None
    try:
        ws_org = db.table("organisations").insert({
            "name": f"{name} (website leads)", "slug": slug, "industry": "website", "timezone": "Africa/Lagos",
            "ticket_prefix": "WS", "subscription_tier": "site_workspace", "subscription_status": "site_workspace",
            "is_live": False, "is_site_workspace": True,
            "business_hours": {d: {"start": "08:00", "end": "17:00"} for d in ("mon", "tue", "wed", "thu", "fri")}
            | {"sat": {"start": "09:00", "end": "13:00"}, "sun": {"start": None, "end": None}},
        }).execute().data[0]["id"]
        role_id = None
        for tmpl in ROLE_TEMPLATES:
            r = db.table("roles").insert({"org_id": ws_org, "name": tmpl["name"], "template": tmpl["template"],
                                          "permissions": tmpl["permissions"]}).execute()
            if tmpl["template"] == "sales_agent":
                role_id = r.data[0]["id"]
        if not role_id:
            raise CaptureError("The standard roles could not be created.")
        user_id = str(uuid.uuid4())
        db.table("users").insert({
            "id": user_id, "org_id": ws_org, "full_name": "Website enquiries", "role_id": role_id, "is_active": True,
            "is_system_user": True, "email": f"website+{ws_org}@system.opsra.internal"}).execute()
        row = {"site_id": site["id"], "org_id": org_id, "workspace_org_id": ws_org, "system_user_id": user_id}
        db.table("site_workspaces").insert(row).execute()
        return row
    except Exception as exc:
        logger.warning("site_capture: workspace creation failed site=%s: %s", site.get("id"), exc)
        won = get_workspace(db, site["id"])        # a parallel request may have finished it
        if won:
            if ws_org and won.get("workspace_org_id") != ws_org:
                _drop_org(db, ws_org)
            return won
        if ws_org:
            _drop_org(db, ws_org)
        raise


def _drop_org(db: Any, ws_org: str) -> None:
    try:
        db.table("organisations").delete().eq("id", ws_org).execute()
    except Exception as exc:
        logger.warning("site_capture: cleanup of workspace %s failed: %s", ws_org, exc)


# ---------------------------------------------------------------------------
# who to tell: the site owner
# ---------------------------------------------------------------------------

def owner_contact(db: Any, org_id: str, site: dict) -> dict:
    """The client's details: the payer on the live tier row, else the site's legal owner."""
    row = _one((db.table("site_addons").select("payer_name, payer_phone, payer_email").eq("site_id", site["id"])
                .eq("org_id", org_id).eq("kind", "tier").neq("status", "cancelled").limit(1).execute()).data) or {}
    lo = site.get("legal_owner") if isinstance(site.get("legal_owner"), dict) else {}
    return {"name": row.get("payer_name") or lo.get("full_name") or "",
            "phone": row.get("payer_phone") or lo.get("phone") or "",
            "email": row.get("payer_email") or lo.get("email") or ""}


def _business(site: dict) -> str:
    return site.get("client_business_name") or "the business"


def _digits(phone: Optional[str]) -> str:
    from app.utils.phone import normalize_phone
    return re.sub(r"\D", "", normalize_phone(phone or "") or "")


# ---------------------------------------------------------------------------
# messages (never raise)
# ---------------------------------------------------------------------------

def _send_email(to: str, subject: str, text: str) -> bool:
    from app.services.site_addon_billing_service import _send_email as send
    return send(to, subject, text)


def _send_whatsapp(db: Any, org_id: str, phone: str, text: str, *, cta: Optional[tuple] = None,
                   template_env: Optional[str] = None, template_params: Optional[list] = None,
                   in_window_only: bool = False) -> bool:
    """Inside the 24-hour window: a normal message (with a button when `cta` = (label, url)). Outside it: the approved
    template named by `template_env`, if set. Uses the shared Opsra sender of the site's organisation."""
    try:
        from app.services import funnel_messaging, site_renewal_service as renewal
        to = _digits(phone)
        number = renewal._number_row(db, org_id)
        if not to or not number:
            return False
        if renewal._in_free_window(db, org_id, to, _now()):
            if cta:
                return bool(funnel_messaging.send_cta_url(db, org_id, number, to, text, cta[0], cta[1], None))
            return bool(funnel_messaging.send_text(db, org_id, number, to, text, None))
        name = os.getenv(template_env) if template_env else None
        if name and template_params and not in_window_only:
            return bool(funnel_messaging.send_template(db, org_id, number, to, name, template_params, lead_id=None))
    except Exception as exc:  # S14
        logger.warning("site_capture: whatsapp send failed: %s", exc)
    return False


def answer_url(key: str, lead_id: str) -> str:
    return f"{public_base()}/sl/{key}/l/{lead_id}"


def reply_to_visitor(db: Any, org_id: str, site: dict, lead: dict) -> bool:
    """The instant reply. Email when there is an address; WhatsApp by the approved template when there is a phone."""
    name = (lead.get("full_name") or "there").split(" ")[0]
    biz = _business(site)
    text = f"Hi {name}, thanks for contacting {biz}. We have your message and will get back to you shortly."
    sent = False
    if lead.get("email"):
        sent = _send_email(lead["email"], f"{biz}: we got your message", text) or sent
    phone = lead.get("whatsapp") or lead.get("phone")
    if phone:
        sent = _send_whatsapp(db, org_id, phone, text, template_env=REPLY_TEMPLATE_ENV,
                              template_params=[name, biz]) or sent
    return sent


def alert_owner(db: Any, org_id: str, site: dict, key: str, lead: dict, *, again: bool = False,
                reminder: bool = False, minutes: Optional[int] = None) -> bool:
    """Tell the owner about the enquiry, with a one-tap link that opens WhatsApp to the visitor."""
    c = owner_contact(db, org_id, site)
    biz = _business(site)
    link = answer_url(key, lead["id"])
    who = lead.get("full_name") or "A visitor"
    bits = [b for b in (lead.get("phone"), lead.get("email")) if b]
    snippet = (lead.get("problem_stated") or "").strip().replace("\n", " ")[:140]
    if reminder:
        text = f"Reminder: {who} sent an enquiry to {biz}{f' {minutes} minutes ago' if minutes else ''} and has not been answered yet."
    else:
        text = f"{'Another enquiry' if again else 'New enquiry'} for {biz} from {who}" + (f" ({', '.join(bits)})" if bits else "") + "."
    if snippet:
        text += f' "{snippet}"'
    sent = False
    if c["email"]:
        sent = _send_email(c["email"], f"{biz}: enquiry from {who}", f"{text}\n\nAnswer on WhatsApp: {link}") or sent
    if c["phone"]:
        sent = _send_whatsapp(db, org_id, c["phone"], text, cta=("Answer now", link), template_env=ALERT_TEMPLATE_ENV,
                              template_params=[biz, who, link]) or sent
    return sent


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

def log_event(db: Any, org_id: str, site_id: str, key_id: Optional[str], kind: str, *, source: Optional[str] = None,
              lead_id: Optional[str] = None, ip: Optional[str] = None) -> None:
    try:
        db.table("site_lead_events").insert({
            "org_id": org_id, "site_id": site_id, "key_id": key_id, "kind": kind, "source": (source or None),
            "lead_id": lead_id, "ip_hash": ip_hash(ip)}).execute()
    except Exception as exc:  # S14
        logger.warning("site_capture: event log failed site=%s kind=%s: %s", site_id, kind, exc)


def clean_source(value: Optional[str]) -> Optional[str]:
    v = _SRC_RE.sub("", (value or "").strip())[:120]
    return v or None


# ---------------------------------------------------------------------------
# the enquiry form
# ---------------------------------------------------------------------------

def validate_submission(name: str, phone: str, email: str, message: str, consent: bool) -> dict:
    name = (name or "").strip()
    phone = re.sub(r"[^\d+\s\-()]", "", (phone or "").strip())
    email = (email or "").strip()
    message = (message or "").strip()
    if not name or len(name) > 120:
        raise CaptureError("Please enter your name.")
    if not phone and not email:
        raise CaptureError("Please enter a phone number or an email address so they can reply.")
    digits = re.sub(r"\D", "", phone)
    if phone and not (7 <= len(digits) <= 15):
        raise CaptureError("That phone number doesn't look right.")
    if email and not _EMAIL_RE.match(email):
        raise CaptureError("That email address doesn't look right.")
    if len(message) > MAX_MESSAGE:
        raise CaptureError("Your message is too long. Please shorten it.")
    if not consent:
        raise CaptureError("Please tick the box to agree that they can contact you about your enquiry.")
    return {"name": name, "phone": phone, "email": email, "message": message}


def allowed_return_url(db: Any, org_id: str, site_id: str, url: Optional[str]) -> Optional[str]:
    """The page to send the visitor back to, only if it is on one of this site's own domains."""
    try:
        u = urlparse(url or "")
        if u.scheme != "https" or not u.hostname:
            return None
        host = u.hostname.lower()
        rows = (db.table("site_domains").select("domain").eq("org_id", org_id).eq("site_id", site_id).execute()).data or []
        ok = {(r.get("domain") or "").lower() for r in rows}
        ok |= {"www." + d for d in ok if d}
        return url if host in ok else None
    except Exception:
        return None


def submit(db: Any, key: str, fields: dict, *, ip: Optional[str] = None, src: Optional[str] = None,
           return_to: Optional[str] = None, honeypot: str = "") -> dict:
    """Handle one enquiry. Returns {"status": ..., ...}:
      "unknown"  the key is not valid
      "off"      the plan does not include the form right now (the page should send the visitor to WhatsApp)
      "ok"       saved ({"business", "back_url", "wa_url", "lead_id"})
    Raises CaptureError for a field problem the visitor can fix. Never raises for message-sending problems."""
    found = resolve_key(db, key)
    if not found:
        return {"status": "unknown"}
    site, krow = found["site"], found["key"]
    org_id = site["org_id"]
    source = clean_source(src)

    if honeypot:                                   # a bot filled the hidden field: look like success, save nothing
        log_event(db, org_id, site["id"], krow["id"], "form_rejected", source="honeypot", ip=ip)
        return {"status": "ok", "business": _business(site), "back_url": None, "wa_url": None, "lead_id": None}

    if not ent.has_feature(db, org_id, site["id"], "form_instant_reply"):
        return {"status": "off", "business": _business(site), "wa_url": _site_wa_url(site, None),
                "back_url": allowed_return_url(db, org_id, site["id"], return_to)}

    consent = bool(fields.get("consent"))
    clean = validate_submission(fields.get("name", ""), fields.get("phone", ""), fields.get("email", ""),
                                fields.get("message", ""), consent)

    ws = ensure_workspace(db, org_id, site)
    ws_org = ws["workspace_org_id"]
    phone = clean["phone"] or None
    again = _existing_lead(db, ws_org, phone) if phone else None
    now = _now()
    use_alerts = ent.has_feature(db, org_id, site["id"], "speed_alerts")
    track = ent.has_feature(db, org_id, site["id"], "source_tracking")

    if again:
        lead = again
        db.table("leads").update({"last_activity_at": _iso(now), "answered_at": None,
                                  "alert_reminder_at": _iso(now + timedelta(minutes=REMINDER_MINUTES)) if use_alerts else None
                                  }).eq("id", again["id"]).eq("org_id", ws_org).execute()
    else:
        lead = _create_lead(db, ws_org, ws["system_user_id"], clean, site, source if track else None, now,
                            _iso(now + timedelta(minutes=REMINDER_MINUTES)) if use_alerts else None)
    log_event(db, org_id, site["id"], krow["id"], "form_submit", source=source, lead_id=lead.get("id"), ip=ip)

    # Messages: the lead is already saved, so a failure here only costs a message.
    try:
        if not again:
            reply_to_visitor(db, org_id, site, lead)
        if use_alerts and lead.get("id"):
            alert_owner(db, org_id, site, krow["key"], lead, again=bool(again))
    except Exception as exc:  # S14
        logger.warning("site_capture: messages failed site=%s: %s", site["id"], exc)

    return {"status": "ok", "business": _business(site), "lead_id": lead.get("id"),
            "back_url": allowed_return_url(db, org_id, site["id"], return_to),
            "wa_url": _site_wa_url(site, None)}


def _existing_lead(db: Any, ws_org: str, phone: str) -> Optional[dict]:
    from app.services.lead_service import _normalise_phone
    p = _normalise_phone(phone)
    if not p:
        return None
    return _one((db.table("leads").select("*").eq("org_id", ws_org).eq("phone", p).is_("deleted_at", "null")
                 .neq("stage", "lost").limit(1).execute()).data)


def _create_lead(db: Any, ws_org: str, system_user_id: str, clean: dict, site: dict, source: Optional[str],
                 now: datetime, reminder_at: Optional[str]) -> dict:
    from app.models.leads import LeadCreate
    from app.services import lead_service
    payload = LeadCreate(full_name=clean["name"], source="landing_page", phone=clean["phone"] or None,
                         email=clean["email"] or None, problem_stated=clean["message"] or None,
                         business_name=None, assigned_to=system_user_id)
    lead = lead_service.create_lead(db, ws_org, system_user_id, payload, entry_path="website_form")
    patch = {"site_id": site["id"], "consent_at": _iso(now), "consent_version": CONSENT_VERSION,
             "source_detail": source, "alert_reminder_at": reminder_at}
    if lead.get("id"):
        db.table("leads").update(patch).eq("id", lead["id"]).eq("org_id", ws_org).execute()
    return {**lead, **patch}


def _site_wa_url(site: dict, text: Optional[str]) -> Optional[str]:
    biz = (site.get("content") or {}).get("business") if isinstance(site.get("content"), dict) else None
    num = re.sub(r"\D", "", str((biz or {}).get("whatsapp_e164") or ""))
    if not num:
        return None
    return f"https://wa.me/{num}" + (f"?text={quote(text)}" if text else "")


# ---------------------------------------------------------------------------
# the tracked WhatsApp link and the owner's "answer now" link
# ---------------------------------------------------------------------------

def wa_redirect(db: Any, key: str, src: Optional[str], text: Optional[str], ip: Optional[str] = None) -> Optional[str]:
    """Log the click (when source tracking is on) and return the wa.me address to send the visitor to. None = bad key.
    The address comes from the site's own content, never from the request, so the link cannot be pointed elsewhere."""
    found = resolve_key(db, key)
    if not found:
        return None
    site, krow = found["site"], found["key"]
    if ent.has_feature(db, site["org_id"], site["id"], "source_tracking"):
        log_event(db, site["org_id"], site["id"], krow["id"], "wa_click", source=clean_source(src), ip=ip)
    return _site_wa_url(site, (text or "")[:300] or None)


def answer_redirect(db: Any, key: str, lead_id: str, ip: Optional[str] = None) -> Optional[str]:
    """The owner tapped 'Answer now': mark the lead answered (stops the reminder) and open WhatsApp to the visitor."""
    found = resolve_key(db, key)
    ws = get_workspace(db, found["site"]["id"]) if found else None
    if not found or not ws:
        return None
    site, krow = found["site"], found["key"]
    lead = _one((db.table("leads").select("*").eq("id", lead_id).eq("org_id", ws["workspace_org_id"])
                 .eq("site_id", site["id"]).limit(1).execute()).data)
    if not lead:
        return None
    now = _now()
    db.table("leads").update({"answered_at": _iso(now), "alert_reminder_at": None}) \
        .eq("id", lead_id).eq("org_id", ws["workspace_org_id"]).is_("answered_at", "null").execute()
    log_event(db, site["org_id"], site["id"], krow["id"], "answer_tap", lead_id=lead_id, ip=ip)
    first = (lead.get("full_name") or "there").split(" ")[0]
    digits = _digits(lead.get("whatsapp") or lead.get("phone"))
    if digits:
        return f"https://wa.me/{digits}?text={quote(f'Hi {first}, this is {_business(site)}. Thanks for your enquiry.')}"
    if lead.get("email"):
        return f"mailto:{quote(lead['email'])}"
    return None


# ---------------------------------------------------------------------------
# the reminder sweep (every few minutes)
# ---------------------------------------------------------------------------

def run_reminders(db: Any, now: Optional[datetime] = None) -> dict:
    """Owners who have not tapped 'Answer now' get one reminder. Each lead is claimed with a conditional update so two
    runs can never both send, and one bad row never stops the rest (S14)."""
    now = now or _now()
    result = {"checked": 0, "sent": 0, "skipped": 0, "failed": 0}
    try:
        rows = (db.table("leads").select("id, org_id, site_id, alert_reminder_at, full_name, phone, whatsapp, email, problem_stated")
                .lte("alert_reminder_at", _iso(now)).is_("answered_at", "null").limit(200).execute()).data or []
    except Exception as exc:  # S14
        logger.warning("site_capture reminders: list failed: %s", exc)
        result["failed"] += 1
        return result
    for lead in rows:
        result["checked"] += 1
        try:
            claim = (db.table("leads").update({"alert_reminder_at": None}).eq("id", lead["id"])
                     .eq("alert_reminder_at", lead["alert_reminder_at"]).execute())
            if not claim.data:
                result["skipped"] += 1
                continue
            site = _one((db.table("sites").select("*").eq("id", lead["site_id"]).is_("deleted_at", "null").limit(1).execute()).data)
            if not site or not ent.has_feature(db, site["org_id"], site["id"], "speed_alerts"):
                result["skipped"] += 1
                continue
            krow = get_or_create_key(db, site["org_id"], site["id"])
            if alert_owner(db, site["org_id"], site, krow["key"], lead, reminder=True, minutes=REMINDER_MINUTES):
                result["sent"] += 1
            else:
                result["failed"] += 1
        except Exception as exc:  # S14
            result["failed"] += 1
            logger.warning("site_capture reminders: lead %s failed: %s", lead.get("id"), exc)
    return result


# ---------------------------------------------------------------------------
# staff view
# ---------------------------------------------------------------------------

def summary(db: Any, org_id: str, site_id: str, days: int = 30) -> dict:
    """What the staff card shows for a site: the key, the form address, the workspace and the last `days` of activity."""
    ent._site_exists(db, org_id, site_id)
    k = get_or_create_key(db, org_id, site_id)
    ws = get_workspace(db, site_id)
    since = _iso(_now() - timedelta(days=days))
    events = (db.table("site_lead_events").select("kind").eq("site_id", site_id).eq("org_id", org_id)
              .gte("created_at", since).execute()).data or []
    counts = {"form_submit": 0, "wa_click": 0, "form_rejected": 0, "answer_tap": 0}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    leads = 0
    if ws:
        leads = len((db.table("leads").select("id").eq("org_id", ws["workspace_org_id"]).eq("site_id", site_id)
                     .is_("deleted_at", "null").execute()).data or [])
    return {"key": k["key"], "form_action": form_action_url(k["key"]), "wa_link": wa_link_url(k["key"]),
            "workspace": bool(ws), "leads_total": leads, "days": days, "events": counts,
            "features": {f: ent.has_feature(db, org_id, site_id, f) for f in ("form_instant_reply", "source_tracking", "speed_alerts")}}
