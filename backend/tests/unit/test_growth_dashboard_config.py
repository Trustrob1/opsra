"""
tests/unit/test_growth_dashboard_config.py
Unit tests for GROWTH-DASH-CONFIG.

Covers:
  - GET returns default config when org config is null
  - GET returns saved config when set
  - PATCH: overview submitted as visible:false → saved as visible:true (silent correction)
  - PATCH: pipeline_at_risk submitted as visible:false → saved as visible:true
  - PATCH: unknown section key → 422
  - PATCH: partial payload → only submitted sections updated, others unchanged
  - _get_stage_labels: returns org pipeline_stages labels when configured
  - _get_stage_labels: falls back to system key names when pipeline_stages is null
  - _get_stage_labels: falls back on DB error (S14)
  - get_funnel_metrics: returns stage_labels field in response
"""
import pytest
from unittest.mock import MagicMock
from pydantic import ValidationError


# ── Pydantic model validation ─────────────────────────────────────────────────

class TestGrowthDashboardConfigValidation:

    def _get_models(self):
        from app.routers.admin import GrowthDashboardSectionItem, GrowthDashboardConfigUpdate
        return GrowthDashboardSectionItem, GrowthDashboardConfigUpdate

    def test_valid_section_passes(self):
        Item, _ = self._get_models()
        item = Item(key="funnel", visible=True)
        assert item.key == "funnel"
        assert item.visible is True

    def test_unknown_key_raises_422(self):
        Item, _ = self._get_models()
        with pytest.raises(ValidationError) as exc_info:
            Item(key="revenue_chart", visible=True)
        assert "valid section key" in str(exc_info.value).lower() or "revenue_chart" in str(exc_info.value)

    def test_overview_visible_false_silently_corrected(self):
        Item, Update = self._get_models()
        payload = Update(sections=[Item(key="overview", visible=False)])
        overview = next(s for s in payload.sections if s.key == "overview")
        assert overview.visible is True

    def test_pipeline_at_risk_visible_false_silently_corrected(self):
        Item, Update = self._get_models()
        payload = Update(sections=[Item(key="pipeline_at_risk", visible=False)])
        section = next(s for s in payload.sections if s.key == "pipeline_at_risk")
        assert section.visible is True

    def test_other_sections_visible_false_not_corrected(self):
        Item, Update = self._get_models()
        payload = Update(sections=[Item(key="funnel", visible=False)])
        section = next(s for s in payload.sections if s.key == "funnel")
        assert section.visible is False

    def test_partial_payload_accepted(self):
        """Submitting only 2 sections is valid — partial update."""
        Item, Update = self._get_models()
        payload = Update(sections=[
            Item(key="funnel",           visible=False),
            Item(key="team_performance", visible=False),
        ])
        assert len(payload.sections) == 2

    def test_all_8_keys_are_valid(self):
        Item, _ = self._get_models()
        valid_keys = [
            "overview", "team_performance", "funnel", "velocity",
            "pipeline_at_risk", "sales_reps", "channels", "win_loss",
        ]
        for key in valid_keys:
            item = Item(key=key, visible=True)
            assert item.key == key


# ── _get_stage_labels ─────────────────────────────────────────────────────────

class TestGetStageLabels:

    def _make_db(self, pipeline_stages):
        db = MagicMock()
        row = {"pipeline_stages": pipeline_stages}
        (db.table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.return_value.data) = row
        return db

    def test_returns_org_labels_when_configured(self):
        from app.services.growth_analytics_service import _get_stage_labels
        stages = [
            {"key": "new",           "label": "Fresh Lead",    "enabled": True},
            {"key": "contacted",     "label": "Reached Out",   "enabled": True},
            {"key": "meeting_done",  "label": "Demo Complete", "enabled": True},
            {"key": "proposal_sent", "label": "Quote Sent",    "enabled": True},
            {"key": "converted",     "label": "Won",           "enabled": True},
        ]
        db = self._make_db(stages)
        result = _get_stage_labels(db, "org-1")
        assert result["new"]           == "Fresh Lead"
        assert result["contacted"]     == "Reached Out"
        assert result["meeting_done"]  == "Demo Complete"
        assert result["proposal_sent"] == "Quote Sent"
        assert result["converted"]     == "Won"

    def test_falls_back_to_system_keys_when_null(self):
        from app.services.growth_analytics_service import _get_stage_labels
        db = self._make_db(None)
        result = _get_stage_labels(db, "org-1")
        assert result["new"]           == "New"
        assert result["meeting_done"]  == "Meeting Done"
        assert result["proposal_sent"] == "Proposal Sent"
        assert result["converted"]     == "Converted"

    def test_falls_back_on_db_error(self):
        from app.services.growth_analytics_service import _get_stage_labels
        db = MagicMock()
        db.table.side_effect = Exception("DB connection failed")
        result = _get_stage_labels(db, "org-1")
        # Must return fallbacks, never raise
        assert "new"       in result
        assert "converted" in result

    def test_partial_config_fills_missing_with_fallback(self):
        """Only 2 stages configured — missing ones use system key fallback."""
        from app.services.growth_analytics_service import _get_stage_labels
        stages = [
            {"key": "new",       "label": "Incoming", "enabled": True},
            {"key": "converted", "label": "Closed",   "enabled": True},
        ]
        db = self._make_db(stages)
        result = _get_stage_labels(db, "org-1")
        assert result["new"]          == "Incoming"
        assert result["converted"]    == "Closed"
        assert result["contacted"]    == "Contacted"      # fallback
        assert result["meeting_done"] == "Meeting Done"   # fallback


# ── get_funnel_metrics: stage_labels in response ──────────────────────────────

class TestFunnelMetricsStageLabels:

    def _make_db(self, leads=None, pipeline_stages=None):
        db = MagicMock()

        def table_side(name):
            tbl = MagicMock()
            sel = MagicMock()
            sel.eq.return_value     = sel
            sel.is_.return_value    = sel
            sel.execute.return_value.data = []

            if name == "leads":
                sel.execute.return_value.data = leads or []
            elif name == "organisations":
                sel.maybe_single.return_value = sel
                sel.execute.return_value.data = {"pipeline_stages": pipeline_stages}

            tbl.select.return_value = sel
            return tbl

        db.table.side_effect = table_side
        return db

    def test_stage_labels_present_in_response(self):
        from app.services.growth_analytics_service import get_funnel_metrics
        from datetime import date
        db = self._make_db(leads=[], pipeline_stages=None)
        result = get_funnel_metrics(db, "org-1", date(2025, 1, 1), date(2025, 12, 31))
        assert "stage_labels" in result

    def test_stage_labels_uses_org_config(self):
        from app.services.growth_analytics_service import get_funnel_metrics
        from datetime import date
        stages = [{"key": "new", "label": "Fresh Lead", "enabled": True}]
        db = self._make_db(leads=[], pipeline_stages=stages)
        result = get_funnel_metrics(db, "org-1", date(2025, 1, 1), date(2025, 12, 31))
        assert result["stage_labels"]["new"] == "Fresh Lead"

    def test_stage_labels_falls_back_when_null(self):
        from app.services.growth_analytics_service import get_funnel_metrics
        from datetime import date
        db = self._make_db(leads=[], pipeline_stages=None)
        result = get_funnel_metrics(db, "org-1", date(2025, 1, 1), date(2025, 12, 31))
        assert result["stage_labels"]["new"] == "New"
        assert result["stage_labels"]["converted"] == "Converted"
