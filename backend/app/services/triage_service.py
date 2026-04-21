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


def create_session(
    db,
    org_id: str,
    phone_number: str,
    expires_minutes: int = 30,
) -> Optional[dict]:
    """
    Insert a new whatsapp_sessions row with session_state='triage_sent'.
    Returns the inserted row dict, or None on failure. S14.
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
) -> None:
    """
    Update session_state (and optionally selected_action / session_data)
    for the given session row. S14.
    """
    try:
        payload: dict = {"session_state": state}
        if selected_action is not None:
            payload["selected_action"] = selected_action
        if session_data is not None:
            payload["session_data"] = session_data
        db.table("whatsapp_sessions").update(payload).eq("id", session_id).execute()
    except Exception as exc:
        logger.warning("update_session failed session_id=%s: %s", session_id, exc)


# ---------------------------------------------------------------------------
# Session message dispatcher
# ---------------------------------------------------------------------------

def handle_session_message(
    db,
    org_id: str,
    phone_number: str,
    session: dict,
    msg_type: str,
    content: Optional[str],
    interactive_payload: Optional[dict],
    contact_name: Optional[str],
    now_ts,
    section: str = "unknown",
) -> None:
    """
    Route an inbound message to the correct handler based on session state.
    section: "unknown" (WH-0) or "customer" (WH-2) — controls which menu is
    re-sent on free text and which dispatcher is called.
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
                # Free text while menu is pending — re-send the correct menu,
                # no new session created.
                from app.services.whatsapp_service import send_triage_menu
                send_triage_menu(db=db, org_id=org_id,
                                 phone_number=phone_number, section=section)

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
            # Non-text or empty while awaiting — silently ignore

        else:
            # 'active' or anything else — session already resolved
            logger.debug(
                "handle_session_message: session %s already in state %s — no-op",
                session.get("id"), state,
            )

    except Exception as exc:
        logger.warning("handle_session_message failed org=%s phone=%s: %s",
                       org_id, phone_number, exc)


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
    2. Create lead.
    3. Update triage session to 'active'.
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

    # 2 — Create the lead regardless (always create on qualify action)
    lead_payload = LeadCreate(
        full_name=contact_name or phone_number,
        phone=phone_number,
        whatsapp=phone_number,
        source=LeadSource.whatsapp_inbound.value,
        contact_type="sales_lead",
    )
    lead = lead_service.create_lead(db, org_id, None, lead_payload)
    lead_id = lead["id"] if lead else None

    update_session(db, session_id, "active", selected_action="qualify")

    # Onboarding gate — qualification_flow must be configured
    if not qualification_flow:
        logger.warning(
            "_action_qualify: qualification_flow not configured for org %s — "
            "sending fallback message and notifying owner",
            org_id,
        )
        # Send fallback message to the lead
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

        # Notify org owner
        _notify_managers(
            db, org_id,
            title="WhatsApp qualification flow not configured",
            body="WhatsApp qualification flow not configured. Please set it up in Admin.",
            resource_type="lead",
            resource_id=lead_id or "",
        )
        return  # Lead created, no qualification session

    # 3 — Validate flow structure
    questions = qualification_flow.get("questions") or []
    if not questions:
        logger.warning(
            "_action_qualify: qualification_flow has no questions for org %s", org_id
        )
        return

    # 4 — Insert lead_qualification_sessions
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

    # 5 — Send Q1 immediately (with opening_message prepended)
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
    """Ask the contact to provide an identifier so we can find their record."""
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
    update_session(db, session_id, "awaiting_identifier",
                   selected_action="identify_customer")


def _action_route_to_role(
    db, org_id: str, phone_number: str, session_id: str,
    item: dict, contact_name: Optional[str], now_ts,
) -> None:
    """Create a business_inquiry lead and notify users with the target role."""
    from app.models.leads import LeadCreate, LeadSource
    from app.services import lead_service
    from app.services.notification_service import _insert_notification

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

    # Notify all users in org with the target role
    users_result = (
        db.table("users")
        .select("id, roles(template)")
        .eq("org_id", org_id)
        .execute()
    )
    for user in (users_result.data or []):
        user_role = (user.get("roles") or {}).get("template", "")
        if user_role.lower() == role.lower():
            _insert_notification(
                db, org_id, user["id"],
                notif_type="new_lead",
                title="New inbound contact",
                body=f"A new {contact_type} contacted via WhatsApp.",
                resource_type="lead",
                resource_id=lead["id"],
            )

    update_session(db, session_id, "active", selected_action="route_to_role")


def _action_free_form(
    db, org_id: str, phone_number: str, session_id: str,
    item: dict, contact_name: Optional[str], now_ts,
) -> None:
    """Create an 'other' lead and notify the first available rep or owner."""
    from app.models.leads import LeadCreate, LeadSource
    from app.services import lead_service
    from app.services.notification_service import _insert_notification

    contact_type = item.get("contact_type", "other")

    lead_payload = LeadCreate(
        full_name=contact_name or phone_number,
        phone=phone_number,
        whatsapp=phone_number,
        source=LeadSource.whatsapp_inbound.value,
        contact_type=contact_type,
    )
    lead = lead_service.create_lead(db, org_id, None, lead_payload)

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
        _insert_notification(
            db, org_id, assigned_to,
            notif_type="new_lead",
            title="New inbound contact",
            body=f"A new contact messaged via WhatsApp.",
            resource_type="lead",
            resource_id=lead["id"],
        )

    update_session(db, session_id, "active", selected_action="free_form")


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
    Falls back to notifying managers if no customer_id or assigned_to.
    All notifications go through _notify_managers/_notify_single_user —
    never imports _insert_notification directly (avoids empty-module import).
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

    update_session(db, session_id, "active", selected_action="create_ticket")


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
    Falls back to _notify_managers when no users match the role.
    Uses _notify_single_user per matched user — no direct _insert_notification.
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

    update_session(db, session_id, "active", selected_action="route_to_role")


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
    Uses _notify_single_user for rep path — no direct _insert_notification.
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

    update_session(db, session_id, "active", selected_action="free_form")


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
                body=f"A contact couldn't be matched to any customer record.",
                resource_type="lead",
                resource_id=lead["id"],
            )

        update_session(db, session_id, "active",
                       selected_action="identify_customer")

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
    WH-2 helper: notify a single known user_id without importing _insert_notification
    directly. Inserts into the notifications table the same way _notify_managers does.
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
    except Exception as exc:
        logger.warning("_notify_single_user failed user=%s: %s", user_id, exc)


def _notify_managers(
    db, org_id: str, title: str, body: str,
    resource_type: str, resource_id: str,
) -> None:
    """Notify all owners and ops_managers in the org. S14."""
    try:
        from app.services.notification_service import _insert_notification

        users_result = (
            db.table("users")
            .select("id, roles(template)")
            .eq("org_id", org_id)
            .execute()
        )
        for user in (users_result.data or []):
            role = (user.get("roles") or {}).get("template", "").lower()
            if role in ("owner", "ops_manager"):
                _insert_notification(
                    db, org_id, user["id"],
                    notif_type="triage_alert",
                    title=title,
                    body=body,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
    except Exception as exc:
        logger.warning("_notify_managers failed org=%s: %s", org_id, exc)