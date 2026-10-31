"""
backend/app/services/calendly_service.py
BOOKING-3C - Calendly intake. A booking made in Calendly appears in Opsra as a lead_demos row (source 'calendly') so it gets the same
WhatsApp confirmation, reminders, no-show handling and recap, and blocks Opsra's own open slots.

Connect: the org pastes a Calendly personal access token. We create one webhook subscription (invitee.created, invitee.canceled)
pointing at /api/v1/webhooks/calendly/<secret token> with our own signing key. Calendly signs every call; we check the signature
and the age of the call before touching anything. The org always comes from that secret token, never from the body.
Calendly owns its double-booking check; we only mirror. Cancelling a Calendly booking in Opsra cancels it in Calendly too.
Reschedule in Opsra is not offered for Calendly bookings: the person uses their Calendly reschedule link.
"""
import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)
_API = "https://api.calendly.com"
_TOLERANCE_SECONDS = 300
PROVIDER = "calendly"


def _err(status: int, code: str, msg: str):
    from app.services.booking_service import _err as e
    return e(status, code, msg)


def public_api_base() -> str:
    return (os.getenv("PUBLIC_API_URL") or "https://opsra.onrender.com").strip().rstrip("/")


def _row(db, org_id: str) -> Optional[dict]:
    rows = db.table("integrations").select("*").eq("org_id", org_id).eq("provider", PROVIDER).limit(1).execute().data or []
    return rows[0] if rows else None


def status(db, org_id: str) -> dict:
    r = _row(db, org_id)
    if not r or r.get("status") != "connected":
        return {"connected": False}
    c = r.get("credentials") or {}
    return {"connected": True, "scope": c.get("scope"), "connected_at": r.get("connected_at"), "calendly_user": c.get("user_name")}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def connect(db, org_id: str, token: str) -> dict:
    token = (token or "").strip()
    if len(token) < 20:
        raise _err(422, "VALIDATION_ERROR", "Paste your Calendly personal access token")
    webhook_token, signing_key = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    url = f"{public_api_base()}/api/v1/webhooks/calendly/{webhook_token}"
    try:
        with httpx.Client(timeout=20) as c:
            me = c.get(f"{_API}/users/me", headers=_headers(token))
            if me.status_code == 401:
                raise _err(422, "CALENDLY_TOKEN", "Calendly did not accept that token. Create a new personal access token and try again.")
            me.raise_for_status()
            res = (me.json() or {}).get("resource") or {}
            user_uri, org_uri = res.get("uri"), res.get("current_organization")
            hook = None
            for scope, key in (("organization", org_uri), ("user", user_uri)):
                body = {"url": url, "events": ["invitee.created", "invitee.canceled"], "organization": org_uri, "scope": scope, "signing_key": signing_key}
                if scope == "user":
                    body["user"] = user_uri
                r = c.post(f"{_API}/webhook_subscriptions", headers=_headers(token), json=body)
                if r.status_code < 300:
                    hook = (r.json() or {}).get("resource") or {}
                    used = scope
                    break
                if r.status_code == 403 and scope == "organization":
                    continue      # not an admin: fall back to this user's own events
                msg = ((r.json() or {}).get("message") if r.content else "") or ""
                if r.status_code in (402, 403):
                    raise _err(422, "CALENDLY_PLAN", "Calendly only allows this on a paid plan (webhooks). " + msg)
                raise _err(502, "CALENDLY_ERROR", f"Calendly refused the connection. {msg}".strip())
            if not hook:
                raise _err(422, "CALENDLY_PLAN", "Calendly only allows webhooks on a paid plan, or with an admin token.")
    except httpx.HTTPError as exc:
        logger.warning("calendly connect failed org=%s: %s", org_id, exc)
        raise _err(502, "CALENDLY_ERROR", "Could not reach Calendly. Try again in a moment.")
    now = datetime.now(timezone.utc).isoformat()
    old = _row(db, org_id)
    if old and old.get("status") == "connected":
        _drop_remote(old)
    db.table("integrations").upsert({
        "org_id": org_id, "provider": PROVIDER, "status": "connected", "connected_at": now, "updated_at": now,
        "credentials": {"access_token": token, "signing_key": signing_key, "webhook_token": webhook_token,
                        "webhook_uri": hook.get("uri"), "scope": used, "user_uri": user_uri, "org_uri": org_uri,
                        "user_name": res.get("name")},
    }, on_conflict="org_id,provider").execute()
    return status(db, org_id)


