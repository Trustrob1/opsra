"""
app/routers/webchat.py
----------------------
WEBCHAT-1/2 — staff routes (login required). Prefix: /api/v1

  POST /conversations/webchat/send   a rep's reply into a web chat (stored only; no Meta call, no fee)
  GET  /webchat/settings             settings + the chat link and key (owner / ops_manager)
  PUT  /webchat/settings             change settings (validated; unknown keys dropped)
  POST /webchat/settings/template    fill the menu from a starter template (salon) — answers are placeholders to edit
  GET  /webchat/stats                visits → started → contact → booked, last 30 days
  GET  /webchat/analytics?days=30    WEBCHAT-5: funnel, by source, by day, chat facts, cost per chat, AI budget
  GET  /webchat/qr.svg?s=tag&download=1   WEBCHAT-5: QR code for the chat link tagged with a source
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import webchat_embed_service as embed
from app.services import webchat_service as wc

logger = logging.getLogger(__name__)
router = APIRouter()

SALON_TEMPLATE = {
    "menu": [
        {"id": "services", "label": "Services and prices", "keywords": ["price", "cost", "how much", "service", "braid", "wig", "hair"],
         "answer": "[Add your services and prices here]"},
        {"id": "products", "label": "Hair products", "keywords": ["product", "shampoo", "oil", "extension"],
         "answer": "[Add what you sell and how to order]"},
        {"id": "hours", "label": "Opening hours", "keywords": ["open", "close", "hours", "time"],
         "answer": "[Add your opening hours]"},
        {"id": "location", "label": "Where to find us", "keywords": ["where", "location", "address", "direction"],
         "answer": "[Add your address]"},
        {"id": "book", "label": "Book an appointment", "action": "booking", "keywords": ["book", "appointment", "reserve"]},
        {"id": "talk", "label": "Talk to us", "action": "human", "keywords": ["human", "person", "call", "agent"]},
    ],
}


class WebchatSend(BaseModel):
    lead_id: str = Field(..., max_length=36)
    message: str = Field(..., min_length=1, max_length=2000)
    reply_to: Optional[str] = Field(default=None, max_length=36)     # WEBCHAT-STAFF-1: quote an earlier message


class WebchatEdit(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class TestWhatsapp(BaseModel):
    phone: str = Field(..., min_length=7, max_length=30)


class TemplateBody(BaseModel):
    template: str = Field(default="salon", max_length=30)


class TeachBody(BaseModel):
    menu_id: str = Field(..., min_length=1, max_length=30)
    keyword: str = Field(..., min_length=1, max_length=30)


def _require_manager(org: dict) -> None:
    role = ((org.get("roles") or {}).get("template") or "").lower()
    if role not in ("owner", "ops_manager", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner or an operations manager can change web chat settings.")


def _require_plan(db, org: dict, key: str) -> None:
    """ACCOUNT-PLANS AP-4. A business that has not been switched on is always allowed."""
    from app.services import webchat_plan_service as plan
    if not plan.allowed(db, org["org_id"], key):
        raise HTTPException(status_code=403, detail=plan.PLAN_MESSAGE)


@router.post("/conversations/webchat/send")
def send_webchat_reply(payload: WebchatSend, db=Depends(get_supabase), org=Depends(get_current_org)):
    """S1: org_id comes from the login, never the body."""
    lead = (db.table("leads").select("id").eq("id", payload.lead_id).eq("org_id", org["org_id"])
            .is_("deleted_at", "null").limit(1).execute().data)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        msg = wc.rep_send(db, org["org_id"], payload.lead_id, payload.message, org["id"], reply_to=payload.reply_to)
    except LookupError:
        raise HTTPException(status_code=422, detail="This contact has no web chat to reply to.")
    except PermissionError:
        raise HTTPException(status_code=400, detail="This web chat has ended.")
    return ok(data=msg, message="Reply sent")


class TypingBody(BaseModel):
    lead_id: str = Field(..., min_length=1, max_length=64)


@router.post("/conversations/webchat/typing")
def webchat_rep_typing(payload: TypingBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    """WEBCHAT-CONTACT-1d: the inbox tells the visitor's page that a team member is writing (sent every few seconds while typing)."""
    if wc.rate_limited(f"reptype:{org['org_id']}:{payload.lead_id}", 40, 60):
        return ok(data={})
    lead = (db.table("leads").select("id").eq("id", payload.lead_id).eq("org_id", org["org_id"])
            .is_("deleted_at", "null").limit(1).execute().data)
    if lead:
        wc.rep_typing(db, org["org_id"], payload.lead_id)
    return ok(data={})


