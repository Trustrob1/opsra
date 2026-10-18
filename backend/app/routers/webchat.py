"""
app/routers/webchat.py
----------------------
WEBCHAT-1/2 — staff routes (login required). Prefix: /api/v1

  POST /conversations/webchat/send   a rep's reply into a web chat (stored only; no Meta call, no fee)
  GET  /webchat/settings             settings + the chat link and key (owner / ops_manager)
  PUT  /webchat/settings             change settings (validated; unknown keys dropped)
  POST /webchat/settings/template    fill the menu from a starter template (salon) — answers are placeholders to edit
  GET  /webchat/stats                visits → started → contact → booked, last 30 days
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
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


class TemplateBody(BaseModel):
    template: Literal["salon"]


def _require_manager(org: dict) -> None:
    role = ((org.get("roles") or {}).get("template") or "").lower()
    if role not in ("owner", "ops_manager", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner or an operations manager can change web chat settings.")


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
