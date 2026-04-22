"""
tests/unit/test_pipeline_stage_service.py
CONFIG-6 — Dynamic Pipeline Stage Configuration

Unit tests for:
  - _get_valid_transitions: disabled stage skipped in transitions
  - _get_valid_transitions: null config returns default transitions
  - move_stage: correctly skips disabled meeting_done
  - get_lead_stage_label: returns org label for known key
  - get_lead_stage_label: falls back to formatted key for unknown
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID  = "00000000-0000-0000-0000-000000000001"
LEAD_ID = "00000000-0000-0000-0000-000000000002"
USER_ID = "00000000-0000-0000-0000-000000000003"

FULL_CONFIG = [
    {"key": "new",           "label": "New Lead",      "enabled": True},
    {"key": "contacted",     "label": "Contacted",     "enabled": True},
    {"key": "meeting_done",  "label": "Demo Done",     "enabled": True},
    {"key": "proposal_sent", "label": "Proposal Sent", "enabled": True},
    {"key": "converted",     "label": "Converted",     "enabled": True},
]

CONFIG_NO_MEETING = [
    {"key": "new",           "label": "New Lead",      "enabled": True},
    {"key": "contacted",     "label": "Contacted",     "enabled": True},
    {"key": "meeting_done",  "label": "Demo Done",     "enabled": False},  # disabled
    {"key": "proposal_sent", "label": "Proposal Sent", "enabled": True},
    {"key": "converted",     "label": "Converted",     "enabled": True},
]

CUSTOM_LABELS_CONFIG = [
    {"key": "new",           "label": "Fresh Lead",          "enabled": True},
    {"key": "contacted",     "label": "Reached Out",         "enabled": True},
    {"key": "meeting_done",  "label": "Consultation Done",   "enabled": True},
    {"key": "proposal_sent", "label": "Quote Sent",          "enabled": True},
    {"key": "converted",     "label": "Client",              "enabled": True},
]


def _db_with_pipeline_stages(config):
    """Build a mock db that returns the given pipeline_stages config."""
    db = MagicMock()
    result = MagicMock()
    result.data = {"pipeline_stages": config}
    (db.table.return_value
       .select.return_value
       .eq.return_value
       .maybe_single.return_value
       .execute.return_value) = result
    return db


def _db_with_null_stages():
    """Build a mock db that returns null pipeline_stages (org has no config)."""
    db = MagicMock()
    result = MagicMock()
    result.data = {"pipeline_stages": None}
    (db.table.return_value
       .select.return_value
       .eq.return_value
       .maybe_single.return_value
       .execute.return_value) = result
    return db


# ---------------------------------------------------------------------------
# _get_valid_transitions
# ---------------------------------------------------------------------------

class TestGetValidTransitions:

    def test_full_config_all_stages_reachable(self):
        from app.services.lead_service import _get_valid_transitions
        db = _db_with_pipeline_stages(FULL_CONFIG)
        t = _get_valid_transitions(db, ORG_ID)

        assert "meeting_done" in t["contacted"]
        assert "proposal_sent" in t["meeting_done"]
        assert "converted" in t["proposal_sent"]

    def test_disabled_meeting_done_skipped_in_transitions(self):
        from app.services.lead_service import _get_valid_transitions
        db = _db_with_pipeline_stages(CONFIG_NO_MEETING)
        t = _get_valid_transitions(db, ORG_ID)

        # contacted should skip meeting_done and go directly to proposal_sent
        assert "meeting_done" not in t["contacted"]
        assert "proposal_sent" in t["contacted"]

    def test_null_config_returns_default_transitions(self):
        from app.services.lead_service import _get_valid_transitions, _DEFAULT_TRANSITIONS
        db = _db_with_null_stages()
        t = _get_valid_transitions(db, ORG_ID)

        # Should match default transitions exactly
        assert t == _DEFAULT_TRANSITIONS

    def test_db_exception_falls_back_to_defaults(self):
        from app.services.lead_service import _get_valid_transitions, _DEFAULT_TRANSITIONS
        db = MagicMock()
        db.table.side_effect = Exception("connection error")
        t = _get_valid_transitions(db, ORG_ID)

        assert t == _DEFAULT_TRANSITIONS

    def test_lost_and_not_ready_always_present(self):
        from app.services.lead_service import _get_valid_transitions
        db = _db_with_pipeline_stages(FULL_CONFIG)
        t = _get_valid_transitions(db, ORG_ID)

        assert "lost" in t
        assert "not_ready" in t
        assert t["lost"] == {"new"}
        assert t["not_ready"] == {"new"}

    def test_converted_is_terminal(self):
        from app.services.lead_service import _get_valid_transitions
        db = _db_with_pipeline_stages(FULL_CONFIG)
        t = _get_valid_transitions(db, ORG_ID)

        assert t["converted"] == set()

    def test_new_always_has_contacted_as_next(self):
        from app.services.lead_service import _get_valid_transitions
        db = _db_with_pipeline_stages(FULL_CONFIG)
        t = _get_valid_transitions(db, ORG_ID)

        assert "contacted" in t["new"]
        assert "lost" in t["new"]


# ---------------------------------------------------------------------------
# move_stage with disabled meeting_done
# ---------------------------------------------------------------------------

class TestMoveStageWithDisabledMeetingDone:

    def _lead(self, stage):
        return {
            "id": LEAD_ID, "org_id": ORG_ID, "stage": stage,
            "full_name": "Test Lead", "deleted_at": None,
        }

    def test_move_stage_skips_disabled_meeting_done(self):
        """contacted → proposal_sent is valid when meeting_done is disabled."""
        from app.services.lead_service import move_stage

        db = MagicMock()
        lead = self._lead("contacted")

        # Call 1: _get_valid_transitions → organisations
        # Call 2: _lead_or_404 → leads
        # Call 3: leads.update
        # Call 4: write_timeline_event → lead_timeline
        # Call 5: write_audit_log → audit_logs
        org_result = MagicMock()
        org_result.data = {"pipeline_stages": CONFIG_NO_MEETING}

        lead_result = MagicMock()
        lead_result.data = lead

        update_result = MagicMock()
        update_result.data = [{**lead, "stage": "proposal_sent"}]

        timeline_result = MagicMock()
        timeline_result.data = [{}]

        audit_result = MagicMock()
        audit_result.data = [{}]

        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
            org_result,   # _get_valid_transitions
            lead_result,  # _lead_or_404
        ]
        db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = update_result
        db.table.return_value.insert.return_value.execute.return_value = timeline_result

        result = move_stage(db, ORG_ID, LEAD_ID, "proposal_sent", USER_ID)
        assert result["stage"] == "proposal_sent"

    def test_move_stage_into_disabled_stage_rejected(self):
        """contacted → meeting_done is invalid when meeting_done is disabled."""
        from app.services.lead_service import move_stage

        db = MagicMock()
        lead = self._lead("contacted")

        org_result = MagicMock()
        org_result.data = {"pipeline_stages": CONFIG_NO_MEETING}

        lead_result = MagicMock()
        lead_result.data = lead

        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
            org_result,
            lead_result,
        ]

        with pytest.raises(HTTPException) as exc_info:
            move_stage(db, ORG_ID, LEAD_ID, "meeting_done", USER_ID)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# get_lead_stage_label
# ---------------------------------------------------------------------------

class TestGetLeadStageLabel:

    def test_returns_org_label_for_known_key(self):
        from app.services.lead_service import get_lead_stage_label
        db = _db_with_pipeline_stages(CUSTOM_LABELS_CONFIG)
        label = get_lead_stage_label(db, ORG_ID, "meeting_done")
        assert label == "Consultation Done"

    def test_returns_org_label_for_new(self):
        from app.services.lead_service import get_lead_stage_label
        db = _db_with_pipeline_stages(CUSTOM_LABELS_CONFIG)
        label = get_lead_stage_label(db, ORG_ID, "new")
        assert label == "Fresh Lead"

    def test_falls_back_to_formatted_key_for_unknown(self):
        """lost and not_ready are not in the config — should format the key."""
        from app.services.lead_service import get_lead_stage_label
        db = _db_with_pipeline_stages(FULL_CONFIG)
        label = get_lead_stage_label(db, ORG_ID, "not_ready")
        assert label == "Not Ready"

    def test_falls_back_when_config_null(self):
        from app.services.lead_service import get_lead_stage_label
        db = _db_with_null_stages()
        label = get_lead_stage_label(db, ORG_ID, "proposal_sent")
        assert label == "Proposal Sent"

    def test_falls_back_on_db_exception(self):
        from app.services.lead_service import get_lead_stage_label
        db = MagicMock()
        db.table.side_effect = Exception("db error")
        label = get_lead_stage_label(db, ORG_ID, "meeting_done")
        assert label == "Meeting Done"
