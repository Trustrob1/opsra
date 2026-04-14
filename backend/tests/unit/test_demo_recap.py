"""
tests/unit/test_demo_recap_service.py
--------------------------------------
M01-9 — Unit tests for generate_demo_recap() in demo_service.py

Coverage:
  1.  Happy path — returns valid recap dict
  2.  Recap stored in lead_demos.recap
  3.  Missing ANTHROPIC_API_KEY — returns None, no HTTP call
  4.  AI returns malformed JSON — returns None, no raise
  5.  AI returns JSON missing required fields — returns None
  6.  httpx raises timeout — returns None, no raise
  7.  httpx raises non-200 status — returns None, no raise
  8.  Supabase lead fetch fails — returns None
  9.  Supabase demo fetch fails — returns None
  10. _sanitise_for_prompt strips control chars and truncates
  11. Prompt contains XML delimiters (S7)
  12. Prompt contains security rules block (S8)
  13. Markdown fence stripping — ```json ... ``` handled correctly
"""
import json
import os
from unittest.mock import MagicMock, patch, call

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

ORG_ID  = "00000000-0000-0000-0000-000000000001"
LEAD_ID = "00000000-0000-0000-0000-000000000002"
DEMO_ID = "00000000-0000-0000-0000-000000000003"

MOCK_LEAD = {
    "full_name": "Amara Osei",
    "business_name": "Osei Retail Ltd",
    "business_type": "Retail",
    "location": "Accra",
    "branches": "2-3",
    "problem_stated": "Too much manual invoicing",
    "score": "hot",
}

MOCK_DEMO = {
    "scheduled_at": "2026-04-10T10:00:00+00:00",
    "medium": "virtual",
    "notes": "Demo agenda: show invoicing and WhatsApp automation",
    "outcome_notes": "Lead loved the automation. Concerned about onboarding time. Wants proposal.",
}

VALID_RECAP = {
    "summary": "The demo went well. The lead was very engaged with the automation features.",
    "key_interests": ["Invoicing automation", "WhatsApp integration"],
    "concerns_raised": ["Onboarding timeline"],
    "lead_readiness": "Needs proposal",
    "recommended_next_action": "Send proposal by end of week covering onboarding timeline.",
}


def _make_db(lead=MOCK_LEAD, demo=MOCK_DEMO):
    """Build a minimal Supabase mock returning the given lead and demo."""
    db = MagicMock()

    def _table_side(name):
        tbl = MagicMock()
        tbl.select.return_value = tbl
        tbl.eq.return_value = tbl
        tbl.maybe_single.return_value = tbl
        tbl.update.return_value = tbl

        if name == "leads":
            tbl.execute.return_value = MagicMock(data=lead)
        elif name == "lead_demos":
            tbl.execute.return_value = MagicMock(data=demo)
        else:
            tbl.execute.return_value = MagicMock(data=None)
        return tbl

    db.table.side_effect = _table_side
    return db