@router.get("/conversations/webchat/typing")
def webchat_visitor_typing(lead_id: str = Query(..., min_length=1, max_length=64), db=Depends(get_supabase), org=Depends(get_current_org)):
    """WEBCHAT-CONTACT-1e: is the visitor of this lead's web chat typing right now? (the open inbox window asks every few seconds)"""
    s = wc.latest_session_for_lead(db, org["org_id"], lead_id)      # only ever this business's own chats
    return ok(data={"typing": bool(s and s.get("status") == "active" and wc.visitor_is_typing(s))})


# ── ORDER-PAID-1: the order a customer placed in this chat, and marking it paid ────────────────────────────

class OrderLead(BaseModel):
    lead_id: str = Field(..., min_length=1, max_length=64)


def _lead_of_org(db, org: dict, lead_id: str) -> None:
    lead = (db.table("leads").select("id").eq("id", lead_id).eq("org_id", org["org_id"]).is_("deleted_at", "null").limit(1).execute().data)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")


@router.get("/conversations/webchat/order")
def webchat_order(lead_id: str = Query(..., min_length=1, max_length=64), db=Depends(get_supabase), org=Depends(get_current_org)):
    from app.services import webchat_order_service as orders
    _lead_of_org(db, org, lead_id)
    return ok(data={"order": orders.order_view(db, org["org_id"], lead_id)})


@router.post("/conversations/webchat/order/mark-paid")
def webchat_order_mark_paid(payload: OrderLead, db=Depends(get_supabase), org=Depends(get_current_org)):
    from app.services import webchat_order_service as orders
    _lead_of_org(db, org, payload.lead_id)
    try:
        view = orders.mark_paid(db, org["org_id"], payload.lead_id, org["id"], org.get("full_name") or org.get("name") or "")
    except LookupError:
        raise HTTPException(status_code=422, detail="There is no order waiting in this chat.")
    except ValueError:
        raise HTTPException(status_code=409, detail="This order is already marked as paid.")
    return ok(data={"order": view}, message="Marked as paid")


# ── WEBCHAT-STAFF-1: staff send files, edit and delete their own web chat messages ─────────────────────────────

def _session_of_message(db, org_id: str, mid: str) -> Optional[dict]:
    """The web chat a message belongs to, found inside this business only (S1)."""
    import re
    if not isinstance(mid, str) or not re.match(r"^[0-9a-fA-F-]{36}$", mid):
        return None
    row = wc._one((db.table("whatsapp_messages").select("webchat_session_id").eq("id", mid).eq("org_id", org_id)
                   .eq("channel", "webchat").limit(1).execute()).data)
    if not row or not row.get("webchat_session_id"):
        return None
    return wc._one((db.table("webchat_sessions").select("*").eq("id", row["webchat_session_id"])
                    .eq("org_id", org_id).limit(1).execute()).data)


@router.post("/conversations/webchat/upload")
def upload_webchat_file(lead_id: str = Form(..., max_length=36), kind: str = Form(...),
                        reply_to: Optional[str] = Form(default=None, max_length=36),
                        file: UploadFile = File(...), db=Depends(get_supabase), org=Depends(get_current_org)):
    """A team member sends a photo, document or voice note into a web chat. The file's real type is checked from its bytes."""
    from app.services import webchat_attachment_service as att
    lead = (db.table("leads").select("id").eq("id", lead_id).eq("org_id", org["org_id"])
            .is_("deleted_at", "null").limit(1).execute().data)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    s = wc.latest_session_for_lead(db, org["org_id"], lead_id)
    if not s:
        raise HTTPException(status_code=422, detail="This contact has no web chat to reply to.")
    if s.get("status") != "active":
        raise HTTPException(status_code=400, detail="This web chat has ended.")
    if wc.rate_limited(f"repupload:{org['id']}", 30, 600):
        raise HTTPException(status_code=429, detail="That is a lot of files. Please wait a few minutes.")
    data = file.file.read(att.MAX_ANY + 1)
    clean, err = att.validate(data, kind, file.filename)
    if err:
        raise HTTPException(status_code=422, detail=err)
    try:
        msg = att.save_attachment(db, s, kind, clean, data, sent_by=org["id"], reply_to=reply_to)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="We could not save the file. Please try again.")
    now = wc._iso(wc._now())
    wc.set_state(db, s, human=True, rep_last_at=now, human_at=now)
    try:
        from app.services import webchat_followup_service as fu
        fu.notify_rep_reply(db, s, wc.get_config(db, org["org_id"]), f"Sent you {att.label(kind)}")
    except Exception as exc:
        logger.warning("webchat rep file follow-up failed: %s", exc)
    return ok(data=msg, message="File sent")


