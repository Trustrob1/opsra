"""
app/services/webchat_call_service.py
------------------------------------
WEBCHAT-CALL-1 - the phone icon in the web chat.

Phone calls are only taken in the business's opening hours (organisations.business_hours, in organisations.timezone).
Chat support and sales are never closed. The server decides open or closed (the visitor's clock is not trusted) and
tells the page: whether calls are open now, the number, when calls reopen, and the hours in words.
Outside hours a visitor can ask for a call back: a task for a rep is due when calls reopen.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_LABEL = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _tz(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Africa/Lagos")
    except Exception:
        return ZoneInfo("Africa/Lagos")


def _hm(v) -> Optional[tuple[int, int]]:
    try:
        h, m = str(v).split(":")[:2]
        h, m = int(h), int(m)
        return (h, m) if 0 <= h <= 24 and 0 <= m < 60 else None
    except Exception:
        return None


def _rules(bh: Optional[dict]) -> dict[int, tuple[tuple[int, int], tuple[int, int]]]:
    out = {}
    for i, key in enumerate(_DAYS):
        d = (bh or {}).get(key)
        if isinstance(d, dict):
            a, b = _hm(d.get("start")), _hm(d.get("end"))
            if a and b and b > a:
                out[i] = (a, b)
    return out


def clock(h: int, m: int) -> str:
    suffix = "am" if h < 12 or h == 24 else "pm"
    return f"{(h % 12) or 12}:{m:02d} {suffix}"


def hours_text(bh: Optional[dict]) -> str:
    """'Mon to Fri 8:00 am to 5:00 pm, Sat 9:00 am to 1:00 pm'"""
    rules = _rules(bh)
    groups: list[list] = []
    for i in range(7):
        if i not in rules:
            continue
        if groups and groups[-1][1] == i - 1 and groups[-1][2] == rules[i]:
            groups[-1][1] = i
        else:
            groups.append([i, i, rules[i]])
    parts = []
    for a, b, (s, e) in groups:
        days = _DAY_LABEL[a] if a == b else (f"{_DAY_LABEL[a]} and {_DAY_LABEL[b]}" if b == a + 1 else f"{_DAY_LABEL[a]} to {_DAY_LABEL[b]}")
        parts.append(f"{days} {clock(*s)} to {clock(*e)}")
    return ", ".join(parts)


def open_state(bh: Optional[dict], tz_name: Optional[str], now: Optional[datetime] = None) -> dict:
    """{'open': bool, 'closes_at': dt|None, 'opens_at': dt|None} in the business's timezone."""
    tz = _tz(tz_name)
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    rules = _rules(bh)
    if not rules:
        return {"open": False, "closes_at": None, "opens_at": None, "no_hours": True}
    today = rules.get(local.weekday())
    if today:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=today[0][0], minutes=today[0][1])
        end = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=today[1][0], minutes=today[1][1])
        if start <= local < end:
            return {"open": True, "closes_at": end, "opens_at": None}
    for add in range(0, 8):
        day = local + timedelta(days=add)
        r = rules.get(day.weekday())
        if not r:
            continue
        start = day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=r[0][0], minutes=r[0][1])
        if start > local:
            return {"open": False, "closes_at": None, "opens_at": start}
    return {"open": False, "closes_at": None, "opens_at": None}


def _opens_words(opens: Optional[datetime], tz_name: Optional[str], now: Optional[datetime] = None) -> str:
    if not opens:
        return ""
    local_now = (now or datetime.now(timezone.utc)).astimezone(_tz(tz_name))
    days = (opens.date() - local_now.date()).days
    when = "today" if days == 0 else ("tomorrow" if days == 1 else opens.strftime("%A"))
    return f"{when} at {clock(opens.hour, opens.minute)}"


def display_number(digits: str) -> str:
    d = digits or ""
    if d.startswith("234") and len(d) == 13:
        d = "0" + d[3:]
    if len(d) == 11:
        return f"{d[:4]} {d[4:7]} {d[7:]}"
    return d if not d else ("+" + d if len(d) > 11 else d)


