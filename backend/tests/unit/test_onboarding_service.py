"""
tests/unit/test_onboarding_service.py
12 unit tests for onboarding_service.py
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from app.services.onboarding_service import get_checklist_status, activate_org, GATE_IDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = "00000000-0000-0000-0000-000000000001"


def _make_db(
    org_overrides: dict | None = None,
    users: list | None = None,
    routing_rules: list | None = None,
    templates: list | None = None,
    kb_articles: list | None = None,
    drip_messages: list | None = None,
) -> MagicMock:
    """Build a mock db that returns controlled data for each table query."""

    org_data = {
        "is_live": False,
        "whatsapp_phone_id": "123456",
        "whatsapp_triage_config": {"menus": []},
        "qualification_flow": {"questions": []},
        "pipeline_stages": {"stages": []},
        "scoring_rubric": {"rubric": []},
        "ticket_categories": ["billing"],
        "sla_hot_hours": 1,
        "sla_business_hours": {"mon": {}},
        "drip_business_types": ["SaaS"],
        "nurture_track_enabled": True,
    }
    if org_overrides:
        org_data.update(org_overrides)

    _users = users if users is not None else [
        {"id": "u1", "whatsapp_number": "+2348000000001", "roles": {"template": "sales_agent"}},
    ]
    _routing = routing_rules if routing_rules is not None else [
        {"id": "r1", "event_type": "ticket_created"},
    ]
    _templates = templates if templates is not None else [
        {"id": "t1", "meta_status": "approved"},
    ]
    _kb = kb_articles if kb_articles is not None else [
        {"id": f"k{i}", "is_published": True} for i in range(5)
    ]
    _drip = drip_messages if drip_messages is not None else [
        {"id": "d1", "is_active": True},
    ]

    def _table(name: str):
        mock = MagicMock()
        if name == "organisations":
            mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = org_data
        elif name == "users":
            mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = _users
        elif name == "routing_rules":
            mock.select.return_value.eq.return_value.execute.return_value.data = _routing
        elif name == "whatsapp_templates":
            mock.select.return_value.eq.return_value.execute.return_value.data = _templates
        elif name == "knowledge_base_articles":
            mock.select.return_value.eq.return_value.execute.return_value.data = _kb
        elif name == "drip_messages":
            mock.select.return_value.eq.return_value.execute.return_value.data = _drip
        elif name == "audit_logs":
            mock.insert.return_value.execute.return_value = MagicMock()
        elif name == "organisations":
            mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
        return mock

    db = MagicMock()
    db.table.side_effect = _table
    return db


# ---------------------------------------------------------------------------
# Tests — get_checklist_status
# ---------------------------------------------------------------------------

def test_all_items_present():
    db = _make_db()
    result = get_checklist_status(db, ORG_ID)
    assert len(result["items"]) == 17


def test_percent_complete_all_complete():
    db = _make_db()
    result = get_checklist_status(db, ORG_ID)
    assert result["percent_complete"] == 100


def test_percent_complete_partial():
    # Remove whatsapp_phone_id so whatsapp_connected = False
    db = _make_db(org_overrides={"whatsapp_phone_id": None})
    result = get_checklist_status(db, ORG_ID)
    assert result["percent_complete"] < 100


def test_go_live_ready_true_when_all_gates_complete():
    db = _make_db()
    result = get_checklist_status(db, ORG_ID)
    assert result["go_live_ready"] is True


def test_go_live_ready_false_when_whatsapp_not_connected():
    db = _make_db(org_overrides={"whatsapp_phone_id": None})
    result = get_checklist_status(db, ORG_ID)
    assert result["go_live_ready"] is False


def test_go_live_ready_false_when_no_approved_template():
    db = _make_db(templates=[{"id": "t1", "meta_status": "pending"}])
    result = get_checklist_status(db, ORG_ID)
    assert result["go_live_ready"] is False


def test_go_live_ready_false_when_kb_below_minimum():
    # Only 4 published articles
    db = _make_db(kb_articles=[{"id": f"k{i}", "is_published": True} for i in range(4)])
    result = get_checklist_status(db, ORG_ID)
    assert result["go_live_ready"] is False


def test_go_live_ready_false_when_no_qualification_flow():
    db = _make_db(org_overrides={"qualification_flow": None})
    result = get_checklist_status(db, ORG_ID)
    assert result["go_live_ready"] is False


def test_go_live_ready_false_when_no_triage_menu():
    db = _make_db(org_overrides={"whatsapp_triage_config": None})
    result = get_checklist_status(db, ORG_ID)
    assert result["go_live_ready"] is False


def test_non_gate_items_do_not_block_go_live():
    # scoring_rubric is not a gate — removing it should not affect go_live_ready
    db = _make_db(org_overrides={"scoring_rubric": None})
    result = get_checklist_status(db, ORG_ID)
    assert result["go_live_ready"] is True
    scoring = next(it for it in result["items"] if it["id"] == "scoring_rubric")
    assert scoring["complete"] is False


def test_activate_org_writes_correct_columns():
    db = _make_db()

    # Capture the update call
    updated_data = {}

    def _table(name):
        mock = MagicMock()
        if name == "organisations":
            def _update(data):
                updated_data.update(data)
                m = MagicMock()
                m.eq.return_value.execute.return_value = MagicMock()
                return m
            mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "is_live": False,
                "whatsapp_phone_id": "123456",
                "whatsapp_triage_config": {"menus": []},
                "qualification_flow": {"questions": []},
                "pipeline_stages": {"stages": []},
                "scoring_rubric": {"rubric": []},
                "ticket_categories": ["billing"],
                "sla_hot_hours": 1,
                "sla_business_hours": {"mon": {}},
                "drip_business_types": ["SaaS"],
                "nurture_track_enabled": True,
            }
            mock.update.side_effect = _update
        elif name == "users":
            mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                {"id": "u1", "whatsapp_number": "+2348000000001", "roles": {"template": "sales_agent"}},
            ]
        elif name == "routing_rules":
            mock.select.return_value.eq.return_value.execute.return_value.data = [
                {"id": "r1", "event_type": "ticket_created"},
            ]
        elif name == "whatsapp_templates":
            mock.select.return_value.eq.return_value.execute.return_value.data = [
                {"id": "t1", "meta_status": "approved"},
            ]
        elif name == "knowledge_base_articles":
            mock.select.return_value.eq.return_value.execute.return_value.data = [
                {"id": f"k{i}", "is_published": True} for i in range(5)
            ]
        elif name == "drip_messages":
            mock.select.return_value.eq.return_value.execute.return_value.data = [
                {"id": "d1", "is_active": True},
            ]
        elif name == "audit_logs":
            mock.insert.return_value.execute.return_value = MagicMock()
        return mock

    db.table.side_effect = _table
    activate_org(db, ORG_ID)

    assert updated_data.get("is_live") is True
    assert "went_live_at" in updated_data
    assert "onboarding_completed_at" in updated_data


def test_activate_org_raises_400_when_gates_incomplete():
    db = _make_db(org_overrides={"whatsapp_phone_id": None})
    with pytest.raises(HTTPException) as exc_info:
        activate_org(db, ORG_ID)
    assert exc_info.value.status_code == 400
