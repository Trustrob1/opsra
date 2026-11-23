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
import time
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

CHAT_THEMES = ("classic", "blue", "midnight", "ink")

DEFAULT_CONFIG: dict = {
    "enabled": False,
    "business_name": "",
    "brand_color": "#028090",
    "chat_theme": "classic",      # WEB-ONLY-1c-LOOK: classic | blue | midnight | ink (the chat page colours; see frontend utils/webchatTheme.js)
    "greeting": "Hi, I'm Chioma. I can answer your questions, share prices and help you order or book. Pick an option below, or type your question.",
    "menu": [],
    "booking_fields": [
        {"key": "service", "label": "What would you like to book?", "required": True},
        {"key": "when", "label": "Preferred day and time", "required": True},
    ],
    "contact_prompt": "To carry on, tell us who you are so we can reach you if we get disconnected.",
    "consent_text": "I agree to be contacted about my enquiry.",
    "fallback": "I am unable to answer that at the moment. Please tap Menu at the top to see the available options, or tap Talk to the team to speak with someone on our team.",
    "human_reply": "Thanks. A team member will reply here as soon as they can.",
    "booking_done": "Thank you. We have your request and will confirm shortly.",
    "redirect_mode": "always",
    "redirect_text": "",
    "ai_enabled": False,          # WEBCHAT-3: AI answers typed questions (after contact details)
    "answer_first": False,        # WEB-ONLY-1c: the AI answers BEFORE the visitor gives contact details (details are asked after the first answer)
    "ai_model": "haiku",          # haiku (cheapest) | sonnet
    "ai_instructions": "",
    "ai_max_turns": 12,
    "wa_followups": False,        # WEBCHAT-4b: OPT-IN WhatsApp follow-ups (each template message costs a Meta fee)
    "wa_followup_mode": "fallback",   # fallback = email first | prefer = WhatsApp first
    "wa_template_name": "",
    "wa_template_lang": "en",
    "wa_monthly_cap": 100,
    "contact_in_chat": True,      # WEBCHAT-CONTACT-1: ask for name / number / consent in the chat itself (False = the pop-up form)
    "fresh_after_hours": 24,      # WEBCHAT-CONTACT-1: a visitor back after this many idle hours gets a fresh view (0 = always show the full history)
    "email_followups": True,      # WEBCHAT-4: email replies / confirmations to visitors who gave an email and consent
    "human_resume_min": 30,       # minutes of team silence after which the bot answers again
    "shop_enabled": False,        # WEBCHAT-3b: product cards, cart and checkout link in the chat
    "products_read": False,       # ONLY-1c-PRODUCTS: Chioma answers price / stock questions from the product list in plain text (no cards, cart or checkout)
    "goals": None,                # WEBCHAT-5b: what counts as a win in the funnel; None = automatic (booking, plus orders and payments when the shop is on)
    "stats_from": None,           # WEBCHAT-5b: ISO time; the numbers ignore anything before it (start counting from now)
    "allowed_domains": [],        # WEBCHAT-EMBED-1: websites that may show the chat bubble; empty = any website
    "site_button": False,         # WEBCHAT-SITE-1b: "Chat with us" link on websites built in Opsra; OFF until the business switches it on
    "widget_side": "right",       # WEBCHAT-EMBED-1: which corner the bubble sits in
    "address": "",                # SMART-1: where the business is, so Chioma can answer "where are you" without AI
    "human_offer": False,         # HUMAN-OFFER-1: the first tap on Talk to the team gets one offer of a quick answer first
    "ask_bar": False,             # ASKBAR-1: show the Chioma ask bar on the website (inline at a placeholder, or docked at the bottom)
    "ask_bar_text": "Ask me anything…",
    "campaigns": [],               # OPENING-CTA-2: one per ad: {tag, label, main, main_label, greeting}; a chat opened with ?s=<tag> gets that ad's greeting and starting button
    "opening": {"style": "list"},  # OPENING-CTA-1: list = every button on the first screen (as before); pair = two big buttons (one main action + Speak to Chioma)
    "call_enabled": False,        # WEBCHAT-CALL-1: phone icon in the chat header; calls only in business hours
    "call_number": "",            # digits; empty = the organisation's business contact / WhatsApp number
}
# WEBCHAT-UI-3: the old default wording pointed at buttons under the message; the menu is now an icon at the top
_LEGACY_TEXT = {
    "greeting": {"Hi! How can we help you today? Pick an option below or type your question.": "Hi, I'm Chioma. I can answer your questions, share prices and help you order or book. Pick an option below, or type your question.",
                 "Hi! How can we help you today? Pick an option below, or tap Menu at the top any time.": "Hi, I'm Chioma. I can answer your questions, share prices and help you order or book. Pick an option below, or type your question."},
    "fallback": {"I did not catch that. Pick one of the options below, or tap Talk to us.": "I am unable to answer that at the moment. Please tap Menu at the top to see the available options, or tap Talk to the team to speak with someone on our team.",
                 "I did not catch that. Tap Menu at the top to see what we can help with, or type your question again.": "I am unable to answer that at the moment. Please tap Menu at the top to see the available options, or tap Talk to the team to speak with someone on our team."},
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
    if "chat_theme" in raw:
        out["chat_theme"] = raw["chat_theme"] if raw["chat_theme"] in CHAT_THEMES else DEFAULT_CONFIG["chat_theme"]
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
    if "contact_in_chat" in raw:
        out["contact_in_chat"] = bool(raw["contact_in_chat"])
    if "fresh_after_hours" in raw:
        try:
            out["fresh_after_hours"] = max(0, min(int(raw["fresh_after_hours"]), 720))
        except (TypeError, ValueError):
            out["fresh_after_hours"] = 24
    if "email_followups" in raw:
        out["email_followups"] = bool(raw["email_followups"])
    if "human_resume_min" in raw:
        try:
            out["human_resume_min"] = max(5, min(int(raw["human_resume_min"]), 1440))
        except (TypeError, ValueError):
            out["human_resume_min"] = 30
    if "shop_enabled" in raw:
        out["shop_enabled"] = bool(raw["shop_enabled"])
    if "products_read" in raw:
        out["products_read"] = bool(raw["products_read"])
    if "allowed_domains" in raw:
        from app.services import webchat_embed_service as embed
        out["allowed_domains"] = embed.sanitise_domains(raw["allowed_domains"])
    if "site_button" in raw:
        out["site_button"] = bool(raw["site_button"])
    if "address" in raw:
        out["address"] = _clean_text(raw["address"], 200)
    if "human_offer" in raw:
        out["human_offer"] = bool(raw["human_offer"])
    if "ask_bar" in raw:
        out["ask_bar"] = bool(raw["ask_bar"])
    if "ask_bar_text" in raw:
        out["ask_bar_text"] = _clean_text(raw["ask_bar_text"], 60) or DEFAULT_CONFIG["ask_bar_text"]
    if "widget_side" in raw:
        out["widget_side"] = "left" if raw["widget_side"] == "left" else "right"
    if "call_enabled" in raw:
        out["call_enabled"] = bool(raw["call_enabled"])
    if "call_number" in raw:
        out["call_number"] = normalise_phone(raw["call_number"]) or ""
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
    if "answer_first" in raw:
        out["answer_first"] = bool(raw["answer_first"])
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
            elif action == "guide":                       # SMART-1: a few tap-to-answer questions, then the team gets a summary
                from app.services import webchat_smart_service as _smart
                g = _smart.clean_guide(it.get("guide"))
                if not g:
                    continue
                item["action"], item["guide"] = "guide", g
            else:
                item["answer"] = _clean_text(it.get("answer"), 1000)
                link = it.get("link")
                if isinstance(link, dict) and _clean_url(link.get("url")):
                    item["link"] = {"label": _clean_text(link.get("label"), 60) or "Open", "url": _clean_url(link["url"])}
            if it.get("featured"):
                item["featured"] = True                      # MENU-MORE: shown first in the chat menu; the rest sit under "More options"
            kws = it.get("keywords") if isinstance(it.get("keywords"), list) else []
            item["keywords"] = [_clean_text(k, 30).lower() for k in kws[:15] if _clean_text(k, 30)]
            menu.append(item)
        out["menu"] = menu
    if "campaigns" in raw:
        out["campaigns"] = clean_campaigns(raw["campaigns"])
    if "opening" in raw:
        out["opening"] = clean_opening(raw["opening"])
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


CAMPAIGNS_MAX = 30
# The six share-link channels and the built-in sources keep their meaning in the stats, so a campaign cannot reuse them.
RESERVED_TAGS = ("instagram", "qr", "site", "facebook", "google", "whatsapp_status", "email", "sms", "whatsapp", "website", "link")


def clean_campaigns(raw) -> list:
    """OPENING-CTA-2: the owner's ads. The tag is what the link carries (?s=tag); the text lives here on the server, never in the link,
    so nobody can make a link that shows a business's chat with words of their own."""
    out, seen = [], set()
    for it in (raw if isinstance(raw, list) else [])[:CAMPAIGNS_MAX]:
        if not isinstance(it, dict):
            continue
        tag = re.sub(r"[^a-z0-9_-]", "", str(it.get("tag") or "").lower())[:30]
        if not tag or tag in seen or tag in RESERVED_TAGS:
            continue
        seen.add(tag)
        out.append({"tag": tag, "label": _clean_text(it.get("label"), 60) or tag,
                    "main": re.sub(r"[^a-z0-9_-]", "", str(it.get("main") or "").lower())[:30],
                    "main_label": _clean_text(it.get("main_label"), 40),
                    "greeting": _clean_text(it.get("greeting"), 400),
                    "image": (str(it.get("image")) if isinstance(it.get("image"), str) and AD_IMAGE_KEY.match(it["image"]) else ""),
                    "video": (str(it.get("video")) if isinstance(it.get("video"), str) and AD_VIDEO_KEY.match(it["video"]) else "")})
    return out


AD_IMAGE_KEY = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")      # OPENING-CTA-5: the picture is a file the owner uploaded through Opsra, named by a random key
AD_VIDEO_KEY = re.compile(r"^[0-9a-f]{32}\.(mp4|webm)$")          # OPENING-CTA-6: a video the owner uploaded, same idea as the picture
AD_VIDEO_MAX_BYTES = 25 * 1024 * 1024
_ORG_ID = re.compile(r"^[0-9a-fA-F-]{36}$")


def ad_image_url(org_id, key, _key=None) -> Optional[str]:
    """Public address of an ad's picture. Built here from the business id and the stored key, so a saved setting can never point a visitor's browser at another website."""
    real = _key if _key is not None else key
    pattern = AD_VIDEO_KEY if _key is not None else AD_IMAGE_KEY
    if not isinstance(org_id, str) or not _ORG_ID.match(org_id) or not isinstance(real, str) or not pattern.match(real):
        return None
    try:
        from app.config import settings
        base = (settings.SUPABASE_URL or "").rstrip("/")
    except Exception:
        return None
    return f"{base}/storage/v1/object/public/catalog/{org_id}/webchat-ads/{real}" if base else None


def ad_video_url(org_id, key) -> Optional[str]:
    """Public address of an ad's video, built the same way as the picture's: from the business id and a key we issued."""
    if not isinstance(key, str) or not AD_VIDEO_KEY.match(key):
        return None
    return ad_image_url(org_id, "0" * 32 + ".jpg", _key=key)


def sniff_video(data: bytes) -> Optional[tuple]:
    """(mime, extension) for a real MP4 or WebM, judged from the bytes. QuickTime (.mov) and photo-format files are refused."""
    head = bytes(data[:16])
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] not in (b"qt  ", b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"avif"):
        return "video/mp4", "mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm", "webm"
    return None


