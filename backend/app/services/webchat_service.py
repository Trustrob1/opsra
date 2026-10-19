"""
app/services/webchat_service.py
-------------------------------
WEBCHAT-1 — Opsra's own chat page: keys, settings, sessions, messages, contact capture.

A visitor opens /c/{key}. The key (webchat_keys) names the org; nothing in a request
body can change which org a chat belongs to. The visitor holds a session token; only
its sha256 is stored. Until the visitor gives a name and a WhatsApp number or an email,
messages live inside the session row (no lead is created for an anonymous visit). When
contact is given a normal lead is created (or the existing one is found) and the earlier
messages move into whatsapp_messages with channel 'webchat', so the chat shows up in the
existing inbox like Instagram and Messenger chats do.

No AI here (WEBCHAT-3). Meta is never called by anything in this module: a web chat
message has no Meta fee.

S14: helpers that run as side effects (events, notifications) never raise.
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

logger = logging.getLogger(__name__)

SESSION_DAYS = 30
HANDOFF_HOURS = 48
HISTORY_CAP = 100
MAX_TEXT = 1000
CONSENT_VERSION = "webchat-2026-10"
MENU_MAX = 12
TOUCH_EVERY_S = 300

DEFAULT_CONFIG: dict = {
    "enabled": False,
    "business_name": "",
    "brand_color": "#028090",
    "greeting": "Hi! How can we help you today? Pick an option below or type your question.",
    "menu": [],
    "booking_fields": [
        {"key": "service", "label": "What would you like to book?", "required": True},
        {"key": "when", "label": "Preferred day and time", "required": True},
    ],
    "contact_prompt": "To carry on, tell us who you are so we can reach you if we get disconnected.",
    "consent_text": "I agree to be contacted about my enquiry.",
    "fallback": "I did not catch that. Pick one of the options below, or tap Talk to us.",
    "human_reply": "Thanks. A team member will reply here as soon as they can.",
    "booking_done": "Thank you. We have your request and will confirm shortly.",
    "redirect_mode": "always",
    "redirect_text": "",
    "ai_enabled": False,          # WEBCHAT-3: AI answers typed questions (after contact details)
    "ai_model": "haiku",          # haiku (cheapest) | sonnet
    "ai_instructions": "",
    "ai_max_turns": 12,
    "wa_followups": False,        # WEBCHAT-4b: OPT-IN WhatsApp follow-ups (each template message costs a Meta fee)
    "wa_followup_mode": "fallback",   # fallback = email first | prefer = WhatsApp first
    "wa_template_name": "",
    "wa_template_lang": "en",
    "wa_monthly_cap": 100,
    "email_followups": True,      # WEBCHAT-4: email replies / confirmations to visitors who gave an email and consent
    "human_resume_min": 30,       # minutes of team silence after which the bot answers again
    "shop_enabled": False,        # WEBCHAT-3b: product cards, cart and checkout link in the chat
    "goals": None,                # WEBCHAT-5b: what counts as a win in the funnel; None = automatic (booking, plus orders and payments when the shop is on)
    "stats_from": None,           # WEBCHAT-5b: ISO time; the numbers ignore anything before it (start counting from now)
}
GOAL_KEYS = ("booking", "order", "paid", "whatsapp", "tap")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def public_base() -> str:
    """Address of the chat page. WEBCHAT_BASE_URL (a domain Opsra owns) wins; else the app's own address."""
    base = os.environ.get("WEBCHAT_BASE_URL", "").strip()
    if not base:
        try:
            from app.config import settings
            base = settings.FRONTEND_URL
        except Exception:
            base = ""
    return base.rstrip("/")


# ── Rate limits: Redis when it is there (shared across workers), else in-process ──

def rate_limited(bucket: str, limit: int, window_s: int) -> bool:
    try:
        from app.services.ai_service import _get_redis
        r = _get_redis()
        if r is not None:
            key = f"wc:rl:{bucket}"
            n = r.incr(key)
            if n == 1:
                r.expire(key, window_s)
            return n > limit
    except Exception as exc:
        logger.warning("webchat rate limit: redis unavailable (%s) — using in-process counter", exc)
    from app.services.site_capture_service import rate_limited as _local
    return _local(f"wc:{bucket}", limit, float(window_s))


