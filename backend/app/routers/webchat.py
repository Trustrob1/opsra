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
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
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


class TestWhatsapp(BaseModel):
    phone: str = Field(..., min_length=7, max_length=30)


class TemplateBody(BaseModel):
    template: Literal["salon"]


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
        msg = wc.rep_send(db, org["org_id"], payload.lead_id, payload.message, org["id"])
    except LookupError:
        raise HTTPException(status_code=422, detail="This contact has no web chat to reply to.")
    except PermissionError:
        raise HTTPException(status_code=400, detail="This web chat has ended.")
    return ok(data=msg, message="Reply sent")


@router.get("/webchat/settings")
def get_settings(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    cfg = wc.get_config(db, org["org_id"])
    key = wc.get_or_create_key(db, org["org_id"])
    return ok({"config": cfg, "key": key, "link": f"{wc.public_base()}/c/{key}",
               "links": {s: f"{wc.public_base()}/c/{key}?s={s}" for s in ("instagram", "qr", "site")}})


@router.put("/webchat/settings")
def put_settings(changes: dict, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok(wc.save_config(db, org["org_id"], changes))


@router.post("/webchat/settings/template")
def apply_template(body: TemplateBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok(wc.save_config(db, org["org_id"], SALON_TEMPLATE))


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
