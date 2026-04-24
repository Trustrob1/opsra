"""
tests/unit/test_sales_mode_service.py
SM-1: Sales Mode Engine — unit tests (12 tests)
"""
import pytest
from unittest.mock import MagicMock, patch
from app.services import sales_mode_service as svc


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _org(mode="consultative", triage_config=None):
    return {
        "id": "org-1",
        "sales_mode": mode,
        "whatsapp_phone_id": "ph-1",
        "whatsapp_triage_config": triage_config or {},
    }


# ── get_entry_experience ──────────────────────────────────────────────────────

def test_consultative_all_types():
    for ct in ("new", "returning_lead", "returning_commerce", "known_customer"):
        assert svc.get_entry_experience(_org("consultative"), ct) == "qualification"


def test_transactional_new():
    assert svc.get_entry_experience(_org("transactional"), "new") == "commerce"


def test_transactional_returning_commerce():
    assert svc.get_entry_experience(_org("transactional"), "returning_commerce") == "commerce"


def test_transactional_known_customer():
    assert svc.get_entry_experience(_org("transactional"), "known_customer") == "known_customer_menu"


def test_hybrid_new():
    assert svc.get_entry_experience(_org("hybrid"), "new") == "hybrid_gate"


def test_hybrid_returning_lead():
    assert svc.get_entry_experience(_org("hybrid"), "returning_lead") == "returning_contact_menu"


def test_hybrid_returning_commerce():
    assert svc.get_entry_experience(_org("hybrid"), "returning_commerce") == "hybrid_gate"


def test_hybrid_known_customer():
    assert svc.get_entry_experience(_org("hybrid"), "known_customer") == "known_customer_menu"


def test_unknown_mode_defaults_to_qualification():
    assert svc.get_entry_experience(_org("unknown_mode"), "new") == "qualification"


# ── get_sales_path ────────────────────────────────────────────────────────────

def test_get_sales_path_buy_now():
    assert svc.get_sales_path(_org("hybrid"), "hybrid_gate", "buy_now") == "transactional"


def test_get_sales_path_talk_sales():
    assert svc.get_sales_path(_org("hybrid"), "hybrid_gate", "talk_sales") == "consultative"


# ── build_hybrid_entry_message ────────────────────────────────────────────────

def test_build_hybrid_entry_message_structure():
    msg = svc.build_hybrid_entry_message("+2341234567890")
    assert msg["type"] == "interactive"
    assert msg["interactive"]["type"] == "button"
    buttons = msg["interactive"]["action"]["buttons"]
    ids = [b["reply"]["id"] for b in buttons]
    assert "buy_now" in ids
    assert "talk_sales" in ids


# ── build_returning_contact_menu ──────────────────────────────────────────────

def test_build_returning_contact_menu_no_items():
    org = _org("hybrid", {"returning_contact_menu": {"items": []}})
    result = svc.build_returning_contact_menu(org, "+2341234567890")
    assert result is None


def test_build_returning_contact_menu_with_items():
    org = _org("hybrid", {
        "returning_contact_menu": {
            "greeting": "Hi!",
            "section_title": "Choose",
            "items": [{"id": "rc_1", "label": "Buy", "description": "", "action": "qualify"}],
        }
    })
    result = svc.build_returning_contact_menu(org, "+2341234567890")
    assert result is not None
    assert result["interactive"]["type"] == "list"
    rows = result["interactive"]["action"]["sections"][0]["rows"]
    assert rows[0]["id"] == "rc_1"


# ── build_known_customer_menu ─────────────────────────────────────────────────

def test_build_known_customer_menu_no_items():
    org = _org("hybrid", {"known_customer_menu": {"items": []}})
    result = svc.build_known_customer_menu(org, "+2341234567890")
    assert result is None


def test_build_known_customer_menu_with_items():
    org = _org("hybrid", {
        "known_customer_menu": {
            "greeting": "Welcome back!",
            "section_title": "How can we help?",
            "items": [{"id": "kc_1", "label": "Support", "description": "", "action": "support_ticket"}],
        }
    })
    result = svc.build_known_customer_menu(org, "+2341234567890")
    assert result is not None
    rows = result["interactive"]["action"]["sections"][0]["rows"]
    assert rows[0]["id"] == "kc_1"