@router.patch("/conversations/webchat/message/{message_id}")
def edit_webchat_message(message_id: str, payload: WebchatEdit, db=Depends(get_supabase), org=Depends(get_current_org)):
    from app.services import webchat_msg_service as msgs
    s = _session_of_message(db, org["org_id"], message_id)
    if not s:
        raise HTTPException(status_code=404, detail="Message not found")
    out, err = msgs.edit(db, s, message_id, payload.message, role="rep", user_id=org["id"])
    if err:
        raise HTTPException(status_code=422, detail=err)
    return ok(data=out, message="Message edited")


@router.delete("/conversations/webchat/message/{message_id}")
def delete_webchat_message(message_id: str, db=Depends(get_supabase), org=Depends(get_current_org)):
    from app.services import webchat_msg_service as msgs
    s = _session_of_message(db, org["org_id"], message_id)
    if not s:
        raise HTTPException(status_code=404, detail="Message not found")
    out, err = msgs.delete(db, s, message_id, role="rep", user_id=org["id"])
    if err:
        raise HTTPException(status_code=422, detail=err)
    return ok(data=out, message="Message deleted")


@router.get("/webchat/settings")
def get_settings(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    cfg = wc.get_config(db, org["org_id"])
    key = wc.get_or_create_key(db, org["org_id"])
    return ok({"config": cfg, "key": key, "link": f"{wc.public_base()}/c/{key}",
               "links": {s: f"{wc.public_base()}/c/{key}?s={s}" for s in ("instagram", "qr", "site", "facebook", "google", "whatsapp_status", "email", "sms")},
               "ad_images": {c["tag"]: wc.ad_image_url(org["org_id"], c.get("image")) for c in (cfg.get("campaigns") or []) if c.get("image")},
               "ad_videos": {c["tag"]: wc.ad_video_url(org["org_id"], c.get("video")) for c in (cfg.get("campaigns") or []) if c.get("video")},
               "embed": {"tag": embed.script_tag(wc.public_base(), key), "seen": embed.seen_list(db, org["org_id"])}})


@router.get("/webchat/products")
def ad_products(db=Depends(get_supabase), org=Depends(get_current_org)):
    """AD-PRODUCT-1: the business's catalogue products (id, title, price) for the 'Product this ad is about' picker in the ad settings."""
    _require_manager(org)
    from app.services import webchat_shop_service as shop
    rows = shop._fetch_all(db, org["org_id"])
    rows = sorted(rows, key=lambda r: str(r.get("title") or "").lower())[:300]
    return ok({"products": [{"id": str(r["id"]), "title": str(r.get("title") or "")[:80], "price": shop._num(r.get("price"))} for r in rows]})


@router.get("/webchat/embed-seen")
def embed_seen(db=Depends(get_supabase), org=Depends(get_current_org)):
    """WEBCHAT-EMBED-2: websites that have loaded the bubble, newest first (powers 'Check installation')."""
    _require_manager(org)
    return ok({"seen": embed.seen_list(db, org["org_id"])})


class EmbedEmail(BaseModel):
    to_email: str = Field(max_length=200)
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/webchat/embed-email")
def embed_email(body: EmbedEmail, db=Depends(get_supabase), org=Depends(get_current_org)):
    """WEBCHAT-EMBED-2: email the install instructions and code to the person who looks after the website.
    The owner types the address and presses Send; only the instructions go out, nothing about customers."""
    _require_manager(org)
    to = (body.to_email or "").strip().lower()
    if not wc._EMAIL_RE.match(to):
        raise HTTPException(status_code=422, detail="That email address does not look right.")
    if wc.rate_limited(f"embedmail:{org['org_id']}", 5, 3600):
        raise HTTPException(status_code=429, detail="Too many emails. Try again in an hour.")
    cfg = wc.get_config(db, org["org_id"])
    key = wc.get_or_create_key(db, org["org_id"])
    subject, text = embed.install_email(cfg["business_name"], body.note or "", embed.script_tag(wc.public_base(), key),
                                        f"{wc.public_base()}/c/{key}")
    from app.services.site_addon_billing_service import _send_email
    if not _send_email(to, subject, text):
        raise HTTPException(status_code=503, detail="The email could not be sent right now. Please try again, or copy the code yourself.")
    return ok({"sent": True}, message="Instructions sent")


@router.post("/webchat/ad-image")
def upload_ad_image(file: UploadFile = File(...), db=Depends(get_supabase), org=Depends(get_current_org)):
    """OPENING-CTA-5: the picture for one ad. A real JPG, PNG or WebP (checked from its bytes) up to 5 MB; returns the key to save on the ad."""
    import uuid
    from app.services import webchat_attachment_service as att
    _require_manager(org)
    if wc.rate_limited(f"adimg:{org['org_id']}", 20, 3600):
        raise HTTPException(status_code=429, detail="That is a lot of pictures. Please wait a few minutes.")
    data = file.file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="That picture is over 5 MB. Choose a smaller one.")
    sniffed = att._sniff(data, "image", file.filename or "")
    if not sniffed or sniffed[1] not in ("jpg", "png", "webp"):
        raise HTTPException(status_code=422, detail="Use a JPG, PNG or WebP picture.")
    mime, ext = sniffed
    key = f"{uuid.uuid4().hex}.{ext}"
    try:
        db.storage.from_("catalog").upload(path=f"{org['org_id']}/webchat-ads/{key}", file=data, file_options={"content-type": mime, "upsert": "false"})
    except Exception as exc:
        logger.warning("webchat ad image upload failed org=%s: %s", org["org_id"], exc)
        raise HTTPException(status_code=503, detail="We could not save the picture. Please try again.")
    return ok({"image": key, "url": wc.ad_image_url(org["org_id"], key)})


