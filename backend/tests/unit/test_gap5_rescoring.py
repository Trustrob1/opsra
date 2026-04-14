"""
tests/unit/test_gap5_rescoring.py
Unit tests for GAP-5 — re-scoring on nurture re-engagement.

Covers:
  - score_lead_with_ai() accepts model param (backward compat + Haiku path)
  - _rescore_lead_on_reengagement() scores and writes back to DB
  - _rescore_lead_on_reengagement() gracefully degrades on AI failure (S14)
  - _rescore_lead_on_reengagement() gracefully degrades on DB failure (S14)
  - handle_re_engagement() includes new score in timeline + notification body
  - handle_re_engagement() returns new_score in result dict
  - Notification body is score-aware (hot/warm vs cold vs unscored)

Pattern 32: dependency_overrides teardowns use pop(), never clear().
Pattern 42: patch at source module, not consumer.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch, call

import pytest

ORG_ID  = str(uuid.uuid4())
LEAD_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())
MGR_ID  = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> MagicMock:
    db    = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[], count=0)
    for m in ("eq", "neq", "in_", "is_", "gte", "lte",
              "maybe_single", "order", "range"):
        getattr(chain, m).return_value = chain
    db.table.return_value.select.return_value  = chain
    db.table.return_value.insert.return_value  = chain
    db.table.return_value.update.return_value  = chain
    return db


def _lead_data() -> dict:
    return {
        "id":             LEAD_ID,
        "full_name":      "Ada Okafor",
        "business_name":  "Ada Bakery",
        "business_type":  "bakery",
        "problem_stated": "I need help managing my customer orders",
        "location":       "Lagos",
        "branches":       2,
        "source":         "whatsapp_inbound",
    }


# ===========================================================================
# score_lead_with_ai — model param
# ===========================================================================

class TestScoreLeadWithAiModelParam:

    def test_defaults_to_sonnet(self):
        """Existing callers get Sonnet — backward compatible."""
        from app.services.ai_service import score_lead_with_ai, SONNET

        with patch("app.services.ai_service.call_claude",
                   return_value="SCORE: warm\nREASON: Good fit") as mock_call:
            score_lead_with_ai(_lead_data())

        _, kwargs = mock_call.call_args
        assert kwargs.get("model") == SONNET or mock_call.call_args[0][1] == SONNET

    def test_accepts_haiku_model(self):
        """Nurture re-scoring can pass HAIKU to reduce cost."""
        from app.services.ai_service import score_lead_with_ai, HAIKU

        with patch("app.services.ai_service.call_claude",
                   return_value="SCORE: cold\nREASON: Limited context") as mock_call:
            result = score_lead_with_ai(_lead_data(), model=HAIKU)

        assert result["score"] == "cold"
        # Verify HAIKU was actually passed to call_claude
        args, kwargs = mock_call.call_args
        passed_model = kwargs.get("model") or (args[1] if len(args) > 1 else None)
        assert passed_model == HAIKU

    def test_returns_score_and_reason(self):
        """Return shape is unchanged — {"score": str, "score_reason": str}."""
        from app.services.ai_service import score_lead_with_ai

        with patch("app.services.ai_service.call_claude",
                   return_value="SCORE: hot\nREASON: High intent and clear need"):
            result = score_lead_with_ai(_lead_data())

        assert result["score"] == "hot"
        assert "score_reason" in result


# ===========================================================================
# _rescore_lead_on_reengagement
# ===========================================================================

class TestRescoreLeadOnReengagement:

    def _setup_db_with_lead(self, db: MagicMock, lead: dict, rubric: dict = None) -> None:
        """Configure db mock to return lead data and optionally a rubric."""
        # All selects share chain — patch _rescore via its internal calls
        # by patching score_lead_with_ai directly (Pattern 42)
        pass  # db mock default (data=[]) is fine; we patch score_lead_with_ai

    def test_scores_lead_and_writes_back(self):
        """Happy path: lead is scored and score written back to DB."""
        from app.services import nurture_service

        db  = _mock_db()
        now = "2026-04-13T10:00:00+00:00"
        # Provide lead data so the "not found" guard does not fire
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=_lead_data())

        with patch("app.services.ai_service.score_lead_with_ai",
                   return_value={"score": "warm", "score_reason": "Re-engaged proactively"}
                   ) as mock_score:
            result = nurture_service._rescore_lead_on_reengagement(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, now_ts=now,
            )

        assert result["score"] == "warm"
        mock_score.assert_called_once()

    def test_writes_score_to_leads_table(self):
        """score, score_reason, score_source='ai' must be written to DB."""
        from app.services import nurture_service

        db  = _mock_db()
        now = "2026-04-13T10:00:00+00:00"
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=_lead_data())

        with patch("app.services.ai_service.score_lead_with_ai",
                   return_value={"score": "hot", "score_reason": "Strong buying signals"}):
            nurture_service._rescore_lead_on_reengagement(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, now_ts=now,
            )

        db.table.return_value.update.assert_called()
        update_call_args = db.table.return_value.update.call_args_list
        score_update = next(
            (c for c in update_call_args
             if "score" in (c.args[0] if c.args else {})),
            None,
        )
        assert score_update is not None, "Expected a DB update call with score fields"
        payload = score_update.args[0]
        assert payload["score"] == "hot"
        assert payload["score_source"] == "ai"

    def test_uses_haiku_model(self):
        """Re-scoring must use HAIKU not SONNET — cost control."""
        from app.services import nurture_service
        from app.services.ai_service import HAIKU

        db  = _mock_db()
        now = "2026-04-13T10:00:00+00:00"
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=_lead_data())

        with patch("app.services.ai_service.score_lead_with_ai",
                   return_value={"score": "cold", "score_reason": None}
                   ) as mock_score:
            nurture_service._rescore_lead_on_reengagement(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, now_ts=now,
            )

        _, kwargs = mock_score.call_args
        assert kwargs.get("model") == HAIKU, (
            "Re-scoring must use HAIKU to keep costs low"
        )

    def test_s14_ai_failure_returns_unscored(self):
        """If AI call fails, returns unscored without raising — S14."""
        from app.services import nurture_service

        db  = _mock_db()
        now = "2026-04-13T10:00:00+00:00"

        with patch("app.services.ai_service.score_lead_with_ai",
                   side_effect=Exception("API timeout")):
            result = nurture_service._rescore_lead_on_reengagement(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, now_ts=now,
            )

        assert result == {"score": "unscored", "score_reason": None}

    def test_s14_db_failure_returns_unscored(self):
        """If DB fetch fails, returns unscored without raising — S14."""
        from app.services import nurture_service

        db = _mock_db()
        db.table.side_effect = Exception("DB connection lost")
        now = "2026-04-13T10:00:00+00:00"

        result = nurture_service._rescore_lead_on_reengagement(
            db=db, org_id=ORG_ID, lead_id=LEAD_ID, now_ts=now,
        )

        assert result["score"] == "unscored"


# ===========================================================================
# handle_re_engagement — score integration
# ===========================================================================

class TestHandleReEngagementWithRescore:

    def _run_re_engagement(self, db, score: str):
        """Helper: run handle_re_engagement with a mocked rescore result."""
        from app.services import nurture_service

        now = "2026-04-13T10:00:00+00:00"
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[])  # no managers

        with patch.object(
            nurture_service,
            "_rescore_lead_on_reengagement",
            return_value={"score": score, "score_reason": "test"},
        ):
            with patch.object(nurture_service, "_log_timeline") as mock_tl:
                with patch.object(nurture_service, "_notify_user") as mock_notif:
                    result = nurture_service.handle_re_engagement(
                        db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                        assigned_to=USER_ID, now_ts=now,
                    )
        return result, mock_tl, mock_notif

    def test_returns_new_score_in_result(self):
        """handle_re_engagement must return new_score in its result dict."""
        db = _mock_db()
        result, _, _ = self._run_re_engagement(db, score="warm")
        assert result["reactivated"] is True
        assert result["new_score"] == "warm"

    def test_timeline_includes_score(self):
        """Timeline description must mention the re-score result."""
        db = _mock_db()
        _, mock_tl, _ = self._run_re_engagement(db, score="hot")
        # _log_timeline is called positionally: (db, org_id, lead_id, event_type, description, now_ts)
        # description is the 5th positional arg (index 4)
        description = mock_tl.call_args[0][4]
        assert "hot" in description, (
            "Timeline description must include the new score"
        )

    def test_notification_body_hot_warm_urgent(self):
        """hot/warm re-score → notification body says to prioritise follow-up."""
        db = _mock_db()
        _, _, mock_notif = self._run_re_engagement(db, score="hot")
        body = mock_notif.call_args_list[0][1]["body"]
        assert "prioritise" in body.lower() or "HOT" in body, (
            "Hot re-score should prompt urgent follow-up in notification"
        )

    def test_notification_body_cold(self):
        """cold re-score → notification body tells rep to qualify further."""
        db = _mock_db()
        _, _, mock_notif = self._run_re_engagement(db, score="cold")
        body = mock_notif.call_args_list[0][1]["body"]
        assert "cold" in body.lower() or "qualify" in body.lower(), (
            "Cold re-score notification should guide rep to qualify further"
        )

    def test_notification_body_unscored_fallback(self):
        """unscored (AI failure) → generic notification body used — no crash."""
        db = _mock_db()
        result, _, mock_notif = self._run_re_engagement(db, score="unscored")
        assert result["reactivated"] is True  # never crashes even on unscored
        body = mock_notif.call_args_list[0][1]["body"]
        assert body  # some body must be present

    def test_rescore_called_once_per_reengagement(self):
        """_rescore_lead_on_reengagement is called exactly once per re-engagement."""
        from app.services import nurture_service

        db  = _mock_db()
        now = "2026-04-13T10:00:00+00:00"
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[])

        with patch.object(
            nurture_service,
            "_rescore_lead_on_reengagement",
            return_value={"score": "warm", "score_reason": None},
        ) as mock_rescore:
            nurture_service.handle_re_engagement(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                assigned_to=USER_ID, now_ts=now,
            )

        mock_rescore.assert_called_once_with(db, ORG_ID, LEAD_ID, now)