# ── Settings ────────────────────────────────────────────────────────────────

def _clean_text(v: Any, n: int) -> str:
    return re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", "", str(v or "")).strip()[:n]


def _clean_url(v: Any) -> Optional[str]:
    u = str(v or "").strip()
    return u[:500] if re.match(r"^https?://[^\s<>\"']+$", u, re.I) else None


def sanitise_config(raw: dict) -> dict:
    """Validate what an admin sends. Unknown keys are dropped; every text has a length cap."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    if "enabled" in raw:
        out["enabled"] = bool(raw["enabled"])
    for k, n in (("business_name", 120), ("greeting", 400), ("contact_prompt", 300), ("consent_text", 300),
                 ("fallback", 300), ("human_reply", 300), ("booking_done", 300), ("redirect_text", 600)):
        if k in raw:
            out[k] = _clean_text(raw[k], n)
    if "brand_color" in raw:
        c = str(raw["brand_color"] or "").strip()
        out["brand_color"] = c if re.match(r"^#[0-9a-fA-F]{6}$", c) else DEFAULT_CONFIG["brand_color"]
    if "wa_followups" in raw:
        out["wa_followups"] = bool(raw["wa_followups"])
    if "wa_followup_mode" in raw:
        out["wa_followup_mode"] = raw["wa_followup_mode"] if raw["wa_followup_mode"] in ("fallback", "prefer") else "fallback"
    if "wa_template_name" in raw:
        name = re.sub(r"[^a-z0-9_]", "", str(raw["wa_template_name"] or "").lower())[:100]
        out["wa_template_name"] = name
    if "wa_template_lang" in raw:
        m = re.match(r"^[A-Za-z]{2,3}(_[A-Za-z]{2,4})?", str(raw["wa_template_lang"] or "").strip())
        out["wa_template_lang"] = m.group(0) if m else "en"
    if "wa_monthly_cap" in raw:
        try:
            out["wa_monthly_cap"] = max(1, min(int(raw["wa_monthly_cap"]), 5000))
        except (TypeError, ValueError):
            out["wa_monthly_cap"] = 100
    if "email_followups" in raw:
        out["email_followups"] = bool(raw["email_followups"])
    if "human_resume_min" in raw:
        try:
            out["human_resume_min"] = max(5, min(int(raw["human_resume_min"]), 1440))
        except (TypeError, ValueError):
            out["human_resume_min"] = 30
    if "shop_enabled" in raw:
        out["shop_enabled"] = bool(raw["shop_enabled"])
    if "goals" in raw:
        g = raw["goals"]
        picked = [k for k in GOAL_KEYS if isinstance(g, list) and k in g]
        out["goals"] = picked or None
    if "stats_from" in raw:
        v = raw["stats_from"]
        if v == "now":
            out["stats_from"] = _iso(_now())
        else:
            try:
                out["stats_from"] = _iso(datetime.fromisoformat(str(v).replace("Z", "+00:00"))) if v else None
            except (TypeError, ValueError):
                out["stats_from"] = None
    if "ai_enabled" in raw:
        out["ai_enabled"] = bool(raw["ai_enabled"])
    if "ai_model" in raw:
        out["ai_model"] = raw["ai_model"] if raw["ai_model"] in ("haiku", "sonnet") else "haiku"
    if "ai_instructions" in raw:
        out["ai_instructions"] = _clean_text(raw["ai_instructions"], 800)
    if "ai_max_turns" in raw:
        try:
            out["ai_max_turns"] = max(1, min(int(raw["ai_max_turns"]), 30))
        except (TypeError, ValueError):
            out["ai_max_turns"] = 12
    if "redirect_mode" in raw:
        out["redirect_mode"] = raw["redirect_mode"] if raw["redirect_mode"] in ("always", "menu_first") else "always"
    if "menu" in raw and isinstance(raw["menu"], list):
        menu, seen = [], set()
        for it in raw["menu"][:MENU_MAX]:
            if not isinstance(it, dict):
                continue
            mid = re.sub(r"[^a-z0-9_-]", "", str(it.get("id") or "").lower())[:30]
            label = _clean_text(it.get("label"), 60)
            if not mid or not label or mid in seen:
                continue
            seen.add(mid)
            item = {"id": mid, "label": label}
            action = it.get("action")
            if action in ("booking", "human"):
                item["action"] = action
            else:
                item["answer"] = _clean_text(it.get("answer"), 1000)
                link = it.get("link")
                if isinstance(link, dict) and _clean_url(link.get("url")):
                    item["link"] = {"label": _clean_text(link.get("label"), 60) or "Open", "url": _clean_url(link["url"])}
            kws = it.get("keywords") if isinstance(it.get("keywords"), list) else []
            item["keywords"] = [_clean_text(k, 30).lower() for k in kws[:15] if _clean_text(k, 30)]
            menu.append(item)
        out["menu"] = menu
    if "booking_fields" in raw and isinstance(raw["booking_fields"], list):
        fields, seen = [], set()
        for f in raw["booking_fields"][:8]:
            if not isinstance(f, dict):
                continue
            key = re.sub(r"[^a-z0-9_]", "", str(f.get("key") or "").lower())[:30]
            label = _clean_text(f.get("label"), 80)
            if key and label and key not in seen:
                seen.add(key)
                fields.append({"key": key, "label": label, "required": bool(f.get("required", True))})
        out["booking_fields"] = fields
    return out


def get_config(db, org_id: str) -> dict:
    """Defaults + the org's stored settings. business_name falls back to the organisation's name."""
    try:
        row = _one((db.table("organisations").select("name, webchat_config").eq("id", org_id).limit(1).execute()).data) or {}
    except Exception as exc:
        logger.warning("webchat get_config failed org=%s: %s", org_id, exc)
        row = {}
    cfg = dict(DEFAULT_CONFIG)
    stored = row.get("webchat_config") if isinstance(row.get("webchat_config"), dict) else {}
    cfg.update(sanitise_config(stored))
    if not cfg.get("business_name"):
        cfg["business_name"] = row.get("name") or "Our team"
    return cfg


def save_config(db, org_id: str, changes: dict) -> dict:
    cur = _one((db.table("organisations").select("webchat_config").eq("id", org_id).limit(1).execute()).data) or {}
    stored = cur.get("webchat_config") if isinstance(cur.get("webchat_config"), dict) else {}
    stored = {**stored, **sanitise_config(changes)}
    db.table("organisations").update({"webchat_config": stored}).eq("id", org_id).execute()
    return get_config(db, org_id)


def public_view(cfg: dict) -> dict:
    """The only settings a visitor's browser receives."""
    return {
        "business_name": cfg["business_name"], "brand_color": cfg["brand_color"], "greeting": cfg["greeting"],
        "menu": [{"id": m["id"], "label": m["label"]} for m in cfg["menu"]],
        "contact_prompt": cfg["contact_prompt"], "consent_text": cfg["consent_text"],
        "booking_fields": cfg["booking_fields"], "shop_enabled": bool(cfg.get("shop_enabled")), "email_enabled": bool(cfg.get("email_followups", True)),
    }


