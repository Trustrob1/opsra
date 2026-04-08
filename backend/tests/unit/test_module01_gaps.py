"""
tests/unit/test_module01_gaps.py
Unit tests for Module 01 gap fills:

  TestNewLeadNotification   — _notify_new_lead (Feature 3)
  TestScoreLeadWithRubric   — score_lead_with_ai rubric injection (Feature 4)
  TestScoreLeadService      — score_lead rubric fetch + score_source (Feature 4)
  TestOverrideLeadScore     — override_lead_score function (Feature 2)
  TestScoreOverrideRoute    — POST /leads/{id}/score-override RBAC (Feature 2)
  TestScoringRubricAdmin    — GET/PATCH /admin/scoring-rubric routes (Feature 4)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"
LEAD_ID = "00000000-0000-0000-0000-000000000003"

FAKE_LEAD = {
    "id": LEAD_ID, "org_id": ORG_ID,
    "full_name": "Tunde Okafor", "business_name": "Tunde Stores",
    "business_type": "retail", "score": "warm", "score_source": "ai",
    "stage": "new", "source": "landing_page",
}

def _manager():
    return {
        "id": USER_ID, "org_id": ORG_ID,
        "roles": {"template": "ops_manager", "permissions": {}},
    }

def _agent():
    return {
        "id": USER_ID, "org_id": ORG_ID,
        "roles": {"template": "sales_agent", "permissions": {}},
    }


# ══════════════════════════════════════════════════════════════════════════════
# TestNewLeadNotification — Feature 3
# ══════════════════════════════════════════════════════════════════════════════

class TestNewLeadNotification:
    """_notify_new_lead creates in-app notifications for assigned rep + owners."""

    def _make_db(self, users, org_phone_id="phone_id_abc"):
        db = MagicMock()

        users_chain = MagicMock()
        users_chain.select.return_value  = users_chain
        users_chain.eq.return_value      = users_chain
        users_chain.execute.return_value = MagicMock(data=users)

        notif_chain = MagicMock()
        notif_chain.insert.return_value  = notif_chain
        notif_chain.execute.return_value = MagicMock(data=[{}])

        org_chain = MagicMock()
        org_chain.select.return_value       = org_chain
        org_chain.eq.return_value           = org_chain
        org_chain.maybe_single.return_value = org_chain
        org_chain.execute.return_value      = MagicMock(
            data={"whatsapp_phone_id": org_phone_id} if org_phone_id else None
        )

        def tbl(name):
            if name == "users":         return users_chain
            if name == "notifications": return notif_chain
            if name == "organisations": return org_chain
            return MagicMock()

        db.table.side_effect = tbl
        self._notif_chain = notif_chain
        return db

    def test_notifies_assigned_rep(self):
        from app.services.lead_service import _notify_new_lead
        users = [{"id": USER_ID, "whatsapp_number": None,
                  "roles": {"template": "sales_agent"}}]
        lead = {**FAKE_LEAD, "assigned_to": USER_ID}
        db = self._make_db(users)
        _notify_new_lead(db, ORG_ID, lead, LEAD_ID)
        self._notif_chain.insert.assert_called_once()
        notif = self._notif_chain.insert.call_args[0][0]
        assert notif["user_id"] == USER_ID
        assert notif["type"] == "new_lead"
        assert notif["resource_id"] == LEAD_ID

    def test_notifies_all_owners_in_org(self):
        from app.services.lead_service import _notify_new_lead
        owner_id = "00000000-0000-0000-0000-999999999999"
        users = [
            {"id": owner_id, "whatsapp_number": None, "roles": {"template": "owner"}},
            {"id": USER_ID,  "whatsapp_number": None, "roles": {"template": "sales_agent"}},
        ]
        lead = {**FAKE_LEAD, "assigned_to": USER_ID}
        db = self._make_db(users)
        _notify_new_lead(db, ORG_ID, lead, LEAD_ID)
        # 2 inserts: owner + assigned agent
        assert self._notif_chain.insert.call_count == 2

    def test_no_duplicate_notification_if_owner_is_assigned(self):
        from app.services.lead_service import _notify_new_lead
        users = [
            {"id": USER_ID, "whatsapp_number": None, "roles": {"template": "owner"}},
        ]
        lead = {**FAKE_LEAD, "assigned_to": USER_ID}
        db = self._make_db(users)
        _notify_new_lead(db, ORG_ID, lead, LEAD_ID)
        # owner is also assigned rep — should only be notified once
        assert self._notif_chain.insert.call_count == 1

    def test_skips_whatsapp_when_no_meta_token(self):
        from app.services.lead_service import _notify_new_lead
        users = [{"id": USER_ID, "whatsapp_number": "+2348000000000",
                  "roles": {"template": "owner"}}]
        lead = {**FAKE_LEAD, "assigned_to": USER_ID}
        db = self._make_db(users)
        with patch("app.services.lead_service._META_WA_TOKEN", ""), \
             patch("app.services.lead_service.os") as mock_os:
            mock_os.getenv.return_value = ""
            import httpx as _httpx
            with patch.object(_httpx, "post") as mock_post:
                _notify_new_lead(db, ORG_ID, lead, LEAD_ID)
                mock_post.assert_not_called()

    def test_s14_never_raises_on_db_failure(self):
        from app.services.lead_service import _notify_new_lead
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB is down")
        # Must not raise
        _notify_new_lead(db, ORG_ID, FAKE_LEAD, LEAD_ID)


# ══════════════════════════════════════════════════════════════════════════════
# TestScoreLeadWithRubric — Feature 4 (ai_service level)
# ══════════════════════════════════════════════════════════════════════════════

class TestScoreLeadWithRubric:
    """score_lead_with_ai injects rubric into system prompt and user prompt."""

    def test_injects_business_context_into_system_prompt(self):
        from app.services.ai_service import score_lead_with_ai
        rubric = {"scoring_business_context": "We sell POS software to retailers."}
        with patch("app.services.ai_service.call_claude", return_value="SCORE: hot\nREASON: Fits ideal profile.") as mock_call:
            score_lead_with_ai(FAKE_LEAD, rubric=rubric)
            _, kwargs = mock_call.call_args
            system = kwargs.get("system", mock_call.call_args[1].get("system", ""))
            assert "We sell POS software" in system

    def test_injects_hot_criteria_into_prompt(self):
        from app.services.ai_service import score_lead_with_ai
        rubric = {"scoring_hot_criteria": "3+ branches and ready to demo"}
        with patch("app.services.ai_service.call_claude", return_value="SCORE: hot\nREASON: Multi-branch.") as mock_call:
            score_lead_with_ai(FAKE_LEAD, rubric=rubric)
            prompt_arg = mock_call.call_args[0][0]
            assert "3+ branches and ready to demo" in prompt_arg

    def test_no_rubric_uses_base_system_prompt(self):
        from app.services.ai_service import score_lead_with_ai, LEAD_SCORING_SYSTEM
        with patch("app.services.ai_service.call_claude", return_value="SCORE: warm\nREASON: Moderate fit.") as mock_call:
            score_lead_with_ai(FAKE_LEAD, rubric=None)
            _, kwargs = mock_call.call_args
            system = kwargs.get("system", "")
            # System should be exactly the base prompt — no org context appended
            assert "ORGANISATION CONTEXT" not in system

    def test_empty_rubric_dict_behaves_as_no_rubric(self):
        from app.services.ai_service import score_lead_with_ai
        with patch("app.services.ai_service.call_claude", return_value="SCORE: cold\nREASON: No clear need.") as mock_call:
            result = score_lead_with_ai(FAKE_LEAD, rubric={})
            prompt_arg = mock_call.call_args[0][0]
            assert "scoring_criteria" not in prompt_arg
            assert result["score"] == "cold"


# ══════════════════════════════════════════════════════════════════════════════
# TestScoreLeadService — Feature 4 (lead_service.score_lead)
# ══════════════════════════════════════════════════════════════════════════════

class TestScoreLeadService:
    """score_lead fetches org rubric and writes score_source='ai'."""

    def _make_db(self, rubric_data=None):
        db = MagicMock()

        lead_chain = MagicMock()
        lead_chain.select.return_value       = lead_chain
        lead_chain.eq.return_value           = lead_chain
        lead_chain.maybe_single.return_value = lead_chain
        lead_chain.update.return_value       = lead_chain
        lead_chain.execute.return_value      = MagicMock(data=FAKE_LEAD)

        org_chain = MagicMock()
        org_chain.select.return_value       = org_chain
        org_chain.eq.return_value           = org_chain
        org_chain.maybe_single.return_value = org_chain
        org_chain.execute.return_value      = MagicMock(data=rubric_data or {})

        tl_chain = MagicMock()
        tl_chain.insert.return_value  = tl_chain
        tl_chain.execute.return_value = MagicMock(data=[{}])

        audit_chain = MagicMock()
        audit_chain.insert.return_value  = audit_chain
        audit_chain.execute.return_value = MagicMock(data=[{}])

        def tbl(name):
            if name == "leads":         return lead_chain
            if name == "organisations": return org_chain
            if name == "lead_timeline": return tl_chain
            if name == "audit_logs":    return audit_chain
            return MagicMock()

        db.table.side_effect = tbl
        self._lead_chain = lead_chain
        return db

    def test_score_source_set_to_ai_in_update(self):
        from app.services.lead_service import score_lead
        db = self._make_db()
        with patch("app.services.lead_service.score_lead_with_ai",
                   return_value={"score": "hot", "score_reason": "Strong fit"}):
            score_lead(db, ORG_ID, LEAD_ID, USER_ID)
        update_call = self._lead_chain.update.call_args[0][0]
        assert update_call["score_source"] == "ai"

    def test_rubric_fetched_and_passed_to_ai(self):
        from app.services.lead_service import score_lead
        rubric = {"scoring_business_context": "POS for retailers"}
        db = self._make_db(rubric_data=rubric)
        with patch("app.services.lead_service.score_lead_with_ai",
                   return_value={"score": "warm", "score_reason": "Moderate"}) as mock_ai:
            score_lead(db, ORG_ID, LEAD_ID, USER_ID)
        _, kwargs = mock_ai.call_args
        assert kwargs.get("rubric") == rubric

    def test_rubric_fetch_failure_falls_back_gracefully(self):
        """If org rubric fetch errors, scoring proceeds with empty rubric."""
        from app.services.lead_service import score_lead
        db = self._make_db()
        db.table("organisations").execute.side_effect = RuntimeError("DB error")
        with patch("app.services.lead_service.score_lead_with_ai",
                   return_value={"score": "cold", "score_reason": "No fit"}) as mock_ai:
            result = score_lead(db, ORG_ID, LEAD_ID, USER_ID)
        _, kwargs = mock_ai.call_args
        assert kwargs.get("rubric") == {}


# ══════════════════════════════════════════════════════════════════════════════
# TestOverrideLeadScore — Feature 2
# ══════════════════════════════════════════════════════════════════════════════

class TestOverrideLeadScore:
    """override_lead_score sets score_source='human' and writes audit trail."""

    def _make_db(self):
        db = MagicMock()

        lead_chain = MagicMock()
        lead_chain.select.return_value       = lead_chain
        lead_chain.eq.return_value           = lead_chain
        lead_chain.maybe_single.return_value = lead_chain
        lead_chain.update.return_value       = lead_chain
        lead_chain.execute.return_value      = MagicMock(data=FAKE_LEAD)

        tl_chain = MagicMock()
        tl_chain.insert.return_value  = tl_chain
        tl_chain.execute.return_value = MagicMock(data=[{}])

        audit_chain = MagicMock()
        audit_chain.insert.return_value  = audit_chain
        audit_chain.execute.return_value = MagicMock(data=[{}])

        def tbl(name):
            if name == "leads":         return lead_chain
            if name == "lead_timeline": return tl_chain
            if name == "audit_logs":    return audit_chain
            return MagicMock()

        db.table.side_effect = tbl
        self._lead_chain = lead_chain
        return db

    def test_sets_score_source_human(self):
        from app.services.lead_service import override_lead_score
        db = self._make_db()
        result = override_lead_score(db, ORG_ID, LEAD_ID, USER_ID, "hot")
        update_call = self._lead_chain.update.call_args[0][0]
        assert update_call["score_source"] == "human"
        assert update_call["score"] == "hot"
        assert result["score_source"] == "human"

    def test_rejects_invalid_score_value(self):
        from app.services.lead_service import override_lead_score
        db = self._make_db()
        with pytest.raises(HTTPException) as exc_info:
            override_lead_score(db, ORG_ID, LEAD_ID, USER_ID, "lukewarm")
        assert exc_info.value.status_code == 400

    def test_all_valid_scores_accepted(self):
        from app.services.lead_service import override_lead_score
        for score in ("hot", "warm", "cold"):
            db = self._make_db()
            result = override_lead_score(db, ORG_ID, LEAD_ID, USER_ID, score)
            assert result["score"] == score


# ══════════════════════════════════════════════════════════════════════════════
# TestScoreOverrideRoute — Feature 2 (router RBAC)
# ══════════════════════════════════════════════════════════════════════════════

class TestScoreOverrideRoute:
    """POST /leads/{id}/score-override — manager-only RBAC enforcement."""

    def setup_method(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_manager_can_override_score(self):
        app.dependency_overrides[get_current_org] = _manager
        with patch("app.routers.leads.lead_service.override_lead_score",
                   return_value={**FAKE_LEAD, "score": "hot", "score_source": "human"}):
            resp = self.client.post(
                f"/api/v1/leads/{LEAD_ID}/score-override",
                json={"score": "hot"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["score_source"] == "human"

    def test_sales_agent_cannot_override_score(self):
        app.dependency_overrides[get_current_org] = _agent
        resp = self.client.post(
            f"/api/v1/leads/{LEAD_ID}/score-override",
            json={"score": "hot"},
        )
        assert resp.status_code == 403

    def test_invalid_score_value_returns_422(self):
        app.dependency_overrides[get_current_org] = _manager
        resp = self.client.post(
            f"/api/v1/leads/{LEAD_ID}/score-override",
            json={"score": "lukewarm"},
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# TestScoringRubricAdmin — Feature 4 (admin routes)
# ══════════════════════════════════════════════════════════════════════════════

class TestScoringRubricAdmin:
    """GET/PATCH /admin/scoring-rubric — reads and writes organisations table."""

    def setup_method(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        # require_permission("manage_users") calls get_current_org internally.
        # Override get_current_org to return a user with manage_users=True —
        # this satisfies has_permission() without needing to key on the factory closure.
        app.dependency_overrides[get_current_org] = lambda: {
            "id": USER_ID, "org_id": ORG_ID,
            "roles": {
                "template": "ops_manager",
                "permissions": {"manage_users": True},
            },
        }
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_get_returns_rubric_fields(self):
        rubric = {
            "scoring_business_context": "POS for retailers",
            "scoring_hot_criteria": "3+ branches",
            "scoring_warm_criteria": None,
            "scoring_cold_criteria": None,
            "scoring_qualification_questions": None,
        }
        chain = MagicMock()
        chain.select.return_value       = chain
        chain.eq.return_value           = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value      = MagicMock(data=rubric)
        self.mock_db.table.return_value = chain

        resp = self.client.get("/api/v1/admin/scoring-rubric")
        assert resp.status_code == 200
        assert resp.json()["data"]["scoring_business_context"] == "POS for retailers"

    def test_patch_updates_organisations_table(self):
        chain = MagicMock()
        chain.update.return_value   = chain
        chain.eq.return_value       = chain
        chain.insert.return_value   = chain
        chain.execute.return_value  = MagicMock(data={})
        self.mock_db.table.return_value = chain

        resp = self.client.patch(
            "/api/v1/admin/scoring-rubric",
            json={"scoring_business_context": "We sell real estate"},
        )
        assert resp.status_code == 200
        chain.update.assert_called_once()
        update_payload = chain.update.call_args[0][0]
        assert update_payload["scoring_business_context"] == "We sell real estate"

    def test_patch_with_empty_body_returns_422(self):
        resp = self.client.patch("/api/v1/admin/scoring-rubric", json={})
        assert resp.status_code == 422
