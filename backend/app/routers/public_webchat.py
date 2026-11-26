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

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.models.common import ok
from app.services import webchat_attachment_service as att
from app.services import webchat_call_service as call
from app.services import webchat_contact_service as contact
from app.services import webchat_email_service as email_svc
from app.services import webchat_embed_service as embed
from app.services import webchat_flow_service as flow
from app.services import webchat_guard_service as guard
from app.services import webchat_msg_service as msgsvc
from app.services import webchat_shop_service as shop
from app.services import webchat_service as wc
from app.services.site_capture_service import ip_hash

logger = logging.getLogger(__name__)
router = APIRouter()

NOT_FOUND = HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "This chat is not available."})


class StartBody(BaseModel):
    source: Optional[str] = Field(default=None, max_length=30)
    handoff: Optional[str] = Field(default=None, max_length=80)
    embed_origin: Optional[str] = Field(default=None, max_length=300)      # WEBCHAT-EMBED-1: the website showing the chat frame


class MessageBody(BaseModel):
    kind: Literal["menu", "text"]
    menu_id: Optional[str] = Field(default=None, max_length=30)
    text: Optional[str] = Field(default=None, max_length=1000)
    reply_to: Optional[str] = Field(default=None, max_length=40)       # WEBCHAT-MSG-1: id of the message being replied to


class EditBody(BaseModel):
    text: str = Field(max_length=1000)


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


class SaveChatBody(BaseModel):
    email: Optional[str] = Field(default=None, max_length=200)
    consent: bool = False


class CallbackBody(BaseModel):
    phone: Optional[str] = Field(default=None, max_length=30)


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


def _returning(s: dict, cfg: dict, messages: list) -> bool:
    """WEBCHAT-CONTACT-1: the visitor is back after a long quiet spell, so the chat page opens with a fresh view
    (the old messages stay saved and one tap shows them)."""
    try:
        hours = int(cfg.get("fresh_after_hours", 24) or 0)
    except (TypeError, ValueError):
        hours = 24
    return bool(hours > 0 and messages and float(s.get("_idle_s") or 0) >= hours * 3600)


def _snapshot(s: dict, cfg: dict, messages: list, ad_product=None) -> dict:
    return {
        "ad_product": ad_product,          # AD-PRODUCT-1: the card of the product the ad is about (None when the ad has none)
        "messages": messages, "has_contact": bool(s.get("lead_id")), "name": s.get("contact_name"),
        "verified_phone": bool(s.get("phone_verified")), "needs_email": bool(s.get("phone_verified") and not s.get("contact_email")),
        "human": wc.is_human(s, cfg), "config": wc.public_view(cfg, s.get("source"), s.get("org_id")),
        "contact_step": (s.get("state") or {}).get("contact_step"),
        "returning": _returning(s, cfg, messages),
    }


def _first_messages(db, org_id: str, cfg: dict, s: dict) -> list:
    """The chat's messages; a brand-new chat gets its greeting (an ad link opens with that ad's own words) and is metered once."""
    msgs = wc.list_messages(db, s)
    if not msgs:
        msgs = [wc.append_message(db, s, "bot", wc.greeting_for(cfg, s.get("source")))]          # OPENING-CTA-2: an ad link can open with its own greeting
        try:  # WA-BUDGET-1: Opsra's per-conversation fee, once per new conversation (idempotent per session)
            from app.services import credit_service
            if credit_service.meter_webchat_conversation(db, org_id, s.get("id")) > 0:
                from app.services import chat_pause_service as pause
                pause.notify_after_charge(db, org_id)           # WEB-ONLY-1c: low-credit / paused note to the owner, at most every 3 days
        except Exception:
            logger.warning("webchat conversation fee failed org=%s", org_id)
    return msgs


def _pause_guard(db, org_id: str) -> None:
    """WEB-ONLY-1c: a web-chat-only business with no credit left has its chat paused until it subscribes or tops up."""
    from app.services import chat_pause_service as pause
    if pause.is_paused(db, org_id):
        raise HTTPException(status_code=503, detail={"code": "CHAT_PAUSED", "message": pause.PAUSED_MESSAGE})


def _embed_guard(found: dict, embed_origin: Optional[str]) -> None:
    """A chat frame on a website that is not on the business's list is refused (only when a list is set)."""
    if embed_origin is not None and not embed.origin_allowed(found["config"].get("allowed_domains"), embed_origin):
        raise HTTPException(status_code=403, detail={"code": "EMBED_NOT_ALLOWED", "message": "This chat cannot be shown on this website."})