# ── Keys ────────────────────────────────────────────────────────────────────

def get_or_create_key(db, org_id: str) -> str:
    row = _one((db.table("webchat_keys").select("key").eq("org_id", org_id).eq("active", True).limit(1).execute()).data)
    if row:
        return row["key"]
    for _ in range(3):
        key = "wc_" + secrets.token_urlsafe(12)
        try:
            db.table("webchat_keys").insert({"key": key, "org_id": org_id, "active": True}).execute()
            return key
        except Exception as exc:
            again = _one((db.table("webchat_keys").select("key").eq("org_id", org_id).eq("active", True).limit(1).execute()).data)
            if again:
                return again["key"]  # another request made one first
            logger.info("webchat key insert retry: %s", exc)
    raise RuntimeError("could not create a chat key")


def resolve_key(db, key: str) -> Optional[dict]:
    """{'org_id', 'config'} for an active key whose org has the chat switched on; else None."""
    if not isinstance(key, str) or not re.match(r"^wc_[A-Za-z0-9_-]{8,40}$", key):
        return None
    row = _one((db.table("webchat_keys").select("org_id").eq("key", key).eq("active", True).limit(1).execute()).data)
    if not row:
        return None
    cfg = get_config(db, row["org_id"])
    if not cfg.get("enabled"):
        return None
    from app.services import webchat_plan_service as plan        # ACCOUNT-PLANS AP-4: what the plan includes
    cfg = plan.apply(db, row["org_id"], cfg)
    if cfg is None:
        return None
    return {"org_id": row["org_id"], "config": cfg, "key": key}