def number_for(cfg: dict) -> str:
    own = wc.normalise_phone(cfg.get("call_number"))
    if own:
        return own
    return wc.normalise_phone((cfg.get("_call_org") or {}).get("fallback_number")) or ""


def status(cfg: dict, now: Optional[datetime] = None) -> Optional[dict]:
    """What the page needs. None when the call button is off or the business has no number."""
    if not cfg.get("call_enabled"):
        return None
    number = number_for(cfg)
    if not number:
        return None
    org = cfg.get("_call_org") or {}
    st = open_state(org.get("business_hours"), org.get("timezone"), now)
    out = {
        "open": bool(st["open"]), "number": number, "display": display_number(number),
        "hours": hours_text(org.get("business_hours")),
        "closes": clock(st["closes_at"].hour, st["closes_at"].minute) if st.get("closes_at") else None,
        "reopens": _opens_words(st.get("opens_at"), org.get("timezone"), now),
    }
    return out


def request_callback(db, session: dict, cfg: dict, phone: Optional[str]) -> dict:
    """Task for a rep, due when calls reopen. {'error'} or {'messages': [...]}."""
    if not session.get("lead_id"):
        return {"error": "Please share your contact details first."}
    st0 = status(cfg)
    if not st0:
        return {"error": "Call backs are not available right now."}
    number = wc.normalise_phone(phone) or wc.normalise_phone(session.get("contact_phone"))
    if not number:
        return {"need_phone": True, "error": "What phone number should we call?"}
    org = cfg.get("_call_org") or {}
    st = open_state(org.get("business_hours"), org.get("timezone"))
    due = st.get("opens_at") if not st["open"] else None
    due_utc = (due or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lead_id, org_id = session["lead_id"], session["org_id"]
    name = session.get("contact_name") or "Web chat visitor"
    assignee = None
    try:
        lead = (db.table("leads").select("assigned_to").eq("id", lead_id).limit(1).execute().data or [None])[0] or {}
        assignee = lead.get("assigned_to")
    except Exception as exc:
        logger.warning("webchat callback lead lookup failed: %s", exc)
    if not assignee:
        try:
            from app.services import funnel_service
            ids = funnel_service._get_manager_ids(db, org_id)
            assignee = ids[0] if ids else None
        except Exception as exc:
            logger.warning("webchat callback manager lookup failed: %s", exc)
    now_iso = wc._iso(wc._now())
    row = {"id": str(uuid.uuid4()), "org_id": org_id, "title": f"Call back: {name}",
           "description": f"{name} asked for a call back from the web chat. Number: +{number}.",
           "task_type": "system_event", "source_module": "leads", "source_record_id": lead_id,
           "priority": "high", "status": "open", "due_at": wc._iso(due_utc), "created_at": now_iso, "updated_at": now_iso}
    if assignee:
        row["assigned_to"] = assignee
    try:
        db.table("tasks").insert(row).execute()
    except Exception as exc:
        logger.warning("webchat callback task failed org=%s: %s", org_id, exc)
        return {"error": "We could not book that just now. Please try again."}
    try:
        from app.services import lead_service
        lead_service.write_timeline_event(db, org_id, lead_id, event_type="webchat_callback", actor_id=None,
                                          description=f"Call back requested from web chat (+{number})", metadata={"phone": number})
    except Exception as exc:
        logger.warning("webchat callback timeline failed: %s", exc)
    wc.notify_managers(db, org_id, f"Call back requested: {name}", f"Call +{number} " + (st0.get("reopens") and f"{st0['reopens']}." or "now."),
                       lead_id, "webchat_callback")
    when = st0["reopens"] if not st["open"] and st0.get("reopens") else "shortly"
    text = f"Done. A team member will call you on {display_number(number)} {when}. If you would rather, leave a voice note or keep chatting with us here."
    return {"messages": [wc.append_message(db, session, "visitor", "Please call me back"), wc.append_message(db, session, "bot", text)]}