def campaign_for(cfg: dict, source) -> Optional[dict]:
    """The ad this chat came from, or None (an unknown tag just means a normal chat)."""
    if not source:
        return None
    tag = clean_source(source)
    for c in cfg.get("campaigns") or []:
        if isinstance(c, dict) and c.get("tag") == tag:
            return c
    return None


def greeting_for(cfg: dict, source=None) -> str:
    c = campaign_for(cfg, source)
    return (c or {}).get("greeting") or cfg["greeting"]


def opening_for(cfg: dict, source=None) -> dict:
    """The first screen for this visitor: an ad's starting button leads (two-button screen), otherwise the business's own setting.
    An ad whose starting button no longer exists quietly falls back to the business's setting."""
    base = opening_view(cfg)
    camp = campaign_for(cfg, source)
    if not camp or not camp.get("main"):
        return base
    bo = cfg.get("opening") if isinstance(cfg.get("opening"), dict) else {}
    ov = opening_view({**cfg, "opening": {"style": "pair", "main": camp["main"], "main_label": camp.get("main_label") or "",
                                         "speak_label": bo.get("speak_label") or "", "speak_reply": bo.get("speak_reply") or ""}})
    return ov if ov.get("style") == "pair" else base


OPENING_STYLES = ("list", "pair")
SPEAK_LABEL = "Speak to Chioma"
SPEAK_REPLY = "Happy to help. Tap a topic below, or type your question."


