"""
app/services/realtor_service.py - REALTOR-LINE-1

A WhatsApp line for realtors (internal and external) on the developer's official number.

A registered staff member (a user whose profile has a WhatsApp number and whose role is sales_agent or affiliate_partner) who
messages the business number gets a realtor menu instead of the buyer menu:

  Register a client   name, WhatsApp number, plot interest. Locks the client to that realtor for `lock_days`; a second realtor
                      (or Ollic's own records) cannot register the same number inside the lock.
  My clients          stage, site visit and payments per client, for that realtor's clients only.
  Request a site visit  pick a client, a day, a time and a group size. Lands as a pending booking ("Needs approval") for the admin.
  Marketing kit       flyer image and text set by the admin.
  My commission       totals by status and the latest entries.

Switched on per organisation with whatsapp_triage_config.realtor_line.enabled = true, so no other organisation changes behaviour.

Also here: the realtor is told when a site visit is confirmed and when the admin records a payment (record_payment also creates the
commission through commissions_service). S14: every public function that runs inside a webhook or a confirmation never raises.
"""
from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SESSION_MINUTES = 30
REALTOR_TEMPLATES = ("sales_agent", "affiliate_partner")
DEFAULT_LOCK_DAYS = 60
DEFAULT_INTERESTS = ["Residential plot", "Commercial plot", "Not sure yet"]
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

MENU_ROWS = [
    ("rl:register", "Register a client", "Lock a new client to you"),
    ("rl:clients", "My clients", "Stage, visit and payments"),
    ("rl:visit", "Request a site visit", "For one of your clients"),
    ("rl:kit", "Marketing kit", "Flyers and price list"),
    ("rl:money", "My commission", "What you have earned"),
]


# ───────────────────────────── small helpers ─────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _digits(value) -> str:
    """Phone as country-code digits (2348031234567): what WhatsApp sends and what inbound leads are stored as.
    A realtor will type 0803..., +234803... or 803...; lead_service's own cleaner keeps a leading 0, so it is not used here."""
    try:
        from app.utils.phone import normalize_phone
        v = normalize_phone(str(value or "")) or ""
    except Exception:
        v = str(value or "")
    v = "".join(ch for ch in v if ch.isdigit())
    if len(v) == 10 and v[0] in "789":       # Nigerian number typed without the leading 0
        v = "234" + v
    return v


def _naira(amount) -> str:
    try:
        return f"N{float(amount):,.0f}"
    except Exception:
        return "N0"


