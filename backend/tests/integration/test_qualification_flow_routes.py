"""
tests/integration/test_qualification_flow_routes.py
WH-1b: Integration tests for GET/PATCH /api/v1/admin/qualification-flow routes.

Covers:
  - GET: returns config (including null when not set)
  - PATCH: saves valid flow
  - PATCH: rejects > 5 questions
  - PATCH: rejects invalid question type
  - PATCH: rejects invalid map_to_lead_field value
  - PATCH: rejects answer_key with special characters
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import uuid

# ── Constants ────────────────────────────────────────────────────────────────

ORG_ID  = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())

_ORG_PAYLOAD = {
    "id":     USER_ID,          # Pattern 61 — "id" not "user_id"
    "org_id": ORG_ID,
    "roles":  {
        "template":    "owner",
        "permissions": {"manage_settings": True},
    },
}

VALID_QUESTION = {
    "id":               "q1",
    "text":             "What brings you here?",
    "type":             "list_select",
    "answer_key":       "inquiry_reason",
    "map_to_lead_field": None,
    "options": [
        {"id": "a", "label": "Pricing"},
        {"id": "b", "label": "Demo"},
        {"id": "c", "label": "Other"},
    ],
}

VALID_FLOW_PAYLOAD = {
    "opening_message": "Hi there! Tell us about yourself.",
    "handoff_message": "Thanks! Our team will be in touch.",
    "questions": [VALID_QUESTION],
}


@pytest.fixture
def client():
    from app.main import app
    from app.database import get_supabase
    from app.routers.admin import get_current_org

    mock_db = MagicMock()

    def _table(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.update.return_value = chain
        chain.execute.return_value = MagicMock(data={"qualification_flow": None})
        return chain

    mock_db.table.side_effect = _table

    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD  # Pattern 44

    yield TestClient(app), mock_db

    app.dependency_overrides.pop(get_supabase, None)  # Pattern 32
    app.dependency_overrides.pop(get_current_org, None)


class TestGetQualificationFlow:

    def test_returns_config(self, client):
        """GET /admin/qualification-flow returns qualification_flow key."""
        tc, _ = client
        resp = tc.get("/api/v1/admin/qualification-flow")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "qualification_flow" in data

    def test_returns_null_when_not_configured(self, client):
        """When qualification_flow is null in DB, response data contains null."""
        tc, db = client
        # Default mock returns None — already configured in fixture
        resp = tc.get("/api/v1/admin/qualification-flow")
        assert resp.status_code == 200
        assert resp.json()["data"]["qualification_flow"] is None


class TestPatchQualificationFlow:

    def test_saves_valid_flow(self, client):
        """PATCH with a valid flow returns 200 and the saved flow."""
        tc, db = client

        # Mock existing flow fetch + save
        existing_chain = MagicMock()
        existing_chain.execute.return_value = MagicMock(data={"qualification_flow": {}})
        existing_chain.select.return_value = existing_chain
        existing_chain.eq.return_value = existing_chain
        existing_chain.maybe_single.return_value = existing_chain

        update_chain = MagicMock()
        update_chain.execute.return_value = MagicMock(data=[])
        update_chain.eq.return_value = update_chain
        update_chain.update.return_value = update_chain

        call_count = [0]
        def _table(name):
            call_count[0] += 1
            if call_count[0] == 1:
                return existing_chain
            return update_chain

        db.table.side_effect = _table

        resp = tc.patch("/api/v1/admin/qualification-flow", json=VALID_FLOW_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "qualification_flow" in data

    def test_rejects_more_than_5_questions(self, client):
        """PATCH with 6 questions returns 422 validation error."""
        tc, _ = client
        payload = {
            **VALID_FLOW_PAYLOAD,
            "questions": [
                {**VALID_QUESTION, "id": f"q{i}", "answer_key": f"key_{i}"}
                for i in range(6)
            ],
        }
        resp = tc.patch("/api/v1/admin/qualification-flow", json=payload)
        assert resp.status_code == 422

    def test_rejects_invalid_question_type(self, client):
        """PATCH with unknown question type returns 422."""
        tc, _ = client
        payload = {
            **VALID_FLOW_PAYLOAD,
            "questions": [{
                **VALID_QUESTION,
                "type": "radio_button",  # invalid
            }],
        }
        resp = tc.patch("/api/v1/admin/qualification-flow", json=payload)
        assert resp.status_code == 422

    def test_rejects_invalid_map_to_lead_field(self, client):
        """PATCH with non-allowlisted map_to_lead_field returns 422."""
        tc, _ = client
        payload = {
            **VALID_FLOW_PAYLOAD,
            "questions": [{
                **VALID_QUESTION,
                "map_to_lead_field": "email",  # not in allowlist
            }],
        }
        resp = tc.patch("/api/v1/admin/qualification-flow", json=payload)
        assert resp.status_code == 422

    def test_rejects_answer_key_with_special_characters(self, client):
        """PATCH with answer_key containing special chars returns 422."""
        tc, _ = client
        payload = {
            **VALID_FLOW_PAYLOAD,
            "questions": [{
                **VALID_QUESTION,
                "answer_key": "my-key!",  # hyphens and ! not allowed
            }],
        }
        resp = tc.patch("/api/v1/admin/qualification-flow", json=payload)
        assert resp.status_code == 422