def clean_opening(raw) -> dict:
    """OPENING-CTA-1: the first-screen setting. style list (default) keeps every button on show; style pair shows one main button
    (a menu button id, or "shop") and a Speak to Chioma button that opens the other topics. Unknown values fall back to list."""
    if not isinstance(raw, dict) or raw.get("style") not in OPENING_STYLES or raw.get("style") == "list":
        return {"style": "list"}
    main = re.sub(r"[^a-z0-9_-]", "", str(raw.get("main") or "").lower())[:30]
    if not main:
        return {"style": "list"}
    return {"style": "pair", "main": main,
            "main_label": _clean_text(raw.get("main_label"), 40),
            "speak_label": _clean_text(raw.get("speak_label"), 30) or SPEAK_LABEL,
            "speak_reply": _clean_text(raw.get("speak_reply"), 200) or SPEAK_REPLY}


def opening_view(cfg: dict) -> dict:
    """What the chat page needs for the first screen. Falls back to the plain list when the main button no longer exists
    (deleted, or shop switched off), so a visitor is never shown a dead button."""
    op = cfg.get("opening") if isinstance(cfg.get("opening"), dict) else {}
    if op.get("style") != "pair" or not op.get("main"):
        return {"style": "list"}
    items = {m.get("id"): m for m in (cfg.get("menu") or []) if m.get("id")}
    if op["main"] == "shop":
        if not cfg.get("shop_enabled"):
            return {"style": "list"}
        kind, label = "shop", "Shop now"
    elif op["main"] in items:
        kind, label = "menu", str(items[op["main"]].get("label") or "")
    else:
        return {"style": "list"}
    return {"style": "pair", "main": {"id": op["main"], "kind": kind, "label": op.get("main_label") or label},
            "speak_label": op.get("speak_label") or SPEAK_LABEL, "speak_reply": op.get("speak_reply") or SPEAK_REPLY}