def chat_link(db, org_id: str, source: Optional[str] = None) -> str:
    link = f"{public_base()}/c/{get_or_create_key(db, org_id)}"
    return link + (f"?s={source}" if source else "")


# ── Sessions ────────────────────────────────────────────────────────────────

def log_event(db, org_id: str, session_id: Optional[str], kind: str, source: Optional[str] = None,
              ref: Optional[str] = None, value_kobo: Optional[int] = None) -> None:
    try:
        row = {"org_id": org_id, "session_id": session_id, "kind": kind, "source": (source or None) and source[:30]}
        if ref:                      # WEBCHAT-5b columns, only sent when used so older events keep working
            row["ref"] = str(ref)[:80]
        if value_kobo is not None:
            row["value_kobo"] = int(value_kobo)
        db.table("webchat_events").insert(row).execute()
    except Exception as exc:
        logger.warning("webchat event failed: %s", exc)


def on_payment_confirmed(db, org_id: str, reference: str) -> bool:
    """WEBCHAT-5b: a Paystack payment came in. If it belongs to a web chat checkout, record 'paid' against the same
    chat and source (once). No-op for any other payment. Never raises."""
    try:
        if not reference:
            return False
        order = _one((db.table("webchat_events").select("session_id, source").eq("org_id", org_id).eq("kind", "order")
                      .eq("ref", reference).limit(1).execute()).data)
        if not order:
            return False
        if _one((db.table("webchat_events").select("id").eq("org_id", org_id).eq("kind", "paid").eq("ref", reference)
                 .limit(1).execute()).data):
            return False
        link = _one((db.table("payment_links").select("amount").eq("org_id", org_id).eq("reference", reference)
                     .limit(1).execute()).data) or {}
        value = int(round(float(link.get("amount") or 0) * 100))
        log_event(db, org_id, order.get("session_id"), "paid", order.get("source"), ref=reference, value_kobo=value)
        return True
    except Exception as exc:
        logger.warning("webchat on_payment_confirmed failed: %s", exc)
        return False


def clean_source(v: Optional[str]) -> str:
    s = re.sub(r"[^a-z0-9_-]", "", str(v or "").lower())[:30]
    return s or "link"


def create_session(db, org_id: str, *, source: Optional[str] = None, source_detail: Optional[str] = None,
                   ip_hash: Optional[str] = None, lead_id: Optional[str] = None, phone: Optional[str] = None,
                   name: Optional[str] = None, phone_verified: bool = False) -> tuple[dict, str]:
    token = new_token()
    now = _now()
    row = {
        "org_id": org_id, "token_hash": hash_token(token), "lead_id": lead_id,
        "contact_phone": phone, "contact_name": name, "phone_verified": phone_verified,
        "source": clean_source(source), "source_detail": (source_detail or None) and str(source_detail)[:100],
        "ip_hash": ip_hash, "history": [], "state": {}, "status": "active",
        "last_activity_at": _iso(now), "expires_at": _iso(now + timedelta(days=SESSION_DAYS)),
    }
    res = db.table("webchat_sessions").insert(row).execute()
    return (_one(res.data) or row), token


def create_handoff(db, org_id: str, *, lead_id: Optional[str], phone: str, name: Optional[str], key: str) -> str:
    """Session for someone who wrote on WhatsApp; returns the link that carries its one-time hand-off token."""
    now = _now()
    token = new_token()
    row = {
        "org_id": org_id, "token_hash": hash_token(new_token()),   # placeholder until the link is opened
        "handoff_hash": hash_token(token), "handoff_expires_at": _iso(now + timedelta(hours=HANDOFF_HOURS)),
        "lead_id": lead_id, "contact_phone": phone, "contact_name": name, "phone_verified": True,
        "source": "whatsapp", "history": [], "state": {}, "status": "active",
        "last_activity_at": _iso(now), "expires_at": _iso(now + timedelta(days=SESSION_DAYS)),
    }
    res = db.table("webchat_sessions").insert(row).execute()
    sid = (_one(res.data) or {}).get("id")
    log_event(db, org_id, sid, "handoff_sent", "whatsapp")
    return f"{public_base()}/c/{key}?h={token}"


