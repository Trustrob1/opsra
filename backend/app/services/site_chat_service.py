"""
app/services/site_chat_service.py
----------------------------------
SITE-1B — the WhatsApp side of the site engine ("site_builder" wa_sales_mode).
Called from routers/webhooks.py._handle_inbound_message, mirroring the
ai_agent / event_funnel per-number intercept pattern (spec §7.1).

Covers spec §7.2 (member gate + main menu), §7.3 (brief-form links only —
the form itself is served by routers/public_forms.py), §7.4 (chat questions,
the backup path to the form), §7.5 (commands) and §7.6 (photos, backup-path
only — form photo uploads go through public_forms.py).

Not in this pass (see SITE-1B_Edits.md):
  • §7.7 timers (beat jobs) — a later pass, once celery_app.py is touched.
  • DESIGN / HOST — depend on SITE-2 (AI design) / SITE-3 (checkout), not
    built yet; both reply with a short "not yet" message.
  • Free-text change requests while `reviewing` going to a classifier — SITE-2.

SITE-2B (this pass): EDIT mints a site_editor_tokens magic link and sends it
— see _send_editor_link(). The link opens the builder portal, whose own auth
and routes live entirely in routers/builder_portal.py / services/
builder_auth_service.py, not here.

S14: this module must never raise past handle_inbound(); the caller
(webhooks.py) also wraps the call, but every DB/network step here is its
own try/except so one bad step doesn't take out the whole conversation.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.models.sites import generate_form_token, slugify_business_name

logger = logging.getLogger(__name__)

_MAX_ASSET_BYTES = 8 * 1024 * 1024
_ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
_FORM_EXPIRY_DAYS = 14
_UNKNOWN_REPLY_THROTTLE_HOURS = 24

_SYNTHETIC_NAME_STEP = {
    "key": "business_name", "prompt": "What's the business name?",
    "type": "text", "required": True, "max_len": 120,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _send_text(db, org_id: str, number_row: dict, sender_phone: str, text: str, lead_id: Optional[str] = None) -> None:
    """S14-safe. Reuses the same helper the AI Agent uses for its own replies."""
    try:
        from app.services.whatsapp_service import send_agent_text_message
        send_agent_text_message(
            db=db, org_id=org_id, phone_number=sender_phone, lead_id=lead_id,
            message=text, phone_id=number_row.get("phone_id"), access_token=number_row.get("access_token"),
        )
    except Exception:
        logger.exception("[SITE-1B] _send_text failed org=%s phone=%s", org_id, sender_phone)


def _save_inbound_message(db, org_id: str, lead_id: Optional[str], msg_type: str, content: Optional[str], msg_id: str) -> None:
    """Best-effort — so site-builder conversations still show up in Opsra's inbox,
    mirroring the ai_agent/event_funnel blocks in webhooks.py."""
    try:
        db.table("whatsapp_messages").insert({
            "org_id": org_id, "lead_id": lead_id,
            "direction": "inbound", "message_type": msg_type,
            "channel": "whatsapp", "content": content,
            "status": "delivered", "meta_message_id": msg_id or None,
            "window_open": True, "window_expires_at": (_now() + timedelta(hours=24)).isoformat(),
            "sent_by": None, "created_at": _now_iso(),
        }).execute()
    except Exception as exc:
        logger.warning("[SITE-1B] message save failed org=%s: %s", org_id, exc)


def _notify_owner(db, org_id: str, text: str) -> None:
    """Best-effort ping to the org owner's own WhatsApp number — used for the
    'new builder waiting' and 'HUMAN requested' notices (spec §7.2/§7.5)."""
    try:
        org_row = _one((db.table("organisations").select("org_business_contact_number")
                         .eq("id", org_id).execute()).data)
        owner_phone = (org_row or {}).get("org_business_contact_number")
        if not owner_phone:
            return
        from app.services.whatsapp_service import _get_org_wa_credentials, _call_meta_send
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        if phone_id and access_token:
            _call_meta_send(phone_id, {
                "messaging_product": "whatsapp", "to": owner_phone,
                "type": "text", "text": {"body": text},
            }, token=access_token)
    except Exception:
        logger.exception("[SITE-1B] _notify_owner failed org=%s", org_id)


def _get_settings(db, org_id: str) -> Optional[dict]:
    return _one((db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data)


def _get_builder(db, org_id: str, phone_number: str) -> Optional[dict]:
    return _one((db.table("site_builders").select("*").eq("org_id", org_id).eq("phone_number", phone_number).limit(1).execute()).data)


def _get_or_create_chat(db, org_id: str, phone_number: str, builder_id: Optional[str]) -> dict:
    row = _one((db.table("site_chats").select("*").eq("org_id", org_id).eq("phone_number", phone_number).limit(1).execute()).data)
    if row:
        return row
    new_row = {
        "org_id": org_id, "phone_number": phone_number, "builder_id": builder_id,
        "state": "menu", "reminder_count": 0, "opted_out": False,
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    res = db.table("site_chats").insert(new_row).execute()
    return _one(res.data) or new_row


def _update_chat(db, chat: dict, updates: dict) -> dict:
    updates = dict(updates)
    updates["updated_at"] = _now_iso()
    db.table("site_chats").update(updates).eq("id", chat["id"]).execute()
    chat.update(updates)
    return chat


def _active_presets(db, org_id: str) -> list[dict]:
    return (db.table("site_presets").select("*").eq("org_id", org_id).eq("is_active", True)
            .order("name").limit(10).execute()).data or []


def _list_active_image_mime(mime: str) -> bool:
    return mime in _ALLOWED_IMAGE_MIME


# ─────────────────────────────── Menu / reply text ───────────────────────────────

def _menu_text(builder: dict) -> str:
    name = (builder.get("full_name") or "").split(" ")[0] or "there"
    return (
        f"Hi {name}! What would you like to do?\n\n"
        "1. Start a new site\n"
        "2. My sites\n"
        "3. Talk to a person\n\n"
        "You can also type MENU, MY SITES, STATUS or HUMAN at any time."
    )


def _new_site_options_text() -> str:
    return (
        "How would you like to start?\n\n"
        "1. Fill the form myself\n"
        "2. Get a link for my client to fill in\n"
        "3. Answer here on WhatsApp\n\n"
        "Reply with 1, 2 or 3 (or MENU to go back)."
    )


def _preset_list_text(presets: list[dict]) -> str:
    lines = ["What kind of business is this for?", ""]
    for i, p in enumerate(presets, start=1):
        lines.append(f"{i}. {p['name']}")
    lines.append("")
    lines.append("Reply with a number (or MENU to go back).")
    return "\n".join(lines)


# ─────────────────────────────── Brief form links ───────────────────────────────

def _create_brief_form(db, org_id: str, builder: dict, audience: str, preset_id: Optional[str] = None,
                        client_label: Optional[str] = None) -> tuple[dict, str]:
    raw_token, token_hash = generate_form_token()
    row = {
        "org_id": org_id, "builder_id": builder["id"], "audience": audience,
        "token_hash": token_hash, "preset_id": preset_id, "answers": {},
        "status": "open", "expires_at": (_now() + timedelta(days=_FORM_EXPIRY_DAYS)).isoformat(),
        "client_label": (client_label or "").strip()[:120] or None,
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    res = db.table("site_brief_forms").insert(row).execute()
    return (_one(res.data) or row), raw_token


def _form_url(settings: dict, raw_token: str) -> str:
    # Per spec §7.3, the form lives on the FRONTEND at /f/{token} — a separate
    # host from the preview_base_url (which is the backend preview host).
    import os
    frontend_base = os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/")
    return f"{frontend_base}/f/{raw_token}"


def _send_form_link(db, org_id: str, number_row: dict, sender_phone: str, builder: dict, settings: dict,
                     audience: str, preset_id: Optional[str] = None) -> None:
    form, raw_token = _create_brief_form(db, org_id, builder, audience, preset_id=preset_id)
    url = _form_url(settings, raw_token)
    if audience == "client":
        text = (
            "Here's a link to send your client — they can fill it in on their own phone, "
            "no login needed:\n\n" + url +
            "\n\nWe'll message you here as soon as they submit it."
        )
    else:
        text = (
            "Here's your form link — fill it in whenever you're ready, it saves as you go:\n\n" + url
        )
    _send_text(db, org_id, number_row, sender_phone, text, lead_id=builder.get("lead_id"))


# ─────────────────────────────── Editor magic link (SITE-2B) ───────────────────────────────

_EDITOR_LINK_EXPIRY_DAYS = 7   # spec §10


def _editor_url(raw_token: str) -> str:
    import os
    frontend_base = os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/")
    return f"{frontend_base}/b/login?t={raw_token}"


def _send_editor_link(db, org_id: str, number_row: dict, sender_phone: str, builder: dict) -> None:
    """EDIT — mints a single-use, 7-day site_editor_tokens row (same hashed-token
    shape as brief forms, spec §18) and sends the builder-portal magic link."""
    if builder.get("status") != "active":
        _send_text(db, org_id, number_row, sender_phone,
                    "Your account isn't active right now — reply HUMAN to talk to someone.", lead_id=builder.get("lead_id"))
        return
    raw_token, token_hash = generate_form_token()
    db.table("site_editor_tokens").insert({
        "org_id": org_id, "builder_id": builder["id"], "token_hash": token_hash,
        "expires_at": (_now() + timedelta(days=_EDITOR_LINK_EXPIRY_DAYS)).isoformat(),
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }).execute()
    url = _editor_url(raw_token)
    text = f"Here's your editor link — it works for 7 days and signs you in automatically:\n\n{url}"
    _send_text(db, org_id, number_row, sender_phone, text, lead_id=builder.get("lead_id"))


# ─────────────────────────────── Chat-question backup path ───────────────────────────────

def _steps_for_preset(preset: dict) -> list[dict]:
    # SITE-1C-2: the personality question is added for every template that doesn't define its own.
    from app.services import site_design_registry
    return [_SYNTHETIC_NAME_STEP] + site_design_registry.with_personality_question(preset.get("brief_questions"))


def _find_step(steps: list[dict], key: Optional[str]) -> Optional[dict]:
    if not key:
        return steps[0] if steps else None
    for s in steps:
        if s.get("key") == key:
            return s
    return None


def _next_step(steps: list[dict], current_key: Optional[str]) -> Optional[dict]:
    keys = [s.get("key") for s in steps]
    if current_key not in keys:
        return steps[0] if steps else None
    idx = keys.index(current_key)
    return steps[idx + 1] if idx + 1 < len(steps) else None


def _question_prompt(step: dict) -> str:
    prompt = step.get("prompt") or step.get("key")
    if step.get("type") == "choice" and step.get("choices"):
        lines = [prompt, ""]
        for i, c in enumerate(step["choices"], start=1):
            lines.append(f"{i}. {c}")
        return "\n".join(lines)
    if step.get("type") == "photos":
        return f"{prompt}\n\nSend one photo at a time. Reply DONE when you've sent them all."
    if step.get("type") == "items":
        return (f"{prompt}\n\nSend one item per message, as: Name - Price - Description\n"
                f"Reply DONE when you've added them all.")
    if step.get("skip_ok"):
        return f"{prompt}\n\n(Reply SKIP to skip this one.)"
    return prompt


def _start_chat_brief(db, org_id: str, chat: dict, builder: dict, preset: dict) -> dict:
    """Creates the `sites` row up front (status=brief_in_progress) so that photos have
    somewhere to attach as soon as they arrive — see module docstring."""
    slug = slugify_business_name("pending") + "-" + preset["key"][:6]
    # extremely unlikely collision guard
    if (db.table("sites").select("id").eq("slug", slug).execute()).data:
        import secrets as _s
        slug = f"{slug}-{_s.token_hex(3)}"
    site_row = {
        "org_id": org_id, "builder_id": builder["id"], "chat_id": chat["id"],
        "preset_id": preset["id"], "client_business_name": "(pending)", "slug": slug,
        "status": "brief_in_progress", "brief": {}, "revision_count": 0,
        "ai_generation_count": 0, "design_rolls": 0,
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    res = db.table("sites").insert(site_row).execute()
    site = _one(res.data) or site_row
    steps = _steps_for_preset(preset)
    return _update_chat(db, chat, {
        "active_site_id": site["id"], "draft_preset_id": preset["id"], "draft_answers": {},
        "step_key": steps[0]["key"], "state": "briefing",
    })


def _finish_chat_brief(db, org_id: str, chat: dict, site: dict) -> None:
    business_name = (chat.get("draft_answers") or {}).get("business_name") or site.get("client_business_name")
    from app.services import site_renderer
    new_slug = site_renderer.generate_slug(business_name or "site")
    brief = chat.get("draft_answers") or {}
    db.table("sites").update({
        "client_business_name": (business_name or "Untitled business")[:255],
        "slug": new_slug, "status": "brief_complete",
        "brief": brief, "updated_at": _now_iso(),
    }).eq("id", site["id"]).execute()

    # SITE-2: generate content/recipe now that the brief (and any chat-path photos) are
    # in. Own try/except — S14, must never break the chat flow that called us.
    try:
        from app.services import site_copy_service
        preset = _one((db.table("site_presets").select("*").eq("id", site["preset_id"]).execute()).data)
        full_site = _one((db.table("sites").select("*").eq("id", site["id"]).execute()).data)
        if preset and full_site:
            content, recipe, source = site_copy_service.generate_content_and_recipe(db, full_site, preset, org_id)
            site_copy_service.apply_generated_content(db, site["id"], content, recipe, source)
    except Exception:
        logger.exception("[SITE-2] content generation failed site=%s", site.get("id"))

    _update_chat(db, chat, {"state": "reviewing", "step_key": None, "draft_preset_id": None, "draft_answers": {}})


def _handle_briefing_reply(db, org_id: str, number_row: dict, sender_phone: str, builder: dict, chat: dict,
                            msg_type: str, content: Optional[str],
                            image_media_id: Optional[str] = None, image_mime: Optional[str] = None) -> None:
    site = _one((db.table("sites").select("*").eq("id", chat.get("active_site_id")).eq("org_id", org_id).execute()).data)
    if not site:
        _update_chat(db, chat, {"state": "menu", "step_key": None, "active_site_id": None})
        _send_text(db, org_id, number_row, sender_phone, "Something went wrong with that site — let's start again.\n\n" + _menu_text(builder), builder.get("lead_id"))
        return
    preset = _one((db.table("site_presets").select("*").eq("id", site["preset_id"]).execute()).data) or {}
    steps = _steps_for_preset(preset)
    step = _find_step(steps, chat.get("step_key"))
    if not step:
        _finish_chat_brief(db, org_id, chat, site)
        _send_text(db, org_id, number_row, sender_phone,
                    "That's everything — thank you! Your brief is complete and our team will start building your preview.",
                    builder.get("lead_id"))
        return

    answers = dict(chat.get("draft_answers") or {})
    key = step["key"]
    text = (content or "").strip()
    upper = text.upper()

    if step.get("type") == "photos":
        if msg_type != "image":
            if upper == "DONE":
                pass  # fall through to advance
            else:
                _send_text(db, org_id, number_row, sender_phone, "Please send a photo, or reply DONE when finished.", builder.get("lead_id"))
                return
        else:
            file_bytes, detected_mime = (None, None)
            if image_media_id:
                file_bytes, detected_mime = _download_meta_media(number_row.get("access_token"), image_media_id)
            mime = image_mime or detected_mime or "image/jpeg"
            stored = _store_site_photo(db, org_id, site["id"], key, file_bytes, mime) if file_bytes else None
            if not stored:
                _send_text(db, org_id, number_row, sender_phone, "That photo didn't come through — please try sending it again, or reply DONE.", builder.get("lead_id"))
                return
            answers[key] = int(answers.get(key) or 0) + 1
            _update_chat(db, chat, {"draft_answers": answers})
            _send_text(db, org_id, number_row, sender_phone, "Got it! Send another, or reply DONE when finished.", builder.get("lead_id"))
            return
    elif step.get("type") == "items":
        if upper != "DONE":
            parts = [p.strip() for p in text.split("-")]
            if len(parts) < 2:
                _send_text(db, org_id, number_row, sender_phone,
                            "Please use the format: Name - Price - Description (description is optional).", builder.get("lead_id"))
                return
            items = list(answers.get("items") or [])
            max_items = int(preset.get("max_items") or 20)
            if len(items) >= max_items:
                _send_text(db, org_id, number_row, sender_phone, f"You've reached the limit of {max_items} items — reply DONE to continue.", builder.get("lead_id"))
                return
            try:
                price = float(re.sub(r"[^\d.]", "", parts[1]) or 0)
            except ValueError:
                price = 0
            items.append({"name": parts[0][:100], "price_ngn": price, "desc": (parts[2] if len(parts) > 2 else "")[:300]})
            answers["items"] = items
            _update_chat(db, chat, {"draft_answers": answers})
            _send_text(db, org_id, number_row, sender_phone, f"Added \"{parts[0][:60]}\". Send the next item, or reply DONE.", builder.get("lead_id"))
            return
    elif step.get("skip_ok") and upper == "SKIP":
        answers[key] = None
    elif step.get("type") == "choice" and step.get("choices"):
        choices = step["choices"]
        chosen = None
        if text.isdigit() and 1 <= int(text) <= len(choices):
            chosen = choices[int(text) - 1]
        else:
            for c in choices:
                if c.strip().lower() == text.lower():
                    chosen = c
                    break
        if chosen is None:
            _send_text(db, org_id, number_row, sender_phone, "Please reply with one of the numbered options.", builder.get("lead_id"))
            return
        answers[key] = chosen
    else:
        if step.get("required") and not text:
            _send_text(db, org_id, number_row, sender_phone, "Sorry, that one's needed — " + _question_prompt(step), builder.get("lead_id"))
            return
        max_len = int(step.get("max_len") or 500)
        answers[key] = text[:max_len]

    if key == "business_name" and answers.get(key):
        db.table("sites").update({"client_business_name": answers[key][:255], "updated_at": _now_iso()}).eq("id", site["id"]).execute()

    nxt = _next_step(steps, key)
    if nxt is None:
        _update_chat(db, chat, {"draft_answers": answers})
        _finish_chat_brief(db, org_id, chat, site)
        _send_text(db, org_id, number_row, sender_phone,
                    "That's everything — thank you! Your brief is complete and our team will start building your preview.",
                    builder.get("lead_id"))
    else:
        _update_chat(db, chat, {"draft_answers": answers, "step_key": nxt["key"]})
        _send_text(db, org_id, number_row, sender_phone, _question_prompt(nxt), builder.get("lead_id"))


def _download_meta_media(access_token: str, media_id: str) -> tuple[Optional[bytes], Optional[str]]:
    try:
        url_resp = httpx.get(
            f"https://graph.facebook.com/v17.0/{media_id}",
            headers={"Authorization": f"Bearer {access_token}"}, timeout=10,
        )
        url_resp.raise_for_status()
        info = url_resp.json()
        download_url = info.get("url")
        mime = info.get("mime_type")
        if not download_url:
            return None, None
        file_resp = httpx.get(download_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
        file_resp.raise_for_status()
        return file_resp.content, mime
    except Exception as exc:
        logger.warning("[SITE-1B] _download_meta_media failed media_id=%s: %s", media_id, exc)
        return None, None


def _store_site_photo(db, org_id: str, site_id: str, slot: str, file_bytes: bytes, mime: str) -> Optional[dict]:
    if mime not in _ALLOWED_IMAGE_MIME or len(file_bytes) > _MAX_ASSET_BYTES:
        return None
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
    import secrets as _s
    storage_path = f"{site_id}/{slot}-{_s.token_hex(4)}.{ext}"
    try:
        db.storage.from_("site-assets").upload(path=storage_path, file=file_bytes,
                                                file_options={"content-type": mime, "upsert": "true"})
        public_url = db.storage.from_("site-assets").get_public_url(storage_path)
        row = {
            "site_id": site_id, "slot": slot, "storage_path": storage_path, "public_url": public_url,
            "mime_type": mime, "bytes": len(file_bytes), "source": "whatsapp",
            "created_at": _now_iso(), "updated_at": _now_iso(),
        }
        res = db.table("site_assets").insert(row).execute()
        return _one(res.data) or row
    except Exception:
        logger.exception("[SITE-1B] _store_site_photo failed site=%s slot=%s", site_id, slot)
        return None


# ─────────────────────────────── Commands ───────────────────────────────

_COMMANDS = {"MENU", "NEW", "FORM", "MY SITES", "MYSITES", "BACK", "RESTART", "STATUS", "HUMAN", "STOP", "START", "DESIGN", "EDIT", "HOST"}


def _my_sites_text(db, org_id: str, builder_id: str) -> str:
    rows = (db.table("sites").select("client_business_name, status, slug").eq("org_id", org_id)
            .eq("builder_id", builder_id).is_("deleted_at", "null").order("created_at", desc=True).limit(10).execute()).data or []
    if not rows:
        return "You don't have any sites yet. Reply NEW to start one."
    lines = ["Your sites:", ""]
    for r in rows:
        lines.append(f"• {r.get('client_business_name') or 'Untitled'} — {r.get('status')}")
    return "\n".join(lines)


def _status_text(db, org_id: str, chat: dict) -> str:
    if not chat.get("active_site_id"):
        return "You don't have an active site right now. Reply NEW to start one."
    site = _one((db.table("sites").select("client_business_name, status").eq("id", chat["active_site_id"]).eq("org_id", org_id).execute()).data)
    if not site:
        return "You don't have an active site right now. Reply NEW to start one."
    return f"{site.get('client_business_name') or 'Your site'} is currently: {site.get('status')}."


def _handle_command(cmd: str, db, org_id: str, number_row: dict, sender_phone: str, builder: dict,
                     chat: dict, settings: dict) -> bool:
    """Returns True if `cmd` was a recognised command and was handled."""
    lead_id = builder.get("lead_id")
    if cmd in ("MENU",):
        _update_chat(db, chat, {"state": "menu", "step_key": None})
        _send_text(db, org_id, number_row, sender_phone, _menu_text(builder), lead_id)
        return True
    if cmd == "NEW":
        _update_chat(db, chat, {"state": "choose_new_type"})
        _send_text(db, org_id, number_row, sender_phone, _new_site_options_text(), lead_id)
        return True
    if cmd == "FORM":
        _update_chat(db, chat, {"state": "menu"})
        _send_form_link(db, org_id, number_row, sender_phone, builder, settings, "builder")
        return True
    if cmd in ("MY SITES", "MYSITES"):
        _send_text(db, org_id, number_row, sender_phone, _my_sites_text(db, org_id, builder["id"]), lead_id)
        return True
    if cmd == "STATUS":
        _send_text(db, org_id, number_row, sender_phone, _status_text(db, org_id, chat), lead_id)
        return True
    if cmd == "HUMAN":
        _update_chat(db, chat, {"state": "handoff"})
        _send_text(db, org_id, number_row, sender_phone, "Sure — a member of our team will reach out to you here shortly.", lead_id)
        _notify_owner(db, org_id, f"Site Builder: {builder.get('full_name')} ({sender_phone}) asked to talk to a person.")
        return True
    if cmd == "BACK":
        _update_chat(db, chat, {"state": "menu", "step_key": None})
        _send_text(db, org_id, number_row, sender_phone, _menu_text(builder), lead_id)
        return True
    if cmd == "RESTART":
        if chat.get("active_site_id") and chat.get("state") in ("briefing", "choose_preset"):
            db.table("sites").update({"deleted_at": _now_iso()}).eq("id", chat["active_site_id"]).eq("status", "brief_in_progress").execute()
        _update_chat(db, chat, {"state": "menu", "step_key": None, "active_site_id": None, "draft_preset_id": None, "draft_answers": {}})
        _send_text(db, org_id, number_row, sender_phone, "No problem, starting over.\n\n" + _menu_text(builder), lead_id)
        return True
    if cmd == "STOP":
        _update_chat(db, chat, {"opted_out": True})
        _send_text(db, org_id, number_row, sender_phone, "You've been paused — reply START any time to pick back up.", lead_id)
        return True
    if cmd == "START":
        _update_chat(db, chat, {"opted_out": False, "state": "menu"})
        _send_text(db, org_id, number_row, sender_phone, "Welcome back!\n\n" + _menu_text(builder), lead_id)
        return True
    if cmd == "EDIT":
        _send_editor_link(db, org_id, number_row, sender_phone, builder)
        return True
    if cmd in ("DESIGN", "HOST"):
        _send_text(db, org_id, number_row, sender_phone,
                    "That's not switched on here yet — our team can help with this for now. Reply HUMAN to talk to someone.", lead_id)
        return True
    return False


# ─────────────────────────────── Entry point ───────────────────────────────

def handle_inbound(db, number_row: dict, sender_phone: str, contact_name: str, msg_type: str,
                    content: Optional[str], msg_id: str, interactive_payload: Optional[dict] = None,
                    image_media_id: Optional[str] = None, image_mime: Optional[str] = None) -> None:
    org_id = number_row["org_id"]
    settings = _get_settings(db, org_id)
    if not settings or not settings.get("enabled"):
        logger.warning("[SITE-1B] site_builder number but site engine disabled org=%s", org_id)
        return

    builder = _get_builder(db, org_id, sender_phone)
    _save_inbound_message(db, org_id, (builder or {}).get("lead_id"), msg_type, content, msg_id)

    # ── Unknown / not-yet-active builder ────────────────────────────────
    if not builder:
        if settings.get("members_only", True):
            _handle_unknown_number(db, org_id, number_row, sender_phone, settings)
            return
        # Open access — self-register as an active builder on first contact.
        builder = {
            "org_id": org_id, "phone_number": sender_phone, "full_name": contact_name or "there",
            "status": "active", "source": "whatsapp_self_serve", "approved_orders_count": 0,
            "joined_at": _now_iso(),
        }
        res = db.table("site_builders").insert(builder).execute()
        builder = _one(res.data) or builder

    if builder.get("status") in ("suspended", "lapsed"):
        _send_text(db, org_id, number_row, sender_phone,
                    "Your Site Builder access is currently paused. Reply HUMAN and we'll help sort it out.",
                    builder.get("lead_id"))
        return
    if builder.get("status") == "pending":
        _handle_unknown_number(db, org_id, number_row, sender_phone, settings, already_pending=True)
        return

    chat = _get_or_create_chat(db, org_id, sender_phone, builder["id"])
    is_first_chat_message = chat.get("state") == "menu" and not chat.get("last_inbound_at")
    _update_chat(db, chat, {"last_inbound_at": _now_iso()})

    text = (content or "").strip()
    upper = text.upper()

    if chat.get("opted_out") and upper != "START":
        return  # paused — only START wakes it back up (checked inside _handle_command too)

    if upper in _COMMANDS:
        if _handle_command(upper, db, org_id, number_row, sender_phone, builder, chat, settings):
            return

    state = chat.get("state") or "menu"

    if state == "menu":
        if upper in ("1",) or "start" in text.lower() or "new" in text.lower():
            _update_chat(db, chat, {"state": "choose_new_type"})
            _send_text(db, org_id, number_row, sender_phone, _new_site_options_text(), builder.get("lead_id"))
            return
        if upper in ("2",) or "my site" in text.lower():
            _send_text(db, org_id, number_row, sender_phone, _my_sites_text(db, org_id, builder["id"]), builder.get("lead_id"))
            return
        if upper in ("3",) or "human" in text.lower() or "person" in text.lower():
            _handle_command("HUMAN", db, org_id, number_row, sender_phone, builder, chat, settings)
            return
        greeting = _menu_text(builder)
        if is_first_chat_message:
            greeting = ("Welcome to the Opsra Site Builder! " + greeting +
                        "\n\nTip: reply FORM any time for a link you (or your client) can fill in on your own phone.")
        _send_text(db, org_id, number_row, sender_phone, greeting, builder.get("lead_id"))
        return

    if state == "choose_new_type":
        if upper == "1":
            _update_chat(db, chat, {"state": "menu"})
            _send_form_link(db, org_id, number_row, sender_phone, builder, settings, "builder")
        elif upper == "2":
            _update_chat(db, chat, {"state": "menu"})
            _send_form_link(db, org_id, number_row, sender_phone, builder, settings, "client")
        elif upper == "3":
            presets = _active_presets(db, org_id)
            if not presets:
                _send_text(db, org_id, number_row, sender_phone, "There aren't any site types set up yet — reply HUMAN and we'll help.", builder.get("lead_id"))
                _update_chat(db, chat, {"state": "menu"})
                return
            _update_chat(db, chat, {"state": "choose_preset"})
            _send_text(db, org_id, number_row, sender_phone, _preset_list_text(presets), builder.get("lead_id"))
        else:
            _send_text(db, org_id, number_row, sender_phone, "Please reply with 1, 2 or 3.", builder.get("lead_id"))
        return

    if state == "choose_preset":
        presets = _active_presets(db, org_id)
        if not (text.isdigit() and 1 <= int(text) <= len(presets)):
            _send_text(db, org_id, number_row, sender_phone, "Please reply with one of the numbers above (or MENU to go back).", builder.get("lead_id"))
            return
        preset = presets[int(text) - 1]
        chat = _start_chat_brief(db, org_id, chat, builder, preset)
        steps = _steps_for_preset(preset)
        _send_text(db, org_id, number_row, sender_phone, _question_prompt(steps[0]), builder.get("lead_id"))
        return

    if state == "briefing":
        _handle_briefing_reply(db, org_id, number_row, sender_phone, builder, chat, msg_type, content,
                                image_media_id, image_mime)
        return

    if state in ("reviewing", "handoff", "idle"):
        _send_text(db, org_id, number_row, sender_phone,
                    "Your site is with our team right now. Reply MENU for options, or HUMAN to talk to someone.",
                    builder.get("lead_id"))
        return

    # Unknown state — fail safe back to menu.
    _update_chat(db, chat, {"state": "menu", "step_key": None})
    _send_text(db, org_id, number_row, sender_phone, _menu_text(builder), builder.get("lead_id"))


def _handle_unknown_number(db, org_id: str, number_row: dict, sender_phone: str, settings: dict, already_pending: bool = False) -> None:
    """Spec §7.2: one short reply with join_url, recorded as `pending`, Trust notified,
    no AI call, no lead/site created, at most once/day."""
    chat = _get_or_create_chat(db, org_id, sender_phone, None)
    last = chat.get("last_inbound_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if _now() - last_dt < timedelta(hours=_UNKNOWN_REPLY_THROTTLE_HOURS):
                _update_chat(db, chat, {"last_inbound_at": _now_iso()})
                return
        except Exception:
            pass
    _update_chat(db, chat, {"last_inbound_at": _now_iso()})

    if not already_pending:
        try:
            db.table("site_builders").insert({
                "org_id": org_id, "phone_number": sender_phone, "full_name": "Pending builder",
                "status": "pending", "source": "whatsapp", "approved_orders_count": 0, "joined_at": _now_iso(),
            }).execute()
            _notify_owner(db, org_id, f"New Site Builder waiting for approval: {sender_phone}.")
        except Exception:
            logger.exception("[SITE-1B] pending builder insert failed org=%s phone=%s", org_id, sender_phone)

    join_url = settings.get("join_url") or "https://opsra.onrender.com"
    text = ("This number is for registered Opsra Site Builders. "
            f"Join here: {join_url}\n\nSomeone from our team will be in touch.")
    _send_text(db, org_id, number_row, sender_phone, text)