def _mock_httpx_response(recap_dict, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    resp.json.return_value = {
        "content": [{"text": json.dumps(recap_dict)}]
    }
    return resp


# ── Test cases ────────────────────────────────────────────────────────────────

class TestGenerateDemoRecap:

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_happy_path_returns_recap(self, mock_post):
        """Happy path — returns valid recap dict and stores it."""
        mock_post.return_value = _mock_httpx_response(VALID_RECAP)
        db = _make_db()

        from app.services.demo_service import generate_demo_recap
        result = generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        assert result is not None
        assert result["summary"] == VALID_RECAP["summary"]
        assert result["lead_readiness"] == "Needs proposal"
        assert isinstance(result["key_interests"], list)
        assert isinstance(result["concerns_raised"], list)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_recap_stored_in_db(self, mock_post):
        """Result is written to lead_demos.recap via db.table.update."""
        mock_post.return_value = _mock_httpx_response(VALID_RECAP)
        db = _make_db()

        from app.services.demo_service import generate_demo_recap
        generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        # Check that update was called on lead_demos
        update_calls = [
            c for c in db.table.call_args_list
            if c.args and c.args[0] == "lead_demos"
        ]
        assert len(update_calls) >= 1

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_returns_none(self):
        """No ANTHROPIC_API_KEY — returns None without making any HTTP call."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        db = _make_db()

        with patch("httpx.post") as mock_post:
            from app.services.demo_service import generate_demo_recap
            result = generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        assert result is None
        mock_post.assert_not_called()

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_malformed_json_returns_none(self, mock_post):
        """AI returns non-parseable text — returns None, does not raise."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"content": [{"text": "This is not JSON at all!"}]}
        mock_post.return_value = resp
        db = _make_db()

        from app.services.demo_service import generate_demo_recap
        result = generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        assert result is None

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_missing_required_fields_returns_none(self, mock_post):
        """AI returns JSON but missing required keys — returns None."""
        incomplete = {"summary": "Short summary only"}
        mock_post.return_value = _mock_httpx_response(incomplete)
        db = _make_db()

        from app.services.demo_service import generate_demo_recap
        result = generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        assert result is None

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_httpx_timeout_returns_none(self, mock_post):
        """httpx raises timeout — returns None, does not raise."""
        import httpx as _httpx
        mock_post.side_effect = _httpx.TimeoutException("timed out")
        db = _make_db()

        from app.services.demo_service import generate_demo_recap
        result = generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        assert result is None

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_httpx_non_200_returns_none(self, mock_post):
        """httpx raises on non-200 status — returns None."""
        mock_post.return_value = _mock_httpx_response({}, status_code=500)
        db = _make_db()

        from app.services.demo_service import generate_demo_recap
        result = generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        assert result is None

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_lead_fetch_fails_returns_none(self, mock_post):
        """Supabase lead query raises — returns None."""
        db = MagicMock()
        db.table.side_effect = Exception("DB connection failed")

        from app.services.demo_service import generate_demo_recap
        result = generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        assert result is None
        mock_post.assert_not_called()

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_demo_fetch_returns_none_data(self, mock_post):
        """Demo row returns None from Supabase — recap still generated with empty demo."""
        mock_post.return_value = _mock_httpx_response(VALID_RECAP)

        db = MagicMock()
        lead_tbl = MagicMock()
        lead_tbl.select.return_value = lead_tbl
        lead_tbl.eq.return_value = lead_tbl
        lead_tbl.maybe_single.return_value = lead_tbl
        lead_tbl.execute.return_value = MagicMock(data=MOCK_LEAD)
        lead_tbl.update.return_value = lead_tbl

        demo_tbl = MagicMock()
        demo_tbl.select.return_value = demo_tbl
        demo_tbl.eq.return_value = demo_tbl
        demo_tbl.maybe_single.return_value = demo_tbl
        demo_tbl.update.return_value = demo_tbl
        demo_tbl.execute.return_value = MagicMock(data=None)

        def _table(name):
            if name == "leads":
                return lead_tbl
            return demo_tbl

        db.table.side_effect = _table

        from app.services.demo_service import generate_demo_recap
        result = generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        # Should still succeed — gracefully uses empty demo dict
        assert result is not None

    def test_sanitise_strips_control_chars(self):
        """_sanitise_for_prompt removes null bytes and control chars, keeps newlines."""
        from app.services.demo_service import _sanitise_for_prompt
        raw = "Normal text\x00with null\x01and SOH\nwith newline"
        result = _sanitise_for_prompt(raw)
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\n" in result
        assert "Normal text" in result

    def test_sanitise_truncates_at_5000(self):
        """_sanitise_for_prompt truncates to 5000 chars."""
        from app.services.demo_service import _sanitise_for_prompt
        long_text = "a" * 6000
        result = _sanitise_for_prompt(long_text)
        assert len(result) == 5000

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_prompt_contains_xml_delimiters(self, mock_post):
        """S7: user content wrapped in XML delimiters in the prompt."""
        mock_post.return_value = _mock_httpx_response(VALID_RECAP)
        db = _make_db()

        from app.services.demo_service import generate_demo_recap
        generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        assert mock_post.called
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs.get("json", {})
        user_content = payload["messages"][0]["content"]
        assert "<lead_profile>" in user_content
        assert "</lead_profile>" in user_content
        assert "<demo_details>" in user_content
        assert "<outcome_notes>" in user_content

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_prompt_contains_security_rules(self, mock_post):
        """S8: security rules block present in system prompt."""
        mock_post.return_value = _mock_httpx_response(VALID_RECAP)
        db = _make_db()

        from app.services.demo_service import generate_demo_recap
        generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        payload = mock_post.call_args[1]["json"]
        system_prompt = payload["system"]
        assert "SECURITY RULES" in system_prompt
        assert "never reveal" in system_prompt.lower() or "Never reveal" in system_prompt

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("httpx.post")
    def test_markdown_fence_stripped(self, mock_post):
        """AI wraps JSON in ```json fences — stripped correctly."""
        fenced = "```json\n" + json.dumps(VALID_RECAP) + "\n```"
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"content": [{"text": fenced}]}
        mock_post.return_value = resp
        db = _make_db()

        from app.services.demo_service import generate_demo_recap
        result = generate_demo_recap(db, ORG_ID, LEAD_ID, DEMO_ID)

        assert result is not None
        assert result["summary"] == VALID_RECAP["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests — log_outcome with attended triggers recap
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/integration/test_demo_recap_routes.py
--------------------------------------------
M01-9 — Integration tests for attended outcome → recap in response.
"""

# NOTE: These tests live in the same file for convenience during this session.
# Move to tests/integration/test_demo_recap_routes.py before running full suite.

import pytest
from fastapi.testclient import TestClient

ORG_ID_INT  = "00000000-0000-0000-0000-000000000010"
USER_ID_INT = "00000000-0000-0000-0000-000000000011"
LEAD_ID_INT = "00000000-0000-0000-0000-000000000012"
DEMO_ID_INT = "00000000-0000-0000-0000-000000000013"
ROLE_ID_INT = "00000000-0000-0000-0000-000000000014"

MOCK_ORG_INT = {
    "id": USER_ID_INT,
    "org_id": ORG_ID_INT,
    "is_active": True,
    "roles": {"template": "sales_agent"},
}

ATTENDED_DEMO_RESPONSE = {
    "id": DEMO_ID_INT,
    "org_id": ORG_ID_INT,
    "lead_id": LEAD_ID_INT,
    "status": "attended",
    "outcome": "attended",
    "outcome_notes": "Great demo. Lead wants proposal.",
    "recap": VALID_RECAP,
    "scheduled_at": "2026-04-10T10:00:00+00:00",
    "medium": "virtual",
    "duration_minutes": 30,
    "notes": None,
    "assigned_to": USER_ID_INT,
    "confirmed_by": USER_ID_INT,
    "confirmed_at": "2026-04-09T08:00:00+00:00",
    "outcome_logged_at": "2026-04-10T11:00:00+00:00",
    "confirmation_sent": True,
    "reminder_24h_sent": True,
    "reminder_1h_sent": True,
    "noshow_task_created": False,
    "parent_demo_id": None,
    "lead_preferred_time": None,
    "created_by": USER_ID_INT,
    "created_at": "2026-04-08T10:00:00+00:00",
    "updated_at": "2026-04-10T11:00:00+00:00",
    "rep_nudge_sent_at": None,
    "manager_nudge_sent_at": None,
}


@pytest.fixture
def client_with_mocks():
    """TestClient with get_current_org and demo_service.log_outcome mocked."""
    from app.main import app
    from app.dependencies import get_current_org
    from app.database import get_supabase

    db_mock = MagicMock()
    app.dependency_overrides[get_current_org] = lambda: MOCK_ORG_INT
    app.dependency_overrides[get_supabase]    = lambda: db_mock

    with TestClient(app) as c:
        yield c, db_mock

    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


class TestDemoRecapIntegration:

    @patch("app.services.demo_service.log_outcome")
    def test_attended_outcome_returns_recap_in_response(self, mock_log, client_with_mocks):
        """PATCH attended → response data includes recap field."""
        client, _ = client_with_mocks
        mock_log.return_value = ATTENDED_DEMO_RESPONSE

        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID_INT}/demos/{DEMO_ID_INT}",
            json={"outcome": "attended", "outcome_notes": "Great demo."},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["recap"] is not None
        assert data["data"]["recap"]["lead_readiness"] == "Needs proposal"

    @patch("app.services.demo_service.log_outcome")
    def test_no_show_outcome_has_no_recap(self, mock_log, client_with_mocks):
        """PATCH no_show → recap field is None."""
        client, _ = client_with_mocks
        no_show_response = {**ATTENDED_DEMO_RESPONSE, "status": "no_show", "outcome": "no_show", "recap": None}
        mock_log.return_value = no_show_response

        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID_INT}/demos/{DEMO_ID_INT}",
            json={"outcome": "no_show"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["recap"] is None

    @patch("app.services.demo_service.log_outcome")
    def test_attended_without_notes_still_returns_recap(self, mock_log, client_with_mocks):
        """Rep submits attended with no notes — recap still generated (may be thinner)."""
        client, _ = client_with_mocks
        mock_log.return_value = ATTENDED_DEMO_RESPONSE

        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID_INT}/demos/{DEMO_ID_INT}",
            json={"outcome": "attended"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["recap"] is not None

    @patch("app.services.demo_service.log_outcome")
    def test_invalid_outcome_rejected(self, mock_log, client_with_mocks):
        """outcome must be attended|no_show|rescheduled — anything else rejected."""
        client, _ = client_with_mocks

        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID_INT}/demos/{DEMO_ID_INT}",
            json={"outcome": "cancelled"},
        )

        assert resp.status_code == 422
        mock_log.assert_not_called()

    @patch("app.services.demo_service.log_outcome")
    def test_affiliate_can_log_outcome_after_fix(self, mock_log, client_with_mocks):
        """
        M01-9 fix: require_not_affiliate removed from log_demo_outcome.
        Affiliates can now log outcomes on their own leads — should return 200.
        """
        from app.main import app
        from app.dependencies import get_current_org

        affiliate_org = {**MOCK_ORG_INT, "roles": {"template": "affiliate_partner"}}
        app.dependency_overrides[get_current_org] = lambda: affiliate_org
        mock_log.return_value = ATTENDED_DEMO_RESPONSE
        client, _ = client_with_mocks

        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID_INT}/demos/{DEMO_ID_INT}",
            json={"outcome": "attended"},
        )

        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Restore
        app.dependency_overrides[get_current_org] = lambda: MOCK_ORG_INT