def exchange_handoff(db, org_id: str, handoff_token: str) -> Optional[tuple[dict, str]]:
    """Single use: trade the WhatsApp link's token for a real session token. None if unknown, used or expired."""
    if not isinstance(handoff_token, str) or not 20 <= len(handoff_token) <= 80:
        return None
    s = _one((db.table("webchat_sessions").select("*").eq("org_id", org_id)
              .eq("handoff_hash", hash_token(handoff_token)).limit(1).execute()).data)
    if not s or s.get("status") != "active":
        return None
    now = _now()
    exp = s.get("handoff_expires_at")
    if s.get("handoff_used_at") or (exp and exp < _iso(now)):
        return None
    token = new_token()
    # compare-and-swap on handoff_used_at so two taps cannot both win
    res = (db.table("webchat_sessions")
           .update({"handoff_used_at": _iso(now), "token_hash": hash_token(token), "last_activity_at": _iso(now),
                    "expires_at": _iso(now + timedelta(days=SESSION_DAYS))})
           .eq("id", s["id"]).is_("handoff_used_at", "null").execute())
    if not res.data:
        return None
    return {**s, "handoff_used_at": _iso(now)}, token


def authenticate(db, org_id: str, token: Optional[str]) -> Optional[dict]:
    """The session behind a token, for THIS org only. Slides the 30-day expiry (at most every 5 minutes)."""
    if not isinstance(token, str) or not 20 <= len(token) <= 80:
        return None
    s = _one((db.table("webchat_sessions").select("*").eq("org_id", org_id)
              .eq("token_hash", hash_token(token)).limit(1).execute()).data)
    if not s or s.get("status") != "active":
        return None
    now = _now()
    if s.get("expires_at") and s["expires_at"] < _iso(now):
        return None
    try:
        last = datetime.fromisoformat(str(s.get("last_activity_at")).replace("Z", "+00:00"))
    except Exception:
        last = now - timedelta(days=1)
    if (now - last).total_seconds() > TOUCH_EVERY_S:
        upd = {"last_activity_at": _iso(now), "expires_at": _iso(now + timedelta(days=SESSION_DAYS))}
        try:
            db.table("webchat_sessions").update(upd).eq("id", s["id"]).execute()
            s.update(upd)
        except Exception as exc:
            logger.warning("webchat touch failed: %s", exc)
    return s


def update_session(db, session: dict, changes: dict) -> dict:
    db.table("webchat_sessions").update(changes).eq("id", session["id"]).eq("org_id", session["org_id"]).execute()
    session.update(changes)
    return session


def set_state(db, session: dict, **kv) -> dict:
    state = dict(session.get("state") or {})
    state.update(kv)
    return update_session(db, session, {"state": state})


# ── Messages ────────────────────────────────────────────────────────────────

def _out(role: str, row: dict) -> dict:
    return {"id": row["id"], "role": role, "text": row.get("content") or row.get("text") or "",
            "at": row.get("created_at") or row.get("at")}


def append_message(db, session: dict, role: str, text: str, sent_by: Optional[str] = None) -> dict:
    """role: visitor | bot | rep. Stored in whatsapp_messages once a lead exists, else inside the session."""
    text = _clean_text(text, MAX_TEXT)
    now = _iso(_now())
    mid = str(uuid.uuid4())
    if session.get("lead_id"):
        row = {
            "id": mid, "org_id": session["org_id"], "lead_id": session["lead_id"], "channel": "webchat",
            "webchat_session_id": session["id"], "message_type": "text", "content": text,
            "direction": "inbound" if role == "visitor" else "outbound",
            "status": "delivered" if role == "visitor" else "sent",
            "sent_by": sent_by if role == "rep" else None, "created_at": now,
        }
        db.table("whatsapp_messages").insert(row).execute()
    else:
        hist = list(session.get("history") or [])
        hist.append({"id": mid, "role": role, "text": text, "at": now})
        session = update_session(db, session, {"history": hist[-HISTORY_CAP:]})
    return {"id": mid, "role": role, "text": text, "at": now}