def default_menu(shop: bool) -> list:
    """WEBCHAT-MENU-1: a business that has not set up any menu gets these three, so visitors always have the Menu button and a way to
    reach the team. Plain, true-for-everyone wording only (no prices or facts are invented). No keywords on purpose: typed questions
    such as 'what are your prices' must still reach the AI / product answer, not a canned reply."""
    if shop:
        order = "Tap Shop below to browse, add what you like to your cart and check out. Or tell me what you are looking for and I will help you find it."
        price = "Tell me the item you have in mind and I will share its price, or tap Shop below to browse with prices."
    else:
        order = "Tell me what you are looking for and I will help. If you would rather speak to a person, tap Talk to the team and we will take your order."
        price = "Tell me the item you have in mind and I will help with its price, or tap Talk to the team and we will send you a quote."
    return [
        {"id": "prices", "label": "See prices", "answer": price, "keywords": [], "builtin": True},
        {"id": "order", "label": "How to order", "answer": order, "keywords": [], "builtin": True},
        {"id": "human", "label": "Talk to the team", "action": "human", "keywords": [], "builtin": True},
    ]


def get_config(db, org_id: str) -> dict:
    """Defaults + the org's stored settings. business_name falls back to the organisation's name."""
    try:
        row = _one((db.table("organisations").select("name, webchat_config, business_hours, timezone, org_whatsapp_number, org_business_contact_number")
                    .eq("id", org_id).limit(1).execute()).data) or {}
    except Exception as exc:
        logger.warning("webchat get_config failed org=%s: %s", org_id, exc)
        row = {}
    cfg = dict(DEFAULT_CONFIG)
    stored = row.get("webchat_config") if isinstance(row.get("webchat_config"), dict) else {}
    cfg.update(sanitise_config(stored))
    for k, m in _LEGACY_TEXT.items():          # a business that never changed the old default gets the new wording
        if cfg.get(k) in m:
            cfg[k] = m[cfg[k]]
    if not cfg.get("business_name"):
        cfg["business_name"] = row.get("name") or "Our team"
    if not cfg.get("menu"):                    # WEBCHAT-MENU-1: nothing set up yet, so start from the default menu (owner can edit it)
        cfg["menu"] = default_menu(bool(cfg.get("shop_enabled")))
    # read-only facts for the call button (no extra database trip); never saved back, never sent to visitors as-is
    cfg["_call_org"] = {"business_hours": row.get("business_hours"), "timezone": row.get("timezone"),
                        "fallback_number": row.get("org_business_contact_number") or row.get("org_whatsapp_number") or ""}
    return cfg


def save_config(db, org_id: str, changes: dict) -> dict:
    cur = _one((db.table("organisations").select("webchat_config").eq("id", org_id).limit(1).execute()).data) or {}
    stored = cur.get("webchat_config") if isinstance(cur.get("webchat_config"), dict) else {}
    stored = {**stored, **sanitise_config(changes)}
    db.table("organisations").update({"webchat_config": stored}).eq("id", org_id).execute()
    clear_key_cache()
    return get_config(db, org_id)


# WEBCHAT-CATALOG-1b: the closing line of a scripted product answer; the chat page puts Open menu + Talk to the team buttons under it
SCRIPTED_TAIL = "Tap Menu for more options, or talk to the team."


def chioma_flags(cfg: dict) -> dict:
    """WEBCHAT-BUBBLE-1/2: what the launcher and the chat page need to show Chioma.
    assistant_active = AI answers are really on (plan included); team_available = inside the business's set hours right now;
    online = either (the green dot shows only when a reply can come now); reopens = when the team is back, in words (else "").
    Never raises: a problem here must not stop the chat."""
    team, reopens = False, ""
    try:
        from app.services import webchat_call_service as call
        org = cfg.get("_call_org") or {}
        st = call.open_state(org.get("business_hours"), org.get("timezone"))
        team = bool(st.get("open"))
        if not team and st.get("opens_at"):
            reopens = call._opens_words(st.get("opens_at"), org.get("timezone"))
    except Exception:
        team, reopens = False, ""
    ai = bool(cfg.get("ai_enabled"))
    return {"assistant_active": ai, "team_available": team, "online": ai or team, "reopens": reopens}