def _drop_remote(row: dict) -> None:
    c = row.get("credentials") or {}
    if c.get("access_token") and c.get("webhook_uri"):
        try:
            with httpx.Client(timeout=15) as cl:
                cl.delete(c["webhook_uri"], headers=_headers(c["access_token"]))
        except Exception as exc:
            logger.warning("calendly webhook delete failed: %s", exc)


def disconnect(db, org_id: str) -> dict:
    r = _row(db, org_id)
    if r:
        _drop_remote(r)
        db.table("integrations").update({"status": "disconnected", "credentials": {}, "updated_at": datetime.now(timezone.utc).isoformat()}
                                        ).eq("org_id", org_id).eq("provider", PROVIDER).execute()
    return {"connected": False}


def verify_signature(signing_key: str, header: Optional[str], raw: bytes, now: Optional[float] = None) -> bool:
    """Calendly-Webhook-Signature: t=<unix>,v1=<hex hmac-sha256 of "<t>.<body>">"""
    try:
        parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
        t, v1 = parts["t"], parts["v1"]
        if abs((now if now is not None else time.time()) - int(t)) > _TOLERANCE_SECONDS:
            return False
        want = hmac.new(signing_key.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(want, v1)
    except Exception:
        return False


def _integration_by_token(db, webhook_token: str) -> Optional[dict]:
    if not webhook_token or len(webhook_token) > 80:
        return None
    rows = (db.table("integrations").select("*").eq("provider", PROVIDER).eq("status", "connected")
            .eq("credentials->>webhook_token", webhook_token).limit(1).execute().data or [])
    return rows[0] if rows else None


def handle_webhook(db, webhook_token: str, raw: bytes, sig_header: Optional[str]) -> dict:
    """Returns {"ok": True, ...}. Raises 401 for an unknown token or bad signature (no detail leaked)."""
    import json
    from fastapi import HTTPException
    integ = _integration_by_token(db, webhook_token)
    if not integ or not verify_signature((integ.get("credentials") or {}).get("signing_key") or "", sig_header, raw):
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Invalid webhook"})
    org_id = integ["org_id"]
    try:
        ev = json.loads(raw)
    except ValueError:
        return {"ok": True, "ignored": "bad_json"}
    kind, payload = ev.get("event"), ev.get("payload") or {}
    try:
        if kind == "invitee.created":
            return on_created(db, org_id, payload)
        if kind == "invitee.canceled":
            return on_canceled(db, org_id, payload)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("calendly webhook failed org=%s event=%s: %s", org_id, kind, exc)
        raise HTTPException(status_code=500, detail={"code": "ERROR", "message": "Could not process"})   # Calendly retries
    return {"ok": True, "ignored": kind}


# ───────────────────────────── create ─────────────────────────────

def _phone_from(payload: dict) -> Optional[str]:
    raw = payload.get("text_reminder_number")
    if not raw:
        for qa in payload.get("questions_and_answers") or []:
            q = (qa.get("question") or "").lower()
            if any(w in q for w in ("phone", "whatsapp", "mobile", "number")) and qa.get("answer"):
                raw = qa["answer"]
                break
    if not raw:
        return None
    try:
        from app.utils.phone import normalize_phone
        return normalize_phone(str(raw))
    except Exception:
        return None


def find_or_create_lead(db, org_id: str, name: str, email: Optional[str], phone: Optional[str]) -> dict:
    email = (email or "").strip().lower() or None
    for col, val in (("email", email), ("phone", phone), ("whatsapp", phone)):
        if val:
            rows = (db.table("leads").select("*").eq("org_id", org_id).eq(col, val).is_("deleted_at", "null").limit(1).execute().data or [])
            if rows:
                return rows[0]
    from app.services import booking_service as bk
    from app.services import lead_service
    from app.models.leads import LeadCreate, LeadSource
    owner = bk.pick_rep(db, org_id)
    if not owner:
        raise _err(422, "NO_OWNER", "No one in this organisation can own a new lead.")
    data = {"full_name": (name or "Calendly guest")[:255], "source": LeadSource.landing_page}
    if email:
        data["email"] = email[:255]
    if phone:
        data["phone"], data["whatsapp"] = phone[:20], phone[:20]
    return lead_service.create_lead(db, org_id, owner, LeadCreate(**data), entry_path="calendly")


def _medium(event: dict) -> str:
    t = ((event.get("location") or {}).get("type") or "").lower()
    if t == "physical":
        return "in_person"
    if t in ("outbound_call", "inbound_call"):
        return "phone"
    return "virtual"


def _owner_for(db, org_id: str, event: dict) -> Optional[str]:
    """The Opsra user whose email matches the Calendly host, else the usual round-robin pick."""
    from app.services import booking_service as bk
    emails = {(m.get("user_email") or "").lower() for m in event.get("event_memberships") or []}
    for u in bk._org_users(db, org_id):
        if (u.get("email") or "").lower() in emails:
            return u["id"]
    return bk.pick_rep(db, org_id)


def on_created(db, org_id: str, p: dict) -> dict:
    from app.services import booking_service as bk
    from app.services import demo_service as ds
    import uuid
    invitee_uri, event = p.get("uri"), p.get("scheduled_event") or {}
    if not invitee_uri or not event.get("start_time"):
        return {"ok": True, "ignored": "incomplete"}
    if (db.table("lead_demos").select("id").eq("org_id", org_id).eq("source", PROVIDER).eq("external_id", invitee_uri).limit(1).execute().data):
        return {"ok": True, "duplicate": True}
    start = bk._parse_dt(event["start_time"])
    end = bk._parse_dt(event["end_time"]) if event.get("end_time") else start + timedelta(minutes=30)
    lead = find_or_create_lead(db, org_id, p.get("name") or "", p.get("email"), _phone_from(p))
    rep = _owner_for(db, org_id, event)
    demo_id, now = str(uuid.uuid4()), bk._now_iso()
    dur = max(5, int((end - start).total_seconds() // 60))
    db.table("lead_demos").insert({
        "id": demo_id, "org_id": org_id, "lead_id": lead["id"], "status": "pending_assignment", "source": PROVIDER,
        "external_id": invitee_uri, "guard_scope": "ext", "medium": _medium(event), "scheduled_at": start.isoformat(),
        "slot_end": end.isoformat(), "duration_minutes": dur, "lead_timezone": p.get("timezone"),
        "external_meta": {"event_uri": event.get("uri"), "event_name": event.get("name"), "cancel_url": p.get("cancel_url"),
                          "reschedule_url": p.get("reschedule_url"), "location": (event.get("location") or {}).get("join_url") or (event.get("location") or {}).get("location")},
        "created_at": now, "updated_at": now,
    }).execute()
    org = bk.get_org(db, org_id)
    if rep:
        ds.confirm_demo(db, org_id, lead["id"], demo_id, None, start.isoformat(), _medium(event), rep, duration_minutes=dur)
    else:
        bk._notify_approval_needed(db, org_id, lead, demo_id, start, org)
    ds._log_timeline(db, org_id, lead["id"], None, "booking_made", f"{event.get('name') or 'Booking'} booked for {bk._fmt_local(start, org)} (Calendly).",
                     {"demo_id": demo_id, "source": PROVIDER})
    return {"ok": True, "demo_id": demo_id}


def on_canceled(db, org_id: str, p: dict) -> dict:
    from app.services import booking_service as bk
    rows = (db.table("lead_demos").select("id, status").eq("org_id", org_id).eq("source", PROVIDER).eq("external_id", p.get("uri")).limit(1).execute().data or [])
    if not rows or rows[0]["status"] not in bk._LIVE_STATUSES:
        return {"ok": True, "ignored": "no_live_booking"}
    moved = bool(p.get("rescheduled"))
    bk.cancel_booking(db, org_id, rows[0]["id"], "lead", "Moved to a new time in Calendly" if moved else "Cancelled in Calendly",
                      from_calendly=True, notify_lead=not moved)
    return {"ok": True, "cancelled": rows[0]["id"]}


# ───────────────────────────── Opsra-side cancel -> Calendly ─────────────────────────────

def cancel_remote(db, org_id: str, demo: dict, reason: Optional[str]) -> bool:
    """Best effort: cancel the event in Calendly so the customer's calendar and Calendly page agree."""
    r = _row(db, org_id)
    token = ((r or {}).get("credentials") or {}).get("access_token")
    uri = (demo.get("external_meta") or {}).get("event_uri")
    if not token or not uri:
        return False
    try:
        with httpx.Client(timeout=15) as c:
            resp = c.post(f"{uri}/cancellation", headers=_headers(token), json={"reason": (reason or "Cancelled by the business")[:500]})
        return resp.status_code < 300
    except Exception as exc:
        logger.warning("calendly remote cancel failed demo=%s: %s", demo.get("id"), exc)
        return False