def _chioma_flags(cfg: dict) -> dict:
    """WEBCHAT-BUBBLE-1: what the launcher needs to show Chioma. assistant_active = AI answers are really on (plan included);
    team_available = inside the business's set hours right now. The green dot shows only when a reply can come now.
    Never raises: a problem here must not stop the bubble."""
    f = wc.chioma_flags(cfg)
    return {"assistant_active": f["assistant_active"], "team_available": f["team_available"], "online": f["online"]}


@router.get("/public/webchat/{key}/widget")
def widget_info(key: str, request: Request, s: Optional[str] = Query(default=None, max_length=60), db=Depends(get_supabase)):
    """WEBCHAT-EMBED-1: what widget.js needs to draw the bubble, on any website. Open to every origin on purpose;
    `allowed` says whether THIS website (the Origin header the browser sent) may show it."""
    from fastapi.responses import JSONResponse
    out = {"allowed": False}
    found = wc.resolve_key(db, key)
    if found:
        cfg = found["config"]
        from app.services import chat_pause_service as pause
        out = {"allowed": embed.origin_allowed(cfg.get("allowed_domains"), request.headers.get("origin")) and not pause.is_paused(db, found["org_id"]),
               "business_name": cfg["business_name"], "goal": cfg.get("visitor_goal") or "", "brand_color": cfg["brand_color"], "side": cfg.get("widget_side", "right"),
               "bar": wc.ask_bar_view(cfg, s), "chat_theme": cfg.get("chat_theme") if cfg.get("chat_theme") in wc.CHAT_THEMES else "classic", **_chioma_flags(cfg)}
    if out.get("allowed") and found:
        from urllib.parse import urlparse
        own = tuple(h for h in ((urlparse(wc.public_base()).hostname or ""),) if h)
        embed.record_seen(db, found["org_id"], request.headers.get("origin"), own)      # lets Settings say "installed on ..."
    return JSONResponse(content={"success": True, "data": out, "message": None, "error": None},
                        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


@router.get("/public/webchat/{key}/config")
def get_config(key: str, response: Response, db=Depends(get_supabase)):
    _nostore(response)
    return ok(wc.public_view(_chat(db, key)["config"]))


@router.post("/public/webchat/{key}/session")
def start_session(key: str, body: StartBody, request: Request, response: Response, db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    _embed_guard(found, body.embed_origin)
    org_id, cfg = found["org_id"], found["config"]
    _pause_guard(db, org_id)
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
        if iph and wc.rate_limited(f"sessburst:{key}:{iph}", 5, 600):          # SAFE: five new chats from one address in ten minutes: the first message gets a check
            wc.set_state(db, s, check_first=True)
    msgs = _first_messages(db, org_id, cfg, s)
    snap = _snapshot(s, cfg, msgs, shop.ad_product(db, s, cfg))
    snap["token"] = token
    return ok(snap)


@router.get("/public/webchat/{key}/session")
def resume_session(key: str, response: Response, authorization: Optional[str] = Header(default=None),
                   po: Optional[str] = Query(default=None, max_length=300), s_: Optional[str] = Query(default=None, alias="s", max_length=60),
                   db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    _embed_guard(found, po)
    s = _session(db, found, authorization)
    if wc.wants_fresh_chat(found["config"], s, s_):            # AD-FRESH-1/2: an ad link over an older chat from elsewhere starts a new one
        if not s.get("lead_id"):
            return ok({"restart": True})                           # nobody to carry over: the page starts a normal fresh chat
        if wc.rate_limited(f"carry:{s['id']}", 3, 3600):
            return ok(_snapshot(s, found["config"], wc.list_messages(db, s), shop.ad_product(db, s, found["config"])))
        ns, token = wc.carry_session(db, s, s_)                    # AD-FRESH-2: same person, new chat for this ad
        wc.log_event(db, ns.get("org_id") or s.get("org_id"), ns.get("id"), "visit", s_)
        snap = _snapshot(ns, found["config"], _first_messages(db, s["org_id"], found["config"], ns), shop.ad_product(db, ns, found["config"]))
        snap["token"] = token
        return ok(snap)
    return ok(_snapshot(s, found["config"], wc.list_messages(db, s), shop.ad_product(db, s, found["config"])))


@router.get("/public/webchat/{key}/messages")
def poll_messages(key: str, response: Response, after: Optional[str] = Query(default=None, max_length=40),
                  authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"poll:{s['id']}", 120, 60):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    return ok({"messages": wc.list_messages(db, s, after=after), "human": wc.is_human(s, found["config"]),
               "rep_typing": wc.rep_is_typing(s)})       # WEBCHAT-CONTACT-1d: shows the typing dots while the team writes


@router.post("/public/webchat/{key}/typing")
def post_typing(key: str, response: Response, authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    """WEBCHAT-CONTACT-1e: the visitor is typing; the team's inbox shows it. Sent at most every few seconds by the page."""
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"vtype:{s['id']}", 30, 60):
        return ok({})
    wc.visitor_typing(db, s)
    return ok({})


@router.post("/public/webchat/{key}/message")
def post_message(key: str, body: MessageBody, response: Response, authorization: Optional[str] = Header(default=None),
                 db=Depends(get_supabase), request: Request = None):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"msg:{s['id']}", 30, 60):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    iph = ip_hash(_client_ip(request)) if request is not None else None
    if iph and wc.rate_limited(f"msgip:{iph}", 240, 3600):          # SAFE: limit by visitor address as well as by chat, so many new chats do not get round it
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    cfg = {**found["config"], "_ip": iph}
    if iph and not (s.get("state") or {}).get("ai_blocked") and guard.address_blocked(found["org_id"], iph):
        wc.set_state(db, s, ai_blocked=True)          # SAFE: this address was blocked from the AI in another chat of this business
    _pause_guard(db, found["org_id"])
    if body.kind == "text" and (s.get("state") or {}).get("viewing"):
        # WEBCHAT-CATALOG-1b: the visitor is on a Storefront product. If no AI answer can be given, the stock "I did not catch
        # that" line is replaced by the product's own catalogue text (the flow uses cfg["fallback"] only when nothing else answered).
        scripted = shop.product_answer(db, s, cfg, body.text or "")
        if scripted:
            cfg = {**cfg, "fallback": scripted, "_fallback_base": cfg["fallback"]}
    return ok(flow.handle_message(db, s, cfg, kind=body.kind, menu_id=body.menu_id, text=body.text, reply_to=body.reply_to))


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


class ContactStartBody(BaseModel):
    why: str = Field(default="", max_length=20)


@router.post("/public/webchat/{key}/contact/start")
def post_contact_start(key: str, body: ContactStartBody, response: Response, authorization: Optional[str] = Header(default=None),
                       db=Depends(get_supabase)):
    """WEBCHAT-CONTACT-1: a button needs the visitor's details (call back, file, voice note, check out): Chioma asks in the chat.
    {form: true} means the chat script is switched off for this business, so the page opens the form as before."""
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    cfg = found["config"]
    if s.get("lead_id") or contact.step_of(s):
        return ok({"messages": [], "contact_step": contact.step_of(s)})
    if not contact.enabled(cfg):
        return ok({"messages": [], "contact_step": None, "form": True})
    if wc.rate_limited(f"cstart:{s['id']}", 10, 3600):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    why = body.why if body.why in contact.INTROS else ""
    return ok({"messages": [contact.start_for(db, s, cfg, why)], "contact_step": "name"})


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


@router.patch("/public/webchat/{key}/message/{message_id}")
def edit_message(key: str, message_id: str, body: EditBody, response: Response, authorization: Optional[str] = Header(default=None),
                 db=Depends(get_supabase)):
    """WEBCHAT-MSG-1: the visitor edits one of their own text messages (15 minutes)."""
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"msgedit:{s['id']}", 30, 600):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    out, err = msgsvc.edit(db, s, message_id, body.text)
    if err:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": err})
    return ok({"message": out})


@router.delete("/public/webchat/{key}/message/{message_id}")
def delete_message(key: str, message_id: str, response: Response, authorization: Optional[str] = Header(default=None),
                   db=Depends(get_supabase)):
    """WEBCHAT-MSG-1: the visitor deletes one of their own messages for everyone."""
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"msgdel:{s['id']}", 30, 600):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    out, err = msgsvc.delete(db, s, message_id)
    if err:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": err})
    return ok({"message": out})