def list_messages(db, session: dict, after: Optional[str] = None, limit: int = 100) -> list[dict]:
    if not session.get("lead_id"):
        msgs = list(session.get("history") or [])
        return [m for m in msgs if not after or m["at"] > after][-limit:]
    q = (db.table("whatsapp_messages").select("id, content, created_at, direction, sent_by")
         .eq("org_id", session["org_id"]).eq("webchat_session_id", session["id"])
         .order("created_at", desc=False).limit(limit))
    if after:
        q = q.gt("created_at", after)
    rows = q.execute().data or []
    return [_out("visitor" if r["direction"] == "inbound" else ("rep" if r.get("sent_by") else "bot"), r) for r in rows]


def _flush_history(db, session: dict) -> None:
    hist = session.get("history") or []
    if not hist or not session.get("lead_id"):
        return
    rows = [{
        "id": m["id"], "org_id": session["org_id"], "lead_id": session["lead_id"], "channel": "webchat",
        "webchat_session_id": session["id"], "message_type": "text", "content": m["text"],
        "direction": "inbound" if m["role"] == "visitor" else "outbound",
        "status": "delivered" if m["role"] == "visitor" else "sent", "sent_by": None, "created_at": m["at"],
    } for m in hist]
    db.table("whatsapp_messages").insert(rows).execute()
    update_session(db, session, {"history": []})


# ── Contact capture → lead ──────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,200}\.[^@\s]{2,}$")


def normalise_phone(raw: Optional[str]) -> Optional[str]:
    """Digits only, Nigerian 0803… → 234803…; None unless 10–15 digits."""
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("0") and len(d) == 11:
        d = "234" + d[1:]
    return d if 10 <= len(d) <= 15 else None


def validate_contact(name: Optional[str], phone: Optional[str], email: Optional[str], consent: bool,
                     require_name: bool = True) -> tuple[dict, Optional[str]]:
    """(clean, error). A WhatsApp-verified session already has a name and number, so only email may be sent."""
    clean = {"name": _clean_text(name, 80), "phone": normalise_phone(phone), "email": _clean_text(email, 200).lower() or None}
    if require_name and len(clean["name"]) < 2:
        return clean, "Please tell us your name."
    if phone and not clean["phone"]:
        return clean, "That WhatsApp number does not look right."
    if clean["email"] and not _EMAIL_RE.match(clean["email"]):
        return clean, "That email does not look right."
    if not clean["phone"] and not clean["email"]:
        return clean, "Please give a WhatsApp number or an email so we can reach you."
    if not consent:
        return clean, "Please tick the box so we can contact you."
    return clean, None


def save_contact(db, session: dict, clean: dict, consent_version: str = CONSENT_VERSION) -> dict:
    """Find or create the lead, link it to the session, move the earlier messages into the inbox."""
    from app.services import funnel_service
    org_id = session["org_id"]
    now = _iso(_now())
    lead_id = session.get("lead_id")
    if not lead_id and clean.get("phone"):
        lead_id = funnel_service._find_org_lead(db, org_id, clean["phone"])
    if not lead_id and clean.get("email"):
        row = _one((db.table("leads").select("id").eq("org_id", org_id).eq("email", clean["email"])
                    .is_("deleted_at", "null").limit(1).execute()).data)
        lead_id = row["id"] if row else None
    if not lead_id:
        from app.models.leads import LeadCreate, LeadSource
        from app.services import lead_service
        payload = LeadCreate(
            full_name=(clean.get("name") or clean.get("phone") or clean.get("email") or "Web chat visitor")[:255],
            phone=(clean["phone"] or None), whatsapp=(clean["phone"] or None), email=clean.get("email"),
            source=LeadSource.landing_page.value,
        )
        lead = lead_service.create_lead(db=db, org_id=org_id, user_id=None, payload=payload, entry_path="webchat")
        lead_id = lead.get("id")
    if not lead_id:
        raise RuntimeError("lead could not be created")
    patch = {"consent_at": now, "consent_version": consent_version,
             "source_detail": f"webchat:{session.get('source') or 'link'}"[:100]}
    try:
        db.table("leads").update(patch).eq("id", lead_id).eq("org_id", org_id).execute()
        if clean.get("email"):
            db.table("leads").update({"email": clean["email"]}).eq("id", lead_id).eq("org_id", org_id).is_("email", "null").execute()
    except Exception as exc:
        logger.warning("webchat lead patch failed lead=%s: %s", lead_id, exc)
    changes = {"lead_id": lead_id, "consent_at": now, "consent_version": consent_version,
               "contact_name": clean.get("name") or session.get("contact_name"),
               "contact_phone": clean.get("phone") or session.get("contact_phone"),
               "contact_email": clean.get("email") or session.get("contact_email")}
    session = update_session(db, session, changes)
    _flush_history(db, session)
    log_event(db, org_id, session["id"], "contact", session.get("source"))
    return session