@router.post("/webchat/ad-video")
def upload_ad_video(file: UploadFile = File(...), db=Depends(get_supabase), org=Depends(get_current_org)):
    """OPENING-CTA-6: the video for one ad. A real MP4 or WebM (checked from its bytes) up to 25 MB; returns the key to save on the ad."""
    import uuid
    _require_manager(org)
    if wc.rate_limited(f"advid:{org['org_id']}", 10, 3600):
        raise HTTPException(status_code=429, detail="That is a lot of videos. Please wait a few minutes.")
    data = file.file.read(wc.AD_VIDEO_MAX_BYTES + 1)
    if len(data) > wc.AD_VIDEO_MAX_BYTES:
        raise HTTPException(status_code=422, detail="That video is over 25 MB. Export a shorter or smaller one.")
    sniffed = wc.sniff_video(data)
    if not sniffed:
        raise HTTPException(status_code=422, detail="Use an MP4 or WebM video.")
    mime, ext = sniffed
    key = f"{uuid.uuid4().hex}.{ext}"
    try:
        db.storage.from_("catalog").upload(path=f"{org['org_id']}/webchat-ads/{key}", file=data, file_options={"content-type": mime, "upsert": "false"})
    except Exception as exc:
        logger.warning("webchat ad video upload failed org=%s: %s", org["org_id"], exc)
        raise HTTPException(status_code=503, detail="We could not save the video. It may be too large for storage; try a smaller one.")
    return ok({"video": key, "url": wc.ad_video_url(org["org_id"], key)})