@router.post("/public/webchat/{key}/callback")
def post_callback(key: str, body: CallbackBody, response: Response, authorization: Optional[str] = Header(default=None),
                  db=Depends(get_supabase)):
    """WEBCHAT-CALL-1: the visitor asks for a call back; a task for a rep is due when calls reopen."""
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"callback:{s['id']}", 3, 86400):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "You have already asked for a call back today."})
    res = call.request_callback(db, s, found["config"], body.phone)
    if res.get("error"):
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": res["error"], "need_phone": bool(res.get("need_phone")),
                                                     "ask_contact": "contact details" in res["error"]})
    return ok({"messages": res["messages"]})


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


class ViewingBody(BaseModel):
    product: str = Field(max_length=60)


@router.post("/public/webchat/{key}/viewing")
def post_viewing(key: str, body: ViewingBody, response: Response, authorization: Optional[str] = Header(default=None),
                 db=Depends(get_supabase)):
    """WEBCHAT-CATALOG-1: the chat was opened from a product page (Storefront). Not gated by the shop switch."""
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"view:{s['id']}", 30, 60):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    return ok(shop.viewing(db, s, found["config"], body.product))


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


# ── WEBCHAT-5b: a visitor tapped a link in the chat (counted once per chat) ──

@router.post("/public/webchat/{key}/tap")
def tap(key: str, response: Response, authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"tap:{s['id']}", 20, 3600):
        return ok({"counted": False})
    if (s.get("state") or {}).get("tapped"):
        return ok({"counted": False})
    wc.set_state(db, s, tapped=True)
    wc.log_event(db, s["org_id"], s["id"], "tap", s.get("source"))
    return ok({"counted": True})