# ── Staff side ──────────────────────────────────────────────────────────────

def notify_managers(db, org_id: str, title: str, body: str, lead_id: Optional[str], kind: str = "webchat") -> None:
    try:
        from app.services import funnel_service
        funnel_service.notify_managers(db, org_id, title, body, kind, lead_id)
    except Exception as exc:
        logger.warning("webchat notify failed org=%s: %s", org_id, exc)


def latest_session_for_lead(db, org_id: str, lead_id: str) -> Optional[dict]:
    return _one((db.table("webchat_sessions").select("*").eq("org_id", org_id).eq("lead_id", lead_id)
                 .order("last_activity_at", desc=True).limit(1).execute()).data)


def set_human(db, session: dict) -> dict:
    """Hand the chat to the team; the bot stays quiet until the team has been silent for human_resume_min."""
    return set_state(db, session, human=True, human_at=_iso(_now()))


def is_human(session: dict, cfg: Optional[dict] = None) -> bool:
    """True while a person is looking after the chat. Lapses after human_resume_min minutes without a team
    message (or, if nobody ever replied, without the hand-over being fresh), so the bot never stays silent forever."""
    state = session.get("state") or {}
    if not state.get("human"):
        return False
    try:
        mins = int((cfg or {}).get("human_resume_min") or DEFAULT_CONFIG["human_resume_min"])
    except (TypeError, ValueError):
        mins = DEFAULT_CONFIG["human_resume_min"]
    stamps = []
    for k in ("rep_last_at", "human_at"):
        try:
            if state.get(k):
                stamps.append(datetime.fromisoformat(str(state[k]).replace("Z", "+00:00")))
        except Exception:
            pass
    if not stamps:
        return False
    return _now() - max(stamps) < timedelta(minutes=mins)


def rep_send(db, org_id: str, lead_id: str, text: str, user_id: str) -> dict:
    """A rep's reply into a web chat. Stored only; the visitor's page picks it up. No Meta call, no fee."""
    s = latest_session_for_lead(db, org_id, lead_id)
    if not s:
        raise LookupError("no web chat for this contact")
    if s.get("status") != "active":
        raise PermissionError("this web chat has ended")
    msg = append_message(db, s, "rep", text, sent_by=user_id)
    set_state(db, s, human=True, rep_last_at=_iso(_now()), human_at=_iso(_now()))
    try:
        from app.services import webchat_followup_service as fu
        fu.notify_rep_reply(db, s, get_config(db, org_id), text)   # WEBCHAT-4/4b: email or WhatsApp when the visitor has left
    except Exception as exc:
        logger.warning("webchat rep email hook failed: %s", exc)
    return msg


def sweep(db, dry_run: bool = False) -> dict:
    """Mark sessions past expires_at as expired and clear their pre-contact history. Returns counts."""
    now = _iso(_now())
    rows = (db.table("webchat_sessions").select("id, lead_id").eq("status", "active")
            .lt("expires_at", now).limit(1000).execute().data or [])
    if not dry_run:
        for r in rows:
            try:
                upd = {"status": "expired"}
                if not r.get("lead_id"):
                    upd["history"] = []
                db.table("webchat_sessions").update(upd).eq("id", r["id"]).execute()
            except Exception as exc:
                logger.warning("webchat sweep failed session=%s: %s", r.get("id"), exc)
    return {"dry_run": dry_run, "expired": len(rows)}