def _parse_dt(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _config(db, org_id: str) -> tuple[dict, dict]:
    """(realtor_line config, org row)."""
    rows = (db.table("organisations").select("whatsapp_triage_config, timezone, name, pipeline_stages")
            .eq("id", org_id).limit(1).execute().data or [])
    org = rows[0] if rows else {}
    cfg = ((org.get("whatsapp_triage_config") or {}).get("realtor_line")) or {}
    return cfg, org


def _tz(org: dict) -> ZoneInfo:
    try:
        return ZoneInfo(org.get("timezone") or "Africa/Lagos")
    except Exception:
        return ZoneInfo("Africa/Lagos")


# ───────────────────────────── who is a realtor ─────────────────────────────

def find_realtor(db, org_id: str, phone: str) -> Optional[dict]:
    """The active realtor whose profile WhatsApp number is this phone, or None."""
    want = _digits(phone)
    if not want:
        return None
    rows = (db.table("users").select("id, full_name, whatsapp_number, roles(template)")
            .eq("org_id", org_id).eq("is_active", True).not_.is_("whatsapp_number", "null").execute().data or [])
    for r in rows:
        if _digits(r.get("whatsapp_number")) != want:
            continue
        role = _one(r.get("roles")) or {}
        if role.get("template") in REALTOR_TEMPLATES:
            return {"id": r["id"], "name": (r.get("full_name") or "").strip() or "there", "number": r.get("whatsapp_number")}
    return None


# ───────────────────────────── conversation state ─────────────────────────────

def _get_session(db, org_id: str, phone: str) -> Optional[dict]:
    rows = db.table("realtor_sessions").select("*").eq("org_id", org_id).eq("phone", phone).limit(1).execute().data or []
    if not rows:
        return None
    exp = _parse_dt(rows[0].get("expires_at"))
    if not exp or exp < _now():
        return None
    return rows[0]


def _set_session(db, org_id: str, phone: str, step: str, data: dict) -> None:
    db.table("realtor_sessions").upsert(
        {"org_id": org_id, "phone": phone, "step": step, "data": data,
         "expires_at": _iso(_now() + timedelta(minutes=SESSION_MINUTES)), "updated_at": _iso()},
        on_conflict="org_id,phone").execute()


def _clear_session(db, org_id: str, phone: str) -> None:
    try:
        db.table("realtor_sessions").delete().eq("org_id", org_id).eq("phone", phone).execute()
    except Exception as exc:
        logger.warning("realtor session clear failed: %s", exc)


# ───────────────────────────── sending ─────────────────────────────

def _send(db, org_id: str, to: str, payload: dict) -> bool:
    try:
        from app.services.whatsapp_service import _call_meta_send, _get_org_wa_credentials
        phone_id, token, _ = _get_org_wa_credentials(db, org_id)
        if not (phone_id or "").strip() or not token:
            return False
        _call_meta_send(phone_id.strip(), {"messaging_product": "whatsapp", "to": to, **payload}, token=token)
        return True
    except Exception as exc:
        logger.warning("realtor line send failed org=%s: %s", org_id, exc)
        return False


def _text(db, org_id, to, body) -> bool:
    return _send(db, org_id, to, {"type": "text", "text": {"body": body[:4000], "preview_url": True}})


def _list(db, org_id, to, body, button, rows, section_title="Choose one") -> bool:
    rows = [{"id": r[0], "title": r[1][:24], "description": (r[2] or "")[:72]} if len(r) > 2
            else {"id": r[0], "title": r[1][:24]} for r in rows]
    return _send(db, org_id, to, {"type": "interactive", "interactive": {
        "type": "list", "body": {"text": body[:1024]},
        "action": {"button": button[:20], "sections": [{"title": section_title[:24], "rows": rows}]}}})


def _buttons(db, org_id, to, body, buttons) -> bool:
    return _send(db, org_id, to, {"type": "interactive", "interactive": {
        "type": "button", "body": {"text": body[:1024]},
        "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons]}}})


def _image(db, org_id, to, url) -> bool:
    return _send(db, org_id, to, {"type": "image", "image": {"link": url}})


def _first(name: str) -> str:
    return (name or "there").split()[0]


def _show_menu(db, org_id, phone, realtor, cfg, lead_in: str = "") -> None:
    body = (lead_in + "\n\n" if lead_in else "") + f"Hi {_first(realtor['name'])}, this is the realtor line. What would you like to do?"
    _list(db, org_id, phone, body, "See options", MENU_ROWS, "Realtor line")


# ───────────────────────────── entry point ─────────────────────────────

def handle_inbound(db, org_id: str, sender_phone: str, contact_name, msg_type: str, content, interactive_payload) -> bool:
    """True when the message was handled here (the sender is a realtor on an org with the realtor line on). Never raises."""
    try:
        cfg, org = _config(db, org_id)
        if not cfg.get("enabled"):
            return False
        realtor = find_realtor(db, org_id, sender_phone)
        if not realtor:
            return False
    except Exception as exc:
        logger.warning("realtor line check failed org=%s: %s", org_id, exc)
        return False
    try:
        rid = None
        if msg_type == "interactive" and isinstance(interactive_payload, dict):
            rid = ((interactive_payload.get("list_reply") or {}).get("id")
                   or (interactive_payload.get("button_reply") or {}).get("id"))
        text = (content or "").strip() if msg_type == "text" else ""
        _dispatch(db, org_id, sender_phone, realtor, cfg, org, text, rid)
    except Exception as exc:
        logger.exception("realtor line failed org=%s: %s", org_id, exc)
        _text(db, org_id, sender_phone, "Sorry, something went wrong on our side. Please type menu to start again.")
    return True


def _dispatch(db, org_id, phone, realtor, cfg, org, text, rid) -> None:
    low = text.lower()
    if rid and rid.startswith("rl:"):                      # a menu choice always wins over a half-finished flow
        _clear_session(db, org_id, phone)
        return _menu_action(db, org_id, phone, realtor, cfg, org, rid)
    if low in ("menu", "hi", "hello", "hey", "start", "cancel", "help", "stop"):
        _clear_session(db, org_id, phone)
        return _show_menu(db, org_id, phone, realtor, cfg)
    sess = _get_session(db, org_id, phone)
    if not sess:
        return _show_menu(db, org_id, phone, realtor, cfg)
    step, data = sess["step"], sess.get("data") or {}
    handler = _STEPS.get(step)
    if not handler:
        _clear_session(db, org_id, phone)
        return _show_menu(db, org_id, phone, realtor, cfg)
    handler(db, org_id, phone, realtor, cfg, org, text, rid, data)


def _menu_action(db, org_id, phone, realtor, cfg, org, rid) -> None:
    if rid == "rl:register":
        _set_session(db, org_id, phone, "reg_name", {})
        _text(db, org_id, phone, "Let's register a client. What is the client's full name?\n\n(Type menu any time to stop.)")
    elif rid == "rl:clients":
        _text(db, org_id, phone, _clients_text(db, org_id, realtor, org))
        _show_menu(db, org_id, phone, realtor, cfg)
    elif rid == "rl:visit":
        clients = _active_clients(db, org_id, realtor["id"], 10)
        if not clients:
            _text(db, org_id, phone, "You have no registered clients yet. Choose Register a client first, then request the visit.")
            return _show_menu(db, org_id, phone, realtor, cfg)
        _set_session(db, org_id, phone, "visit_client", {})
        _list(db, org_id, phone, "Which client is the site visit for?", "Pick a client",
              [(f"rv:{c['id']}", c["client_name"], f"Code {c['ref_code']}") for c in clients], "Your clients")
    elif rid == "rl:kit":
        kit = cfg.get("kit") or {}
        if kit.get("image_url"):
            _image(db, org_id, phone, kit["image_url"])
        _text(db, org_id, phone, kit.get("text") or "Ask the Ollic team for the latest flyers and price list.")
        _show_menu(db, org_id, phone, realtor, cfg)
    elif rid == "rl:money":
        _text(db, org_id, phone, _commission_text(db, org_id, realtor["id"]))
        _show_menu(db, org_id, phone, realtor, cfg)
    else:
        _show_menu(db, org_id, phone, realtor, cfg)


# ───────────────────────────── register a client ─────────────────────────────

def _step_reg_name(db, org_id, phone, realtor, cfg, org, text, rid, data):
    name = " ".join(text.split())[:100]
    if len(name) < 2:
        return _text(db, org_id, phone, "Please type the client's full name.")
    _set_session(db, org_id, phone, "reg_phone", {"name": name})
    _text(db, org_id, phone, f"What is {_first(name)}'s WhatsApp number? (for example 0803 123 4567)")


def _step_reg_phone(db, org_id, phone, realtor, cfg, org, text, rid, data):
    digits = _digits(text)
    if not (10 <= len(digits) <= 15):
        return _text(db, org_id, phone, "That doesn't look like a phone number. Please type it again, for example 0803 123 4567.")
    state, info = check_client_phone(db, org_id, digits, realtor["id"])
    name = data.get("name") or "the client"
    tz = _tz(org)
    if state == "mine":
        until = _parse_dt(info.get("locked_until"))
        _clear_session(db, org_id, phone)
        _text(db, org_id, phone, f"{name} is already registered to you (code {info['ref_code']})"
              + (f", locked until {until.astimezone(tz).strftime('%d %b %Y')}." if until else "."))
        return _show_menu(db, org_id, phone, realtor, cfg)
    if state == "taken":
        until = _parse_dt(info.get("locked_until"))
        _clear_session(db, org_id, phone)
        _text(db, org_id, phone, "This number is already registered with another realtor"
              + (f" until {until.astimezone(tz).strftime('%d %b %Y')}." if until else ".")
              + " If you believe this is a mistake, please contact the Ollic team.")
        return _show_menu(db, org_id, phone, realtor, cfg)
    if state == "existing":
        since = _parse_dt(info.get("created_at"))
        _clear_session(db, org_id, phone)
        _text(db, org_id, phone, "This number is already in Ollic's records"
              + (f" since {since.astimezone(tz).strftime('%d %b %Y')}" if since else "")
              + ", so it can't be registered as a new client. If this is your client, please contact the Ollic team.")
        return _show_menu(db, org_id, phone, realtor, cfg)
    new_data = {"name": name, "client_phone": digits}
    if state == "attach":
        new_data["lead_id"] = info["id"]
    _set_session(db, org_id, phone, "reg_interest", new_data)
    interests = cfg.get("interests") or DEFAULT_INTERESTS
    _list(db, org_id, phone, f"What is {_first(name)} interested in?", "Pick one",
          [(f"ri:{i}", label) for i, label in enumerate(interests[:10])], "Interest")


def _step_reg_interest(db, org_id, phone, realtor, cfg, org, text, rid, data):
    interests = cfg.get("interests") or DEFAULT_INTERESTS
    interest = None
    if rid and rid.startswith("ri:"):
        try:
            interest = interests[int(rid[3:])]
        except Exception:
            interest = None
    elif text:
        interest = text[:100]
    if not interest:
        return _list(db, org_id, phone, "Please pick what the client is interested in.", "Pick one",
                     [(f"ri:{i}", label) for i, label in enumerate(interests[:10])], "Interest")
    rc = register_client(db, org_id, realtor, data["name"], data["client_phone"], interest,
                         int(cfg.get("lock_days") or DEFAULT_LOCK_DAYS), lead_id=data.get("lead_id"))
    _clear_session(db, org_id, phone)
    until = _parse_dt(rc["locked_until"])
    _text(db, org_id, phone, f"Done. {rc['client_name']} is registered to you.\n\nReference code: {rc['ref_code']}\n"
          f"Protected until {until.astimezone(_tz(org)).strftime('%d %b %Y')}.\n\n"
          "Ask the client to quote this code when paying, and choose Request a site visit when they are ready to see the estate.")
    _show_menu(db, org_id, phone, realtor, cfg)


def check_client_phone(db, org_id: str, digits: str, realtor_id: str) -> tuple[str, dict]:
    """('mine'|'taken'|'existing'|'attach'|'free', info). An expired lock is released first."""
    rows = (db.table("realtor_clients").select("*").eq("org_id", org_id).eq("client_phone", digits)
            .eq("status", "active").limit(1).execute().data or [])
    if rows:
        rc = rows[0]
        until = _parse_dt(rc.get("locked_until"))
        if until and until < _now():
            db.table("realtor_clients").update({"status": "released"}).eq("id", rc["id"]).execute()
        else:
            return ("mine" if rc["realtor_user_id"] == realtor_id else "taken"), rc
    for col in ("whatsapp", "phone"):
        leads = (db.table("leads").select("id, assigned_to, stage, created_at").eq("org_id", org_id).eq(col, digits)
                 .is_("deleted_at", "null").neq("stage", "lost").order("created_at", desc=True).limit(1).execute().data or [])
        if leads:
            lead = leads[0]
            if lead.get("assigned_to") == realtor_id:
                return "attach", lead      # the realtor's own earlier lead: register it, do not duplicate
            return "existing", lead
    return "free", {}


def register_client(db, org_id: str, realtor: dict, name: str, digits: str, interest: str, lock_days: int,
                    lead_id: Optional[str] = None) -> dict:
    from app.models.leads import LeadCreate, LeadSource
    from app.services import lead_service
    from app.services import demo_service as ds
    if not lead_id:
        lead = lead_service.create_lead(db, org_id, realtor["id"], LeadCreate(
            full_name=name, source=LeadSource.manual_referral, whatsapp=digits, business_type=interest[:100],
            referrer=realtor["name"][:255], assigned_to=realtor["id"]))
        lead_id = lead["id"]
    code = "-".join(["OLL", "".join(random.choice(_CODE_CHARS) for _ in range(5))])
    row = {"id": str(uuid.uuid4()), "org_id": org_id, "realtor_user_id": realtor["id"], "lead_id": lead_id,
           "client_name": name, "client_phone": digits, "interest": interest, "ref_code": code,
           "locked_until": _iso(_now() + timedelta(days=lock_days)), "status": "active"}
    db.table("realtor_clients").insert(row).execute()
    try:
        ds._log_timeline(db, org_id, lead_id, realtor["id"], "realtor_registered",
                         f"Registered by realtor {realtor['name']}. Reference {code}. Interest: {interest}.", {"ref_code": code})
        mgr = ds._get_manager_id(db, org_id, exclude_user_id=realtor["id"])
        if mgr:
            _notify_in_app(db, org_id, mgr, "realtor_client_registered", f"{realtor['name']} registered {name}",
                           f"Reference {code}. Interest: {interest}.", lead_id)
    except Exception as exc:
        logger.warning("register_client follow-ups failed: %s", exc)
    return row


# ───────────────────────────── site visit request ─────────────────────────────

def _prompt_day(db, org_id, phone, org, name):
    tz = _tz(org)
    today = datetime.now(tz).date()
    rows = []
    for n in range(1, 9):
        d = today + timedelta(days=n)
        rows.append((f"vd:{d.isoformat()}", d.strftime("%a %d %b")))
    _list(db, org_id, phone, f"Which day would {_first(name)} like to visit?", "Pick a day", rows, "Visit day")


def _step_visit_client(db, org_id, phone, realtor, cfg, org, text, rid, data):
    rc = None
    if rid and rid.startswith("rv:"):
        rows = (db.table("realtor_clients").select("*").eq("id", rid[3:]).eq("org_id", org_id)
                .eq("realtor_user_id", realtor["id"]).eq("status", "active").limit(1).execute().data or [])
        rc = rows[0] if rows else None
    if not rc:
        return _menu_action(db, org_id, phone, realtor, cfg, org, "rl:visit")
    _set_session(db, org_id, phone, "visit_day", {"rc_id": rc["id"], "lead_id": rc["lead_id"], "name": rc["client_name"]})
    _prompt_day(db, org_id, phone, org, rc["client_name"])


def _prompt_time(db, org_id, phone):
    _buttons(db, org_id, phone, "What time of day suits them?",
             [("vt:10", "Morning (10 AM)"), ("vt:12", "Midday (12 PM)"), ("vt:15", "Afternoon (3 PM)")])


def _step_visit_day(db, org_id, phone, realtor, cfg, org, text, rid, data):
    if not (rid and rid.startswith("vd:")):
        return _prompt_day(db, org_id, phone, org, data.get("name"))
    _set_session(db, org_id, phone, "visit_time", {**data, "day": rid[3:]})
    _prompt_time(db, org_id, phone)


def _prompt_group(db, org_id, phone):
    _buttons(db, org_id, phone, "How many people will come?",
             [("vg:1", "Just 1 person"), ("vg:3", "2 to 3 people"), ("vg:5", "4 or more")])


def _step_visit_time(db, org_id, phone, realtor, cfg, org, text, rid, data):
    if not (rid and rid.startswith("vt:")):
        return _prompt_time(db, org_id, phone)
    _set_session(db, org_id, phone, "visit_group", {**data, "hour": int(rid[3:])})
    _prompt_group(db, org_id, phone)


def _step_visit_group(db, org_id, phone, realtor, cfg, org, text, rid, data):
    if not (rid and rid.startswith("vg:")):
        return _prompt_group(db, org_id, phone)
    group = {"1": "1 person", "3": "2 to 3 people", "5": "4 or more people"}.get(rid[3:], "not stated")
    _clear_session(db, org_id, phone)
    when = create_visit_request(db, org_id, realtor, data["lead_id"], data["name"], data["day"], data["hour"], group, org)
    if not when:
        _text(db, org_id, phone, "Sorry, I couldn't send that request. Please contact the Ollic team to arrange the visit.")
    else:
        _text(db, org_id, phone, f"Site visit requested for {data['name']} on {when} ({group}).\n\n"
              "The Ollic team will confirm it and you will get a message here.")
    _show_menu(db, org_id, phone, realtor, cfg)


def create_visit_request(db, org_id: str, realtor: dict, lead_id: str, client_name: str, day: str, hour: int, group: str,
                         org: dict) -> Optional[str]:
    """Creates a pending site-visit booking for the admin to confirm. Returns the local date/time text, or None on failure."""
    try:
        from app.services import booking_service as bk
        from app.services import demo_service as ds
        tz = _tz(org)
        y, m, d = (int(x) for x in day.split("-"))
        start_utc = datetime(y, m, d, int(hour), 0, tzinfo=tz).astimezone(timezone.utc)
        svc = _one((db.table("booking_services").select("id, name, duration_minutes, medium")
                    .eq("org_id", org_id).eq("slug", "site-inspection").eq("active", True).limit(1).execute().data) or [])
        if not svc:
            svc = _one((db.table("booking_services").select("id, name, duration_minutes, medium")
                        .eq("org_id", org_id).eq("medium", "in_person").eq("active", True).limit(1).execute().data) or [])
        if not svc:
            return None
        dur = int(svc.get("duration_minutes") or 60)
        demo_id = str(uuid.uuid4())
        now = _iso()
        db.table("lead_demos").insert({
            "id": demo_id, "org_id": org_id, "lead_id": lead_id, "status": "pending_assignment", "service_id": svc["id"],
            "source": "realtor", "medium": "in_person", "scheduled_at": start_utc.isoformat(),
            "slot_end": (start_utc + timedelta(minutes=dur)).isoformat(), "duration_minutes": dur,
            "notes": f"Site visit requested by realtor {realtor['name']}. Group: {group}.",
            "created_by": realtor["id"], "guard_scope": "ext", "created_at": now, "updated_at": now}).execute()
        lead = ds._confirm_lead_in_org(db, org_id, lead_id)
        when = start_utc.astimezone(tz).strftime("%a %d %b at %I:%M %p").replace(" 0", " ")
        ds._log_timeline(db, org_id, lead_id, realtor["id"], "site_visit_requested",
                         f"Site visit requested by {realtor['name']} for {when} ({group}). Waiting for approval.",
                         {"demo_id": demo_id, "source": "realtor"})
        bk._notify_approval_needed(db, org_id, lead, demo_id, start_utc, bk.get_org(db, org_id))
        return when
    except Exception as exc:
        logger.exception("create_visit_request failed org=%s lead=%s: %s", org_id, lead_id, exc)
        return None


# ───────────────────────────── my clients / my commission ─────────────────────────────

def _active_clients(db, org_id, realtor_id, limit) -> list:
    return (db.table("realtor_clients").select("*").eq("org_id", org_id).eq("realtor_user_id", realtor_id)
            .eq("status", "active").order("created_at", desc=True).limit(limit).execute().data or [])


_VISIT_TEXT = {"pending_assignment": "requested", "confirmed": "confirmed", "attended": "done", "no_show": "missed"}


def _clients_text(db, org_id: str, realtor: dict, org: dict) -> str:
    clients = _active_clients(db, org_id, realtor["id"], 12)
    if not clients:
        return "You have no registered clients yet. Choose Register a client to add your first one."
    ids = [c["lead_id"] for c in clients]
    labels = {s.get("key"): s.get("label") for s in (org.get("pipeline_stages") or []) if isinstance(s, dict)}
    stages = {r["id"]: r.get("stage") for r in (db.table("leads").select("id, stage").in_("id", ids).execute().data or [])}
    visits: dict = {}
    for r in (db.table("lead_demos").select("lead_id, status, scheduled_at, medium").in_("lead_id", ids)
              .eq("medium", "in_person").is_("deleted_at", "null").order("created_at").execute().data or []):
        visits[r["lead_id"]] = r                      # the latest one wins
    paid: dict = {}
    for r in (db.table("client_payments").select("lead_id, amount_ngn").in_("lead_id", ids).execute().data or []):
        paid[r["lead_id"]] = paid.get(r["lead_id"], 0) + float(r["amount_ngn"] or 0)
    tz = _tz(org)
    lines = []
    for i, c in enumerate(clients, 1):
        stage = stages.get(c["lead_id"]) or "new"
        v = visits.get(c["lead_id"])
        if v:
            when = _parse_dt(v.get("scheduled_at"))
            vtxt = f"{_VISIT_TEXT.get(v['status'], v['status'])}" + (f" {when.astimezone(tz).strftime('%d %b')}" if when and v["status"] in ("pending_assignment", "confirmed") else "")
        else:
            vtxt = "not requested"
        lines.append(f"{i}. {c['client_name']} ({c['ref_code']})\n   {labels.get(stage) or stage.replace('_', ' ').title()} | Visit: {vtxt} | Paid: {_naira(paid.get(c['lead_id'], 0))}")
    return "Your clients:\n\n" + "\n\n".join(lines)


def _commission_text(db, org_id: str, realtor_id: str) -> str:
    rows = (db.table("commissions").select("amount_ngn, status, event_type, created_at").eq("org_id", org_id)
            .eq("affiliate_user_id", realtor_id).order("created_at", desc=True).limit(200).execute().data or [])
    if not rows:
        return "No commission yet. It appears here as soon as Ollic confirms a payment from one of your clients."
    totals: dict = {}
    for r in rows:
        totals[r["status"]] = totals.get(r["status"], 0) + float(r["amount_ngn"] or 0)
    names = {"pending": "Pending approval", "approved": "Approved", "paid": "Paid out"}
    out = ["Your commission:", ""]
    for key in ("pending", "approved", "paid"):
        if key in totals:
            out.append(f"{names[key]}: {_naira(totals[key])}")
    out += ["", "Latest:"]
    for r in rows[:5]:
        out.append(f"- {_naira(r['amount_ngn'])} ({names.get(r['status'], r['status'])})")
    return "\n".join(out)


_STEPS = {
    "reg_name": _step_reg_name, "reg_phone": _step_reg_phone, "reg_interest": _step_reg_interest,
    "visit_client": _step_visit_client, "visit_day": _step_visit_day, "visit_time": _step_visit_time,
    "visit_group": _step_visit_group,
}


# ───────────────────────────── notifications to the realtor ─────────────────────────────

def _notify_in_app(db, org_id, user_id, ntype, title, body, lead_id) -> None:
    try:
        db.table("notifications").insert({
            "id": str(uuid.uuid4()), "org_id": org_id, "user_id": user_id, "type": ntype, "title": title, "body": body,
            "resource_type": "lead", "resource_id": lead_id, "is_read": False, "created_at": _iso()}).execute()
    except Exception as exc:
        logger.warning("realtor in-app notification failed: %s", exc)


def realtor_for_lead(db, org_id: str, lead_id: str) -> Optional[dict]:
    rows = (db.table("realtor_clients").select("realtor_user_id, client_name, ref_code").eq("org_id", org_id)
            .eq("lead_id", lead_id).eq("status", "active").limit(1).execute().data or [])
    if not rows:
        return None
    u = _one(db.table("users").select("id, full_name, whatsapp_number").eq("id", rows[0]["realtor_user_id"]).limit(1).execute().data)
    if not u:
        return None
    return {**u, "client_name": rows[0]["client_name"], "ref_code": rows[0]["ref_code"]}


def _tell_realtor(db, org_id: str, realtor: dict, ntype: str, title: str, body: str, lead_id: str) -> None:
    """In-app always. WhatsApp is free-form, so it only lands inside the 24-hour window after the realtor last messaged the line."""
    _notify_in_app(db, org_id, realtor["id"], ntype, title, body, lead_id)
    number = (realtor.get("whatsapp_number") or "").strip()
    if number:
        _text(db, org_id, _digits(number), f"{title}\n\n{body}")


def on_visit_confirmed(db, org_id: str, lead_id: str, when_text: str) -> None:
    """Called after the admin confirms a booking. Tells the realtor who registered this client. Never raises."""
    try:
        realtor = realtor_for_lead(db, org_id, lead_id)
        if realtor:
            _tell_realtor(db, org_id, realtor, "realtor_visit_confirmed", f"Site visit confirmed for {realtor['client_name']}",
                          f"{realtor['client_name']} is booked for {when_text}. Please make sure they know the date.", lead_id)
    except Exception as exc:
        logger.warning("on_visit_confirmed failed: %s", exc)


# ───────────────────────────── payments ─────────────────────────────

def list_payments(db, org_id: str, lead_id: str) -> dict:
    rows = (db.table("client_payments").select("*").eq("org_id", org_id).eq("lead_id", lead_id)
            .order("received_at", desc=True).execute().data or [])
    return {"payments": rows, "total_ngn": sum(float(r["amount_ngn"] or 0) for r in rows),
            "realtor": _realtor_name(db, org_id, lead_id)}


def _realtor_name(db, org_id, lead_id) -> Optional[str]:
    r = realtor_for_lead(db, org_id, lead_id)
    return (r or {}).get("full_name")


def record_payment(db, org_id: str, lead_id: str, amount_ngn: float, reference: Optional[str], note: Optional[str],
                   user_id: str) -> dict:
    """Admin confirms money received in the company account. Creates the commission and tells the realtor."""
    from app.services import commissions_service
    from app.services import demo_service as ds
    lead = ds._confirm_lead_in_org(db, org_id, lead_id)
    realtor = realtor_for_lead(db, org_id, lead_id)
    affiliate_id = (realtor or {}).get("id") or lead.get("assigned_to")
    row = {"id": str(uuid.uuid4()), "org_id": org_id, "lead_id": lead_id, "realtor_user_id": affiliate_id,
           "amount_ngn": round(float(amount_ngn), 2), "reference": (reference or None), "note": (note or None),
           "received_by": user_id, "received_at": _iso()}
    db.table("client_payments").insert(row).execute()
    commission = None
    if affiliate_id:
        commissions_service.auto_create_commission(db, org_id, affiliate_id, "payment_confirmed", lead_id=lead_id,
                                                   deal_amount=float(amount_ngn))
        commission = _one((db.table("commissions").select("amount_ngn, status").eq("org_id", org_id).eq("lead_id", lead_id)
                           .eq("affiliate_user_id", affiliate_id).eq("event_type", "payment_confirmed")
                           .order("created_at", desc=True).limit(1).execute().data) or [])
    name = lead.get("full_name") or "the client"
    try:
        ds._log_timeline(db, org_id, lead_id, user_id, "payment_recorded",
                         f"Payment of {_naira(amount_ngn)} received" + (f" (ref {reference})" if reference else "") + ".",
                         {"amount_ngn": float(amount_ngn)})
        if realtor:
            amt = float((commission or {}).get("amount_ngn") or 0)
            body = f"Ollic confirmed a payment of {_naira(amount_ngn)} from {name}." + (
                f" Your commission on it: {_naira(amt)} (pending approval)." if amt > 0 else "")
            _tell_realtor(db, org_id, realtor, "realtor_payment_confirmed", f"Payment received for {name}", body, lead_id)
    except Exception as exc:
        logger.warning("record_payment follow-ups failed: %s", exc)
    return {"payment": row, "commission": commission}
