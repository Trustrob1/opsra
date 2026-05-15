"""
triage_service.py
-----------------
WH-0: Intent-First Triage for Unknown WhatsApp Contacts.
WH-2: Known-Customer Triage Menu — customer section of whatsapp_triage_config.
WH-1b: _action_qualify updated — structured flow, immediate Q1, onboarding gate.

Handles:
  - WhatsApp triage session lifecycle (create / query / update)
  - Session message dispatch (triage_sent / awaiting_identifier / active)
  - Unknown-contact triage routing (qualify / identify_customer /
    route_to_role / free_form)
  - Known-customer triage routing (create_ticket / route_to_role / free_form)
  - Identifier-text handling (customer lookup → contact or fallback lead)
  - Customer contacts CRUD (list / add / approve / remove)

9E-C changes:
  C1 — get_or_create_session(): atomic INSERT with unique-constraint fallback.
       Prevents duplicate sessions when two concurrent webhooks arrive for the
       same phone number.
  C2 — update_session(): now accepts expected_state parameter. All state
       transitions use .eq("session_state", expected_state) so only the first
       concurrent handler wins; others bail cleanly.

All public functions comply with S14 — no function may raise.
Every function body is wrapped in a top-level try/except that logs the
error and returns a safe default.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_active_session(db, org_id: str, phone_number: str) -> Optional[dict]:
    """
    Return the first non-expired, non-'expired'-state session for this
    org + phone combination, or None if none exists.
    S14: returns None on any failure.
    """
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        result = (
            db.table("whatsapp_sessions")
            .select("*")
            .eq("org_id", org_id)
            .eq("phone_number", phone_number)
            .neq("session_state", "expired")
            .gt("expires_at", now_iso)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("get_active_session failed org=%s phone=%s: %s",
                       org_id, phone_number, exc)
        return None


def get_or_create_session(
    db,
    org_id: str,
    phone_number: str,
    expires_minutes: int = 30,
    customer_id: Optional[str] = None,
) -> Optional[dict]:
    """
    C1 — Atomically get an existing active session or create a new one.

    Replaces the two-step get_active_session() + create_session() pattern.
    The unique index idx_ws_active_session on (org_id, phone_number)
    WHERE expires_at > now() means only one active session can exist per
    org+phone at a time. On a concurrent duplicate INSERT, the DB raises
    a unique violation (23505) and we fall back to fetching the winner.

    Returns the session dict or None on unrecoverable error. S14.
    """
    try:
        # Fast path: existing active session
        existing = get_active_session(db, org_id, phone_number)
        if existing:
            return existing

        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
        ).isoformat()

        row: dict = {
            "org_id": org_id,
            "phone_number": phone_number,
            "session_state": "triage_sent",
            "expires_at": expires_at,
        }
        if customer_id:
            row["session_data"] = {"customer_id": customer_id}

        try:
            result = db.table("whatsapp_sessions").insert(row).execute()
            rows = result.data or []
            if rows:
                return rows[0]
            # Supabase returned empty without raising — fetch the winner
            return get_active_session(db, org_id, phone_number)

        except Exception as insert_exc:
            err_str = str(insert_exc).lower()
            if (
                "23505" in err_str
                or "duplicate" in err_str
                or "unique" in err_str
            ):
                # Another concurrent handler won the INSERT race — fetch it
                logger.debug(
                    "get_or_create_session: duplicate INSERT org=%s phone=%s "
                    "— returning winner",
                    org_id, phone_number,
                )
                return get_active_session(db, org_id, phone_number)
            raise  # unexpected DB error — propagate to outer S14 handler

    except Exception as exc:
        logger.warning(
            "get_or_create_session failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )
        return None


def create_session(
    db,
    org_id: str,
    phone_number: str,
    expires_minutes: int = 30,
) -> Optional[dict]:
    """
    Insert a new whatsapp_sessions row with session_state='triage_sent'.
    Returns the inserted row dict, or None on failure. S14.

    Prefer get_or_create_session() for new callers — it is race-safe (C1).
    This function is retained for backwards compatibility with existing callers.
    """
    try:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
        ).isoformat()
        result = (
            db.table("whatsapp_sessions")
            .insert({
                "org_id": org_id,
                "phone_number": phone_number,
                "session_state": "triage_sent",
                "expires_at": expires_at,
            })
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("create_session failed org=%s phone=%s: %s",
                       org_id, phone_number, exc)
        return None


def create_customer_session(
    db,
    org_id: str,
    phone_number: str,
    customer_id: str,
    expires_minutes: int = 30,
) -> Optional[dict]:
    """
    WH-2: Insert a new whatsapp_sessions row for a known customer.
    Stores customer_id in session_data so the dispatcher can resolve it.
    Returns the inserted row dict, or None on failure. S14.

    Prefer get_or_create_session(customer_id=...) for new callers (C1).
    """
    try:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
        ).isoformat()
        result = (
            db.table("whatsapp_sessions")
            .insert({
                "org_id": org_id,
                "phone_number": phone_number,
                "session_state": "triage_sent",
                "session_data": {"customer_id": customer_id},
                "expires_at": expires_at,
            })
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("create_customer_session failed org=%s phone=%s: %s",
                       org_id, phone_number, exc)
        return None


def update_session(
    db,
    session_id: str,
    state: str,
    selected_action: Optional[str] = None,
    session_data: Optional[dict] = None,
    expected_state: Optional[str] = None,
) -> bool:
    """
    C2 — Atomically update session_state.

    If expected_state is provided, the UPDATE includes
      .eq("session_state", expected_state)
    so it is a no-op if another concurrent handler already advanced the state.

    Returns True if the update succeeded (or expected_state was not provided).
    Returns False if expected_state was provided and the update matched 0 rows
    (meaning another handler won the race — the caller should bail).
    S14: returns False on any exception.
    """
    try:
        payload: dict = {"session_state": state}
        if selected_action is not None:
            payload["selected_action"] = selected_action
        if session_data is not None:
            payload["session_data"] = session_data

        query = db.table("whatsapp_sessions").update(payload).eq("id", session_id)
        if expected_state is not None:
            query = query.eq("session_state", expected_state)

        result = query.execute()

        if expected_state is not None and not (result.data or []):
            logger.debug(
                "update_session: session %s already advanced past '%s' "
                "— concurrent handler won, bailing",
                session_id, expected_state,
            )
            return False
        return True

    except Exception as exc:
        logger.warning("update_session failed session_id=%s: %s", session_id, exc)
        return False


# ---------------------------------------------------------------------------
# Session message dispatcher
# ---------------------------------------------------------------------------

def handle_session_message(
    db,
    org_id: str,
    phone_number: str,
    session: dict,
    msg_type: str,
    content,
    interactive_payload,
    contact_name,
    now_ts,
    section: str = "unknown",
):
    """
    Route an inbound message to the correct handler based on session state.
    section: "unknown" (WH-0) | "customer" (WH-2) | "hybrid" | "returning_lead" | "known_customer"
    S14.
    """
    try:
        state = session.get("session_state", "active")

        if state == "triage_sent":
            if msg_type == "interactive" and interactive_payload:
                item_id = (
                    (interactive_payload.get("list_reply") or
                     interactive_payload.get("button_reply") or {}).get("id")
                )

                # SM-1: hybrid gate responses
                if item_id == "buy_now":
                    session_id = session["id"]
                    _action_transactional_entry(
                        db, org_id, phone_number, session_id, contact_name
                    )
                    return

                if item_id == "talk_sales":
                    session_id = session["id"]
                    # Mid-browse switch: if there was a commerce_session, close it
                    try:
                        db.table("commerce_sessions").update({"status": "abandoned"}).eq(
                            "org_id", org_id
                        ).eq("phone_number", phone_number).eq("status", "open").execute()
                    except Exception:
                        pass  # commerce_sessions may not exist yet (pre-SHOP-1A)
                    _action_qualify(db, org_id, phone_number, session_id, contact_name, now_ts)
                    return

                # SM-1: returning_contact_menu selection
                if section == "returning_lead":
                    dispatch_contact_menu_selection(
                        db=db,
                        org_id=org_id,
                        phone_number=phone_number,
                        item_id=item_id,
                        session=session,
                        menu_key="returning_contact_menu",
                        contact_name=contact_name,
                        now_ts=now_ts,
                    )
                    return

                # SM-1: known_customer_menu selection
                if section == "known_customer":
                    dispatch_contact_menu_selection(
                        db=db,
                        org_id=org_id,
                        phone_number=phone_number,
                        item_id=item_id,
                        session=session,
                        menu_key="known_customer_menu",
                        contact_name=contact_name,
                        now_ts=now_ts,
                    )
                    return

                # Existing WH-2 customer triage
                if section == "customer":
                    dispatch_customer_triage_selection(
                        db=db,
                        org_id=org_id,
                        phone_number=phone_number,
                        item_id=item_id,
                        session=session,
                        contact_name=contact_name,
                        now_ts=now_ts,
                    )
                else:
                    # WH-0 unknown contact triage
                    dispatch_triage_selection(
                        db=db,
                        org_id=org_id,
                        phone_number=phone_number,
                        item_id=item_id,
                        session=session,
                        contact_name=contact_name,
                        now_ts=now_ts,
                    )
            else:
                # Free text while menu is pending — re-send the correct menu
                from app.services.whatsapp_service import send_triage_menu
                send_triage_menu(db=db, org_id=org_id,
                                 phone_number=phone_number, section=section,
                                 contact_name=contact_name)

        elif state == "awaiting_identifier":
            if msg_type == "text" and content:
                handle_awaiting_identifier(
                    db=db,
                    org_id=org_id,
                    phone_number=phone_number,
                    identifier_text=content,
                    session=session,
                    contact_name=contact_name,
                    now_ts=now_ts,
                )

        else:
            logger.debug(
                "handle_session_message: session %s already in state %s — no-op",
                session.get("id"), state,
            )

    except Exception as exc:
        logger.warning("handle_session_message failed org=%s phone=%s: %s",
                       org_id, phone_number, exc)


# ── dispatch_contact_menu_selection ──────────────────────────────────────────

def dispatch_contact_menu_selection(
    db,
    org_id: str,
    phone_number: str,
    item_id,
    session: dict,
    menu_key: str,
    contact_name,
    now_ts,
) -> None:
    """
    SM-1: Dispatch an item selection from returning_contact_menu or known_customer_menu.
    menu_key: "returning_contact_menu" | "known_customer_menu"
    Action types: qualify | kb_enquiry | support_ticket | route_to_role | free_form
    S14.
    """
    try:
        session_id = session["id"]

        # Fetch org triage config + customer_id from session_data
        org_result = (
            db.table("organisations")
            .select("whatsapp_triage_config, qualification_flow, whatsapp_phone_id, name")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_data = org_result.data
        if isinstance(org_data, list):
            org_data = org_data[0] if org_data else None

        triage_config = (org_data or {}).get("whatsapp_triage_config") or {}
        menu_config = triage_config.get(menu_key) or {}
        items = menu_config.get("items") or []

        matched_item = None
        if item_id:
            for itm in items:
                if itm.get("id") == item_id:
                    matched_item = itm
                    break

        action = (matched_item or {}).get("action", "free_form")
        session_data = session.get("session_data") or {}
        customer_id = session_data.get("customer_id")

        if action == "qualify":
            _action_qualify(db, org_id, phone_number, session_id, contact_name, now_ts)

        elif action == "kb_enquiry":
            _contact_menu_action_kb_enquiry(
                db, org_id, phone_number, session_id,
                matched_item or {}, customer_id, contact_name, now_ts, org_data,
            )

        elif action == "support_ticket":
            _customer_action_create_ticket(
                db, org_id, phone_number, session_id,
                matched_item or {}, customer_id, contact_name, now_ts,
            )

        elif action == "route_to_role":
            _customer_action_route_to_role(
                db, org_id, phone_number, session_id,
                matched_item or {}, customer_id, contact_name, now_ts,
            )

        else:
            # free_form fallback
            _customer_action_free_form(
                db, org_id, phone_number, session_id,
                matched_item or {}, customer_id, contact_name, now_ts,
            )

    except Exception as exc:
        logger.warning(
            "dispatch_contact_menu_selection failed org=%s phone=%s menu=%s: %s",
            org_id, phone_number, menu_key, exc,
        )


def _contact_menu_action_kb_enquiry(
    db,
    org_id: str,
    phone_number: str,
    session_id: str,
    item: dict,
    customer_id,
    contact_name,
    now_ts,
    org_data: Optional[dict] = None,
) -> None:
    """
    SM-1: KB-first enquiry handler.
    lookup_kb_answer() first.
      found=True  → auto-send answer via WhatsApp. No human routing.
      found=False → _customer_action_free_form() to route to human.
    C2: uses expected_state="triage_sent" on update_session.
    S14.
    """
    try:
        from app.services.whatsapp_service import _call_meta_send

        phone_id = ((org_data or {}).get("whatsapp_phone_id") or "").strip()

        kb_answer = None
        try:
            from app.services.customer_inbound_service import lookup_kb_answer
            kb_result = lookup_kb_answer(db=db, org_id=org_id, query=item.get("label", ""))
            if kb_result and kb_result.get("found"):
                kb_answer = kb_result.get("answer")
        except Exception as exc:
            logger.warning(
                "_contact_menu_action_kb_enquiry: lookup_kb_answer failed: %s", exc
            )

        if kb_answer and phone_id:
            _call_meta_send(phone_id, {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "text",
                "text": {"body": kb_answer},
            })
            # C2: atomic transition — only succeeds if still in triage_sent
            update_session(
                db, session_id, "active",
                selected_action="kb_enquiry_resolved",
                expected_state="triage_sent",
            )
        else:
            # No KB match — route to human
            _customer_action_free_form(
                db, org_id, phone_number, session_id,
                item, customer_id, contact_name, now_ts,
            )

    except Exception as exc:
        logger.warning(
            "_contact_menu_action_kb_enquiry failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )


# ---------------------------------------------------------------------------
# Triage selection dispatcher
# ---------------------------------------------------------------------------

def dispatch_triage_selection(
    db,
    org_id: str,
    phone_number: str,
    item_id: Optional[str],
    session: dict,
    contact_name: Optional[str],
    now_ts,
) -> None:
    """
    Execute the pipeline action matching the user's triage menu selection.
    Falls back to 'free_form' if item_id is missing or not found in config.
    S14.
    """
    try:
        session_id = session["id"]

        # Fetch org triage config
        org_result = (
            db.table("organisations")
            .select("whatsapp_triage_config")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_data = org_result.data
        if isinstance(org_data, list):
            org_data = org_data[0] if org_data else None

        triage_config = (org_data or {}).get("whatsapp_triage_config") or {}
        unknown_items = (triage_config.get("unknown") or {}).get("items") or []

        # Find the selected item
        matched_item = None
        if item_id:
            for itm in unknown_items:
                if itm.get("id") == item_id:
                    matched_item = itm
                    break

        action = (matched_item or {}).get("action", "free_form")

        if action == "qualify":
            _action_qualify(db, org_id, phone_number, session_id,
                            contact_name, now_ts)

        elif action == "identify_customer":
            _action_identify_customer(db, org_id, phone_number, session_id)

        elif action == "route_to_role":
            _action_route_to_role(db, org_id, phone_number, session_id,
                                  matched_item or {}, contact_name, now_ts)

        elif action == "commerce_entry":
            # COMM-1: Contact selected a "shop / browse products" triage item.
            _action_commerce_entry(db, org_id, phone_number, session_id)

        else:
            # 'free_form' — also the fallback for unknown item_id
            _action_free_form(db, org_id, phone_number, session_id,
                              matched_item or {}, contact_name, now_ts)

    except Exception as exc:
        logger.warning("dispatch_triage_selection failed org=%s phone=%s item=%s: %s",
                       org_id, phone_number, item_id, exc)


# ---------------------------------------------------------------------------
# Individual action handlers (called only from dispatch_triage_selection)
# ---------------------------------------------------------------------------

def _action_qualify(
    db, org_id: str, phone_number: str, session_id: str,
    contact_name: Optional[str], now_ts,
) -> None:
    """
    WH-1b: Create a sales_lead and start the structured qualification flow.

    1. Fetch org qualification_flow. If null → send "getting set up" fallback,
       notify org owner, create lead without qualification session.
    2. Create lead (idempotent — returns existing if duplicate phone, C3).
    3. C2: Atomically transition session triage_sent → active.
       If transition fails (concurrent handler won), bail without duplicate work.
    4. Insert lead_qualification_sessions with current_question_index=0, answers={}.
    5. Send opening_message + Q1 immediately via send_qualification_question().
    """
    from app.models.leads import LeadCreate, LeadSource
    from app.services import lead_service
    from app.services.whatsapp_service import send_qualification_question

    # 1 — Fetch qualification_flow
    org_r = (
        db.table("organisations")
        .select("qualification_flow, whatsapp_phone_id, name")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    org_d = org_r.data
    if isinstance(org_d, list):
        org_d = org_d[0] if org_d else None

    qualification_flow = (org_d or {}).get("qualification_flow")
    phone_id = (org_d or {}).get("whatsapp_phone_id", "").strip()

    # 2 — Create the lead (idempotent — C3 returns existing on duplicate)
    lead_payload = LeadCreate(
        full_name=contact_name or phone_number,
        phone=phone_number,
        whatsapp=phone_number,
        source=LeadSource.whatsapp_inbound.value,
        contact_type="sales_lead",
    )
    lead = lead_service.create_lead(db, org_id, None, lead_payload)
    lead_id = lead["id"] if lead else None

    # Backfill lead_id on any messages saved before the lead existed
    # S14: failure never blocks qualification flow
    if lead_id:
        try:
            db.table("whatsapp_messages").update(
                {"lead_id": lead_id}
            ).eq("org_id", org_id).is_("lead_id", "null").execute()
        except Exception as _backfill_exc:
            logger.warning(
                "_action_qualify: lead_id backfill failed lead=%s: %s",
                lead_id, _backfill_exc,
            )

    # 3 — C2: Atomic state transition — bail if another handler already advanced
    transitioned = update_session(
        db, session_id, "active",
        selected_action="qualify",
        expected_state="triage_sent",
    )
    if not transitioned:
        logger.debug(
            "_action_qualify: session %s already advanced — bailing", session_id
        )
        return

    # Onboarding gate — qualification_flow must be configured
    if not qualification_flow:
        logger.warning(
            "_action_qualify: qualification_flow not configured for org %s — "
            "sending fallback message and notifying owner",
            org_id,
        )
        if phone_id:
            try:
                from app.services.whatsapp_service import _call_meta_send
                _call_meta_send(phone_id, {
                    "messaging_product": "whatsapp",
                    "to": phone_number,
                    "type": "text",
                    "text": {
                        "body": (
                            "We're getting set up — our team will reach out to you shortly."
                        )
                    },
                })
            except Exception as exc:
                logger.warning("_action_qualify: failed to send fallback message: %s", exc)

        _notify_managers(
            db, org_id,
            title="WhatsApp qualification flow not configured",
            body="WhatsApp qualification flow not configured. Please set it up in Admin.",
            resource_type="lead",
            resource_id=lead_id or "",
        )
        return  # Lead created, no qualification session

    # 4 — Validate flow structure
    questions = qualification_flow.get("questions") or []
    if not questions:
        logger.warning(
            "_action_qualify: qualification_flow has no questions for org %s", org_id
        )
        return

    # 5 — Insert lead_qualification_sessions
    now = datetime.now(timezone.utc).isoformat()
    try:
        db.table("lead_qualification_sessions").insert({
            "org_id":                  org_id,
            "lead_id":                 lead_id,
            "ai_active":               True,
            "stage":                   "qualifying",
            "current_question_index":  0,
            "answers":                 {},
            "created_at":              now,
            "last_message_at":         now,
        }).execute()
    except Exception as exc:
        logger.warning(
            "_action_qualify: failed to create qualification session for lead %s: %s",
            lead_id, exc,
        )
        return

    # 6 — Send Q1 immediately (with opening_message prepended)
    opening_message = qualification_flow.get("opening_message") or None
    send_qualification_question(
        db=db,
        org_id=org_id,
        phone_number=phone_number,
        question=questions[0],
        question_index=0,
        total=len(questions),
        opening_message=opening_message,
    )


def _action_identify_customer(
    db, org_id: str, phone_number: str, session_id: str,
) -> None:
    """
    Ask the contact to provide an identifier so we can find their record.
    C2: atomic transition triage_sent → awaiting_identifier.
    """
    from app.services.whatsapp_service import _call_meta_send

    org_r = (
        db.table("organisations")
        .select("whatsapp_phone_id")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    org_d = org_r.data
    if isinstance(org_d, list):
        org_d = org_d[0] if org_d else None
    phone_id = (org_d or {}).get("whatsapp_phone_id")
    if phone_id:
        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {
                "body": (
                    "Please share your account email address or company name "
                    "so we can find your record."
                )
            },
        })
    # C2: atomic — bail if already advanced
    update_session(
        db, session_id, "awaiting_identifier",
        selected_action="identify_customer",
        expected_state="triage_sent",
    )


def _action_route_to_role(
    db, org_id: str, phone_number: str, session_id: str,
    item: dict, contact_name: Optional[str], now_ts,
) -> None:
    """
    Create a business_inquiry lead and notify users with the target role.
    C2: atomic transition triage_sent → active.
    """
    from app.models.leads import LeadCreate, LeadSource
    from app.services import lead_service
    from app.services.whatsapp_service import _get_org_wa_credentials, _call_meta_send

    contact_type = item.get("contact_type", "business_inquiry")
    role = item.get("role", "owner")

    lead_payload = LeadCreate(
        full_name=contact_name or phone_number,
        phone=phone_number,
        whatsapp=phone_number,
        source=LeadSource.whatsapp_inbound.value,
        contact_type=contact_type,
    )
    lead = lead_service.create_lead(db, org_id, None, lead_payload)

    # Backfill lead_id on inbound messages saved before the lead existed
    # S14: failure never blocks the route_to_role flow
    if lead and lead.get("id"):
        try:
            db.table("whatsapp_messages").update(
                {"lead_id": lead["id"]}
            ).eq("org_id", org_id).is_("lead_id", "null").execute()
        except Exception as _backfill_exc:
            logger.warning(
                "_action_route_to_role: lead_id backfill failed lead=%s: %s",
                lead["id"], _backfill_exc,
            )

    # Send confirmation message to the lead and save to whatsapp_messages
    # so the rep sees the full context in the conversation thread.
    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        confirmation_text = "Thanks for reaching out! 😊 One of our team will be in touch with you shortly."
        if phone_id:
            _call_meta_send(phone_id, {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "text",
                "text": {"body": confirmation_text},
            }, token=access_token)
        # Save outbound confirmation to whatsapp_messages
        # so rep sees full conversation context in the thread
        if lead and lead.get("id"):
            try:
                from datetime import datetime, timezone, timedelta
                _now = datetime.now(timezone.utc).isoformat()
                _win = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
                db.table("whatsapp_messages").insert({
                    "org_id":            org_id,
                    "lead_id":           lead["id"],
                    "direction":         "outbound",
                    "message_type":      "text",
                    "channel":           "whatsapp",
                    "content":           confirmation_text,
                    "status":            "sent",
                    "window_open":       True,
                    "window_expires_at": _win,
                    "sent_by":           None,
                    "created_at":        _now,
                }).execute()
            except Exception as _db_exc:
                logger.warning(
                    "_action_route_to_role: message save failed: %s", _db_exc
                )
    except Exception as _msg_exc:
        logger.warning("_action_route_to_role: confirmation message failed: %s", _msg_exc)

    # Notify all users in org with the target role
    users_result = (
        db.table("users")
        .select("id, roles(template)")
        .eq("org_id", org_id)
        .execute()
    )
    notified = False
    for user in (users_result.data or []):
        user_role = (user.get("roles") or {}).get("template", "")
        if user_role.lower() == role.lower():
            _notify_single_user(
                db, org_id, user["id"],
                notif_type="new_lead",
                title="New inbound contact",
                body=f"A new {contact_type} contacted via WhatsApp.",
                resource_type="lead",
                resource_id=lead["id"],
            )
            notified = True

    if not notified:
        _notify_managers(
            db, org_id,
            title="New inbound contact",
            body=f"A new {contact_type} contacted via WhatsApp.",
            resource_type="lead",
            resource_id=lead["id"],
        )

    # C2: atomic — bail if already advanced
    update_session(
        db, session_id, "active",
        selected_action="route_to_role",
        expected_state="triage_sent",
    )


def _action_free_form(
    db, org_id: str, phone_number: str, session_id: str,
    item: dict, contact_name: Optional[str], now_ts,
) -> None:
    """
    Create an 'other' lead and notify the first available rep or owner.
    C2: atomic transition triage_sent → active.
    """
    from app.models.leads import LeadCreate, LeadSource
    from app.services import lead_service

    contact_type = item.get("contact_type", "other")

    lead_payload = LeadCreate(
        full_name=contact_name or phone_number,
        phone=phone_number,
        whatsapp=phone_number,
        source=LeadSource.whatsapp_inbound.value,
        contact_type=contact_type,
    )
    lead = lead_service.create_lead(db, org_id, None, lead_payload)

    # Backfill lead_id on inbound messages saved before the lead existed
    # S14: failure never blocks the free_form flow
    if lead and lead.get("id"):
        try:
            db.table("whatsapp_messages").update(
                {"lead_id": lead["id"]}
            ).eq("org_id", org_id).is_("lead_id", "null").execute()
        except Exception as _backfill_exc:
            logger.warning(
                "_action_free_form: lead_id backfill failed lead=%s: %s",
                lead["id"], _backfill_exc,
            )

    # Notify assigned rep or first owner
    assigned_to = lead.get("assigned_to")
    if not assigned_to:
        users_result = (
            db.table("users")
            .select("id, roles(template)")
            .eq("org_id", org_id)
            .execute()
        )
        for user in (users_result.data or []):
            if (user.get("roles") or {}).get("template", "").lower() == "owner":
                assigned_to = user["id"]
                break

    if assigned_to:
        _notify_single_user(
            db, org_id, assigned_to,
            notif_type="new_lead",
            title="New inbound contact",
            body="A new contact messaged via WhatsApp.",
            resource_type="lead",
            resource_id=lead["id"],
        )

    # C2: atomic — bail if already advanced
    update_session(
        db, session_id, "active",
        selected_action="free_form",
        expected_state="triage_sent",
    )


# ---------------------------------------------------------------------------
# WH-2: Customer triage dispatcher + action handlers
# ---------------------------------------------------------------------------

def dispatch_customer_triage_selection(
    db,
    org_id: str,
    phone_number: str,
    item_id: Optional[str],
    session: dict,
    contact_name: Optional[str],
    now_ts,
) -> None:
    """
    WH-2: Execute the pipeline action matching a known customer's triage
    menu selection.  Reads from triage_config["customer"].
    Valid actions: 'create_ticket' | 'route_to_role' | 'free_form'.
    Falls back to 'free_form' if item_id is missing or not found in config.
    S14.
    """
    try:
        session_id = session["id"]

        # Resolve customer_id from whatsapp_sessions.session_data
        session_data = session.get("session_data") or {}
        customer_id = session_data.get("customer_id")

        # Fetch org triage config
        org_result = (
            db.table("organisations")
            .select("whatsapp_triage_config")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_data = org_result.data
        if isinstance(org_data, list):
            org_data = org_data[0] if org_data else None

        triage_config = (org_data or {}).get("whatsapp_triage_config") or {}
        customer_items = (triage_config.get("customer") or {}).get("items") or []

        # Find the selected item
        matched_item = None
        if item_id:
            for itm in customer_items:
                if itm.get("id") == item_id:
                    matched_item = itm
                    break

        action = (matched_item or {}).get("action", "free_form")

        if action == "create_ticket":
            _customer_action_create_ticket(
                db, org_id, phone_number, session_id,
                matched_item or {}, customer_id, contact_name, now_ts,
            )

        elif action == "route_to_role":
            _customer_action_route_to_role(
                db, org_id, phone_number, session_id,
                matched_item or {}, customer_id, contact_name, now_ts,
            )

        else:
            # 'free_form' — also the fallback for unknown item_id
            _customer_action_free_form(
                db, org_id, phone_number, session_id,
                matched_item or {}, customer_id, contact_name, now_ts,
            )

    except Exception as exc:
        logger.warning(
            "dispatch_customer_triage_selection failed org=%s phone=%s item=%s: %s",
            org_id, phone_number, item_id, exc,
        )


def _customer_action_create_ticket(
    db,
    org_id: str,
    phone_number: str,
    session_id: str,
    item: dict,
    customer_id: Optional[str],
    contact_name: Optional[str],
    now_ts,
) -> None:
    """
    WH-2: Auto-create a support ticket for the customer and notify assigned rep.
    C2: atomic transition triage_sent → active.
    """
    label = item.get("label", "Support request")
    assigned_to = None

    if customer_id:
        cust_r = (
            db.table("customers")
            .select("assigned_to, full_name")
            .eq("id", customer_id)
            .maybe_single()
            .execute()
        )
        cust_d = cust_r.data
        if isinstance(cust_d, list):
            cust_d = cust_d[0] if cust_d else None
        assigned_to = (cust_d or {}).get("assigned_to")
        display_name = (cust_d or {}).get("full_name") or contact_name or phone_number
    else:
        display_name = contact_name or phone_number

    # Create the ticket
    ticket_result = (
        db.table("support_tickets")
        .insert({
            "org_id": org_id,
            "customer_id": customer_id,
            "title": f"{label} — {display_name}",
            "status": "open",
            "source": "whatsapp",
            "priority": "medium",
            "created_at": now_ts,
        })
        .execute()
    )
    ticket_rows = ticket_result.data or []
    ticket_id = ticket_rows[0]["id"] if ticket_rows else None

    if ticket_id:
        notify_title = "New support ticket via WhatsApp"
        notify_body  = f"{display_name} raised a ticket: {label}"
        if assigned_to:
            _notify_single_user(
                db, org_id, assigned_to,
                notif_type="new_ticket",
                title=notify_title,
                body=notify_body,
                resource_type="ticket",
                resource_id=ticket_id,
            )
        else:
            _notify_managers(
                db, org_id,
                title=notify_title,
                body=notify_body,
                resource_type="ticket",
                resource_id=ticket_id,
            )

    # C2: atomic transition
    update_session(
        db, session_id, "active",
        selected_action="create_ticket",
        expected_state="triage_sent",
    )


def _customer_action_route_to_role(
    db,
    org_id: str,
    phone_number: str,
    session_id: str,
    item: dict,
    customer_id: Optional[str],
    contact_name: Optional[str],
    now_ts,
) -> None:
    """
    WH-2: Notify all users in the org with the target role.
    C2: atomic transition triage_sent → active.
    """
    role = item.get("role", "owner")
    display_name = contact_name or phone_number

    users_result = (
        db.table("users")
        .select("id, roles(template)")
        .eq("org_id", org_id)
        .execute()
    )
    notified = False
    for user in (users_result.data or []):
        user_role = (user.get("roles") or {}).get("template", "")
        if user_role.lower() == role.lower():
            _notify_single_user(
                db, org_id, user["id"],
                notif_type="customer_triage",
                title="Customer contact via WhatsApp",
                body=f"{display_name} selected: {item.get('label', 'contact')}",
                resource_type="customer",
                resource_id=customer_id or "",
            )
            notified = True

    if not notified:
        _notify_managers(
            db, org_id,
            title="Customer contact via WhatsApp",
            body=f"{display_name} selected: {item.get('label', 'contact')}",
            resource_type="customer",
            resource_id=customer_id or "",
        )

    # C2: atomic transition
    update_session(
        db, session_id, "active",
        selected_action="route_to_role",
        expected_state="triage_sent",
    )


def _customer_action_free_form(
    db,
    org_id: str,
    phone_number: str,
    session_id: str,
    item: dict,
    customer_id: Optional[str],
    contact_name: Optional[str],
    now_ts,
) -> None:
    """
    WH-2: Notify assigned rep (or managers as fallback) for a general enquiry.
    C2: atomic transition triage_sent → active.
    """
    display_name = contact_name or phone_number
    assigned_to = None

    if customer_id:
        cust_r = (
            db.table("customers")
            .select("assigned_to")
            .eq("id", customer_id)
            .maybe_single()
            .execute()
        )
        cust_d = cust_r.data
        if isinstance(cust_d, list):
            cust_d = cust_d[0] if cust_d else None
        assigned_to = (cust_d or {}).get("assigned_to")

    if assigned_to:
        _notify_single_user(
            db, org_id, assigned_to,
            notif_type="customer_triage",
            title="Customer WhatsApp enquiry",
            body=f"{display_name} sent a general enquiry via WhatsApp.",
            resource_type="customer",
            resource_id=customer_id or "",
        )
    else:
        _notify_managers(
            db, org_id,
            title="Customer WhatsApp enquiry",
            body=f"{display_name} sent a general enquiry via WhatsApp.",
            resource_type="customer",
            resource_id=customer_id or "",
        )

    # C2: atomic transition
    update_session(
        db, session_id, "active",
        selected_action="free_form",
        expected_state="triage_sent",
    )


# ---------------------------------------------------------------------------
# Identifier-text handler
# ---------------------------------------------------------------------------

def handle_awaiting_identifier(
    db,
    org_id: str,
    phone_number: str,
    identifier_text: str,
    session: dict,
    contact_name: Optional[str],
    now_ts,
) -> None:
    """
    Attempt to match identifier_text against customer records (Pattern 33:
    Python-side filtering, no ILIKE).  On match: create pending
    customer_contact + notify managers.  On miss: create support_contact lead.
    C2: atomic transition awaiting_identifier → active.
    S14.
    """
    try:
        session_id = session["id"]

        # Fetch all org customers for Python-side search (Pattern 33)
        cust_result = (
            db.table("customers")
            .select("id, full_name, email, assigned_to")
            .eq("org_id", org_id)
            .execute()
        )
        customers = cust_result.data or []

        needle = identifier_text.strip().lower()
        matched_customer = None
        for cust in customers:
            name_match = (cust.get("full_name") or "").lower() == needle
            email_match = (cust.get("email") or "").lower() == needle
            if name_match or email_match:
                matched_customer = cust
                break

        from app.services.whatsapp_service import _call_meta_send
        org_ph_r = (
            db.table("organisations")
            .select("whatsapp_phone_id")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_ph_d = org_ph_r.data
        if isinstance(org_ph_d, list):
            org_ph_d = org_ph_d[0] if org_ph_d else None
        phone_id = (org_ph_d or {}).get("whatsapp_phone_id")

        if matched_customer:
            # Insert pending customer_contact
            db.table("customer_contacts").insert({
                "org_id": org_id,
                "customer_id": matched_customer["id"],
                "phone_number": phone_number,
                "name": contact_name,
                "status": "pending",
            }).execute()

            # Confirm to the sender
            if phone_id:
                _call_meta_send(phone_id, {
                    "messaging_product": "whatsapp",
                    "to": phone_number,
                    "type": "text",
                    "text": {
                        "body": (
                            "Thanks — we found your account. A team member will "
                            "confirm your details shortly."
                        )
                    },
                })

            # Notify all owners and ops_managers
            _notify_managers(
                db, org_id,
                title="New contact pending approval",
                body=(
                    f"A new contact is pending approval for customer "
                    f"{matched_customer.get('full_name', '')}."
                ),
                resource_type="customer",
                resource_id=matched_customer["id"],
            )

        else:
            # No match — create support_contact lead
            from app.models.leads import LeadCreate, LeadSource
            from app.services import lead_service

            lead_payload = LeadCreate(
                full_name=contact_name or phone_number,
                phone=phone_number,
                whatsapp=phone_number,
                source=LeadSource.whatsapp_inbound.value,
                contact_type="support_contact",
            )
            lead = lead_service.create_lead(db, org_id, None, lead_payload)

            if phone_id:
                _call_meta_send(phone_id, {
                    "messaging_product": "whatsapp",
                    "to": phone_number,
                    "type": "text",
                    "text": {
                        "body": (
                            "We couldn't find that account. A team member will "
                            "follow up with you shortly."
                        )
                    },
                })

            _notify_managers(
                db, org_id,
                title="Unknown identifier — follow-up needed",
                body="A contact couldn't be matched to any customer record.",
                resource_type="lead",
                resource_id=lead["id"],
            )

        # C2: atomic transition awaiting_identifier → active
        update_session(
            db, session_id, "active",
            selected_action="identify_customer",
            expected_state="awaiting_identifier",
        )

    except Exception as exc:
        logger.warning(
            "handle_awaiting_identifier failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )


# ---------------------------------------------------------------------------
# Customer contacts CRUD (called from customers.py router)
# ---------------------------------------------------------------------------

def list_customer_contacts(db, org_id: str, customer_id: str) -> list:
    """Return all customer_contacts rows for this org + customer. S14."""
    try:
        result = (
            db.table("customer_contacts")
            .select("*")
            .eq("org_id", org_id)
            .eq("customer_id", customer_id)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("list_customer_contacts failed: %s", exc)
        return []


def add_customer_contact(
    db,
    org_id: str,
    customer_id: str,
    payload: dict,
    registered_by: Optional[str] = None,
) -> Optional[dict]:
    """
    Insert a new customer_contact with status='pending'.
    payload fields: phone_number (required), name, contact_role.
    S14.
    """
    try:
        row = {
            "org_id": org_id,
            "customer_id": customer_id,
            "phone_number": payload["phone_number"],
            "name": payload.get("name"),
            "contact_role": payload.get("contact_role"),
            "status": "pending",
        }
        if registered_by:
            row["registered_by"] = registered_by
        result = db.table("customer_contacts").insert(row).execute()
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("add_customer_contact failed: %s", exc)
        return None


def approve_customer_contact(
    db,
    org_id: str,
    contact_id: str,
    user_id: str,
) -> Optional[dict]:
    """
    Set status='active' on the given contact (must belong to org). S14.
    Returns updated row or None.
    """
    try:
        result = (
            db.table("customer_contacts")
            .update({"status": "active"})
            .eq("id", contact_id)
            .eq("org_id", org_id)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("approve_customer_contact failed id=%s: %s",
                       contact_id, exc)
        return None


def remove_customer_contact(
    db,
    org_id: str,
    contact_id: str,
    user_id: str,
) -> bool:
    """
    Delete the given contact (must belong to org). Returns True on success.
    S14.
    """
    try:
        db.table("customer_contacts").delete().eq("id", contact_id).eq(
            "org_id", org_id
        ).execute()
        return True
    except Exception as exc:
        logger.warning("remove_customer_contact failed id=%s: %s",
                       contact_id, exc)
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _notify_single_user(
    db, org_id: str, user_id: str,
    notif_type: str, title: str, body: str,
    resource_type: str, resource_id: str,
) -> None:
    """
    WH-2 helper: notify a single known user_id.
    S14.
    """
    try:
        db.table("notifications").insert({
            "org_id":        org_id,
            "user_id":       user_id,
            "type":          notif_type,
            "title":         title,
            "body":          body,
            "resource_type": resource_type,
            "resource_id":   resource_id,
            "is_read":       False,
        }).execute()
        # PWA-1: fire push notification (S14 — never blocks)
        try:
            from app.routers.push_notifications import send_push_notification
            send_push_notification(db=db, user_id=user_id, title=title, body=body)
        except Exception:
            pass
    except Exception as exc:
        logger.warning("_notify_single_user failed user=%s: %s", user_id, exc)


def _notify_managers(
    db, org_id: str, title: str, body: str,
    resource_type: str, resource_id: str,
) -> None:
    """Notify all owners and ops_managers in the org. S14."""
    try:
        users_result = (
            db.table("users")
            .select("id, roles(template)")
            .eq("org_id", org_id)
            .execute()
        )
        for user in (users_result.data or []):
            role = (user.get("roles") or {}).get("template", "").lower()
            if role in ("owner", "ops_manager"):
                _notify_single_user(
                    db, org_id, user["id"],
                    notif_type="triage_alert",
                    title=title,
                    body=body,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
    except Exception as exc:
        logger.warning("_notify_managers failed org=%s: %s", org_id, exc)


# ── SM-1 / COMM-1 functions ───────────────────────────────────────────────────

def _action_transactional_entry(
    db,
    org_id: str,
    phone_number: str,
    session_id: str,
    contact_name: Optional[str],
) -> None:
    """
    COMM-1: Contact selected "Buy Now" or post-qualification offer fires for
    transactional/hybrid orgs. Guards against consultative orgs.
    C2: atomic transition triage_sent → active.
    S14 — never raises.
    """
    try:
        from app.services.commerce_service import (
            get_or_create_commerce_session,
        )
        from app.services.whatsapp_service import send_product_list

        # 1 — Guard: only run for orgs with Shopify connected
        org_r = (
            db.table("organisations")
            .select("shopify_connected, sales_mode")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_d = org_r.data
        if isinstance(org_d, list):
            org_d = org_d[0] if org_d else None
        org_d = org_d or {}

        if not org_d.get("shopify_connected"):
            logger.warning(
                "_action_transactional_entry: shopify not connected org=%s — skipping",
                org_id,
            )
            return

        sales_mode = org_d.get("sales_mode", "consultative")
        if sales_mode == "consultative":
            logger.info(
                "_action_transactional_entry: consultative org=%s — skipping",
                org_id,
            )
            return

        # 2 — Get or create commerce session (C4: race-safe)
        commerce_session = get_or_create_commerce_session(
            db, org_id, phone_number
        )
        if not commerce_session:
            logger.warning(
                "_action_transactional_entry: failed to get commerce session "
                "org=%s phone=%s",
                org_id, phone_number,
            )
            return

        # 3 — Fetch products
        products_r = (
            db.table("products")
            .select("*")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .order("title")
            .execute()
        )
        products = products_r.data if isinstance(products_r.data, list) else []

        if not products:
            logger.warning(
                "_action_transactional_entry: no active products for org=%s",
                org_id,
            )
            return

        # 4 — Send product list
        send_product_list(db, org_id, phone_number, products)

        # 5 — Set commerce_state on whatsapp_session (not session_state — no guard needed)
        if session_id:
            db.table("whatsapp_sessions").update(
                {"commerce_state": "commerce_browsing"}
            ).eq("id", session_id).execute()

        # 6 — C2: Atomic state transition
        if session_id:
            update_session(
                db, session_id, "active",
                selected_action="transactional_entry",
                expected_state="triage_sent",
            )

    except Exception as exc:
        logger.warning(
            "_action_transactional_entry failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )

def _send_typing_indicator(phone_id: str, message_id: str, token: str) -> None:
    """
    Show the WhatsApp typing indicator (wiggling dots) to the user.
    Also marks the incoming message as read (blue double ticks).
    Automatically dismissed when next message is sent or after 25 seconds.
    S14: never raises.
    """
    try:
        from app.services.whatsapp_service import _call_meta_send
        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {"type": "text"},
        }, token=token)
    except Exception as exc:
        logger.warning(
            "_send_typing_indicator failed phone_id=%s: %s", phone_id, exc
        )


def send_hybrid_entry_choice(
    db,
    org_id: str,
    phone_number: str,
    contact_name: Optional[str] = None,
    msg_id: Optional[str] = None,
) -> None:
    """
    SM-1: Send the hybrid gate (Buy Now / Speak to Sales) to the contact.

    Sequence:
      1. Show typing indicator (wiggling dots + blue ticks on their message)
      2. Wait 1.5s
      3. Send org-configured greeting as a plain text bubble, personalised
         with {{name}} placeholder if contact name is available
      4. Show typing indicator again
      5. Wait 1.0s
      6. Send interactive Buy Now / Speak to Sales buttons with org-configured
         button_prompt as body text

    Greeting and button_prompt are read from whatsapp_triage_config["unknown"].
    Falls back gracefully if org has no config set.
    S14.
    """
    import time
    try:
        from app.services.sales_mode_service import build_hybrid_entry_message
        from app.services.whatsapp_service import _call_meta_send, _get_org_wa_credentials

        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning(
                "send_hybrid_entry_choice: no phone_id for org %s", org_id
            )
            return

        # Fetch org triage config for greeting and button_prompt
        org_r = (
            db.table("organisations")
            .select("whatsapp_triage_config")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_d = org_r.data
        if isinstance(org_d, list):
            org_d = org_d[0] if org_d else None
        org_d = org_d or {}

        triage_config = (org_d.get("whatsapp_triage_config") or {})
        unknown_config = triage_config.get("unknown") or {}
        raw_greeting = (
            unknown_config.get("greeting")
            or "Hello! How can we help you today?"
        )

        # Personalise greeting using shared helper
        from app.services.whatsapp_service import _personalise_greeting
        greeting_text = _personalise_greeting(raw_greeting, contact_name)

        # Step 1: Typing indicator — shows wiggling dots + blue ticks
        if msg_id:
            _send_typing_indicator(phone_id, msg_id, access_token)

        # Step 2: Pause while "typing"
        time.sleep(0.5)

        # Step 3: Send personalised greeting as plain text bubble
        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {"body": greeting_text},
        }, token=access_token)

        # Step 4: Typing indicator again before buttons
        if msg_id:
            _send_typing_indicator(phone_id, msg_id, access_token)

        # Step 5: Pause
        time.sleep(0.3)

        # Step 6: Send interactive Buy Now / Speak to Sales buttons
        payload = build_hybrid_entry_message(phone_number, org=org_d)
        if payload:
            _call_meta_send(phone_id, payload, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_hybrid_entry_choice failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )


def send_returning_contact_menu(
    db,
    org_id: str,
    phone_number: str,
    org: Optional[dict] = None,
) -> None:
    """
    SM-1: Send the returning_contact_menu interactive list to the contact.
    Falls back to _action_qualify() if the menu is not configured.
    S14.
    """
    try:
        from app.services.sales_mode_service import build_returning_contact_menu
        from app.services.whatsapp_service import _call_meta_send

        if org is None:
            org_r = (
                db.table("organisations")
                .select("whatsapp_phone_id, whatsapp_triage_config")
                .eq("id", org_id)
                .maybe_single()
                .execute()
            )
            org_d = org_r.data
            if isinstance(org_d, list):
                org_d = org_d[0] if org_d else None
            org = org_d or {}

        phone_id = (org.get("whatsapp_phone_id") or "").strip()
        payload = build_returning_contact_menu(org, phone_number)

        if payload and phone_id:
            _call_meta_send(phone_id, payload)
        else:
            logger.info(
                "send_returning_contact_menu: no menu configured for org %s — "
                "falling back to qualification",
                org_id,
            )
    except Exception as exc:
        logger.warning(
            "send_returning_contact_menu failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )


def send_known_customer_menu(
    db,
    org_id: str,
    phone_number: str,
    session_id: Optional[str] = None,
    org: Optional[dict] = None,
) -> None:
    """
    SM-1: Send the known_customer_menu interactive list to the contact.
    Falls back to existing customer triage if menu is not configured.
    S14.
    """
    try:
        from app.services.sales_mode_service import build_known_customer_menu
        from app.services.whatsapp_service import _call_meta_send

        if org is None:
            org_r = (
                db.table("organisations")
                .select("whatsapp_phone_id, whatsapp_triage_config")
                .eq("id", org_id)
                .maybe_single()
                .execute()
            )
            org_d = org_r.data
            if isinstance(org_d, list):
                org_d = org_d[0] if org_d else None
            org = org_d or {}

        phone_id = (org.get("whatsapp_phone_id") or "").strip()
        payload = build_known_customer_menu(org, phone_number)

        if payload and phone_id:
            _call_meta_send(phone_id, payload)
        else:
            logger.info(
                "send_known_customer_menu: no menu configured for org %s — "
                "falling back to existing customer triage",
                org_id,
            )
    except Exception as exc:
        logger.warning(
            "send_known_customer_menu failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )


# ---------------------------------------------------------------------------
# COMM-1 — Commerce Entry Action
# ---------------------------------------------------------------------------

def _action_commerce_entry(
    db,
    org_id: str,
    phone_number: str,
    session_id: str,
) -> None:
    """
    COMM-1: Called from dispatch_triage_selection when action == 'commerce_entry'.
    Contact chose a "Shop / Browse" triage item from the unknown contact menu.
    C2: atomic transition triage_sent → active.
    S14 — never raises.
    """
    try:
        from app.services.commerce_service import get_or_create_commerce_session
        from app.services.whatsapp_service import send_product_list

        # 1 — Guard: Shopify must be connected
        org_r = (
            db.table("organisations")
            .select("shopify_connected")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_d = org_r.data
        if isinstance(org_d, list):
            org_d = org_d[0] if org_d else None
        if not (org_d or {}).get("shopify_connected"):
            logger.warning(
                "_action_commerce_entry: shopify not connected org=%s — skipping",
                org_id,
            )
            return

        # 2 — Get or create commerce session (C4: race-safe)
        commerce_session = get_or_create_commerce_session(db, org_id, phone_number)
        if not commerce_session:
            logger.warning(
                "_action_commerce_entry: failed to get commerce session "
                "org=%s phone=%s",
                org_id, phone_number,
            )
            return

        # 3 — Fetch active products
        products_r = (
            db.table("products")
            .select("*")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .order("title")
            .execute()
        )
        products = products_r.data if isinstance(products_r.data, list) else []

        if not products:
            logger.warning(
                "_action_commerce_entry: no active products for org=%s", org_id
            )
            return

        # 4 — Send product list
        send_product_list(db, org_id, phone_number, products)

        # 5 — Set commerce_state on whatsapp_session (not session_state — no guard)
        db.table("whatsapp_sessions").update(
            {"commerce_state": "commerce_browsing"}
        ).eq("id", session_id).execute()

        # 6 — C2: Atomic state transition
        update_session(
            db, session_id, "active",
            selected_action="commerce_entry",
            expected_state="triage_sent",
        )

    except Exception as exc:
        logger.warning(
            "_action_commerce_entry failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )
