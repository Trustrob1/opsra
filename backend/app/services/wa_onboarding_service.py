"""
app/services/wa_onboarding_service.py
-------------------------------------
WA-AUTO-3 - the first-login wizard for a WhatsApp-automation-only business.

State lives in wa_onboarding (one row per organisation). Connecting the number itself still uses POST /admin/whatsapp/connect,
which checks the phone number id and token with Meta. This service holds the rest: the business basics, the "please connect it
for me" request, the live test, and finishing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

LANGUAGES = ("English", "Pidgin", "Yoruba", "Igbo", "Hausa", "French")
_MAX_SELL, _MAX_HOURS, _MAX_NOTE = 1500, 300, 500
TEST_WINDOW_MINUTES = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _one(res: Any) -> dict:
    data = getattr(res, "data", None)
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def _fail(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _row(db: Any, org_id: str) -> dict:
    try:
        return _one(db.table("wa_onboarding").select("*").eq("org_id", org_id).limit(1).execute())
    except Exception as exc:
        logger.warning("wa_onboarding: read failed org=%s: %s", org_id, exc)
        return {}


def _save(db: Any, org_id: str, fields: dict) -> None:
    fields = {**fields, "updated_at": _iso(_now())}
    if _row(db, org_id):
        db.table("wa_onboarding").update(fields).eq("org_id", org_id).execute()
    else:
        db.table("wa_onboarding").insert({"org_id": org_id, **fields}).execute()


def _connection(db: Any, org_id: str) -> dict:
    try:
        o = _one(db.table("organisations").select("whatsapp_phone_id, whatsapp_access_token, name").eq("id", org_id).limit(1).execute())
    except Exception as exc:
        logger.warning("wa_onboarding: connection read failed org=%s: %s", org_id, exc)
        o = {}
    return {"connected": bool(o.get("whatsapp_phone_id") and o.get("whatsapp_access_token")),
            "phone_id": o.get("whatsapp_phone_id"), "business_name": o.get("name")}


def state(db: Any, org_id: str) -> dict:
    r = _row(db, org_id)
    conn = _connection(db, org_id)
    return {"basics": r.get("basics") or {}, "setup_requested": bool(r.get("setup_requested_at")),
            "setup_requested_at": r.get("setup_requested_at"), "completed": bool(r.get("completed_at")),
            "connected": conn["connected"], "phone_id": conn["phone_id"], "business_name": conn["business_name"],
            "languages": list(LANGUAGES)}


def _clean(value: Any, limit: int, label: str, required: bool = False) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        _fail(422, "VALIDATION_ERROR", f"{label} is needed.")
    if len(text) > limit:
        _fail(422, "VALIDATION_ERROR", f"{label} must be {limit} characters or fewer.")
    return text


BASICS_TITLE = "About our business"


def _publish_basics(db: Any, org_id: str, user_id: Optional[str], basics: dict) -> bool:
    """Puts the basics where the bot already looks (a published knowledge-base article), so they help from the first message.
    S14: a problem here never loses the saved basics."""
    content = (f"What we sell: {basics['what_you_sell']}\nOpening hours: {basics['hours']}\n"
               f"Reply to customers in: {basics['language']}")
    now = _iso(_now())
    try:
        found = _one(db.table("knowledge_base_articles").select("id").eq("org_id", org_id).eq("title", BASICS_TITLE).limit(1).execute())
        if found.get("id"):
            db.table("knowledge_base_articles").update({"content": content, "is_published": True, "updated_at": now}).eq("id", found["id"]).eq("org_id", org_id).execute()
        else:
            db.table("knowledge_base_articles").insert({
                "org_id": org_id, "category": "product_overview", "title": BASICS_TITLE, "content": content,
                "tags": ["wa_basics"], "is_published": True, "usage_count": 0, "version": 1, "created_by": user_id,
                "created_at": now, "updated_at": now,
            }).execute()
        return True
    except Exception as exc:
        logger.warning("wa_onboarding: basics not added to the bot's knowledge org=%s: %s", org_id, exc)
        return False


def save_basics(db: Any, org_id: str, what_you_sell: str, hours: str, language: str, user_id: Optional[str] = None) -> dict:
    if language not in LANGUAGES:
        _fail(422, "VALIDATION_ERROR", "Pick one of the languages in the list.")
    basics = {"what_you_sell": _clean(what_you_sell, _MAX_SELL, "What you sell", required=True),
              "hours": _clean(hours, _MAX_HOURS, "Opening hours", required=True), "language": language}
    _save(db, org_id, {"basics": basics})
    _publish_basics(db, org_id, user_id, basics)
    return basics


def request_setup(db: Any, org_id: str, user_id: str, phone: str, note: str) -> dict:
    """The owner asks Opsra to connect the number. Recorded once per request, and Opsra's own owners are notified."""
    phone = _clean(phone, 30, "Your WhatsApp number", required=True)
    if not any(ch.isdigit() for ch in phone) or sum(ch.isdigit() for ch in phone) < 7:
        _fail(422, "VALIDATION_ERROR", "Enter the WhatsApp number with its country code, for example 2348012345678.")
    note = _clean(note, _MAX_NOTE, "Note")
    _save(db, org_id, {"setup_requested_at": _iso(_now()), "setup_phone": phone, "setup_note": note or None})
    notified = _notify_platform(db, org_id, phone, note)
    return {"requested": True, "notified": notified}


def _notify_platform(db: Any, org_id: str, phone: str, note: str) -> int:
    """S14: a notification problem never fails the request; the row above is the record."""
    try:
        from app.services import platform_guard as pg
        pid = pg.platform_id(db)
        if not pid:
            return 0
        name = _connection(db, org_id).get("business_name") or "A business"
        users = db.table("users").select("id, roles").eq("org_id", pid).execute().data or []
        sent = 0
        for u in users:
            template = ((u.get("roles") or {}).get("template") or "") if isinstance(u.get("roles"), dict) else ""
            if template not in ("owner", "ops_manager"):
                continue
            db.table("notifications").insert({
                "org_id": pid, "user_id": u["id"], "title": f"{name} wants help connecting WhatsApp",
                "body": f"Number: {phone}. {note}"[:1000], "type": "wa_setup_request",
                "resource_type": "organisation", "resource_id": org_id, "is_read": False, "created_at": _iso(_now()),
            }).execute()
            sent += 1
        return sent
    except Exception as exc:
        logger.warning("wa_onboarding: platform notification failed org=%s: %s", org_id, exc)
        return 0


def test_status(db: Any, org_id: str) -> dict:
    """Has someone messaged the number lately, and did a reply go out? Looks at the last hour only."""
    since = _iso(_now().replace(microsecond=0) - timedelta(minutes=TEST_WINDOW_MINUTES))
    out = {"inbound_at": None, "reply_at": None}
    for direction, key in (("inbound", "inbound_at"), ("outbound", "reply_at")):
        try:
            rows = (db.table("whatsapp_messages").select("created_at").eq("org_id", org_id).eq("direction", direction)
                    .gte("created_at", since).order("created_at", desc=True).limit(1).execute().data) or []
            out[key] = rows[0]["created_at"] if rows else None
        except Exception as exc:
            logger.warning("wa_onboarding: test status failed org=%s: %s", org_id, exc)
    out["ok"] = bool(out["inbound_at"] and out["reply_at"])
    return out


def complete(db: Any, org_id: str) -> dict:
    if not _connection(db, org_id)["connected"]:
        _fail(409, "NOT_CONNECTED", "Connect your WhatsApp number first.")
    _save(db, org_id, {"completed_at": _iso(_now())})
    return {"completed": True}
