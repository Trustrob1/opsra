"""
tests/integration/test_lead_form_routes.py

Integration tests for M01-2 — hosted web form lead capture:
  GET  /api/v1/leads/forms/{org_slug}  — serves HTML form (no JWT)
  GET  /api/v1/leads/form/{org_slug}   — returns org config JSON (no JWT)
  POST /api/v1/leads/capture           — accepts public form submission (no JWT)

All three routes are public — no get_current_org override needed.
get_supabase still overridden per Pattern 3.

Patterns:
  - Pattern 3  : get_supabase ALWAYS overridden
  - Pattern 9  : normalise list vs dict
  - Pattern 32 : pop() teardown
  - S14        : duplicate lead on capture returns 200 with success message
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID   = "00000000-0000-0000-0000-000000000001"
ORG_SLUG = "test-org"
ORG_NAME = "Test Organisation"
LEAD_ID  = "00000000-0000-0000-0000-000000000010"

_ORG_ROW = {"id": ORG_ID, "name": ORG_NAME, "slug": ORG_SLUG}

_NEW_LEAD = {
    "id":       LEAD_ID,
    "org_id":   ORG_ID,
    "full_name": "Emeka Obi",
    "phone":    "08012345678",
    "source":   "landing_page",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chain(data=None):
    chain = MagicMock()
    result = MagicMock()
    result.data = data if data is not None else []
    chain.execute.return_value = result
    for m in ("select", "eq", "is_", "maybe_single", "insert",
              "update", "order", "limit", "neq", "in_"):
        getattr(chain, m).return_value = chain
    return chain


def _db_with_org(org_row=_ORG_ROW):
    db = MagicMock()
    org_chain = _chain(org_row)

    def _tbl(name):
        if name == "organisations": return org_chain
        if name == "leads":         return _chain([])
        if name == "audit_logs":    return _chain([])
        if name == "lead_timeline": return _chain([])
        if name == "notifications": return _chain([])
        return _chain()

    db.table.side_effect = _tbl
    return db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from app.main import app
    from app.database import get_supabase
    db = _db_with_org()
    app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(app, raise_server_exceptions=False), db
    app.dependency_overrides.pop(get_supabase, None)


@pytest.fixture
def client_no_org():
    """Client whose DB returns no org for any slug."""
    from app.main import app
    from app.database import get_supabase
    db = _db_with_org(org_row=None)
    app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(app, raise_server_exceptions=False), db
    app.dependency_overrides.pop(get_supabase, None)


# ===========================================================================
# GET /api/v1/leads/form/{org_slug} — org config JSON
# ===========================================================================

class TestGetFormConfig:

    def test_returns_200_with_org_name(self, client):
        tc, _ = client
        resp = tc.get(f"/api/v1/leads/form/{ORG_SLUG}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["org_name"] == ORG_NAME
        assert data["org_slug"] == ORG_SLUG

    def test_returns_404_for_unknown_slug(self, client_no_org):
        tc, _ = client_no_org
        resp = tc.get("/api/v1/leads/form/unknown-slug")
        assert resp.status_code == 404

    def test_no_jwt_required(self, client):
        """Route is public — no Authorization header needed."""
        tc, _ = client
        resp = tc.get(f"/api/v1/leads/form/{ORG_SLUG}")
        assert resp.status_code == 200

    def test_response_envelope_shape(self, client):
        tc, _ = client
        resp = tc.get(f"/api/v1/leads/form/{ORG_SLUG}")
        body = resp.json()
        assert body["success"] is True
        assert "org_name" in body["data"]
        assert "org_slug" in body["data"]


# ===========================================================================
# POST /api/v1/leads/capture — form submission
# ===========================================================================

class TestCaptureLeadRoute:

    _VALID_PAYLOAD = {
        "org_slug":       ORG_SLUG,
        "full_name":      "Emeka Obi",
        "phone":          "08012345678",
        "email":          "emeka@store.com",
        "business_name":  "Emeka Supermart",
        "business_type":  "Supermarket",
        "problem_stated": "We lose track of stock.",
        "utm_source":     "facebook",
        "utm_campaign":   "march_launch",
        "utm_ad":         "supermarket_v1",
    }

    def test_valid_submission_returns_201(self, client):
        tc, _ = client
        with patch("app.routers.leads.lead_service.create_lead",
                   return_value=_NEW_LEAD):
            resp = tc.post("/api/v1/leads/capture", json=self._VALID_PAYLOAD)
        assert resp.status_code == 201
        assert resp.json()["success"] is True

    def test_success_message_in_response(self, client):
        tc, _ = client
        with patch("app.routers.leads.lead_service.create_lead",
                   return_value=_NEW_LEAD):
            resp = tc.post("/api/v1/leads/capture", json=self._VALID_PAYLOAD)
        assert "Thank you" in resp.json()["message"]

    def test_lead_created_with_landing_page_source(self, client):
        tc, _ = client
        with patch("app.routers.leads.lead_service.create_lead",
                   return_value=_NEW_LEAD) as mock_create:
            tc.post("/api/v1/leads/capture", json=self._VALID_PAYLOAD)
        _, kwargs = mock_create.call_args
        assert kwargs["payload"].source == "landing_page"

    def test_utm_fields_passed_to_lead(self, client):
        tc, _ = client
        with patch("app.routers.leads.lead_service.create_lead",
                   return_value=_NEW_LEAD) as mock_create:
            tc.post("/api/v1/leads/capture", json=self._VALID_PAYLOAD)
        _, kwargs = mock_create.call_args
        payload = kwargs["payload"]
        assert payload.utm_source   == "facebook"
        assert payload.utm_campaign == "march_launch"
        assert payload.utm_ad       == "supermarket_v1"

    def test_minimal_payload_only_required_fields(self, client):
        """Only full_name, phone, org_slug required — all others optional."""
        tc, _ = client
        with patch("app.routers.leads.lead_service.create_lead",
                   return_value=_NEW_LEAD):
            resp = tc.post("/api/v1/leads/capture", json={
                "org_slug":  ORG_SLUG,
                "full_name": "Ada Eze",
                "phone":     "07011111111",
            })
        assert resp.status_code == 201

    def test_unknown_org_slug_returns_404(self, client_no_org):
        tc, _ = client_no_org
        resp = tc.post("/api/v1/leads/capture", json={
            "org_slug":  "unknown-org",
            "full_name": "Test User",
            "phone":     "08099999999",
        })
        assert resp.status_code == 404

    def test_missing_required_fields_returns_422(self, client):
        """Pydantic validation — full_name missing → 422."""
        tc, _ = client
        resp = tc.post("/api/v1/leads/capture", json={
            "org_slug": ORG_SLUG,
            "phone":    "08012345678",
            # full_name missing
        })
        assert resp.status_code == 422

    def test_missing_phone_returns_422(self, client):
        tc, _ = client
        resp = tc.post("/api/v1/leads/capture", json={
            "org_slug":  ORG_SLUG,
            "full_name": "Test User",
            # phone missing
        })
        assert resp.status_code == 422

    def test_duplicate_lead_returns_201_not_409(self, client):
        """
        Duplicate detection fires → capture returns 201 with success message.
        We never tell the form submitter it was a duplicate — they just see success.
        """
        from fastapi import HTTPException
        from app.models.common import ErrorCode
        tc, _ = client
        dup_exc = HTTPException(
            status_code=409,
            detail={"code": ErrorCode.DUPLICATE_DETECTED, "message": "Duplicate"},
        )
        with patch("app.routers.leads.lead_service.create_lead",
                   side_effect=dup_exc):
            resp = tc.post("/api/v1/leads/capture", json=self._VALID_PAYLOAD)
        assert resp.status_code == 201
        assert "Thank you" in resp.json()["message"]

    def test_no_jwt_required(self, client):
        """Route is public — no Authorization header."""
        tc, _ = client
        with patch("app.routers.leads.lead_service.create_lead",
                   return_value=_NEW_LEAD):
            resp = tc.post("/api/v1/leads/capture", json=self._VALID_PAYLOAD)
        assert resp.status_code == 201

    def test_system_user_id_used(self, client):
        """Public form submissions use user_id='system', not a real user."""
        tc, _ = client
        with patch("app.routers.leads.lead_service.create_lead",
                   return_value=_NEW_LEAD) as mock_create:
            tc.post("/api/v1/leads/capture", json=self._VALID_PAYLOAD)
        _, kwargs = mock_create.call_args
        assert kwargs["user_id"] == "system"


# ===========================================================================
# GET /api/v1/leads/forms/{org_slug} — HTML form serving
# ===========================================================================

class TestServeLeadForm:

    def test_returns_html_response(self, client):
        tc, _ = client
        # Patch the template file read so test doesn't need filesystem
        html = "<html><body>ORG_SLUG='{{ORG_SLUG}}' API_BASE='{{API_BASE}}'</body></html>"
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value=html):
            resp = tc.get(f"/api/v1/leads/forms/{ORG_SLUG}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_org_slug_injected_into_html(self, client):
        tc, _ = client
        html = "const ORG_SLUG = '{{ORG_SLUG}}';"
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value=html):
            resp = tc.get(f"/api/v1/leads/forms/{ORG_SLUG}")
        assert ORG_SLUG in resp.text
        assert "{{ORG_SLUG}}" not in resp.text

    def test_api_base_injected_into_html(self, client):
        tc, _ = client
        html = "const API_BASE = '{{API_BASE}}';"
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value=html):
            resp = tc.get(f"/api/v1/leads/forms/{ORG_SLUG}")
        assert "{{API_BASE}}" not in resp.text

    def test_returns_404_when_template_missing(self, client):
        tc, _ = client
        with patch("pathlib.Path.exists", return_value=False):
            resp = tc.get(f"/api/v1/leads/forms/{ORG_SLUG}")
        assert resp.status_code == 404

    def test_no_jwt_required(self, client):
        tc, _ = client
        html = "<html><body>{{ORG_SLUG}} {{API_BASE}}</body></html>"
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value=html):
            resp = tc.get(f"/api/v1/leads/forms/{ORG_SLUG}")
        assert resp.status_code == 200
