"""
tests/unit/test_lead_form_config_service.py
Unit tests for LEAD-FORM-CONFIG service helpers.

Covers:
  - get_lead_form_config: returns default when org config is null
  - get_lead_form_config: returns org config when set
  - product_interest null — scoring falls back to problem_stated
  - product_interest populated, problem_stated null — scoring uses product_interest
  - Both present — problem_stated takes priority
  - PATCH validation: unknown key → 422
  - PATCH validation: label over 50 chars → 422
  - PATCH validation: required=true + visible=false → 422
  - PATCH validation: phone/full_name in payload silently ignored

Pattern T3: ast.parse dry-run validation applied before submission.
"""
import pytest
from unittest.mock import MagicMock, patch
from pydantic import ValidationError


# ── get_lead_form_config ──────────────────────────────────────────────────────

class TestGetLeadFormConfig:
    def _make_db(self, lead_form_config_value):
        """Build a mock db that returns the given lead_form_config from organisations."""
        db = MagicMock()
        row = {"lead_form_config": lead_form_config_value}
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = row
        return db

    def test_returns_default_when_config_is_null(self):
        from app.services.lead_service import get_lead_form_config, _DEFAULT_LEAD_FORM_CONFIG
        db = self._make_db(None)
        result = get_lead_form_config(db, org_id="org-1")
        assert result == _DEFAULT_LEAD_FORM_CONFIG

    def test_returns_default_when_config_is_empty_list(self):
        from app.services.lead_service import get_lead_form_config, _DEFAULT_LEAD_FORM_CONFIG
        db = self._make_db([])
        result = get_lead_form_config(db, org_id="org-1")
        assert result == _DEFAULT_LEAD_FORM_CONFIG

    def test_returns_org_config_when_set(self):
        from app.services.lead_service import get_lead_form_config
        custom = [
            {"key": "email", "label": "Email", "visible": True, "required": False},
            {"key": "product_interest", "label": "Product Interest", "visible": True, "required": True},
        ]
        db = self._make_db(custom)
        result = get_lead_form_config(db, org_id="org-1")
        assert result == custom

    def test_returns_default_on_db_error(self):
        from app.services.lead_service import get_lead_form_config, _DEFAULT_LEAD_FORM_CONFIG
        db = MagicMock()
        db.table.side_effect = Exception("DB connection failed")
        result = get_lead_form_config(db, org_id="org-1")
        assert result == _DEFAULT_LEAD_FORM_CONFIG

    def test_returns_default_when_data_is_list_with_null(self):
        """Handles supabase returning data as list (test mock normalisation)."""
        from app.services.lead_service import get_lead_form_config, _DEFAULT_LEAD_FORM_CONFIG
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = [{"lead_form_config": None}]
        result = get_lead_form_config(db, org_id="org-1")
        assert result == _DEFAULT_LEAD_FORM_CONFIG


# ── AI scoring: product_interest fallback ────────────────────────────────────

class TestProductInterestScoringFallback:
    """
    Tests that score_lead_with_ai uses product_interest as fallback
    when problem_stated is null (LEAD-FORM-CONFIG spec).
    """

    def _score(self, lead_data, mock_response="SCORE: hot\nREASON: Good fit"):
        """Run score_lead_with_ai with a mocked Claude call."""
        with patch("app.services.ai_service.call_claude", return_value=mock_response):
            from app.services.ai_service import score_lead_with_ai
            return score_lead_with_ai(lead_data)

    def test_uses_problem_stated_when_present(self):
        lead = {
            "full_name": "Emeka", "problem_stated": "Need inventory management",
            "product_interest": None,
        }
        with patch("app.services.ai_service.call_claude") as mock_call:
            mock_call.return_value = "SCORE: hot\nREASON: Clear need stated"
            from app.services.ai_service import score_lead_with_ai
            score_lead_with_ai(lead)
            call_args = mock_call.call_args[0][0]  # first positional arg = prompt
            assert "Need inventory management" in call_args

    def test_falls_back_to_product_interest_when_problem_stated_is_null(self):
        lead = {
            "full_name": "Amaka", "problem_stated": None,
            "product_interest": "Pillow Top Mattresses",
        }
        with patch("app.services.ai_service.call_claude") as mock_call:
            mock_call.return_value = "SCORE: warm\nREASON: Product interest shown"
            from app.services.ai_service import score_lead_with_ai
            score_lead_with_ai(lead)
            call_args = mock_call.call_args[0][0]
            assert "Pillow Top Mattresses" in call_args

    def test_problem_stated_takes_priority_when_both_present(self):
        lead = {
            "full_name": "Chidi",
            "problem_stated": "Stock management headache",
            "product_interest": "Retail POS",
        }
        with patch("app.services.ai_service.call_claude") as mock_call:
            mock_call.return_value = "SCORE: hot\nREASON: Direct problem stated"
            from app.services.ai_service import score_lead_with_ai
            score_lead_with_ai(lead)
            call_args = mock_call.call_args[0][0]
            assert "Stock management headache" in call_args

    def test_both_null_returns_unscored_on_empty_response(self):
        lead = {"full_name": "Test", "problem_stated": None, "product_interest": None}
        with patch("app.services.ai_service.call_claude", return_value=""):
            from app.services.ai_service import score_lead_with_ai
            result = score_lead_with_ai(lead)
        assert result["score"] == "unscored"