def _human_menu_id(cfg: dict) -> Optional[str]:
    for m in cfg.get("menu") or []:
        if m.get("action") == "human":
            return m.get("id")
    return None


def public_view(cfg: dict, source: Optional[str] = None, org_id: Optional[str] = None) -> dict:
    """The only settings a visitor's browser receives. `source` is the chat's link tag: an ad it names changes the greeting and first screen."""
    return {
        "chioma": chioma_flags(cfg), "human_menu_id": _human_menu_id(cfg), "scripted_tail": SCRIPTED_TAIL, "contact_in_chat": bool(cfg.get("contact_in_chat", True)),
        "business_name": cfg["business_name"], "brand_color": cfg["brand_color"], "chat_theme": cfg.get("chat_theme") if cfg.get("chat_theme") in CHAT_THEMES else "classic",
        "greeting": greeting_for(cfg, source), "opening": opening_for(cfg, source),
        "ad_image": ad_image_url(org_id, (campaign_for(cfg, source) or {}).get("image")),
        "ad_video": ad_video_url(org_id, (campaign_for(cfg, source) or {}).get("video")),
        "menu": [{"id": m["id"], "label": m["label"], **({"primary": True} if m.get("action") == "booking" else {}), **({"featured": True} if m.get("featured") else {})} for m in cfg["menu"]],      # a Book a call button is drawn solid
        "contact_prompt": cfg["contact_prompt"], "consent_text": cfg["consent_text"], "fallback": cfg["fallback"],
        "booking_fields": cfg["booking_fields"], "shop_enabled": bool(cfg.get("shop_enabled")), "email_enabled": bool(cfg.get("email_followups", True)),
        "call": _call_status(cfg),
    }


def ask_bar_view(cfg: dict, source: Optional[str] = None) -> Optional[dict]:
    """ASKBAR-1: what widget.js needs to draw the ask bar, or None when the business has not switched it on.
    Chips are the first three chat buttons, a Book a call button first. Labels only; the answers stay on the server."""
    if not cfg.get("ask_bar"):
        return None
    items = [m for m in (cfg.get("menu") or []) if m.get("id") and m.get("label")]
    featured = [m for m in items if m.get("featured") and m.get("action") != "human"]
    pool = featured or items                       # MENU-MORE: the owner's featured buttons lead (a campaign can feature just one or two)
    pool = sorted(pool, key=lambda m: 0 if m.get("action") == "booking" else 1)          # stable: the rest keep their order
    lead_id, lead_label = None, ""
    camp = campaign_for(cfg, source)                                  # OPENING-CTA-2: a visitor from an ad sees that ad's main button first and solid
    if camp and camp.get("main") and camp["main"] != "shop":
        hit = next((m for m in items if m.get("id") == camp["main"] and m.get("action") != "human"), None)
        if hit:
            lead_id, lead_label = hit["id"], camp.get("main_label") or ""
            pool = [hit] + [m for m in pool if m.get("id") != hit["id"]]
    chips = pool[:3]
    return {"text": _clean_text(cfg.get("ask_bar_text"), 60) or DEFAULT_CONFIG["ask_bar_text"],
            "chips": [{"id": m["id"], "label": str((lead_label if m["id"] == lead_id and lead_label else m["label"]))[:60],
                       "primary": (m["id"] == lead_id) if lead_id else m.get("action") == "booking"} for m in chips],
            "more": len(items) > len(chips)}                                              # a More button opens the chat's full button list


def _call_status(cfg: dict) -> Optional[dict]:
    try:
        from app.services import webchat_call_service as call
        return call.status(cfg)
    except Exception as exc:
        logger.warning("webchat call status failed: %s", exc)
        return None


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


_KEY_CACHE: dict = {}          # WEBCHAT-SPEED-1: key -> (expires_at, result). Every chat request used to cost ~10 database round trips here.
_KEY_CACHE_TTL_S = 30


def clear_key_cache() -> None:
    _KEY_CACHE.clear()


def resolve_key(db, key: str) -> Optional[dict]:
    """{'org_id', 'config'} for an active key whose org has the chat switched on; else None.
    Positive answers are cached for 30 seconds per worker (settings and plan changes show up within that time)."""
    if not isinstance(key, str) or not re.match(r"^wc_[A-Za-z0-9_-]{8,40}$", key):
        return None
    hit = _KEY_CACHE.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    res = _resolve_key_uncached(db, key)
    if res is not None:
        if len(_KEY_CACHE) > 500:
            _KEY_CACHE.clear()
        _KEY_CACHE[key] = (time.monotonic() + _KEY_CACHE_TTL_S, res)
    return res


