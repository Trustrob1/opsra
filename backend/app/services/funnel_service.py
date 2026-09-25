"""
app/services/funnel_service.py
-------------------------------
FUNNEL-1A — Event Funnel engine (webinar attendees).

Spec: Opsra Context/website-business/FUNNEL-1_Spec.md

Public entry points:
  current_price(funnel, reg, now, seats)       — pure pricing (hybrid: window | deadline)
  handle_inbound(...)                          — called from webhooks intercept (wa_sales_mode='event_funnel')
  get_pay_redirect(db, token, seats)           — public /f/{token} → Paystack checkout
  on_payment_confirmed(db, org_id, reference)  — hook after paystack_storefront_service.mark_paid
  is_funnel_reference(db, org_id, reference)   — mark_paid guard (skip generic confirmation)
  plan_next_step(...) / process_registration(...) — used by workers/funnel_worker.py
  get_funnel_stats(db, org_id, funnel_id)      — dashboard numbers

Rules followed:
  • org_id ALWAYS from the number row / funnel row (never the sender) — spec F2.
  • S14: nothing here raises into the webhook or worker; failures are logged.
  • Pattern 33: no ILIKE — Python-side matching.
  • Supabase Max Rows: every list read is paginated (_fetch_all).
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.models.funnels import FunnelMessages, FunnelSettings, FunnelStep  # noqa: E402
from app.services import funnel_messaging  # noqa: E402

logger = logging.getLogger(__name__)

PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "https://opsra.onrender.com").rstrip("/")
LAGOS = ZoneInfo("Africa/Lagos")
PAGE = 1000  # Supabase default Max Rows

ACTIVE_REG_STATUSES = ("new", "paid")

# ---------------------------------------------------------------------------
# Defaults (from the Option B guide — every text is editable per funnel)
# ---------------------------------------------------------------------------

DEFAULT_MESSAGES: dict[str, Any] = {
    "greeting": (
        "Hi {name} 👋 Thanks for reaching out!\n\n"
        "📌 *{event}*\n"
        "🎤 Hosted live by Trust Robert\n"
        "📅 {date}\n"
        "💻 On Google Meet: join from your phone or laptop\n"
        "{price_line}\n"
        "🎁 Every attendee gets my ChatGPT Website Prompt Pack free\n\n"
        "Tap the button below to pay. After paying, you'll get the class group link immediately."
    ),
    "pay_button": "Pay {price}",
    "faq_prompt": "Got a question? Tap one below 👇 or just type it.",
    "faq": [
        {"id": "faq_learn", "title": "What will I learn?",
         "answer": "How to use ChatGPT to plan, write and build a professional website step by step, "
                   "with zero coding, and how to put it online. You follow along live."},
        {"id": "faq_phone", "title": "Join on my phone?",
         "answer": "Yes! Google Meet works on any smartphone. Install the app before the class. "
                   "A laptop is easier, but your phone is fine."},
        {"id": "faq_tech", "title": "I'm not technical",
         "answer": "This class is made for you. If you can type a WhatsApp message, you can follow along. "
                   "ChatGPT does the technical part."},
    ],
    "pay_link_resend": "Here's your payment link 👇\n{price_line}",
    "group_offer": (
        "👥 *Group deal:* {group_size} seats for {group_price}.\n"
        "Pay once below, then forward the class group link I send you to your friends."
    ),
    "paid_confirmation": (
        "Payment received, welcome aboard! 🎉\n"
        "✅ Seat confirmed: {date}\n"
        "👥 Class group: {group_link}\n"
        "🎁 Prompt Pack: {bonus_link}\n\n"
        "📧 Please reply with the *Gmail address* you'll use to join the Google Meet, so I can send your invite.\n\n"
        "Know someone who'd love this? Tell them to message this number and say code *{ref_code}*. "
        "1 friend pays → your question is answered first. 3 friends pay → I refund your ticket."
    ),
    "already_paid": "You're already registered ✅\n👥 Class group: {group_link}",
    "email_thanks": "Thanks! I'll send the Google Meet invite to {email} 📧",
    "handoff_ack": "Thanks for your message 🙏 I'll reply personally shortly.",
    "closed": "Registration for *{event}* has closed. Thank you for your interest 🙏",
    "no_funnel": "Thanks for your message! Registration isn't open right now — we'll let you know when the next class opens.",
    "opted_out": "You've been unsubscribed. Reply START any time to opt back in.",
    "opted_in": "Welcome back! You'll get class updates again. Reply STOP any time to unsubscribe.",
}

_CHECKIN = {
    "key": "checkin_3h", "anchor": "first_message", "offset_minutes": 180, "audience": "unpaid",
    "text": "Hi {name} 😊 Did you get a chance to look at the class details? Tap a button above or reply with any question.",
}
_EVENT_REMINDERS = [
    {"key": "class_this_week", "anchor": "event_start", "offset_minutes": -(2 * 24 * 60 + 10 * 60),
     "audience": "unpaid", "include_pay_button": True,
     "text": "The website class is this {event_day} at {event_time} 🗓️ Registration closes {close_time}. Join here 👇",
     "template_name": "class_this_saturday", "template_params": ["{pay_link}"]},
    {"key": "class_tomorrow", "anchor": "event_start", "offset_minutes": -(24 * 60 + 10 * 60),
     "audience": "unpaid", "include_pay_button": True,
     "text": "Tomorrow at {event_time} 🚀 We're building professional websites with ChatGPT, live, no coding. Join here 👇",
     "template_name": "class_tomorrow", "template_params": ["{pay_link}"]},
    {"key": "class_tonight", "anchor": "event_start", "offset_minutes": -11 * 60,
     "audience": "unpaid", "include_pay_button": True,
     "text": "Tonight's the night! Class starts at {event_time} on Google Meet. Registration closes {close_time} 👇",
     "template_name": "class_tonight", "template_params": ["{pay_link}"]},
]

DEFAULT_SEQUENCE_WINDOW: list[dict] = [
    _CHECKIN,
    {"key": "early_ends", "anchor": "first_message", "offset_minutes": 20 * 60, "audience": "unpaid",
     "only_if_early": True, "include_pay_button": True,
     "text": "Hi {name}, quick heads-up: your {price} price ends at {deadline} ⏳ After that it's {regular_price}. Lock it in 👇"},
    {"key": "window_closed", "anchor": "window_end", "offset_minutes": 60, "audience": "unpaid",
     "include_pay_button": True,
     "text": ("Hi {name}, your {early_price} window has closed, so the class is now {regular_price}. "
              "You'll still get the free Prompt Pack 🎁\n\nI share one useful tip a day in the free prep group: {prep_link}"),
     "template_name": "window_closed", "template_params": ["{pay_link}"]},
    *_EVENT_REMINDERS,
]

DEFAULT_SEQUENCE_DEADLINE: list[dict] = [
    _CHECKIN,
    {"key": "early_ends_tomorrow", "anchor": "early_deadline", "offset_minutes": -24 * 60, "audience": "unpaid",
     "only_if_early": True, "include_pay_button": True,
     "text": "Hi {name}, the {price} price ends tomorrow ({deadline}) ⏳ After that it's {regular_price} 👇"},
    {"key": "early_ends_tonight", "anchor": "early_deadline", "offset_minutes": -4 * 60, "audience": "unpaid",
     "only_if_early": True, "include_pay_button": True,
     "text": "Last call, {name}: {price} ends tonight at {deadline} ⏳ 👇"},
    {"key": "early_closed", "anchor": "early_deadline", "offset_minutes": 60 * 10, "audience": "unpaid",
     "include_pay_button": True,
     "text": ("The {early_price} price has ended; the class is now {regular_price}. "
              "Free daily tips in the prep group: {prep_link}"),
     "template_name": "window_closed", "template_params": ["{pay_link}"]},
    *_EVENT_REMINDERS,
]

DEFAULT_SETTINGS = FunnelSettings().model_dump()

_OPT_OUT = frozenset({"stop", "unsubscribe", "optout", "opt out", "opt-out", "quit", "remove me"})
_OPT_IN = frozenset({"start", "subscribe", "optin", "opt in"})
_PAY_RE = re.compile(r"\b(pay|payment|link|register|registration|price|how much|account)\b", re.I)
_GROUP_RE = re.compile(r"\b(group|3 seats|three seats|3 of us|friends)\b", re.I)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_REF_RE = re.compile(r"\b([A-Za-z]{2}\d{4})\b")
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I/O


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _dt(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _one(data: Any) -> Optional[dict]:
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


def _fetch_all(build: Callable[[], Any], page: int = PAGE, max_pages: int = 50) -> list[dict]:
    """Paginate a Supabase select. build() must return a fresh query builder."""
    out: list[dict] = []
    for i in range(max_pages):
        res = build().range(i * page, i * page + page - 1).execute()
        rows = res.data or []
        out.extend(rows)
        if len(rows) < page:
            break
    return out


def _first_name(name: Optional[str]) -> str:
    n = (name or "").strip().split()
    first = n[0] if n else ""
    if not first or first.isdigit() or first.startswith("+"):
        return "there"
    return first[:40]


def format_money(amount: Optional[float], currency: str = "NGN") -> str:
    if amount is None:
        return ""
    a = float(amount)
    txt = f"{a:,.0f}" if a == int(a) else f"{a:,.2f}"
    return f"₦{txt}" if (currency or "NGN").upper() == "NGN" else f"{currency} {txt}"


def format_local(dt: Optional[datetime], fmt: str = "%a %d %b, %-I:%M %p") -> str:
    if not dt:
        return ""
    try:
        return dt.astimezone(LAGOS).strftime(fmt)
    except ValueError:  # Windows strftime has no %-I
        return dt.astimezone(LAGOS).strftime(fmt.replace("%-I", "%I")).replace(" 0", " ")


def phone_variants(phone: str) -> list[str]:
    p = (phone or "").replace(" ", "").replace("-", "")
    digits = p.lstrip("+")
    out = {digits, "+" + digits}
    if digits.startswith("234") and len(digits) > 3:
        out.add("0" + digits[3:])
    return sorted(out)


def funnel_messages(funnel: dict) -> dict:
    """Stored messages merged over defaults (validated — S13)."""
    merged = dict(DEFAULT_MESSAGES)
    try:
        stored = FunnelMessages(**(funnel.get("messages") or {})).model_dump(exclude_none=True)
        merged.update(stored)
    except Exception as exc:
        logger.warning("funnel %s: invalid messages config, using defaults: %s", funnel.get("id"), exc)
    return merged


def funnel_settings(funnel: dict) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    try:
        merged.update(FunnelSettings(**(funnel.get("settings") or {})).model_dump())
    except Exception as exc:
        logger.warning("funnel %s: invalid settings, using defaults: %s", funnel.get("id"), exc)
    return merged


def funnel_sequence(funnel: dict) -> list[dict]:
    raw = funnel.get("sequence")
    if not raw:
        raw = DEFAULT_SEQUENCE_DEADLINE if funnel.get("pricing_mode") == "deadline" else DEFAULT_SEQUENCE_WINDOW
    steps: list[dict] = []
    for s in raw:
        try:
            steps.append(FunnelStep(**s).model_dump())
        except Exception as exc:
            logger.warning("funnel %s: skipping invalid step %s: %s", funnel.get("id"), s.get("key"), exc)
    return steps


# ---------------------------------------------------------------------------
# Pricing (pure)
# ---------------------------------------------------------------------------

@dataclass
class PriceQuote:
    status: str                       # "open" | "closed"
    tier: Optional[str] = None        # "early" | "regular" | "group"
    amount: Optional[float] = None
    seats: int = 1
    early_ends_at: Optional[datetime] = None   # when the early price stops for this lead (None = not early)


def early_ends_at(funnel: dict, reg: dict, now: datetime) -> Optional[datetime]:
    """The moment the early price stops for this registration, if it is still early now."""
    candidates: list[datetime] = []
    mode = funnel.get("pricing_mode") or "window"
    if mode == "window":
        first = _dt(reg.get("first_message_at"))
        if first:
            candidates.append(first + timedelta(hours=int(funnel.get("window_hours") or 24)))
    elif mode == "deadline":
        d = _dt(funnel.get("early_deadline_at"))
        if d:
            candidates.append(d)
    ov = _dt(reg.get("early_override_until"))
    if ov:
        candidates.append(ov)
    live = [c for c in candidates if now < c]
    if not live:
        return None
    end = max(live)
    close = _dt(funnel.get("registration_closes_at"))
    return min(end, close) if close else end


def current_price(funnel: dict, reg: dict, now: datetime, seats: int = 1) -> PriceQuote:
    close = _dt(funnel.get("registration_closes_at"))
    if funnel.get("status") != "active" or (close and now >= close):
        return PriceQuote(status="closed")
    ends = early_ends_at(funnel, reg, now)
    group_size = funnel.get("group_size")
    if seats and seats > 1:
        if not group_size or not funnel.get("group_price") or seats != int(group_size):
            seats = 1
        else:
            return PriceQuote(status="open", tier="group", amount=float(funnel["group_price"]),
                              seats=int(group_size), early_ends_at=ends)
    if ends:
        return PriceQuote(status="open", tier="early", amount=float(funnel["early_price"]), early_ends_at=ends)
    return PriceQuote(status="open", tier="regular", amount=float(funnel["regular_price"]))


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_ad_code(text: Optional[str], ad_codes: list) -> Optional[str]:
    """First configured ad code appearing as a whole word (case-insensitive)."""
    if not text or not ad_codes:
        return None
    codes = sorted(
        {str((c.get("code") if isinstance(c, dict) else c) or "").upper() for c in ad_codes} - {""},
        key=len, reverse=True,
    )
    upper = text.upper()
    for code in codes:
        if re.search(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", upper):
            return code
    return None


def parse_ref_codes(text: Optional[str]) -> list[str]:
    return [m.upper() for m in _REF_RE.findall(text or "")]


def parse_email(text: Optional[str]) -> Optional[str]:
    m = _EMAIL_RE.search(text or "")
    return m.group(0).lower()[:255] if m else None


def new_ref_code() -> str:
    return "".join(secrets.choice(_REF_ALPHABET) for _ in range(2)) + "".join(
        secrets.choice(string.digits) for _ in range(4))


def new_pay_token() -> str:
    return secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def pay_url(reg: dict, seats: int = 1) -> str:
    base = f"{PUBLIC_API_URL}/f/{reg.get('pay_token')}"
    return f"{base}?seats={seats}" if seats > 1 else base


def build_context(funnel: dict, reg: dict, now: datetime) -> dict:
    cur = funnel.get("currency") or "NGN"
    quote = current_price(funnel, reg, now)
    event_at = _dt(funnel.get("event_starts_at"))
    close_at = _dt(funnel.get("registration_closes_at"))
    price = format_money(quote.amount, cur) if quote.amount is not None else format_money(funnel.get("regular_price"), cur)
    regular = format_money(funnel.get("regular_price"), cur)
    if quote.status == "closed":
        price_line = ""
    elif quote.tier == "early":
        price_line = f"💰 *{price}* if you pay by {format_local(quote.early_ends_at)} ({regular} after)"
    else:
        price_line = f"💰 *{price}*"
    group_size = funnel.get("group_size")
    return {
        "name": _first_name(reg.get("name")),
        "event": funnel.get("event_title") or funnel.get("name") or "",
        "date": (format_local(event_at, "%A, %d %B · %-I:%M %p") + " WAT") if event_at else "",
        "event_day": format_local(event_at, "%A") if event_at else "",
        "event_time": (format_local(event_at, "%-I:%M %p") + " WAT") if event_at else "",
        "close_time": format_local(close_at, "%A %-I:%M %p") if close_at else "",
        "price": price,
        "price_line": price_line,
        "early_price": format_money(funnel.get("early_price"), cur),
        "regular_price": regular,
        "group_price": format_money(funnel.get("group_price"), cur) if funnel.get("group_price") else "",
        "group_size": str(group_size) if group_size else "",
        "deadline": format_local(quote.early_ends_at) if quote.early_ends_at else "",
        "pay_link": pay_url(reg),
        "group_pay_link": pay_url(reg, int(group_size)) if group_size else "",
        "group_link": funnel.get("paid_group_link") or "",
        "prep_link": funnel.get("prep_group_link") or "",
        "bonus_link": funnel.get("bonus_link") or "",
        "ref_code": reg.get("ref_code") or "",
        "email": reg.get("email") or "",
    }


def render(text: Optional[str], ctx: dict) -> str:
    """Whitelisted {placeholder} substitution, single pass (no injection via values).
    A line whose placeholders are ALL empty is dropped (e.g. no bonus link set);
    unknown placeholders are left as typed."""
    if not text:
        return ""
    out_lines: list[str] = []
    for line in str(text).split("\n"):
        keys = [k for k in _PLACEHOLDER_RE.findall(line) if k in ctx]
        if keys and all(not str(ctx.get(k) or "") for k in keys):
            continue
        out_lines.append(_PLACEHOLDER_RE.sub(lambda m: str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0), line))
    return "\n".join(out_lines).strip()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def log_event(db, org_id: str, funnel_id: str, registration_id: Optional[str], type_: str,
              step_key: Optional[str] = None, detail: Optional[dict] = None) -> bool:
    """Insert a funnel_events row. Returns False on failure (incl. unique step_key conflict)."""
    try:
        db.table("funnel_events").insert({
            "org_id": org_id, "funnel_id": funnel_id, "registration_id": registration_id,
            "type": type_, "step_key": step_key, "detail": detail or {}, "created_at": _iso(_now()),
        }).execute()
        return True
    except Exception as exc:
        logger.info("funnel_events insert skipped (%s/%s): %s", type_, step_key, exc)
        return False


def _recent_event(db, registration_id: str, type_: str, within: timedelta) -> bool:
    try:
        since = _iso(_now() - within)
        res = (db.table("funnel_events").select("id").eq("registration_id", registration_id)
               .eq("type", type_).gte("created_at", since).limit(1).execute())
        return bool(res.data)
    except Exception:
        return False


def get_active_funnel_for_number(db, org_id: str, number_id: str) -> Optional[dict]:
    try:
        res = (db.table("event_funnels").select("*").eq("org_id", org_id)
               .eq("whatsapp_number_id", number_id).eq("status", "active").limit(1).execute())
        return _one(res.data)
    except Exception as exc:
        logger.warning("get_active_funnel_for_number failed org=%s: %s", org_id, exc)
        return None


def get_registration(db, funnel_id: str, phone: str) -> Optional[dict]:
    try:
        res = (db.table("funnel_registrations").select("*").eq("funnel_id", funnel_id)
               .eq("phone", phone).limit(1).execute())
        return _one(res.data)
    except Exception as exc:
        logger.warning("get_registration failed funnel=%s: %s", funnel_id, exc)
        return None


def _update_reg(db, reg: dict, updates: dict) -> dict:
    updates = dict(updates)
    updates["updated_at"] = _iso(_now())
    try:
        db.table("funnel_registrations").update(updates).eq("id", reg["id"]).eq("org_id", reg["org_id"]).execute()
    except Exception as exc:
        logger.warning("funnel_registrations update failed reg=%s: %s", reg.get("id"), exc)
    merged = dict(reg)
    merged.update(updates)
    return merged


def _get_manager_ids(db, org_id: str) -> list[str]:
    """Pattern 48 — join roles(template), filter in Python."""
    try:
        res = db.table("users").select("id, roles(template)").eq("org_id", org_id).execute()
        return [r["id"] for r in (res.data or [])
                if ((r.get("roles") or {}).get("template") or "").lower() in ("owner", "admin", "ops_manager")]
    except Exception as exc:
        logger.warning("funnel: manager lookup failed org=%s: %s", org_id, exc)
        return []


def notify_managers(db, org_id: str, title: str, body: str, notif_type: str, lead_id: Optional[str]) -> None:
    """Rule 2: resource_type + resource_id (no metadata column). S14."""
    now = _iso(_now())
    for uid in _get_manager_ids(db, org_id):
        try:
            db.table("notifications").insert({
                "org_id": org_id, "user_id": uid, "title": title[:200], "body": body[:1000],
                "type": notif_type, "resource_type": "lead", "resource_id": lead_id,
                "is_read": False, "created_at": now,
            }).execute()
        except Exception as exc:
            logger.warning("funnel notify failed user=%s: %s", uid, exc)


def _find_org_lead(db, org_id: str, phone: str) -> Optional[str]:
    variants = phone_variants(phone)
    for col in ("whatsapp", "phone"):
        try:
            res = (db.table("leads").select("id").eq("org_id", org_id).in_(col, variants)
                   .is_("deleted_at", "null").limit(1).execute())
            row = _one(res.data)
            if row:
                return row["id"]
        except Exception as exc:
            logger.warning("funnel: lead lookup failed org=%s: %s", org_id, exc)
    return None


def _get_or_create_lead(db, org_id: str, phone: str, name: Optional[str], first_text: Optional[str],
                        ad_code: Optional[str], referral: dict) -> Optional[str]:
    existing = _find_org_lead(db, org_id, phone)
    if existing:
        return existing
    try:
        from app.models.leads import LeadCreate, LeadSource
        from app.services import lead_service
        payload = LeadCreate(
            full_name=((name or "").strip() or phone)[:255],
            phone=phone[:20], whatsapp=phone[:20],
            source=LeadSource.whatsapp_inbound.value,
            problem_stated=(first_text or None) and first_text[:5000],
        )
        lead = lead_service.create_lead(
            db=db, org_id=org_id, user_id=None, payload=payload,
            utm_source="facebook" if referral else None,
            campaign_id=(referral.get("ctwa_clid") or referral.get("source_id")) if referral else None,
            entry_path="whatsapp",
            utm_ad=ad_code,
        )
        return lead.get("id")
    except Exception as exc:
        logger.warning("funnel: create_lead failed org=%s: %s", org_id, exc)
        return _find_org_lead(db, org_id, phone)  # duplicate race → reuse


def _create_registration(db, funnel: dict, phone: str, name: Optional[str], lead_id: Optional[str],
                         ad_code: Optional[str], referral: dict, referred_by_id: Optional[str],
                         now: datetime) -> Optional[dict]:
    for _ in range(4):
        row = {
            "org_id": funnel["org_id"], "funnel_id": funnel["id"], "lead_id": lead_id,
            "phone": phone, "name": (name or "")[:255] or None,
            "ad_code": ad_code, "ctwa_clid": (referral.get("ctwa_clid") or None) if referral else None,
            "ad_headline": ((referral.get("headline") or "")[:255] or None) if referral else None,
            "referred_by_id": referred_by_id, "ref_code": new_ref_code(), "pay_token": new_pay_token(),
            "status": "new", "seats": 1, "amount_paid": 0, "done_steps": [],
            "first_message_at": _iso(now), "last_inbound_at": _iso(now),
            "created_at": _iso(now), "updated_at": _iso(now),
        }
        try:
            res = db.table("funnel_registrations").insert(row).execute()
            return _one(res.data) or row
        except Exception as exc:
            existing = get_registration(db, funnel["id"], phone)
            if existing:
                return existing  # two inbound messages raced — use the winner
            logger.info("funnel: registration insert retry (ref/pay token collision?): %s", exc)
    logger.warning("funnel: could not create registration funnel=%s", funnel.get("id"))
    return None


def _save_inbound(db, org_id: str, lead_id: Optional[str], msg_type: str, content: Optional[str],
                  msg_id: Optional[str]) -> None:
    try:
        db.table("whatsapp_messages").insert({
            "org_id": org_id, "lead_id": lead_id, "direction": "inbound",
            "message_type": msg_type if msg_type in ("text", "image") else "text",
            "channel": "whatsapp", "content": content, "status": "delivered",
            "meta_message_id": msg_id or None, "window_open": True,
            "window_expires_at": _iso(_now() + timedelta(hours=24)),
            "sent_by": None, "created_at": _iso(_now()),
        }).execute()
    except Exception as exc:
        logger.warning("funnel: inbound save failed org=%s: %s", org_id, exc)


# ---------------------------------------------------------------------------
# Outbound building blocks
# ---------------------------------------------------------------------------

def send_pay_message(db, funnel: dict, number_row: dict, reg: dict, body_key_or_text: str,
                     seats: int = 1, now: Optional[datetime] = None, raw_text: bool = False) -> bool:
    now = now or _now()
    msgs = funnel_messages(funnel)
    ctx = build_context(funnel, reg, now)
    quote = current_price(funnel, reg, now, seats=seats)
    body = render(body_key_or_text if raw_text else msgs.get(body_key_or_text), ctx)
    if quote.status == "closed":
        return funnel_messaging.send_text(db, funnel["org_id"], number_row, reg["phone"],
                                          render(msgs["closed"], ctx), reg.get("lead_id"))
    btn_ctx = dict(ctx)
    btn_ctx["price"] = format_money(quote.amount, funnel.get("currency") or "NGN")
    button = render(msgs.get("pay_button") or "Pay {price}", btn_ctx)[:20]
    return funnel_messaging.send_cta_url(db, funnel["org_id"], number_row, reg["phone"], body, button,
                                         pay_url(reg, quote.seats), reg.get("lead_id"))


def send_greeting(db, funnel: dict, number_row: dict, reg: dict, now: datetime) -> None:
    msgs = funnel_messages(funnel)
    sent = send_pay_message(db, funnel, number_row, reg, "greeting", now=now)
    faq = msgs.get("faq") or []
    if faq:
        funnel_messaging.send_reply_buttons(
            db, funnel["org_id"], number_row, reg["phone"],
            render(msgs.get("faq_prompt"), build_context(funnel, reg, now)) or "Questions?",
            [{"id": f["id"], "title": f["title"]} for f in faq], reg.get("lead_id"))
    log_event(db, funnel["org_id"], funnel["id"], reg["id"], "greeting_sent", detail={"ok": sent})


# ---------------------------------------------------------------------------
# Inbound (webhooks intercept)
# ---------------------------------------------------------------------------

def handle_inbound(db, number_row: dict, sender_phone: str, contact_name: Optional[str],
                   msg_type: str, content: Optional[str], msg_id: Optional[str],
                   interactive_payload: Optional[dict], referral: Optional[dict],
                   now: Optional[datetime] = None) -> None:
    """Entry point for numbers in wa_sales_mode='event_funnel'. S14 — never raises."""
    now = now or _now()
    org_id = number_row.get("org_id")
    try:
        if not org_id:
            return
        funnel = get_active_funnel_for_number(db, org_id, number_row.get("id"))
        text = (content or "").strip()
        if not funnel:
            _save_inbound(db, org_id, _find_org_lead(db, org_id, sender_phone), msg_type, content, msg_id)
            funnel_messaging.send_text(db, org_id, number_row, sender_phone, DEFAULT_MESSAGES["no_funnel"])
            return
        msgs = funnel_messages(funnel)
        referral = referral or {}
        reg = get_registration(db, funnel["id"], sender_phone)

        # ── New lead ──────────────────────────────────────────────────────
        if not reg:
            ad_code = parse_ad_code(text, funnel.get("ad_codes") or [])
            referred_by_id = None
            for code in parse_ref_codes(text):
                try:
                    r = (db.table("funnel_registrations").select("id").eq("funnel_id", funnel["id"])
                         .eq("ref_code", code).limit(1).execute())
                    row = _one(r.data)
                    if row:
                        referred_by_id = row["id"]
                        break
                except Exception:
                    pass
            lead_id = _get_or_create_lead(db, org_id, sender_phone, contact_name, text, ad_code, referral)
            reg = _create_registration(db, funnel, sender_phone, contact_name, lead_id, ad_code,
                                       referral, referred_by_id, now)
            _save_inbound(db, org_id, lead_id, msg_type, content, msg_id)
            if not reg:
                return
            log_event(db, org_id, funnel["id"], reg.get("id"), "lead_created",
                      detail={"ad_code": ad_code, "referred": bool(referred_by_id)})
            if current_price(funnel, reg, now).status == "closed":
                funnel_messaging.send_text(db, org_id, number_row, sender_phone,
                                           render(msgs["closed"], build_context(funnel, reg, now)), lead_id)
                return
            send_greeting(db, funnel, number_row, reg, now)
            return

        # ── Existing registration ────────────────────────────────────────
        _save_inbound(db, org_id, reg.get("lead_id"), msg_type, content, msg_id)
        settings = funnel_settings(funnel)
        reg = _update_reg(db, reg, {
            "last_inbound_at": _iso(now),
            "paused_until": _iso(now + timedelta(minutes=int(settings["pause_minutes_after_reply"]))),
        })
        lower = text.lower()
        ctx = build_context(funnel, reg, now)

        if lower in _OPT_OUT:
            _update_reg(db, reg, {"status": "opted_out"})
            _set_lead_opt_out(db, org_id, reg.get("lead_id"), True)
            funnel_messaging.send_text(db, org_id, number_row, sender_phone, msgs["opted_out"], reg.get("lead_id"))
            log_event(db, org_id, funnel["id"], reg["id"], "opted_out")
            return
        if lower in _OPT_IN:
            if reg.get("status") == "opted_out":
                _update_reg(db, reg, {"status": "paid" if reg.get("paid_at") else "new"})
                _set_lead_opt_out(db, org_id, reg.get("lead_id"), False)
                funnel_messaging.send_text(db, org_id, number_row, sender_phone, msgs["opted_in"], reg.get("lead_id"))
            return
        if reg.get("status") == "opted_out":
            return

        faq_id = ((interactive_payload or {}).get("button_reply") or {}).get("id")
        if faq_id:
            for f in msgs.get("faq") or []:
                if f.get("id") == faq_id:
                    funnel_messaging.send_text(db, org_id, number_row, sender_phone,
                                               render(f.get("answer"), ctx), reg.get("lead_id"))
                    return

        is_paid = reg.get("status") == "paid"
        quote = current_price(funnel, reg, now)

        if is_paid:
            email = parse_email(text)
            if email and not reg.get("email"):
                reg = _update_reg(db, reg, {"email": email})
                _set_lead_email(db, org_id, reg.get("lead_id"), email)
                log_event(db, org_id, funnel["id"], reg["id"], "email_captured")
                funnel_messaging.send_text(db, org_id, number_row, sender_phone,
                                           render(msgs["email_thanks"], build_context(funnel, reg, now)),
                                           reg.get("lead_id"))
                return
            if (len(text.split()) <= 8 and _PAY_RE.search(text)) or "group link" in lower:
                funnel_messaging.send_text(db, org_id, number_row, sender_phone,
                                           render(msgs["already_paid"], ctx), reg.get("lead_id"))
                return
            _handoff(db, funnel, number_row, reg, text, now)
            return

        if quote.status == "closed":
            if not _recent_event(db, reg["id"], "closed_sent", timedelta(hours=24)):
                funnel_messaging.send_text(db, org_id, number_row, sender_phone,
                                           render(msgs["closed"], ctx), reg.get("lead_id"))
                log_event(db, org_id, funnel["id"], reg["id"], "closed_sent")
            return

        # Keyword shortcuts only for SHORT messages — a long question goes to a person.
        short = len(text.split()) <= 8
        if short and funnel.get("group_size") and funnel.get("group_price") and _GROUP_RE.search(text):
            send_pay_message(db, funnel, number_row, reg, "group_offer", seats=int(funnel["group_size"]), now=now)
            return
        if short and _PAY_RE.search(text):
            send_pay_message(db, funnel, number_row, reg, "pay_link_resend", now=now)
            return
        _handoff(db, funnel, number_row, reg, text, now)
    except Exception as exc:
        logger.warning("funnel handle_inbound failed org=%s: %s", org_id, exc)


def _set_lead_opt_out(db, org_id: str, lead_id: Optional[str], value: bool) -> None:
    if not lead_id:
        return
    try:
        db.table("leads").update({"whatsapp_opted_out": value}).eq("id", lead_id).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.warning("funnel: lead opt flag failed lead=%s: %s", lead_id, exc)


def _set_lead_email(db, org_id: str, lead_id: Optional[str], email: str) -> None:
    if not lead_id:
        return
    try:
        db.table("leads").update({"email": email}).eq("id", lead_id).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.info("funnel: lead email update skipped lead=%s: %s", lead_id, exc)


def _handoff(db, funnel: dict, number_row: dict, reg: dict, text: str, now: datetime) -> None:
    org_id = funnel["org_id"]
    first_flag = not reg.get("needs_human")
    _update_reg(db, reg, {"needs_human": True})
    if first_flag:
        notify_managers(db, org_id, f"Webinar lead needs you: {reg.get('name') or reg.get('phone')}",
                        (text or "")[:300], "funnel_handoff", reg.get("lead_id"))
    if not _recent_event(db, reg["id"], "handoff", timedelta(hours=6)):
        funnel_messaging.send_text(db, org_id, number_row, reg["phone"],
                                   render(funnel_messages(funnel)["handoff_ack"], build_context(funnel, reg, now)),
                                   reg.get("lead_id"))
        log_event(db, org_id, funnel["id"], reg["id"], "handoff")


# ---------------------------------------------------------------------------
# Public pay link
# ---------------------------------------------------------------------------

@dataclass
class PayRedirect:
    kind: str                    # "redirect" | "closed" | "already_paid" | "not_found" | "error"
    url: Optional[str] = None
    event: Optional[str] = None
    group_link: Optional[str] = None


def get_pay_redirect(db, token: str, seats: int = 1, now: Optional[datetime] = None) -> PayRedirect:
    now = now or _now()
    if not token or len(token) > 64 or not re.fullmatch(r"[A-Za-z0-9_\-]+", token):
        return PayRedirect("not_found")
    try:
        reg = _one((db.table("funnel_registrations").select("*").eq("pay_token", token).limit(1).execute()).data)
        if not reg:
            return PayRedirect("not_found")
        funnel = _one((db.table("event_funnels").select("*").eq("id", reg["funnel_id"])
                       .eq("org_id", reg["org_id"]).limit(1).execute()).data)
        if not funnel:
            return PayRedirect("not_found")
        event = funnel.get("event_title") or funnel.get("name")
        if reg.get("status") == "paid" and seats <= 1:
            return PayRedirect("already_paid", event=event, group_link=funnel.get("paid_group_link"))
        quote = current_price(funnel, reg, now, seats=seats)
        if quote.status == "closed":
            return PayRedirect("closed", event=event)
        if not reg.get("lead_id"):
            return PayRedirect("error", event=event)

        # Reuse a recent pending link for the same amount/seats (no Paystack spam on refresh)
        try:
            since = _iso(now - timedelta(hours=12))
            pend = (db.table("funnel_payments").select("*").eq("registration_id", reg["id"])
                    .eq("status", "pending").gte("created_at", since).execute()).data or []
            for p in pend:
                if float(p.get("amount") or 0) == float(quote.amount) and int(p.get("seats") or 1) == quote.seats \
                        and p.get("checkout_url"):
                    log_event(db, reg["org_id"], funnel["id"], reg["id"], "pay_link_opened",
                              detail={"tier": quote.tier, "reused": True})
                    return PayRedirect("redirect", url=p["checkout_url"], event=event)
        except Exception as exc:
            logger.info("funnel: pending link lookup failed reg=%s: %s", reg.get("id"), exc)

        from app.services import paystack_storefront_service
        link = paystack_storefront_service.generate_payment_link(
            db=db, org_id=reg["org_id"], lead_id=reg["lead_id"], amount=float(quote.amount),
            payment_type="full", currency=funnel.get("currency") or "NGN",
            trigger_stage=None, target_stage_on_paid=None, created_by=None,
        )
        db.table("funnel_payments").insert({
            "org_id": reg["org_id"], "funnel_id": funnel["id"], "registration_id": reg["id"],
            "reference": link["reference"], "checkout_url": link["checkout_url"],
            "amount": float(quote.amount), "tier": quote.tier, "seats": quote.seats,
            "status": "pending", "created_at": _iso(now),
        }).execute()
        log_event(db, reg["org_id"], funnel["id"], reg["id"], "pay_link_opened",
                  detail={"tier": quote.tier, "amount": quote.amount, "seats": quote.seats})
        return PayRedirect("redirect", url=link["checkout_url"], event=event)
    except Exception as exc:
        logger.warning("funnel get_pay_redirect failed: %s", exc)
        return PayRedirect("error")


# ---------------------------------------------------------------------------
# Payment hook
# ---------------------------------------------------------------------------

def is_funnel_reference(db, org_id: str, reference: str) -> bool:
    try:
        res = (db.table("funnel_payments").select("id").eq("org_id", org_id)
               .eq("reference", reference).limit(1).execute())
        return bool(res.data)
    except Exception:
        return False


def _number_row_by_id(db, org_id: str, number_id: Optional[str]) -> Optional[dict]:
    if not number_id:
        return None
    try:
        return _one((db.table("whatsapp_numbers").select("*").eq("id", number_id)
                     .eq("org_id", org_id).limit(1).execute()).data)
    except Exception:
        return None


def on_payment_confirmed(db, org_id: str, reference: str, now: Optional[datetime] = None) -> bool:
    """Returns True if the reference belonged to a funnel (handled), False otherwise. S14."""
    now = now or _now()
    try:
        fp = _one((db.table("funnel_payments").select("*").eq("org_id", org_id)
                   .eq("reference", reference).limit(1).execute()).data)
        if not fp:
            return False
        if fp.get("status") != "pending":
            return True  # idempotent

        from app.services import paystack_storefront_service
        ver = paystack_storefront_service.verify_transaction(db, org_id, reference)
        data = ver.get("data") or {}
        paid_amount = float(data.get("amount") or 0) / 100.0
        if not ver.get("verified") or data.get("status") != "success" or paid_amount + 0.001 < float(fp["amount"]):
            db.table("funnel_payments").update({"status": "mismatch"}).eq("id", fp["id"]) \
                .eq("status", "pending").execute()
            log_event(db, org_id, fp["funnel_id"], fp["registration_id"], "payment_amount_mismatch",
                      detail={"expected": fp["amount"], "paid": paid_amount, "verified": ver.get("verified")})
            notify_managers(db, org_id, "Webinar payment needs checking",
                            f"Reference {reference}: expected {fp['amount']}, Paystack says {paid_amount}.",
                            "funnel_payment_issue", None)
            return True

        # Claim: only one webhook delivery may move pending → paid
        claim = (db.table("funnel_payments").update({"status": "paid", "paid_at": _iso(now)})
                 .eq("id", fp["id"]).eq("status", "pending").execute())
        if not claim.data:
            return True

        reg = _one((db.table("funnel_registrations").select("*").eq("id", fp["registration_id"])
                    .eq("org_id", org_id).limit(1).execute()).data)
        funnel = _one((db.table("event_funnels").select("*").eq("id", fp["funnel_id"])
                       .eq("org_id", org_id).limit(1).execute()).data)
        if not reg or not funnel:
            return True
        reg = _update_reg(db, reg, {
            "status": "paid",
            "amount_paid": float(reg.get("amount_paid") or 0) + paid_amount,
            "seats": max(int(reg.get("seats") or 1), int(fp.get("seats") or 1)),
            "paid_at": reg.get("paid_at") or _iso(now),
            "payment_reference": reference,
            "price_tier_paid": fp.get("tier"),
            "needs_human": False,
        })
        log_event(db, org_id, funnel["id"], reg["id"], "payment_confirmed",
                  detail={"amount": paid_amount, "tier": fp.get("tier"), "seats": fp.get("seats")})
        number_row = _number_row_by_id(db, org_id, funnel.get("whatsapp_number_id"))
        if number_row:
            funnel_messaging.send_text(db, org_id, number_row, reg["phone"],
                                       render(funnel_messages(funnel)["paid_confirmation"],
                                              build_context(funnel, reg, now)),
                                       reg.get("lead_id"))
        notify_managers(db, org_id, f"Webinar seat paid: {reg.get('name') or reg.get('phone')}",
                        f"{format_money(paid_amount, funnel.get('currency') or 'NGN')} · {fp.get('tier')}"
                        + (f" · code {reg.get('ad_code')}" if reg.get("ad_code") else ""),
                        "funnel_payment", reg.get("lead_id"))
        return True
    except Exception as exc:
        logger.warning("funnel on_payment_confirmed failed org=%s ref=%s: %s", org_id, reference, exc)
        return True


def mark_paid_manually(db, org_id: str, funnel: dict, reg: dict, amount: float, seats: int,
                       note: Optional[str], user_id: Optional[str], send_confirmation: bool = True) -> dict:
    """Bank transfer / cash — admin action from the dashboard."""
    now = _now()
    reg = _update_reg(db, reg, {
        "status": "paid", "amount_paid": float(reg.get("amount_paid") or 0) + float(amount),
        "seats": max(int(reg.get("seats") or 1), seats), "paid_at": reg.get("paid_at") or _iso(now),
        "price_tier_paid": "manual", "needs_human": False,
    })
    log_event(db, org_id, funnel["id"], reg["id"], "manual_paid",
              detail={"amount": amount, "seats": seats, "note": (note or "")[:500], "by": user_id})
    if send_confirmation:
        number_row = _number_row_by_id(db, org_id, funnel.get("whatsapp_number_id"))
        if number_row:
            funnel_messaging.send_text(db, org_id, number_row, reg["phone"],
                                       render(funnel_messages(funnel)["paid_confirmation"],
                                              build_context(funnel, reg, now)), reg.get("lead_id"))
    return reg


# ---------------------------------------------------------------------------
# Sequence planning (pure) + processing
# ---------------------------------------------------------------------------

def _anchor_time(anchor: str, funnel: dict, reg: dict) -> Optional[datetime]:
    mode = funnel.get("pricing_mode") or "window"
    if anchor == "first_message":
        return _dt(reg.get("first_message_at"))
    if anchor == "window_end":
        if mode != "window":
            return None
        first = _dt(reg.get("first_message_at"))
        return first + timedelta(hours=int(funnel.get("window_hours") or 24)) if first else None
    if anchor == "early_deadline":
        return _dt(funnel.get("early_deadline_at")) if mode == "deadline" else None
    if anchor == "event_start":
        return _dt(funnel.get("event_starts_at"))
    if anchor == "registration_close":
        return _dt(funnel.get("registration_closes_at"))
    return None


@dataclass
class StepPlan:
    action: str                     # "send" | "skip" | "wait" | "none"
    step: Optional[dict] = None
    reason: str = ""
    channel: Optional[str] = None   # "text" | "template"


def plan_next_step(funnel: dict, reg: dict, steps: list[dict], now: datetime,
                   sent_last_24h: int = 0, quiet: bool = False) -> StepPlan:
    """Decide what to do for ONE registration right now. Pure — unit-tested."""
    status = reg.get("status")
    if status not in ACTIVE_REG_STATUSES:
        return StepPlan("none", reason="inactive")
    settings = funnel_settings(funnel)
    done = set(reg.get("done_steps") or [])
    first = _dt(reg.get("first_message_at"))
    close = _dt(funnel.get("registration_closes_at"))
    stale_after = timedelta(minutes=int(settings["stale_after_minutes"]))

    due: list[tuple[datetime, dict]] = []
    for step in steps:
        if not step.get("enabled", True) or step["key"] in done:
            continue
        aud = step.get("audience", "unpaid")
        if aud == "unpaid" and status != "new":
            continue
        if aud == "paid" and status != "paid":
            continue
        anchor = _anchor_time(step["anchor"], funnel, reg)
        if anchor is None:
            return StepPlan("skip", step, reason="anchor_not_applicable")
        at = anchor + timedelta(minutes=int(step["offset_minutes"]))
        if at > now:
            continue
        due.append((at, step))
    if not due:
        return StepPlan("none")
    due.sort(key=lambda x: x[0])
    at, step = due[0]

    if first and step["anchor"] != "first_message" and at < first:
        return StepPlan("skip", step, reason="before_join")
    if now - at > stale_after:
        return StepPlan("skip", step, reason="stale")
    if step.get("audience", "unpaid") == "unpaid" and close and now >= close:
        return StepPlan("skip", step, reason="registration_closed")
    quote = current_price(funnel, reg, now)
    if step.get("only_if_early") and quote.tier != "early":
        return StepPlan("skip", step, reason="no_longer_early")
    paused = _dt(reg.get("paused_until"))
    if paused and now < paused:
        return StepPlan("wait", step, reason="paused")
    if quiet and settings["respect_quiet_hours"]:
        return StepPlan("wait", step, reason="quiet_hours")
    if quote.tier != "early" and sent_last_24h >= int(settings["max_auto_per_day_after_window"]):
        return StepPlan("wait", step, reason="daily_cap")

    last_in = _dt(reg.get("last_inbound_at"))
    window_open = bool(last_in and now - last_in < timedelta(hours=23, minutes=50))
    if window_open and step.get("text"):
        return StepPlan("send", step, channel="text")
    if step.get("template_name"):
        return StepPlan("send", step, channel="template")
    return StepPlan("skip", step, reason="window_closed_no_template")


def execute_step(db, funnel: dict, number_row: dict, reg: dict, plan: StepPlan, now: datetime) -> str:
    """Claim the step (unique funnel_events row), then send. Returns 'sent'|'skipped'|'failed'|'raced'."""
    step = plan.step or {}
    key = step.get("key")
    if plan.action == "skip":
        if log_event(db, funnel["org_id"], funnel["id"], reg["id"], "step_skipped", key, {"reason": plan.reason}):
            _update_reg(db, reg, {"done_steps": list(reg.get("done_steps") or []) + [key]})
            return "skipped"
        _update_reg(db, reg, {"done_steps": list(reg.get("done_steps") or []) + [key]})
        return "raced"
    # FUNNEL-1B: template sends get their own event type so the template budget can count them
    sent_type = "template_sent" if plan.channel == "template" else "step_sent"
    if not log_event(db, funnel["org_id"], funnel["id"], reg["id"], sent_type, key, {"channel": plan.channel}):
        _update_reg(db, reg, {"done_steps": list(reg.get("done_steps") or []) + [key]})
        return "raced"
    _update_reg(db, reg, {"done_steps": list(reg.get("done_steps") or []) + [key]})

    ctx = build_context(funnel, reg, now)
    if plan.channel == "text":
        if step.get("include_pay_button"):
            ok = send_pay_message(db, funnel, number_row, reg, step["text"], now=now, raw_text=True)
        else:
            ok = funnel_messaging.send_text(db, funnel["org_id"], number_row, reg["phone"],
                                            render(step["text"], ctx), reg.get("lead_id"))
    else:
        params = [render(p, ctx) for p in (step.get("template_params") or [])]
        ok = funnel_messaging.send_template(db, funnel["org_id"], number_row, reg["phone"],
                                            step["template_name"], params, lead_id=reg.get("lead_id"))
    if not ok:
        try:
            db.table("funnel_events").update({"type": "step_failed"}).eq("registration_id", reg["id"]) \
                .eq("step_key", key).execute()
        except Exception:
            pass
        return "failed"
    return "sent"


# ---------------------------------------------------------------------------
# Stats (dashboard)
# ---------------------------------------------------------------------------

def get_funnel_stats(db, org_id: str, funnel: dict) -> dict:
    regs = _fetch_all(lambda: db.table("funnel_registrations")
                      .select("id, status, ad_code, amount_paid, seats, paid_at, first_message_at, "
                              "referred_by_id, needs_human, price_tier_paid, name, ref_code, email")
                      .eq("org_id", org_id).eq("funnel_id", funnel["id"]).order("created_at"))
    window_h = int(funnel.get("window_hours") or 24)
    total = len(regs)
    paid = [r for r in regs if r.get("status") == "paid"]
    paid_24h = 0
    for r in paid:
        f, p = _dt(r.get("first_message_at")), _dt(r.get("paid_at"))
        if f and p and p - f <= timedelta(hours=window_h):
            paid_24h += 1
    by_code: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    for r in regs:
        code = r.get("ad_code") or ("referral" if r.get("referred_by_id") else "unknown")
        b = by_code.setdefault(code, {"code": code, "leads": 0, "paid": 0, "seats": 0, "revenue": 0.0})
        b["leads"] += 1
        d = (_dt(r.get("first_message_at")) or _now()).astimezone(LAGOS).date().isoformat()
        day = by_day.setdefault(d, {"date": d, "leads": 0, "paid": 0, "revenue": 0.0})
        day["leads"] += 1
        if r.get("status") == "paid":
            b["paid"] += 1
            b["seats"] += int(r.get("seats") or 1)
            b["revenue"] += float(r.get("amount_paid") or 0)
            pd = (_dt(r.get("paid_at")) or _now()).astimezone(LAGOS).date().isoformat()
            pday = by_day.setdefault(pd, {"date": pd, "leads": 0, "paid": 0, "revenue": 0.0})
            pday["paid"] += 1
            pday["revenue"] += float(r.get("amount_paid") or 0)
    refs: dict[str, int] = {}
    for r in paid:
        if r.get("referred_by_id"):
            refs[r["referred_by_id"]] = refs.get(r["referred_by_id"], 0) + 1
    by_id = {r["id"]: r for r in regs}
    referrers = sorted(
        [{"registration_id": k, "name": (by_id.get(k) or {}).get("name"), "ref_code": (by_id.get(k) or {}).get("ref_code"),
          "paid_referrals": v} for k, v in refs.items()],
        key=lambda x: -x["paid_referrals"])
    return {
        "leads": total,
        "paid": len(paid),
        "seats": sum(int(r.get("seats") or 1) for r in paid),
        "revenue": round(sum(float(r.get("amount_paid") or 0) for r in paid), 2),
        "conversion": round(len(paid) / total, 4) if total else 0.0,
        "conversion_in_window": round(paid_24h / total, 4) if total else 0.0,
        "needs_human": sum(1 for r in regs if r.get("needs_human")),
        "missing_email": sum(1 for r in paid if not r.get("email")),
        "by_ad_code": sorted(by_code.values(), key=lambda x: -x["revenue"]),
        "by_day": sorted(by_day.values(), key=lambda x: x["date"]),
        "referrers": referrers[:50],
    }
