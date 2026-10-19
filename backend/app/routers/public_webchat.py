"""
app/routers/public_webchat.py
-----------------------------
WEBCHAT-1 — public (no login) routes behind the chat page /c/{key}. Prefix: /api/v1/public/webchat

Org comes from the key in the path only. The session token travels in the Authorization
header (Bearer) and only its hash is stored. Responses are no-store. Every write is rate
limited (Redis when available) and the contact form carries a honeypot field.

  GET  /{key}/config                       look and menu
  POST /{key}/session                      start (or hand off from WhatsApp) → token + messages
  GET  /{key}/session                      resume with the token → messages
  GET  /{key}/messages?after=ISO           poll for new messages (rep replies)
  POST /{key}/message                      menu tap or typed text → scripted reply
  POST /{key}/contact                      name + WhatsApp/email + consent → lead
  POST /{key}/booking                      booking form (needs contact)
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.models.common import ok
from app.services import webchat_flow_service as flow
from app.services import webchat_shop_service as shop
from app.services import webchat_service as wc
from app.services.site_capture_service import ip_hash

logger = logging.getLogger(__name__)
router = APIRouter()

NOT_FOUND = HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "This chat is not available."})


class StartBody(BaseModel):
    source: Optional[str] = Field(default=None, max_length=30)
    handoff: Optional[str] = Field(default=None, max_length=80)


class MessageBody(BaseModel):
    kind: Literal["menu", "text"]
    menu_id: Optional[str] = Field(default=None, max_length=30)
    text: Optional[str] = Field(default=None, max_length=1000)


class ContactBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    phone: Optional[str] = Field(default=None, max_length=30)
    email: Optional[str] = Field(default=None, max_length=200)
    consent: bool = False
    website: Optional[str] = Field(default=None, max_length=200)   # honeypot: real visitors leave it empty


class CartBody(BaseModel):
    action: Literal["add", "remove", "clear"]
    product_id: Optional[str] = Field(default=None, max_length=60)
    variant_id: Optional[str] = Field(default=None, max_length=80)
    qty: int = Field(default=1, ge=1, le=10)


class BookingBody(BaseModel):
    fields: dict = Field(default_factory=dict)


def _nostore(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else None) or (request.client.host if request.client else None)


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return None


def _chat(db, key: str) -> dict:
    found = wc.resolve_key(db, key)
    if not found:
        raise NOT_FOUND
    return found


def _session(db, found: dict, authorization: Optional[str]) -> dict:
    s = wc.authenticate(db, found["org_id"], _bearer(authorization))
    if not s:
        raise HTTPException(status_code=401, detail={"code": "SESSION_EXPIRED", "message": "Your chat session has ended. Please start again."})
    return s


def _snapshot(s: dict, cfg: dict, messages: list) -> dict:
    return {
        "messages": messages, "has_contact": bool(s.get("lead_id")), "name": s.get("contact_name"),
        "verified_phone": bool(s.get("phone_verified")), "needs_email": bool(s.get("phone_verified") and not s.get("contact_email")),
        "human": bool((s.get("state") or {}).get("human")), "config": wc.public_view(cfg),
    }


@router.get("/public/webchat/{key}/config")
def get_config(key: str, response: Response, db=Depends(get_supabase)):
    _nostore(response)
    return ok(wc.public_view(_chat(db, key)["config"]))


@router.post("/public/webchat/{key}/session")
def start_session(key: str, body: StartBody, request: Request, response: Response, db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    org_id, cfg = found["org_id"], found["config"]
    iph = ip_hash(_client_ip(request))
    if wc.rate_limited(f"sess:{key}:{iph}", 20, 86400):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many chats started. Please try again later."})
    s, token = None, None
    if body.handoff:
        ex = wc.exchange_handoff(db, org_id, body.handoff)
        if ex:
            s, token = ex
    if not s:
        s, token = wc.create_session(db, org_id, source=body.source, ip_hash=iph)
        wc.log_event(db, org_id, s.get("id"), "visit", body.source)
    msgs = wc.list_messages(db, s)
    if not msgs:
        msgs = [wc.append_message(db, s, "bot", cfg["greeting"])]
    snap = _snapshot(s, cfg, msgs)
    snap["token"] = token
    return ok(snap)


@router.get("/public/webchat/{key}/session")
def resume_session(key: str, response: Response, authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    return ok(_snapshot(s, found["config"], wc.list_messages(db, s)))


@router.get("/public/webchat/{key}/messages")
def poll_messages(key: str, response: Response, after: Optional[str] = Query(default=None, max_length=40),
                  authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"poll:{s['id']}", 120, 60):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    return ok({"messages": wc.list_messages(db, s, after=after), "human": bool((s.get("state") or {}).get("human"))})


@router.post("/public/webchat/{key}/message")
def post_message(key: str, body: MessageBody, response: Response, authorization: Optional[str] = Header(default=None),
                 db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"msg:{s['id']}", 30, 60):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    return ok(flow.handle_message(db, s, found["config"], kind=body.kind, menu_id=body.menu_id, text=body.text))


@router.post("/public/webchat/{key}/contact")
def post_contact(key: str, body: ContactBody, response: Response, authorization: Optional[str] = Header(default=None),
                 db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if body.website:                       # honeypot filled: pretend it worked, do nothing
        return ok({"messages": []})
    if wc.rate_limited(f"contact:{s['id']}", 6, 3600):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many attempts. Please try again later."})
    res = flow.handle_contact(db, s, found["config"], name=body.name, phone=body.phone, email=body.email, consent=body.consent)
    if res.get("error"):
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": res["error"]})
    return ok(res)


@router.post("/public/webchat/{key}/booking")
def post_booking(key: str, body: BookingBody, response: Response, authorization: Optional[str] = Header(default=None),
                 db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"booking:{s['id']}", 5, 86400):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many requests today. Please contact us directly."})
    res = flow.handle_booking(db, s, found["config"], body.fields)
    if res.get("error"):
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": res["error"]})
    return ok(res)


# ── WEBCHAT-3b: shop (only when the business switched it on) ───────────────

def _shop_on(found: dict) -> None:
    if not found["config"].get("shop_enabled"):
        raise NOT_FOUND


@router.get("/public/webchat/{key}/products")
def list_products(key: str, response: Response, q: Optional[str] = Query(default=None, max_length=60),
                  authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    _shop_on(found)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"shop:{s['id']}", 60, 60):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    return ok({"products": shop.search(db, s["org_id"], q), "cart": shop.view(s)})


@router.get("/public/webchat/{key}/cart")
def get_cart(key: str, response: Response, authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    _shop_on(found)
    return ok(shop.view(_session(db, found, authorization)))


@router.post("/public/webchat/{key}/cart")
def change_cart(key: str, body: CartBody, response: Response, authorization: Optional[str] = Header(default=None),
                db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    _shop_on(found)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"cart:{s['id']}", 60, 60):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    if body.action == "add":
        res = shop.add(db, s, body.product_id or "", body.variant_id, body.qty)
    elif body.action == "remove":
        res = shop.remove(db, s, body.product_id or "", body.variant_id)
    else:
        res = shop.clear(db, s)
    if res.get("error"):
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": res["error"]})
    return ok(res)


@router.post("/public/webchat/{key}/checkout")
def checkout(key: str, response: Response, authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    _shop_on(found)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"checkout:{s['id']}", 5, 3600):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many attempts. Please contact us directly."})
    res = shop.checkout(db, s, found["config"])
    if res.get("error"):
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": res["error"], "ask_contact": bool(res.get("ask_contact"))})
    return ok(res)