def _resolve_key_uncached(db, key: str) -> Optional[dict]:
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
    s["_idle_s"] = (now - last).total_seconds()          # WEBCHAT-CONTACT-1: read by the resume snapshot (never stored)
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
    out = {"id": row["id"], "role": role, "text": row.get("content") or row.get("text") or "",
           "at": row.get("created_at") or row.get("at")}
    if row.get("deleted_at"):                                                          # WEBCHAT-MSG-1
        out["deleted"] = True
        out["text"] = ""
    else:
        if row.get("message_type") in ("image", "audio", "document") and row.get("media_url"):   # WEBCHAT-ATTACH-1
            out["attachment"] = {"kind": row["message_type"], "name": out["text"], "url": row["media_url"]}
        if row.get("edited_at"):
            out["edited"] = True
    rid = row.get("reply_to_id") or row.get("reply_to")
    if rid:
        out["reply_to"] = str(rid)
    return out


QUOTE_LEN = 140
_ATT_WORD = {"image": "Photo", "audio": "Voice note", "document": "Document"}


def _quote_of(role: str, row: dict) -> dict:
    """The little quoted snippet shown inside a reply."""
    if row.get("deleted_at"):
        text = "This message was deleted"
    elif row.get("message_type") in ("image", "audio", "document"):
        text = _ATT_WORD.get(row["message_type"], "File") if row["message_type"] != "document" else (row.get("content") or "Document")
    else:
        text = row.get("content") or row.get("text") or ""
    return {"id": str(row["id"]), "role": role, "text": str(text)[:QUOTE_LEN]}


def find_message(db, session: dict, mid: str) -> Optional[tuple]:
    """('db', row, role) or ('hist', item, role) for a message of THIS session, else None."""
    if not isinstance(mid, str) or not re.match(r"^[0-9a-fA-F-]{36}$", mid):
        return None
    if not session.get("lead_id"):
        for m in session.get("history") or []:
            if m.get("id") == mid:
                return ("hist", m, m.get("role") or "bot")
        return None
    row = _one((db.table("whatsapp_messages").select("*").eq("id", mid).eq("org_id", session["org_id"])
                .eq("webchat_session_id", session["id"]).limit(1).execute()).data)
    if not row:
        return None
    return ("db", row, "visitor" if row.get("direction") == "inbound" else ("rep" if row.get("sent_by") else "bot"))


def quote_for(db, session: dict, mid: Optional[str]) -> Optional[dict]:
    found = find_message(db, session, mid) if mid else None
    return _quote_of(found[2], found[1]) if found else None


def append_message(db, session: dict, role: str, text: str, sent_by: Optional[str] = None,
                   reply_to: Optional[str] = None) -> dict:
    """role: visitor | bot | rep. Stored in whatsapp_messages once a lead exists, else inside the session.
    reply_to: id of an earlier message of this chat (checked here; anything else is dropped)."""
    text = _clean_text(text, MAX_TEXT)
    now = _iso(_now())
    mid = str(uuid.uuid4())
    quote = quote_for(db, session, reply_to) if reply_to else None
    rid = quote["id"] if quote else None
    if session.get("lead_id"):
        row = {
            "id": mid, "org_id": session["org_id"], "lead_id": session["lead_id"], "channel": "webchat",
            "webchat_session_id": session["id"], "message_type": "text", "content": text,
            "direction": "inbound" if role == "visitor" else "outbound",
            "status": "delivered" if role == "visitor" else "sent",
            "sent_by": sent_by if role == "rep" else None, "created_at": now,
        }
        if rid:
            row["reply_to_id"] = rid
        db.table("whatsapp_messages").insert(row).execute()
        if role == "visitor":
            touch_lead(db, session["org_id"], session["lead_id"], now)
    else:
        hist = list(session.get("history") or [])
        item = {"id": mid, "role": role, "text": text, "at": now}
        if rid:
            item["reply_to"] = rid
        hist.append(item)
        session = update_session(db, session, {"history": hist[-HISTORY_CAP:]})
    out = {"id": mid, "role": role, "text": text, "at": now}
    if rid:
        out["reply_to"], out["reply"] = rid, quote
    return out


def touch_lead(db, org_id: str, lead_id: str, now: Optional[str] = None) -> None:
    """WEBCHAT-CONTACT-1d: a visitor writing in the chat counts as lead activity. The Lead Center sorts every column by
    leads.last_activity_at, so without this an older lead that comes back through the chat stays buried far down its column."""
    try:
        db.table("leads").update({"last_activity_at": now or _iso(_now())}).eq("id", lead_id).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.warning("webchat lead touch failed lead=%s: %s", lead_id, exc)


