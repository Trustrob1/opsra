"""
tests/integration/test_ai_agent_routes.py
AI-AGENT-1C — integration tests for the 5 new admin routes:
  GET/PATCH /api/v1/admin/ai-agent-config
  GET/POST  /api/v1/admin/whatsapp-numbers
  PATCH     /api/v1/admin/whatsapp-numbers/{number_id}

Conventions followed (per Build Status patterns):
  Pattern 32 — class-based, autouse fixture overrides + pops dependencies.
  Pattern 37 — org["roles"]["template"], not org.get("role").
  Pattern 44 — override get_current_org directly.
  Pattern 58 — _ORG_PAYLOAD nests permissions/template inside "roles".
  Pattern 61 — user UUID is at org["id"], never org["user_id"].
  Pattern 62 — db injected via Depends(get_supabase); TestClient + overrides.
  Pattern 63 — lazy `from app.services.ai_agent_service import
               _get_or_create_ai_agent_user` inside the route body is patched
               at "app.services.ai_agent_service._get_or_create_ai_agent_user".
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

ORG_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "22222222-2222-2222-2222-222222222222"
NUMBER_ID = "33333333-3333-3333-3333-333333333333"
AGENT_USER_ID = "44444444-4444-4444-4444-444444444444"


def _org_payload(template="owner"):
    return {"id": USER_ID, "org_id": ORG_ID, "roles": {"template": template}}


def _chain(data):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.limit.return_value = chain
    chain.maybe_single.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.execute.return_value = MagicMock(data=data)
    return chain


def _table_side(mapping, default=None):
    """mapping: {table_name: data}. Returns a db.table side_effect function."""
    def side(name):
        if name in mapping:
            return _chain(mapping[name])
        return _chain(default if default is not None else [])
    return side


# ═══════════════════════════════════════════════════════════════════════════
# GET/PATCH /api/v1/admin/ai-agent-config
# ═══════════════════════════════════════════════════════════════════════════

class TestAIAgentConfigRoutes:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _org_payload("owner")
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_AIR_I_01_get_returns_existing_config(self):
        """AIR-I-01: GET returns the org's ai_agent_config."""
        self.mock_db.table.side_effect = _table_side({
            "organisations": {"ai_agent_config": {"business_model": "physical_product"}},
        })
        with TestClient(app) as client:
            resp = client.get("/api/v1/admin/ai-agent-config")
        assert resp.status_code == 200
        assert resp.json()["data"]["business_model"] == "physical_product"

    def test_AIR_I_02_get_returns_default_empty_config(self):
        """AIR-I-02: GET returns {} when ai_agent_config is null."""
        self.mock_db.table.side_effect = _table_side({"organisations": None})
        with TestClient(app) as client:
            resp = client.get("/api/v1/admin/ai-agent-config")
        assert resp.status_code == 200
        assert resp.json()["data"] == {}

    def test_AIR_I_03_patch_owner_can_update(self):
        """AIR-I-03: owner PATCH merges and saves config, 200."""
        self.mock_db.table.side_effect = _table_side({
            "organisations": {"ai_agent_config": {"business_model": "physical_product"}},
            "whatsapp_numbers": [],  # no numbers in ai_agent mode yet — gate doesn't block
        })
        with TestClient(app) as client:
            resp = client.patch(
                "/api/v1/admin/ai-agent-config",
                json={"qualifying_criteria": "Has budget and wants delivery this week"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["qualifying_criteria"] == "Has budget and wants delivery this week"
        assert resp.json()["data"]["business_model"] == "physical_product"  # merged, not overwritten

    def test_AIR_I_04_patch_non_owner_gets_403(self):
        """AIR-I-04: sales_agent role → 403 FORBIDDEN."""
        app.dependency_overrides[get_current_org] = lambda: _org_payload("sales_agent")
        with TestClient(app) as client:
            resp = client.patch(
                "/api/v1/admin/ai-agent-config",
                json={"qualifying_criteria": "x"},
            )
        assert resp.status_code == 403

    def test_AIR_I_05_patch_rejects_empty_qualifying_criteria_when_number_active(self):
        """AIR-I-05: a number already running ai_agent + empty qualifying_criteria → 422."""
        self.mock_db.table.side_effect = _table_side({
            "organisations": {"ai_agent_config": {"qualifying_criteria": "existing"}},
            "whatsapp_numbers": [{"id": NUMBER_ID}],  # a number IS in ai_agent mode
        })
        with TestClient(app) as client:
            resp = client.patch(
                "/api/v1/admin/ai-agent-config",
                json={"qualifying_criteria": ""},
            )
        assert resp.status_code == 422

    def test_AIR_I_06_patch_field_validation_rejects_bad_business_model(self):
        """AIR-I-06: business_model outside the 4 allowed enum values → 422."""
        with TestClient(app) as client:
            resp = client.patch(
                "/api/v1/admin/ai-agent-config",
                json={"business_model": "not_a_real_type"},
            )
        assert resp.status_code == 422

    def test_AIR_I_07_patch_rejects_max_turns_out_of_range(self):
        """AIR-I-07: max_turns_before_escalation outside 5-50 → 422."""
        with TestClient(app) as client:
            resp = client.patch(
                "/api/v1/admin/ai-agent-config",
                json={"max_turns_before_escalation": 100},
            )
        assert resp.status_code == 422

    def test_AIR_I_08_patch_rejects_too_many_fields_to_extract(self):
        """AIR-I-08: fields_to_extract > 5 items → 422."""
        with TestClient(app) as client:
            resp = client.patch(
                "/api/v1/admin/ai-agent-config",
                json={"fields_to_extract": [
                    {"answer_key": f"k{i}", "map_to_lead_field": None} for i in range(6)
                ]},
            )
        assert resp.status_code == 422

    def test_AIR_I_09_patch_rejects_invalid_map_to_lead_field(self):
        """AIR-I-09: map_to_lead_field outside the allow-list → 422."""
        with TestClient(app) as client:
            resp = client.patch(
                "/api/v1/admin/ai-agent-config",
                json={"fields_to_extract": [
                    {"answer_key": "k1", "map_to_lead_field": "not_a_real_field"}
                ]},
            )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# GET/POST /api/v1/admin/whatsapp-numbers
# ═══════════════════════════════════════════════════════════════════════════

class TestWhatsAppNumbersListCreateRoutes:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _org_payload("owner")
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_AIR_I_10_get_returns_numbers_with_masked_token(self):
        """AIR-I-10: GET returns numbers list; access_token never in plain, only masked."""
        self.mock_db.table.side_effect = _table_side({
            "whatsapp_numbers": [{
                "id": NUMBER_ID, "phone_id": "phone-1", "access_token": "supersecrettoken123",
                "waba_id": "waba-1", "label": "Primary", "wa_sales_mode": "human",
                "is_primary": True, "created_at": "2026-07-01T00:00:00Z",
            }],
        })
        with TestClient(app) as client:
            resp = client.get("/api/v1/admin/whatsapp-numbers")
        assert resp.status_code == 200
        row = resp.json()["data"][0]
        assert "access_token" not in row
        assert row["access_token_masked"].endswith("123")
        assert row["access_token_masked"].startswith("••••••")

    def test_AIR_I_11_post_owner_can_create_human_mode(self):
        """AIR-I-11: owner creates a number in default 'human' mode → 201."""
        self.mock_db.table.side_effect = _table_side({
            "whatsapp_numbers": [{
                "id": NUMBER_ID, "phone_id": "phone-2", "access_token": "tok-abcdef",
                "waba_id": "waba-2", "label": "Second Line", "wa_sales_mode": "human",
                "is_primary": False,
            }],
        })
        with TestClient(app) as client:
            resp = client.post("/api/v1/admin/whatsapp-numbers", json={
                "phone_id": "phone-2", "access_token": "tok-abcdef",
                "waba_id": "waba-2", "label": "Second Line",
            })
        assert resp.status_code == 201
        assert "access_token" not in resp.json()["data"]

    def test_AIR_I_12_post_non_owner_gets_403(self):
        """AIR-I-12: sales_agent role → 403, no insert attempted."""
        app.dependency_overrides[get_current_org] = lambda: _org_payload("sales_agent")
        with TestClient(app) as client:
            resp = client.post("/api/v1/admin/whatsapp-numbers", json={
                "phone_id": "p", "access_token": "t", "waba_id": "w", "label": "L",
            })
        assert resp.status_code == 403

    def test_AIR_I_13_post_ai_agent_mode_without_qualifying_criteria_rejected(self):
        """AIR-I-13: wa_sales_mode='ai_agent' + no qualifying_criteria set → 422."""
        self.mock_db.table.side_effect = _table_side({
            "organisations": {"ai_agent_config": {}},  # no qualifying_criteria
        })
        with TestClient(app) as client:
            resp = client.post("/api/v1/admin/whatsapp-numbers", json={
                "phone_id": "p", "access_token": "t", "waba_id": "w", "label": "L",
                "wa_sales_mode": "ai_agent",
            })
        assert resp.status_code == 422

    def test_AIR_I_14_post_ai_agent_mode_with_criteria_creates_agent_user(self):
        """AIR-I-14: valid ai_agent creation → 201, _get_or_create_ai_agent_user called
        (Pattern 63 — patched at source module, since it's a lazy import in admin.py)."""
        self.mock_db.table.side_effect = _table_side({
            "organisations": {"ai_agent_config": {"qualifying_criteria": "has budget"}},
            "whatsapp_numbers": [{
                "id": NUMBER_ID, "phone_id": "p", "access_token": "t",
                "waba_id": "w", "label": "L", "wa_sales_mode": "ai_agent", "is_primary": False,
            }],
        })
        with patch(
            "app.services.ai_agent_service._get_or_create_ai_agent_user",
            return_value=AGENT_USER_ID,
        ) as mock_get_agent:
            with TestClient(app) as client:
                resp = client.post("/api/v1/admin/whatsapp-numbers", json={
                    "phone_id": "p", "access_token": "t", "waba_id": "w", "label": "L",
                    "wa_sales_mode": "ai_agent",
                })
        assert resp.status_code == 201
        mock_get_agent.assert_called_once()

    def test_AIR_I_15_post_validation_error_on_missing_required_field(self):
        """AIR-I-15: missing required field (e.g. label) → 422 from Pydantic."""
        with TestClient(app) as client:
            resp = client.post("/api/v1/admin/whatsapp-numbers", json={
                "phone_id": "p", "access_token": "t", "waba_id": "w",
            })
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /api/v1/admin/whatsapp-numbers/{number_id}
# ═══════════════════════════════════════════════════════════════════════════

class TestWhatsAppNumberUpdateRoute:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _org_payload("owner")
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_AIR_I_16_owner_can_update_label(self):
        """AIR-I-16: owner PATCH label only → 200."""
        self.mock_db.table.side_effect = _table_side({
            "whatsapp_numbers": {"id": NUMBER_ID},  # existence check
        })
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/admin/whatsapp-numbers/{NUMBER_ID}",
                json={"label": "Renamed Line"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["label"] == "Renamed Line"

    def test_AIR_I_17_404_when_number_not_found(self):
        """AIR-I-17: number_id not found for this org → 404."""
        self.mock_db.table.side_effect = _table_side({"whatsapp_numbers": None})
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/admin/whatsapp-numbers/{NUMBER_ID}",
                json={"label": "Whatever"},
            )
        assert resp.status_code == 404

    def test_AIR_I_18_422_when_no_fields_given(self):
        """AIR-I-18: empty payload → 422 (nothing to update)."""
        self.mock_db.table.side_effect = _table_side({
            "whatsapp_numbers": {"id": NUMBER_ID},
        })
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/admin/whatsapp-numbers/{NUMBER_ID}",
                json={},
            )
        assert resp.status_code == 422

    def test_AIR_I_19_non_owner_gets_403(self):
        """AIR-I-19: sales_agent role → 403."""
        app.dependency_overrides[get_current_org] = lambda: _org_payload("sales_agent")
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/admin/whatsapp-numbers/{NUMBER_ID}",
                json={"label": "x"},
            )
        assert resp.status_code == 403

    def test_AIR_I_20_mode_change_to_ai_agent_without_criteria_rejected(self):
        """AIR-I-20: switching an existing number to ai_agent without qualifying_criteria → 422."""
        self.mock_db.table.side_effect = _table_side({
            "whatsapp_numbers": {"id": NUMBER_ID},
            "organisations": {"ai_agent_config": {}},
        })
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/admin/whatsapp-numbers/{NUMBER_ID}",
                json={"wa_sales_mode": "ai_agent"},
            )
        assert resp.status_code == 422

    def test_AIR_I_21_mode_change_to_ai_agent_with_criteria_creates_agent_user(self):
        """AIR-I-21: valid mode switch to ai_agent → 200, agent user creation attempted."""
        self.mock_db.table.side_effect = _table_side({
            "whatsapp_numbers": {"id": NUMBER_ID},
            "organisations": {"ai_agent_config": {"qualifying_criteria": "has budget"}},
        })
        with patch(
            "app.services.ai_agent_service._get_or_create_ai_agent_user",
            return_value=AGENT_USER_ID,
        ) as mock_get_agent:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/admin/whatsapp-numbers/{NUMBER_ID}",
                    json={"wa_sales_mode": "ai_agent"},
                )
        assert resp.status_code == 200
        mock_get_agent.assert_called_once()

    def test_AIR_I_22_credentials_not_updatable_via_this_route(self):
        """AIR-I-22: phone_id/access_token/waba_id are not fields on WhatsAppNumberUpdate —
        passing them is silently ignored (extra fields), not applied."""
        self.mock_db.table.side_effect = _table_side({
            "whatsapp_numbers": {"id": NUMBER_ID},
        })
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/admin/whatsapp-numbers/{NUMBER_ID}",
                json={"label": "New Label", "access_token": "should-be-ignored"},
            )
        assert resp.status_code == 200
        assert "access_token" not in resp.json()["data"]
