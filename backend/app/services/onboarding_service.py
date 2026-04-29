"""
app/services/onboarding_service.py
Onboarding checklist status and go-live activation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checklist definition
# ---------------------------------------------------------------------------

# Each entry: (id, label, group, is_gate)
CHECKLIST_ITEMS: list[tuple[str, str, str, bool]] = [
    # Team & Access
    ("team_user",           "At least 1 staff user added",       "Team & Access",       False),
    ("routing_rule",        "Routing rules configured",           "Team & Access",       False),
    # Lead Pipeline
    ("scoring_rubric",      "Lead scoring rubric set",            "Lead Pipeline",       False),
    ("qualification_flow",  "Qualification flow configured",      "Lead Pipeline",       True),
    ("pipeline_confirmed",  "Pipeline stages confirmed",          "Lead Pipeline",       False),
    # WhatsApp
    ("whatsapp_connected",  "WhatsApp API connected",             "WhatsApp",            True),
    ("wa_template_approved","≥1 approved WhatsApp template",      "WhatsApp",            True),
    ("triage_menu",         "Triage menu configured",             "WhatsApp",            True),
    ("sales_mode_configured",   "Sales mode configured",              "WhatsApp",            False),
    ("contact_menus_configured", "Contact menus configured",           "WhatsApp",            False),
    # Support
    ("ticket_routing",      "Ticket routing rule exists",         "Support",             False),
    ("ticket_categories",   "Ticket categories confirmed",        "Support",             False),
    ("kb_minimum",          "Knowledge base populated (≥5 articles)", "Support",         True),
    # Customer Engagement
    ("drip_sequence",       "Drip sequence configured",           "Customer Engagement", False),
    ("sla_targets",         "SLA targets reviewed",               "Customer Engagement", False),
    ("business_hours",      "Business hours configured",          "Customer Engagement", False),
    ("business_types",      "Business types configured",          "Customer Engagement", False),
    ("nurture_reviewed",    "Nurture engine reviewed",            "Customer Engagement", False),
    # Notifications
    ("staff_whatsapp",      "Staff WhatsApp numbers set",         "Notifications",       False),
]

GATE_IDS = {item_id for item_id, _, _, is_gate in CHECKLIST_ITEMS if is_gate}


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def get_checklist_status(db: Any, org_id: str) -> dict:
    """
    Single-pass DB query set to evaluate all 17 checklist items.
    Returns percent_complete, go_live_ready, is_live, and full items list.
    Pattern 33: no ILIKE — all filtering done Python-side.
    """

    # ------------------------------------------------------------------
    # Batch queries — fetch everything needed in one pass
    # ------------------------------------------------------------------

    # 1. organisations row
    org_row = (
        db.table("organisations")
        .select("*")
        .eq("id", org_id)
        .single()
        .execute()
    )
    org = org_row.data or {}

    # 2. users (non-owner staff count + staff with whatsapp)
    users_rows = (
        db.table("users")
        .select("id, whatsapp_number, roles(template)")
        .eq("org_id", org_id)
        .eq("is_active", True)
        .execute()
    )
    users = users_rows.data or []

    # 3. routing_rules
    routing_rows = (
        db.table("routing_rules")
        .select("id, event_type")
        .eq("org_id", org_id)
        .execute()
    )
    routing_rules = routing_rows.data or []

    # 4. whatsapp_templates (approved)
    templates_rows = (
        db.table("whatsapp_templates")
        .select("id, meta_status")
        .eq("org_id", org_id)
        .execute()
    )
    templates = templates_rows.data or []

    # 5. knowledge_base_articles (published)
    kb_rows = (
        db.table("knowledge_base_articles")
        .select("id, is_published")
        .eq("org_id", org_id)
        .execute()
    )
    kb_articles = kb_rows.data or []

    # 6. drip_messages (active)
    drip_rows = (
        db.table("drip_messages")
        .select("id, is_active")
        .eq("org_id", org_id)
        .execute()
    )
    drip_messages = drip_rows.data or []

    # ------------------------------------------------------------------
    # Derived counts (Pattern 33 — Python-side filtering only)
    # ------------------------------------------------------------------

    # team_user: non-owner staff
    non_owner_users = [
        u for u in users
        if (u.get("roles") or {}).get("template", "").lower() != "owner"
    ]

    # routing_rule: any routing rule
    routing_count = len(routing_rules)

    # ticket_routing: event_type starts with "ticket_"
    ticket_routing_count = len(
        [r for r in routing_rules if r.get("event_type", "").startswith("ticket_")]
    )

    # wa_template_approved
    approved_templates = [
        t for t in templates if t.get("meta_status") == "approved"
    ]

    # kb_minimum: published articles
    published_kb = [a for a in kb_articles if a.get("is_published") is True]

    # drip_sequence: active drip messages
    active_drip = [d for d in drip_messages if d.get("is_active") is True]

    # staff_whatsapp: any user with whatsapp_number set
    staff_with_wa = [u for u in users if u.get("whatsapp_number")]

    # ------------------------------------------------------------------
    # Evaluate each checklist item
    # ------------------------------------------------------------------

    item_states: dict[str, bool] = {
        "team_user":            len(non_owner_users) >= 1,
        "routing_rule":         routing_count >= 1,
        "scoring_rubric":       org.get("scoring_rubric") is not None,
        "qualification_flow":   org.get("qualification_flow") is not None,
        "pipeline_confirmed":   org.get("pipeline_stages") is not None,
        "whatsapp_connected":   org.get("whatsapp_phone_id") is not None,
        "wa_template_approved": len(approved_templates) >= 1,
        "triage_menu":          org.get("whatsapp_triage_config") is not None,
        "sales_mode_configured":    org.get("sales_mode") is not None,
        "contact_menus_configured": org.get("returning_contact_menu") is not None,
        "ticket_routing":       ticket_routing_count >= 1,
        "ticket_categories":    org.get("ticket_categories") is not None,
        "kb_minimum":           len(published_kb) >= 5,
        "drip_sequence":        len(active_drip) >= 1,
        "sla_targets":          org.get("sla_hot_hours") is not None,
        "business_hours":       org.get("sla_business_hours") is not None,
        "business_types":       org.get("drip_business_types") is not None,
        "nurture_reviewed":     org.get("nurture_track_enabled") is not None,
        "staff_whatsapp":       len(staff_with_wa) >= 1,
    }

    # ------------------------------------------------------------------
    # Build items list
    # ------------------------------------------------------------------

    items = [
        {
            "id":       item_id,
            "label":    label,
            "group":    group,
            "complete": item_states[item_id],
            "is_gate":  is_gate,
        }
        for item_id, label, group, is_gate in CHECKLIST_ITEMS
    ]

    complete_count = sum(1 for it in items if it["complete"])
    total = len(items)
    percent_complete = round((complete_count / total) * 100) if total else 0

    go_live_ready = all(item_states[gid] for gid in GATE_IDS)
    is_live = bool(org.get("is_live", False))

    return {
        "percent_complete": percent_complete,
        "go_live_ready": go_live_ready,
        "is_live": is_live,
        "items": items,
    }


def activate_org(db: Any, org_id: str) -> str:
    """
    Activates an org — sets is_live, went_live_at, onboarding_completed_at.
    Raises HTTPException(400) if go_live_ready is False.
    Returns went_live_at ISO string.
    """
    status = get_checklist_status(db, org_id)

    if not status["go_live_ready"]:
        incomplete_gates = [
            it["id"] for it in status["items"]
            if it["is_gate"] and not it["complete"]
        ]
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Cannot activate — required setup steps are incomplete",
                "incomplete_gates": incomplete_gates,
            },
        )

    now_iso = datetime.now(timezone.utc).isoformat()

    db.table("organisations").update({
        "is_live": True,
        "went_live_at": now_iso,
        "onboarding_completed_at": now_iso,
    }).eq("id", org_id).execute()

    # Audit log
    try:
        db.table("audit_logs").insert({
            "org_id": org_id,
            "actor_id": None,
            "action": "org.activated",
            "resource_type": "organisation",
            "resource_id": org_id,
            "metadata": {"went_live_at": now_iso},
        }).execute()
    except Exception as exc:
        logger.warning("audit log insert failed for org.activated: %s", exc)

    return now_iso