REP_TYPING_S = 6
_TYPING_LOCAL: dict = {}      # used only when Redis is not reachable


def _typing_set(who: str, sid: str) -> None:
    """WEBCHAT-CONTACT-1d/1e: 'who' is typing in chat 'sid' for the next few seconds. Kept in Redis (a few seconds, no database write),
    NOT in the session state: a typing ping must never overwrite state that a message is changing at the same moment."""
    try:
        from app.services.ai_service import _get_redis
        r = _get_redis()
        if r is not None:
            r.setex(f"wc:typing:{who}:{sid}", REP_TYPING_S, "1")
            return
    except Exception as exc:
        logger.warning("webchat typing: redis unavailable (%s)", exc)
    _TYPING_LOCAL[(who, sid)] = _now().timestamp() + REP_TYPING_S


def _typing_get(who: str, sid: str) -> bool:
    try:
        from app.services.ai_service import _get_redis
        r = _get_redis()
        if r is not None:
            return bool(r.exists(f"wc:typing:{who}:{sid}"))
    except Exception:
        pass
    return _TYPING_LOCAL.get((who, sid), 0) > _now().timestamp()


def typing_clear(who: str, sid: str) -> None:
    _TYPING_LOCAL.pop((who, sid), None)
    try:
        from app.services.ai_service import _get_redis
        r = _get_redis()
        if r is not None:
            r.delete(f"wc:typing:{who}:{sid}")
    except Exception:
        pass


def rep_is_typing(s: dict) -> bool:
    """A team member is writing a reply to this visitor right now (the inbox pings every few seconds)."""
    return _typing_get("rep", str(s.get("id")))


def visitor_is_typing(s: Optional[dict]) -> bool:
    """The visitor is writing a message right now (their page pings every few seconds while they type)."""
    return bool(s) and _typing_get("visitor", str(s.get("id")))


def visitor_typing(db, session: dict) -> None:
    _typing_set("visitor", str(session["id"]))


def rep_typing(db, org_id: str, lead_id: str) -> None:
    s = latest_session_for_lead(db, org_id, lead_id)
    if s and s.get("status") == "active":
        _typing_set("rep", str(s["id"]))


def _attach_quotes(db, session: dict, outs: list, source_rows: list) -> list:
    """Fill in out['reply'] for messages that quote another message (one extra query at most)."""
    need = {o["reply_to"] for o in outs if o.get("reply_to")}
    if not need:
        return outs
    known: dict = {}
    for o, r in zip(outs, source_rows):
        known[str(o["id"])] = _quote_of(o["role"], r)
    missing = [i for i in need if i not in known]
    if missing and session.get("lead_id"):
        try:
            rows = (db.table("whatsapp_messages").select("id, content, message_type, direction, sent_by, deleted_at")
                    .eq("org_id", session["org_id"]).eq("webchat_session_id", session["id"]).in_("id", missing).execute().data) or []
            for r in rows:
                known[str(r["id"])] = _quote_of("visitor" if r["direction"] == "inbound" else ("rep" if r.get("sent_by") else "bot"), r)
        except Exception as exc:
            logger.warning("webchat quote lookup failed: %s", exc)
    elif missing:
        for m in session.get("history") or []:
            known.setdefault(str(m["id"]), _quote_of(m.get("role") or "bot", m))
    for o in outs:
        if o.get("reply_to"):
            q = known.get(o["reply_to"])
            if q:
                o["reply"] = q
            else:
                o.pop("reply_to", None)
    return outs


def _first_name(full: Optional[str]) -> str:
    parts = str(full or "").strip().split()
    return parts[0][:30] if parts else ""


def _attach_rep_names(db, outs: list, rows: list) -> None:
    """WEBCHAT-BUBBLE-2: the first name of the team member who wrote a reply (out['by']), so the visitor sees who joined.
    One extra query at most; never raises; no name = the page says 'the team'."""
    ids = sorted({str(r["sent_by"]) for r in rows if r.get("sent_by")})
    if not ids:
        return
    try:
        found = (db.table("users").select("id, full_name").in_("id", ids).execute().data) or []
        names = {str(u["id"]): _first_name(u.get("full_name")) for u in found}
    except Exception as exc:
        logger.warning("webchat rep name lookup failed: %s", exc)
        return
    for o, r in zip(outs, rows):
        n = names.get(str(r.get("sent_by") or ""))
        if o.get("role") == "rep" and n:
            o["by"] = n