# ── WEBCHAT-4: email follow-ups ─────────────────────────────────────────────

@router.post("/public/webchat/{key}/upload")
def post_upload(key: str, response: Response, file: UploadFile = File(...), kind: str = Form(...),
                authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    """WEBCHAT-ATTACH-1: a photo, voice note or document from the visitor. Needs contact details first; the file's
    real type is checked from its bytes; the team is told, and the chat is handed to a person."""
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if not s.get("lead_id"):
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "ask_contact": True,
                                                     "message": "Please share your contact details first, then send your file."})
    if wc.rate_limited(f"upload:{s['id']}", 10, 600):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "That is a lot of files. Please wait a few minutes."})
    data = file.file.read(att.MAX_ANY + 1)
    clean, err = att.validate(data, kind, file.filename)
    if err:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": err})
    try:
        msg = att.save_attachment(db, s, kind, clean, data)
    except RuntimeError:
        raise HTTPException(status_code=503, detail={"code": "UPLOAD_FAILED", "message": "We could not save your file. Please try again."})
    cfg = found["config"]
    out = [msg]
    po = (s.get("state") or {}).get("pending_order")
    if po and kind in ("image", "document"):          # ORDER-CONFIRM-1: with an order waiting, a photo or document is the payment receipt
        wc.set_state(db, s, pending_order={**po, "status": "receipt_uploaded"})
        flow._notify_human(db, s, cfg, "Payment receipt uploaded for the order waiting on payment. Check it and confirm here.")
        s = wc.set_human(db, s)
        out.append(wc.append_message(db, s, "bot", "Thank you. We received your payment receipt. A team member will confirm your payment here shortly."))
        return ok({"messages": out, "human": True})
    flow._notify_human(db, s, cfg, f"Sent {att.label(kind)}")
    s = wc.set_human(db, s)
    # always answer, so the visitor sees the file was received (a chat already with a person used to stay silent)
    out.append(wc.append_message(db, s, "bot", f"Thanks, we received {att.label(kind)}. A team member will take a look and reply here."))
    return ok({"messages": out, "human": True})


@router.post("/public/webchat/{key}/save-chat")
def save_chat(key: str, body: SaveChatBody, response: Response, authorization: Optional[str] = Header(default=None),
              db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"savechat:{s['id']}", 3, 3600):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many emails. Please try again later."})
    res = email_svc.save_email(db, s, found["config"], body.email, body.consent)
    if res.get("error"):
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": res["error"]})
    return ok(res)


@router.post("/public/webchat/{key}/email-optout")
def email_optout(key: str, response: Response, authorization: Optional[str] = Header(default=None), db=Depends(get_supabase)):
    _nostore(response)
    found = _chat(db, key)
    s = _session(db, found, authorization)
    if wc.rate_limited(f"optout:{s['id']}", 10, 3600):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Slow down a little."})
    return ok(email_svc.opt_out(db, s))