# ── Pydantic model validation ─────────────────────────────────────────────────

class TestLeadFormConfigValidation:
    """Tests for LeadFormFieldItem and LeadFormConfigUpdate Pydantic models."""

    def _get_models(self):
        # Import from admin router — these are defined there
        from app.routers.admin import LeadFormFieldItem, LeadFormConfigUpdate
        return LeadFormFieldItem, LeadFormConfigUpdate

    def test_valid_field_passes(self):
        LeadFormFieldItem, _ = self._get_models()
        f = LeadFormFieldItem(key="email", label="Email Address", visible=True, required=False)
        assert f.key == "email"
        assert f.label == "Email Address"

    def test_unknown_key_raises_422(self):
        LeadFormFieldItem, _ = self._get_models()
        with pytest.raises(ValidationError) as exc_info:
            LeadFormFieldItem(key="birthday", label="Birthday", visible=True, required=False)
        assert "configurable field key" in str(exc_info.value).lower() or "birthday" in str(exc_info.value)

    def test_label_over_50_chars_raises_422(self):
        LeadFormFieldItem, _ = self._get_models()
        with pytest.raises(ValidationError):
            LeadFormFieldItem(key="email", label="A" * 51, visible=True, required=False)

    def test_hidden_required_combo_raises_422(self):
        LeadFormFieldItem, _ = self._get_models()
        with pytest.raises(ValidationError) as exc_info:
            LeadFormFieldItem(key="email", label="Email", visible=False, required=True)
        assert "required=true" in str(exc_info.value).lower() or "hidden" in str(exc_info.value).lower()

    def test_visible_required_combo_is_valid(self):
        LeadFormFieldItem, _ = self._get_models()
        f = LeadFormFieldItem(key="email", label="Email", visible=True, required=True)
        assert f.required is True

    def test_phone_key_silently_ignored_in_update(self):
        """phone in payload is silently filtered out — never configurable."""
        LeadFormFieldItem, LeadFormConfigUpdate = self._get_models()
        # phone is in _IMMUTABLE_LEAD_FIELD_KEYS — validator filters it out
        # key validator allows it through (returns as-is), but update validator strips it
        payload = LeadFormConfigUpdate(fields=[
            LeadFormFieldItem(key="email", label="Email", visible=True, required=False),
            LeadFormFieldItem(key="phone", label="Phone", visible=True, required=True),
        ])
        # phone should be filtered from fields
        keys = [f.key for f in payload.fields]
        assert "phone" not in keys

    def test_full_name_key_silently_ignored_in_update(self):
        """full_name in payload is silently filtered out — never configurable."""
        LeadFormFieldItem, LeadFormConfigUpdate = self._get_models()
        payload = LeadFormConfigUpdate(fields=[
            LeadFormFieldItem(key="location", label="Location", visible=True, required=False),
            LeadFormFieldItem(key="full_name", label="Full Name", visible=True, required=True),
        ])
        keys = [f.key for f in payload.fields]
        assert "full_name" not in keys

    def test_empty_label_raises_422(self):
        LeadFormFieldItem, _ = self._get_models()
        with pytest.raises(ValidationError):
            LeadFormFieldItem(key="email", label="   ", visible=True, required=False)

    def test_product_interest_key_is_valid(self):
        """product_interest is a new configurable field — must be accepted."""
        LeadFormFieldItem, _ = self._get_models()
        f = LeadFormFieldItem(key="product_interest", label="Product Interest", visible=True, required=False)
        assert f.key == "product_interest"