def list_messages(db, session: dict, after: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Messages after a time. A message edited or deleted after that time is sent again so the page can update it."""
    if not session.get("lead_id"):
        msgs = list(session.get("history") or [])
        pick = [m for m in msgs if not after or m["at"] > after or (m.get("edited_at") or "") > after or (m.get("deleted_at") or "") > after][-limit:]
        return _attach_quotes(db, session, [_out(m.get("role") or "bot", m) for m in pick], pick)
    q = (db.table("whatsapp_messages")
         .select("id, content, created_at, direction, sent_by, message_type, media_url, reply_to_id, edited_at, deleted_at")
         .eq("org_id", session["org_id"]).eq("webchat_session_id", session["id"])
         .order("created_at", desc=False).limit(limit))
    if after:
        q = q.or_(f"created_at.gt.{after},edited_at.gt.{after},deleted_at.gt.{after}")
    rows = q.execute().data or []
    outs = [_out("visitor" if r["direction"] == "inbound" else ("rep" if r.get("sent_by") else "bot"), r) for r in rows]
    _attach_rep_names(db, outs, rows)
    return _attach_quotes(db, session, outs, rows)


def _flush_history(db, session: dict) -> None:
    hist = session.get("history") or []
    if not hist or not session.get("lead_id"):
        return
    rows = []
    for m in hist:
        r = {
            "id": m["id"], "org_id": session["org_id"], "lead_id": session["lead_id"], "channel": "webchat",
            "webchat_session_id": session["id"], "message_type": "text", "content": m["text"],
            "direction": "inbound" if m["role"] == "visitor" else "outbound",
            "status": "delivered" if m["role"] == "visitor" else "sent", "sent_by": None, "created_at": m["at"],
        }
        for k_src, k_dst in (("reply_to", "reply_to_id"), ("edited_at", "edited_at"), ("deleted_at", "deleted_at"), ("original", "original_content")):
            if m.get(k_src):
                r[k_dst] = m[k_src]
        rows.append(r)
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
    created = False
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
        created = True
    if not lead_id:
        raise RuntimeError("lead could not be created")
    patch = {"consent_at": now, "consent_version": consent_version, "last_activity_at": now,
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
    try:     # WEBCHAT-CONTACT-1c: a visible trace on the lead, so the chat is easy to find even when the number matched an older lead
        from app.services import lead_service
        who = (clean.get("name") or "A visitor")[:60]
        how = "created from this chat" if created else "an existing lead, matched by WhatsApp number"
        lead_service.write_timeline_event(db, org_id, lead_id, event_type="webchat_started", actor_id=None,
                                          description=f"Web chat: {who} chatted with Chioma on your website ({how}). See Conversations.",
                                          metadata={"session_id": session["id"], "source": session.get("source")})
    except Exception as exc:
        logger.warning("webchat timeline note failed lead=%s: %s", lead_id, exc)
    return session


# ── Staff side ──────────────────────────────────────────────────────────────

def assigned_rep_id(db, org_id: str, lead_id: Optional[str]) -> Optional[str]:
    """The sales rep this lead is assigned to, if that person belongs to this business (else None)."""
    if not lead_id:
        return None
    try:
        lead = _one((db.table("leads").select("assigned_to").eq("id", lead_id).eq("org_id", org_id).limit(1).execute()).data)
        rep = (lead or {}).get("assigned_to")
        if not rep:
            return None
        user = _one((db.table("users").select("id").eq("id", rep).eq("org_id", org_id).limit(1).execute()).data)
        return str(user["id"]) if user else None
    except Exception as exc:
        logger.warning("webchat assigned rep lookup failed lead=%s: %s", lead_id, exc)
        return None


def notify_managers(db, org_id: str, title: str, body: str, lead_id: Optional[str], kind: str = "webchat",
                    to_assigned_rep: bool = False) -> None:
    """to_assigned_rep: tell the lead's assigned rep instead of the managers (managers only when nobody is assigned)."""
    try:
        from app.services import funnel_service
        rep = assigned_rep_id(db, org_id, lead_id) if to_assigned_rep else None
        if rep:
            db.table("notifications").insert({
                "org_id": org_id, "user_id": rep, "title": title[:200], "body": body[:1000], "type": kind,
                "resource_type": "lead", "resource_id": lead_id, "is_read": False, "created_at": _iso(_now()),
            }).execute()
            return
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


def rep_send(db, org_id: str, lead_id: str, text: str, user_id: str, reply_to: Optional[str] = None) -> dict:
    """A rep's reply into a web chat. Stored only; the visitor's page picks it up. No Meta call, no fee.
    reply_to: id of an earlier message of this chat to quote (WEBCHAT-STAFF-1)."""
    s = latest_session_for_lead(db, org_id, lead_id)
    if not s:
        raise LookupError("no web chat for this contact")
    if s.get("status") != "active":
        raise PermissionError("this web chat has ended")
    msg = append_message(db, s, "rep", text, sent_by=user_id, reply_to=reply_to)
    set_state(db, s, human=True, rep_last_at=_iso(_now()), human_at=_iso(_now()))
    typing_clear("rep", str(s["id"]))
    touch_lead(db, org_id, lead_id)
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