@router.put("/webchat/settings")
def put_settings(changes: dict, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok(wc.save_config(db, org["org_id"], changes))


@router.post("/webchat/settings/template")
def apply_template(body: TemplateBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    from app.services import webchat_smart_service as smart
    chosen = smart.STARTERS.get(body.template)
    if not chosen:
        raise HTTPException(status_code=422, detail="Pick one of the starter menus.")
    return ok(wc.save_config(db, org["org_id"], {"menu": chosen["menu"], "opening": chosen.get("opening") or {"style": "list"}}))      # OPENING-CTA-1: a starter also sets the two-button first screen


@router.get("/webchat/starters")
def starters(org=Depends(get_current_org)):
    _require_manager(org)
    from app.services import webchat_smart_service as smart
    return ok(smart.starter_list())


@router.get("/webchat/checklist")
def checklist(db=Depends(get_supabase), org=Depends(get_current_org)):
    """SMART-1: what is still missing for Chioma to be useful (menu, keywords, hours, number, address, booking, unanswered)."""
    _require_manager(org)
    from app.services import knowledge_gap_service as kg
    from app.services import webchat_smart_service as smart
    try:
        open_n = len(kg.list_open(db, org["org_id"]))
    except Exception:
        open_n = 0
    return ok(smart.checklist(wc.get_config(db, org["org_id"]), open_n))


@router.get("/webchat/unanswered")
def unanswered(db=Depends(get_supabase), org=Depends(get_current_org)):
    """SMART-1: typed questions Chioma could not answer, with a suggested keyword for each."""
    _require_manager(org)
    from app.services import knowledge_gap_service as kg
    from app.services import webchat_smart_service as smart
    rows = kg.list_open(db, org["org_id"])
    for r in rows:
        r["suggest"] = smart.suggest_keyword(r.get("question") or "")
    return ok(rows[:50])


@router.post("/webchat/unanswered/{gap_id}/teach")
def teach_unanswered(gap_id: str, body: TeachBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    from app.services import webchat_smart_service as smart
    try:
        return ok(smart.teach(db, org["org_id"], gap_id, body.menu_id, body.keyword))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/webchat/unanswered/{gap_id}/dismiss")
def dismiss_unanswered(gap_id: str, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    from app.services import knowledge_gap_service as kg
    return ok(kg.dismiss(db, org["org_id"], gap_id))


@router.post("/webchat/settings/test-whatsapp")
def test_whatsapp(body: TestWhatsapp, db=Depends(get_supabase), org=Depends(get_current_org)):
    """Send the approved template once to a phone number, to check it works. Costs one Meta message."""
    _require_manager(org)
    if wc.rate_limited(f"watest:{org['org_id']}", 3, 3600):
        raise HTTPException(status_code=429, detail="Too many test messages. Try again in an hour.")
    from app.services import webchat_whatsapp_service as wa
    res = wa.send_test(db, org["org_id"], wc.get_config(db, org["org_id"]), body.phone)
    if res.get("error"):
        raise HTTPException(status_code=422, detail=res["error"])
    return ok(data=res, message="Test message sent")


@router.get("/webchat/stats")
def stats(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    rows = (db.table("webchat_events").select("kind").eq("org_id", org["org_id"]).gte("created_at", since)
            .limit(20000).execute().data or [])
    counts: dict = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return ok({"days": 30, "counts": counts})


@router.get("/webchat/analytics")
def analytics(days: int = Query(default=30, ge=1, le=90), db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    _require_plan(db, org, "webchat_insights")
    from app.services import webchat_analytics_service as an
    return ok(an.analytics(db, org["org_id"], days))


@router.get("/webchat/qr.svg")
def qr_svg(s: str = Query(default="qr", max_length=30), download: bool = False, db=Depends(get_supabase),
           org=Depends(get_current_org)):
    """QR code for this business's chat link, tagged with a source so the funnel shows where scans came from."""
    _require_manager(org)
    _require_plan(db, org, "webchat_insights")
    import io
    import segno
    key = wc.get_or_create_key(db, org["org_id"])
    tag = wc.clean_source(s)
    link = f"{wc.public_base()}/c/{key}?s={tag}"
    buf = io.BytesIO()
    segno.make(link, error="m").save(buf, kind="svg", scale=10, border=2, dark="#0F1733", xmldecl=False)
    headers = {"Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="chat-qr-{tag}.svg"'
    return Response(content=buf.getvalue(), media_type="image/svg+xml", headers=headers)
