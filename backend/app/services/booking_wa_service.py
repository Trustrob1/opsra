"""
app/services/booking_wa_service.py
-----------------------------------
BOOKING-2C - pick, confirm, reschedule and cancel a booking entirely inside WhatsApp.

Flow (inside the 24h window, WhatsApp interactive messages):
  day list  ->  time list  ->  confirm buttons  ->  booked (standard confirmation) + "Reschedule / Cancel" buttons
Outside the window nothing interactive can be sent: the booking link template goes out instead.

Safety rules:
  * Reply ids only point INTO what this service stored for the lead (booking_wa_sessions.offered); the real slot
    is never read from the reply id, and every booking goes through booking_service.book_slot / reschedule_booking /
    cancel_booking, so the database guard stays the authority.
  * The org always comes from the receiving number (webhook), never from the reply.
  * A free-text message, or 30 minutes of silence, ends the conversation so it never traps a chat.
Reply ids: bk:d:<i> day, bk:md:<offset> more days, bk:t:<i> time, bk:mt:<offset> more times, bk:back other day,
           bk:ok confirm, bk:link send the link, bk:rs:<demo_id> reschedule, bk:cx:<demo_id> cancel,
           bk:cxy:<demo_id> yes cancel, bk:keep keep it.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.services import booking_service as bk

logger = logging.getLogger(__name__)

PREFIX = "bk:"
_SESSION_MINUTES = 30
_MAX_STARTS_PER_DAY = 5
_LOOKAHEAD_DAYS = 21


# ───────────────────────────── helpers ─────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def is_picker_reply(reply_id: Optional[str]) -> bool:
    return bool(reply_id) and str(reply_id).startswith(PREFIX)


def reply_id_from_message(message: dict) -> tuple[Optional[str], Optional[str]]:
    """(id, title) of an interactive list/button reply, or a template quick-reply button payload."""
    inter = message.get("interactive") or {}
    rep = inter.get("button_reply") or inter.get("list_reply")
    if rep:
        return rep.get("id"), rep.get("title")
    btn = message.get("button") or {}
    if btn.get("payload"):
        return btn.get("payload"), btn.get("text")
    return None, None


def _tz_label(org: dict) -> str:
    name = org.get("timezone") or "Africa/Lagos"
    return name.split("/")[-1].replace("_", " ") + " time"


def _local(dt_utc: datetime, org: dict) -> datetime:
    return dt_utc.astimezone(ZoneInfo(org.get("timezone") or "Africa/Lagos"))


def _day_title(d: date) -> str:
    return d.strftime("%a %d %b").replace(" 0", " ")[:24]


def _time_title(dt_local: datetime) -> str:
    return dt_local.strftime("%I:%M %p").lstrip("0").lower()[:24]


def _first(res):
    data = getattr(res, "data", None)
    if isinstance(data, list):
        return data[0] if data else None
    return data


# ───────────────────────────── sending ─────────────────────────────

def _creds(db, org_id: str, lead: dict):
    from app.services.whatsapp_service import _get_lead_wa_credentials
    phone_id, token, _ = _get_lead_wa_credentials(db, org_id, lead.get("id"))
    to = (lead.get("whatsapp") or lead.get("phone") or "").strip()
    if not (phone_id and token and to):
        return None
    return phone_id, token, to


def _log_out(db, org_id: str, lead_id: str, content: str, mtype: str) -> None:
    try:
        db.table("whatsapp_messages").insert({
            "org_id": org_id, "lead_id": lead_id, "direction": "outbound", "message_type": mtype,
            "channel": "whatsapp", "content": content, "status": "sent", "window_open": True,
            "window_expires_at": (_now() + timedelta(hours=24)).isoformat(), "sent_by": None, "created_at": _iso(_now()),
        }).execute()
    except Exception as exc:
        logger.warning("booking_wa: log failed lead=%s: %s", lead_id, exc)


def _send_interactive(db, org_id: str, lead: dict, interactive: dict, log_text: str) -> bool:
    """S14: never raises. Returns True when Meta accepted the message."""
    try:
        from app.services.whatsapp_service import _call_meta_send
        c = _creds(db, org_id, lead)
        if not c:
            return False
        phone_id, token, to = c
        _call_meta_send(phone_id, {"messaging_product": "whatsapp", "to": to, "type": "interactive", "interactive": interactive}, token=token)
        _log_out(db, org_id, lead["id"], log_text, "interactive")
        return True
    except Exception as exc:
        logger.warning("booking_wa: interactive send failed lead=%s: %s", lead.get("id"), exc)
        return False


def _send_text(db, org_id: str, lead: dict, text: str) -> bool:
    from app.services import demo_service as ds
    return bool(ds._auto_send_wa(db, org_id, lead, text).get("sent"))


def _list_message(body: str, button: str, rows: list[dict]) -> dict:
    return {"type": "list", "body": {"text": body[:1024]},
            "action": {"button": button[:20], "sections": [{"title": "Choose", "rows": rows[:10]}]}}


def _buttons_message(body: str, buttons: list[tuple[str, str]]) -> dict:
    return {"type": "button", "body": {"text": body[:1024]},
            "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons[:3]]}}


# ───────────────────────────── session ─────────────────────────────

def _active_session(db, lead_id: str) -> Optional[dict]:
    rows = (db.table("booking_wa_sessions").select("*").eq("lead_id", lead_id).eq("status", "active")
            .limit(1).execute().data or [])
    return rows[0] if rows else None


def _close_sessions(db, lead_id: str, status: str = "expired") -> None:
    try:
        db.table("booking_wa_sessions").update({"status": status, "updated_at": _iso(_now())}) \
            .eq("lead_id", lead_id).eq("status", "active").execute()
    except Exception as exc:
        logger.warning("booking_wa: close sessions failed lead=%s: %s", lead_id, exc)


def abandon_if_active(db, org_id: str, lead_id: Optional[str]) -> None:
    """Called for every inbound message that is NOT a picker reply: the lead moved on, so end the conversation. S14."""
    if not lead_id:
        return
    try:
        if _active_session(db, lead_id):
            _close_sessions(db, lead_id, "expired")
    except Exception as exc:
        logger.warning("booking_wa: abandon check failed lead=%s: %s", lead_id, exc)


def _save(db, session_id: str, **fields) -> None:
    fields["updated_at"] = _iso(_now())
    db.table("booking_wa_sessions").update(fields).eq("id", session_id).execute()


def _starts_today(db, lead_id: str) -> int:
    since = _iso(_now() - timedelta(hours=24))
    rows = db.table("booking_wa_sessions").select("id").eq("lead_id", lead_id).gte("created_at", since).execute().data or []
    return len(rows)


# ───────────────────────────── start ─────────────────────────────

def start_picker(db, org_id: str, lead_id: str, service_id: Optional[str] = None,
                 demo_id: Optional[str] = None, user_id: Optional[str] = None, force_link: bool = False) -> dict:
    """
    Begin the conversation. Returns {"started": bool, "reason": str|None, "fallback": "link"|None}.
    Window closed (or force_link): the booking link template is sent instead, because a list message needs an open window.
    """
    from app.services import demo_service as ds
    from app.services.whatsapp_service import _last_inbound_window
    cfg = bk.get_settings(db, org_id)
    if not cfg.get("native_enabled"):
        return {"started": False, "reason": "not_enabled", "fallback": None}
    lead = ds._confirm_lead_in_org(db, org_id, lead_id)
    org = bk.get_org(db, org_id)
    services = bk.list_services(db, org_id, active_only=True)
    if not services:
        return {"started": False, "reason": "no_service", "fallback": None}
    service = next((s for s in services if s["id"] == service_id), None) if service_id else None
    service = service or services[0]

    if force_link or not _last_inbound_window(db, org_id, lead_id):
        return {**_send_link(db, org_id, lead, cfg, service, user_id), "started": False}

    if _starts_today(db, lead_id) >= _MAX_STARTS_PER_DAY:
        return {"started": False, "reason": "too_many", "fallback": None}
    days = _day_options(db, org, service, demo_id)
    if not days:
        _send_text(db, org_id, lead, f"We don't have any open times for your {cfg['label']} right now. We'll message you as soon as some open up.")
        return {"started": False, "reason": "no_slots", "fallback": None}

    _close_sessions(db, lead_id)
    sess = (db.table("booking_wa_sessions").insert({
        "org_id": org_id, "lead_id": lead_id, "service_id": service["id"], "demo_id": demo_id, "step": "day", "status": "active",
        "offered": {"days": [d.isoformat() for d in days], "times": [], "date": None},
        "expires_at": _iso(_now() + timedelta(minutes=_SESSION_MINUTES)),
    }).execute().data or [None])[0]
    if not sess:
        return {"started": False, "reason": "error", "fallback": None}
    ok = _send_day_list(db, org_id, lead, org, cfg, sess, 0, intro=True, moving=bool(demo_id))
    return {"started": ok, "reason": None if ok else "send_failed", "fallback": None}


def _send_link(db, org_id: str, lead: dict, cfg: dict, service: dict, user_id: Optional[str]) -> dict:
    from app.services import demo_service as ds
    token = bk.create_link(db, org_id, lead["id"], service["id"], user_id)
    url = f"{bk.public_base()}/b/{token}"
    first = (lead.get("full_name") or "").split(" ")[0] or "there"
    res = ds._auto_send_wa(db, org_id, lead, f"Hi {first}, you can pick a time for your {cfg['label']} here: {url}",
                           template_name=bk.BOOKING_LINK_TEMPLATE, template_vars=[first, cfg["label"], url])
    return {"reason": res.get("reason") if not res.get("sent") else None, "fallback": "link", "url": url, "sent": bool(res.get("sent"))}


def _day_options(db, org: dict, service: dict, demo_id: Optional[str]) -> list[date]:
    tz = ZoneInfo(org.get("timezone") or "Africa/Lagos")
    today = _now().astimezone(tz).date()
    slots = bk.get_open_slots(db, org, service, today, today + timedelta(days=_LOOKAHEAD_DAYS), exclude_demo_id=demo_id)
    return sorted({s.astimezone(tz).date() for s in slots})


def _times_on(db, org: dict, service: dict, d: date, demo_id: Optional[str]) -> list[datetime]:
    return bk.get_open_slots(db, org, service, d, d, exclude_demo_id=demo_id)


# ───────────────────────────── messages ─────────────────────────────

def _send_day_list(db, org_id, lead, org, cfg, sess, offset: int, intro: bool = False, moving: bool = False) -> bool:
    days = [date.fromisoformat(x) for x in (sess.get("offered") or {}).get("days", [])]
    rest = days[offset:]
    page = rest if len(rest) <= 10 else rest[:9]
    rows = [{"id": f"bk:d:{offset + i}", "title": _day_title(d), "description": "Tap to see times"} for i, d in enumerate(page)]
    if len(rest) > len(page):
        rows.append({"id": f"bk:md:{offset + len(page)}", "title": "More days"})
    first = (lead.get("full_name") or "").split(" ")[0]
    head = (f"Hi {first}! " if intro and first else "") + (f"Pick a new day for your {cfg['label']}." if moving else f"Pick a day for your {cfg['label']}.")
    body = f"{head} Times are in {_tz_label(org)}."
    return _send_interactive(db, org_id, lead, _list_message(body, "Choose a day", rows), f"[Day list] {body}")


def _send_time_list(db, org_id, lead, org, cfg, sess, d: date, times: list[datetime], offset: int) -> bool:
    rest = times[offset:]
    page = rest if len(rest) <= 9 else rest[:8]
    rows = [{"id": f"bk:t:{offset + i}", "title": _time_title(_local(t, org))} for i, t in enumerate(page)]
    if len(rest) > len(page):
        rows.append({"id": f"bk:mt:{offset + len(page)}", "title": "More times"})
    rows.append({"id": "bk:back", "title": "Other day"})
    body = f"Open times on {d.strftime('%A %d %B').replace(' 0', ' ')} ({_tz_label(org)}):"
    return _send_interactive(db, org_id, lead, _list_message(body, "Choose a time", rows), f"[Time list] {body}")


def _send_change_buttons(db, org_id, lead, cfg, demo_id: str) -> None:
    _send_interactive(db, org_id, lead, _buttons_message(f"Need to change your {cfg['label']}?", [(f"bk:rs:{demo_id}", "Reschedule"), (f"bk:cx:{demo_id}", "Cancel it")]),
                      "[Buttons] Reschedule / Cancel")


# ───────────────────────────── replies ─────────────────────────────

def handle_reply(db, org_id: str, lead_id: str, reply_id: str, reply_title: Optional[str] = None) -> bool:
    """Handle one picker reply. Returns True when it was a picker reply (handled, even if it only said sorry). S14."""
    if not is_picker_reply(reply_id):
        return False
    try:
        return _handle(db, org_id, lead_id, str(reply_id))
    except Exception as exc:
        logger.exception("booking_wa: handler failed org=%s lead=%s id=%s: %s", org_id, lead_id, reply_id, exc)
        try:
            from app.services import demo_service as ds
            _send_text(db, org_id, ds._confirm_lead_in_org(db, org_id, lead_id), "Sorry, something went wrong. A member of our team will help you book a time.")
        except Exception:
            pass
        return True


def _handle(db, org_id: str, lead_id: str, rid: str) -> bool:
    from app.services import demo_service as ds
    lead = ds._confirm_lead_in_org(db, org_id, lead_id)
    org = bk.get_org(db, org_id)
    cfg = bk.get_settings(db, org_id)
    parts = rid.split(":")          # bk:<kind>[:<arg>]
    kind = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    # actions on an existing booking do not need a live picker session
    if kind in ("rs", "cx", "cxy", "keep"):
        return _handle_change(db, org_id, lead, org, cfg, kind, arg)

    sess = _active_session(db, lead_id)
    if not sess or bk._parse_dt(sess["expires_at"]) < _now():
        if sess:
            _close_sessions(db, lead_id)
        _send_text(db, org_id, lead, "That took a little while, so let's start again.")
        start_picker(db, org_id, lead_id)
        return True

    service = _service_of(db, org_id, sess)
    off = sess.get("offered") or {}
    demo_id = sess.get("demo_id")

    if kind == "d":                                     # chose a day
        i = _idx(arg, off.get("days", []))
        if i is None:
            return _bad(db, org_id, lead, sess, org, cfg)
        d = date.fromisoformat(off["days"][i])
        times = _times_on(db, org, service, d, demo_id)
        if not times:
            _send_text(db, org_id, lead, "Sorry, that day just filled up. Please choose another.")
            return _send_day_list(db, org_id, lead, org, cfg, sess, 0)
        _save(db, sess["id"], step="time", offered={**off, "date": d.isoformat(), "times": [_iso(t) for t in times]},
              expires_at=_iso(_now() + timedelta(minutes=_SESSION_MINUTES)))
        return _send_time_list(db, org_id, lead, org, cfg, sess, d, times, 0)

    if kind == "md":                                    # more days
        o = _offset(arg, off.get("days", []))
        if o is None:
            return _bad(db, org_id, lead, sess, org, cfg)
        return _send_day_list(db, org_id, lead, org, cfg, sess, o)

    if kind == "mt":                                    # more times
        o = _offset(arg, off.get("times", []))
        if o is None or not off.get("date"):
            return _bad(db, org_id, lead, sess, org, cfg)
        times = [bk._parse_dt(t) for t in off["times"]]
        return _send_time_list(db, org_id, lead, org, cfg, sess, date.fromisoformat(off["date"]), times, o)

    if kind == "back":                                  # other day
        _save(db, sess["id"], step="day")
        return _send_day_list(db, org_id, lead, org, cfg, sess, 0)

    if kind == "t":                                     # chose a time
        i = _idx(arg, off.get("times", []))
        if i is None:
            return _bad(db, org_id, lead, sess, org, cfg)
        start = bk._parse_dt(off["times"][i])
        _save(db, sess["id"], step="confirm", chosen_start=_iso(start), expires_at=_iso(_now() + timedelta(minutes=_SESSION_MINUTES)))
        when = _local(start, org).strftime("%A %d %B at %I:%M %p").replace(" 0", " ")
        verb = "Move your" if demo_id else "Book your"
        body = f"{verb} {cfg['label']} to {when} ({_tz_label(org)})?"
        return _send_interactive(db, org_id, lead, _buttons_message(body, [("bk:ok", "Confirm"), ("bk:back", "Pick another time"), ("bk:link", "Send me the link")]),
                                 f"[Confirm] {body}")

    if kind == "link":                                  # wants the web page instead (other timezone, etc.)
        _close_sessions(db, lead_id, "done")
        _send_link(db, org_id, lead, cfg, service, None)
        return True

    if kind == "ok":                                    # confirmed: book through the one guarded path
        if sess.get("step") != "confirm" or not sess.get("chosen_start"):
            return _bad(db, org_id, lead, sess, org, cfg)
        return _book(db, org_id, lead, org, cfg, sess, service, bk._parse_dt(sess["chosen_start"]))

    return _bad(db, org_id, lead, sess, org, cfg)


def _service_of(db, org_id: str, sess: dict) -> dict:
    if sess.get("service_id"):
        try:
            return bk.get_service(db, org_id, sess["service_id"])
        except HTTPException:
            pass
    return bk.list_services(db, org_id, active_only=True)[0]


def _idx(arg: str, lst: list) -> Optional[int]:
    return int(arg) if arg.isdigit() and int(arg) < len(lst) else None


def _offset(arg: str, lst: list) -> Optional[int]:
    return int(arg) if arg.isdigit() and 0 < int(arg) < len(lst) else None


def _bad(db, org_id, lead, sess, org, cfg) -> bool:
    _send_text(db, org_id, lead, "Sorry, I didn't catch that. Let's pick a day again.")
    _save(db, sess["id"], step="day")
    return _send_day_list(db, org_id, lead, org, cfg, sess, 0)


def _book(db, org_id, lead, org, cfg, sess, service, start) -> bool:
    demo_id = sess.get("demo_id")
    try:
        if demo_id:
            demo = bk.reschedule_booking(db, org_id, demo_id, start, by="lead")
        else:
            demo = bk.book_slot(db, org_id, lead["id"], service, start, source="whatsapp")
    except HTTPException as exc:
        code = (exc.detail or {}).get("code") if isinstance(exc.detail, dict) else None
        msg = (exc.detail or {}).get("message") if isinstance(exc.detail, dict) else None
        if code == "SLOT_TAKEN":
            _send_text(db, org_id, lead, "Sorry, that time was just taken. Here are the times that are still open.")
            d = start.astimezone(ZoneInfo(org.get("timezone") or "Africa/Lagos")).date()
            times = _times_on(db, org, service, d, demo_id)
            if times:
                _save(db, sess["id"], step="time", offered={**(sess.get("offered") or {}), "date": d.isoformat(), "times": [_iso(t) for t in times]})
                return _send_time_list(db, org_id, lead, org, cfg, sess, d, times, 0)
            _save(db, sess["id"], step="day")
            return _send_day_list(db, org_id, lead, org, cfg, sess, 0)
        _close_sessions(db, lead["id"], "done")
        _send_text(db, org_id, lead, msg or "Sorry, I couldn't book that. A member of our team will help you.")
        return True
    _close_sessions(db, lead["id"], "done")
    status = (demo or {}).get("status")
    demo_id = (demo or {}).get("id") or demo_id
    pay = (demo or {}).get("payment")
    if pay and pay.get("status") == "pending":   # BOOKING-3A: held until the deposit is paid
        mins = int(service.get("deposit_hold_minutes") or 30)
        _send_text(db, org_id, lead, (f"Almost done! To secure {_local(start, org).strftime('%A %d %B at %I:%M %p').replace(' 0', ' ')}, "
                                      f"please pay the {pay.get('currency')} {float(pay.get('amount') or 0):,.2f} deposit within {mins} minutes: {pay.get('pay_url')}"))
        return True
    if status == "pending_assignment":
        _send_text(db, org_id, lead, f"Thanks! We've got your request for {_local(start, org).strftime('%A %d %B at %I:%M %p').replace(' 0', ' ')}. We'll confirm it shortly.")
    elif demo_id and sess.get("demo_id"):
        pass   # reschedule_booking already sent "has been moved to ..."
    if demo_id and status != "pending_assignment":
        _send_change_buttons(db, org_id, lead, cfg, demo_id)
    return True


def _handle_change(db, org_id, lead, org, cfg, kind: str, demo_id: str) -> bool:
    """Reschedule / cancel buttons. The booking must belong to this lead in this org (checked server side)."""
    demo = None
    if demo_id:
        rows = (db.table("lead_demos").select("*").eq("id", demo_id).eq("org_id", org_id).eq("lead_id", lead["id"])
                .is_("deleted_at", "null").limit(1).execute().data or [])
        demo = rows[0] if rows else None
    if kind == "keep":
        _send_text(db, org_id, lead, "No problem, your booking stays as it is.")
        return True
    if not demo or demo.get("status") not in bk._LIVE_STATUSES:
        _send_text(db, org_id, lead, "I can't find an upcoming booking to change. Reply here and a member of our team will help.")
        return True
    try:
        bk._check_cutoff(db, org_id, demo, enforce=True)
    except HTTPException as exc:
        _send_text(db, org_id, lead, (exc.detail or {}).get("message") if isinstance(exc.detail, dict) else "This booking can no longer be changed online. Please reply here and we'll help.")
        return True
    if kind == "rs":
        start_picker(db, org_id, lead["id"], service_id=demo.get("service_id"), demo_id=demo["id"])
        return True
    if kind == "cx":
        body = f"Cancel your {cfg['label']}?"
        _send_interactive(db, org_id, lead, _buttons_message(body, [(f"bk:cxy:{demo['id']}", "Yes, cancel it"), ("bk:keep", "Keep it")]), f"[Confirm] {body}")
        return True
    if kind == "cxy":
        try:
            bk.cancel_booking(db, org_id, demo["id"], by="lead", reason="Cancelled on WhatsApp")
        except HTTPException as exc:
            _send_text(db, org_id, lead, (exc.detail or {}).get("message") if isinstance(exc.detail, dict) else "Sorry, I couldn't cancel that. Please reply here.")
        return True
    return True
