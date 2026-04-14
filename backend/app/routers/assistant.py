"""
app/routers/assistant.py
--------------------------
Aria AI Assistant routes (M01-10b).

Routes (all under /api/v1 prefix):
  GET  /briefing              — check if morning briefing should be shown
  POST /briefing/seen         — mark briefing as seen for today
  POST /assistant/message     — streaming Haiku chat (SSE: text/event-stream)
  GET  /assistant/history     — last 20 messages for the authenticated user

Security:
  S1  — org_id from JWT only (via get_current_org)
  S2  — get_current_org as dependency (Pattern 28)
  S3  — Pydantic validation on MessageRequest
  S4  — max 5 000 chars on message body
  S6  — _sanitise_for_prompt() applied before AI injection
  S7  — user content in XML delimiters
  S8  — security rules in every system prompt
  Pattern 53 — static routes (/briefing, /briefing/seen) declared first

Pattern: db is ALWAYS injected via Depends(get_supabase) — never called
directly inside the function body, so integration test overrides work.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date

import anthropic
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.services.assistant_service import (
    HAIKU_MODEL,
    MAX_TOKENS,
    _sanitise_for_prompt,
    _wrap_user_content,
    build_chat_payload,
    get_briefing_status,
    get_history,
    mark_briefing_seen,
    store_message,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Pydantic models ──────────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5_000)  # S3, S4


# ─── GET /briefing ────────────────────────────────────────────────────────────
# Pattern 53: static routes BEFORE any parameterised routes

@router.get("/briefing")
async def check_briefing(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Return {show: bool, content: str|None}.
    Frontend auto-opens Aria panel when show == true.
    """
    user_id = org["id"]   # get_current_org returns "id" not "user_id"

    status_payload = get_briefing_status(db, user_id)
    return {"success": True, "data": status_payload}


# ─── POST /briefing/seen ──────────────────────────────────────────────────────

@router.post("/briefing/seen")
async def seen_briefing(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Mark today's briefing as seen. Prevents re-showing on refresh."""
    user_id = org["id"]   # get_current_org returns "id" not "user_id"

    mark_briefing_seen(db, user_id)
    return {"success": True}


# ─── POST /assistant/message (SSE streaming) ─────────────────────────────────

@router.post("/assistant/message")
async def post_message(
    body: MessageRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Accept a user message and stream the Aria reply via SSE.

    Response: text/event-stream
      data: {"text": "<chunk>"}  — one or more times
      data: [DONE]               — stream complete

    The user message and full AI response are stored in assistant_messages.
    """
    org_id        = org["org_id"]
    user_id       = org["id"]                 # get_current_org returns "id" not "user_id"
    role_template = org["roles"]["template"]  # Pattern 37

    # S6 — sanitise before any storage or AI injection
    clean_text = _sanitise_for_prompt(body.message)

    # Store user message first
    store_message(db, org_id, user_id, "user", clean_text)

    # Build system prompt + messages list
    system_prompt, messages = build_chat_payload(
        db, org_id, user_id, role_template, clean_text
    )

    api_key = os.getenv("ANTHROPIC_API_KEY", "")

    async def sse_generator():
        full_text: list[str] = []
        try:
            async with anthropic.AsyncAnthropic(api_key=api_key) as client:
                async with client.messages.stream(
                    model=HAIKU_MODEL,
                    max_tokens=MAX_TOKENS,
                    system=system_prompt,
                    messages=messages,
                ) as stream:
                    async for chunk in stream.text_stream:
                        full_text.append(chunk)
                        yield f"data: {json.dumps({'text': chunk})}\n\n"

        except Exception as exc:
            logger.error("assistant stream error for user %s: %s", user_id, exc)
            error_msg = "I'm having trouble responding right now. Please try again."
            yield f"data: {json.dumps({'text': error_msg})}\n\n"
            full_text = [error_msg]

        finally:
            # Persist the complete AI response using the injected db
            if full_text:
                complete = "".join(full_text)
                try:
                    store_message(db, org_id, user_id, "assistant", complete)
                except Exception as exc:
                    logger.error("assistant: failed to store AI response — %s", exc)

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",   # Prevent nginx buffering
        },
    )


# ─── GET /assistant/history ───────────────────────────────────────────────────

@router.get("/assistant/history")
async def get_assistant_history(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Return the last 20 messages for the authenticated user."""
    org_id  = org["org_id"]
    user_id = org["id"]   # get_current_org returns "id" not "user_id"

    messages = get_history(db, org_id, user_id)
    return {"success": True, "data": messages}