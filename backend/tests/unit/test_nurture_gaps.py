"""
tests/test_nurture_gaps.py
Unit + integration tests for M01-10a gap fixes (GAP-1 through GAP-4).

GAP-1 — Manual reactivation from nurture
GAP-2 — Not-ready detection skipped during active qualification session
GAP-3 — Empty sequence guard in graduation worker
GAP-4 — Unsubscribe path (is_unsubscribe_signal, mark_lead_unsubscribed,
         webhook handler, worker filters)

Pattern 32: all dependency_overrides teardowns use pop(), never clear().
Pattern 24: test UUIDs are valid UUID4 strings.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# UUID constants
# ---------------------------------------------------------------------------
ORG_ID   = str(uuid.uuid4())
LEAD_ID  = str(uuid.uuid4())
USER_ID  = str(uuid.uuid4())
MGR_ID   = str(uuid.uuid4())
OWNER_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> MagicMock:
    """Return a chainable Supabase mock."""
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[], count=0)
    db.table.return_value.select.return_value = chain
    db.table.return_value.insert.return_value = chain
    db.table.return_value.update.return_value = chain
    db.table.return_value.delete.return_value = chain
    for method in ("eq", "neq", "in_", "is_", "gte", "lte", "maybe_single",
                   "order", "range", "not_", "ilike"):
        getattr(chain, method).return_value = chain
    return db


def _make_lead(
    nurture_track: bool = True,
    stage: str = "not_ready",
    nurture_opted_out: bool = False,
) -> dict:
    return {
        "id":                      LEAD_ID,
        "org_id":                  ORG_ID,
        "full_name":               "Test Lead",
        "stage":                   stage,
        "nurture_track":           nurture_track,
        "nurture_opted_out":       nurture_opted_out,
        "nurture_sequence_position": 3,
        "last_nurture_sent_at":    "2026-04-01T00:00:00+00:00",
        "assigned_to":             USER_ID,
        "deleted_at":              None,
    }


# ===========================================================================
# GAP-1 — reactivate_from_nurture (service)
# ===========================================================================

class TestReactivateFromNurtureService:

    def test_success_resets_nurture_fields(self):
        """Happy path: nurture-track lead is moved back to stage=new."""
        from app.services import lead_service

        lead = _make_lead(nurture_track=True, stage="not_ready")
        # updates the service will apply
        updates = {
            "stage": "new",
            "nurture_track": False,
            "nurture_sequence_position": 0,
            "last_nurture_sent_at": None,
        }

        db = _mock_db()
        # Default chain returns data=[] for all calls.
        # update().execute() returns [] → service falls back to {**lead, **updates}
        # which contains all expected field values.
        # select() for manager notification returns [] → no notification inserts (fine).

        with patch.object(lead_service, "_lead_or_404", return_value=lead):
            result = lead_service.reactivate_from_nurture(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                user_id=USER_ID, reason="Spoke by phone",
            )

        assert result["stage"] == "new"
        assert result["nurture_track"] is False
        assert result["nurture_sequence_position"] == 0
        assert result["last_nurture_sent_at"] is None

    def test_raises_400_if_not_on_nurture_track(self):
        """Lead not on nurture track — must raise 400 INVALID_TRANSITION."""
        from app.services.lead_service import reactivate_from_nurture
        from fastapi import HTTPException

        db = _mock_db()
        lead = _make_lead(nurture_track=False, stage="new")

        db.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.is_.return_value.maybe_single.return_value \
            .execute.return_value = MagicMock(data=lead)

        with pytest.raises(HTTPException) as exc_info:
            reactivate_from_nurture(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                user_id=USER_ID,
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "INVALID_TRANSITION"

    def test_raises_404_if_lead_not_found(self):
        """Non-existent lead — must raise 404 NOT_FOUND."""
        from app.services.lead_service import reactivate_from_nurture
        from fastapi import HTTPException

        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.is_.return_value.maybe_single.return_value \
            .execute.return_value = MagicMock(data=None)

        with pytest.raises(HTTPException) as exc_info:
            reactivate_from_nurture(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                user_id=USER_ID,
            )
        assert exc_info.value.status_code == 404

    def test_timeline_written_with_human_actor(self):
        """Timeline event must use actor_id=user_id (not None — this is a human action)."""
        from app.services import lead_service

        lead = _make_lead(nurture_track=True)
        db = _mock_db()

        db.table.return_value.update.return_value.eq.return_value \
            .eq.return_value.execute.return_value = MagicMock(data=[{
                **lead, "stage": "new", "nurture_track": False,
                "nurture_sequence_position": 0, "last_nurture_sent_at": None,
            }])
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[])

        # Patch _lead_or_404 directly — isolates from chain collision (Pattern 42)
        with patch.object(lead_service, "_lead_or_404", return_value=lead):
            with patch.object(lead_service, "write_timeline_event") as mock_tl:
                lead_service.reactivate_from_nurture(
                    db=db, org_id=ORG_ID, lead_id=LEAD_ID, user_id=USER_ID,
                )

        mock_tl.assert_called_once()
        _, kwargs = mock_tl.call_args
        assert kwargs.get("actor_id") == USER_ID, (
            "Timeline must use rep user_id — not None (Pattern 55 only applies to system events)"
        )
        assert kwargs.get("event_type") == "nurture_reactivated"


# ===========================================================================
# GAP-1 — reactivate-from-nurture endpoint (integration)
# ===========================================================================

class TestReactivateFromNurtureEndpoint:

    def test_patch_returns_200(self):
        """PATCH /{lead_id}/reactivate-from-nurture returns 200 with updated lead."""
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org
        from app.services import lead_service

        org_override = {
            "id": USER_ID, "org_id": ORG_ID,
            "roles": {"template": "sales_agent"},
        }
        updated_lead = {
            **_make_lead(nurture_track=False, stage="new"),
            "nurture_sequence_position": 0,
            "last_nurture_sent_at": None,
        }
        db_mock = _mock_db()

        app.dependency_overrides[get_current_org] = lambda: org_override
        app.dependency_overrides[get_supabase]    = lambda: db_mock

        try:
            with patch.object(lead_service, "reactivate_from_nurture",
                              return_value=updated_lead) as mock_fn:
                client = TestClient(app)
                resp = client.patch(
                    f"/api/v1/leads/{LEAD_ID}/reactivate-from-nurture",
                    json={"reason": "Called on WhatsApp directly"},
                )
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)

        assert resp.status_code == 200
        mock_fn.assert_called_once_with(
            db=db_mock,
            org_id=ORG_ID,
            lead_id=LEAD_ID,
            user_id=USER_ID,
            reason="Called on WhatsApp directly",
        )

    def test_affiliate_partner_blocked(self):
        """affiliate_partner cannot reactivate leads from nurture — must return 403."""
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        org_override = {
            "id": USER_ID, "org_id": ORG_ID,
            "roles": {"template": "affiliate_partner"},
        }
        app.dependency_overrides[get_current_org] = lambda: org_override
        app.dependency_overrides[get_supabase]    = lambda: _mock_db()

        client = TestClient(app)
        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}/reactivate-from-nurture",
            json={},
        )

        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

        assert resp.status_code == 403


# ===========================================================================
# GAP-2 — Not-ready detection skipped during active qualification session
# ===========================================================================

class TestNotReadyGuardDuringQualification:

    def _make_message(self, content: str) -> dict:
        return {"from": "+2348000000001", "id": "msg-123",
                "type": "text", "text": {"body": content}}

    def test_not_ready_skipped_when_active_session_exists(self):
        """
        If lead has an active qualification session (ai_active=True),
        is_not_ready_signal must never be called — the bot owns the conversation.
        """
        from app.routers import webhooks

        db = _mock_db()

        # Active qualification session exists — execute returns non-empty data
        db.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.execute.return_value = MagicMock(
                data=[{"id": str(uuid.uuid4())}]
            )

        # is_not_ready_signal is lazily imported inside _handle_inbound_message.
        # Pattern 42: patch the source module, not the consumer.
        with patch("app.services.nurture_service.is_not_ready_signal") as mock_signal:
            with patch(
                "app.routers.webhooks._lookup_record_by_phone",
                return_value=(ORG_ID, None, LEAD_ID, USER_ID),
            ):
                with patch("app.routers.webhooks._handle_structured_qualification_turn"):
                    webhooks._handle_inbound_message(
                        db=db,
                        message=self._make_message("not ready, call me later"),
                        contact_name="Test",
                        phone_number_id="phone-id-1",
                    )

        mock_signal.assert_not_called()

    def test_not_ready_fires_without_active_session(self):
        """
        With no active qualification session, is_not_ready_signal IS called
        and graduation proceeds normally.

        No DB mock overrides needed — _mock_db() default (data=[]) is correct:
          - Nurture track check: data=[] → nurture_track=None → falsy → skip re-engagement
          - Session check: data=[] → _has_active_session=False → not-ready detection runs
        """
        from app.routers import webhooks

        db = _mock_db()

        # Pattern 42: patch source module for lazy imports
        with patch(
            "app.routers.webhooks._lookup_record_by_phone",
            return_value=(ORG_ID, None, LEAD_ID, USER_ID),
        ):
            with patch(
                "app.services.nurture_service.is_not_ready_signal",
                return_value=True,
            ) as mock_signal:
                with patch("app.services.nurture_service.graduate_lead_self_identified"):
                    with patch("app.routers.webhooks._handle_structured_qualification_turn"):
                        webhooks._handle_inbound_message(
                            db=db,
                            message=self._make_message("not ready"),
                            contact_name="Test",
                            phone_number_id="phone-id-1",
                        )

        mock_signal.assert_called_once()


# ===========================================================================
# GAP-3 — Empty sequence guard in graduation worker
# ===========================================================================

class TestGraduationWorkerEmptySequence:

    def test_skips_graduation_and_notifies_owner_when_sequence_empty(self):
        """
        If org has nurture enabled but empty sequence, worker must:
        1. NOT graduate any leads
        2. Insert one warning notification to the org owner
        """
        from app.workers.lead_graduation_worker import run_lead_graduation_check

        db = _mock_db()

        orgs = [{
            "id": ORG_ID,
            "nurture_track_enabled": True,
            "conversion_attempt_days": 14,
            "nurture_sequence": [],  # empty!
        }]
        owner_user = {"id": OWNER_ID, "roles": {"template": "owner"}}

        call_count = {"orgs": 0, "users": 0, "leads": 0, "notifications": 0}

        def table_side_effect(name: str):
            mock = MagicMock()
            chain = MagicMock()
            chain.execute.return_value = MagicMock(data=[])

            for m in ("eq", "neq", "in_", "is_", "gte", "lte",
                      "maybe_single", "order", "range"):
                getattr(chain, m).return_value = chain

            if name == "organisations":
                chain.execute.return_value = MagicMock(data=orgs)
            elif name == "users":
                chain.execute.return_value = MagicMock(data=[owner_user])
                call_count["users"] += 1
            elif name == "leads":
                call_count["leads"] += 1
            elif name == "notifications":
                call_count["notifications"] += 1

            mock.select.return_value = chain
            mock.insert.return_value = chain
            mock.update.return_value = chain
            return mock

        db.table.side_effect = table_side_effect

        with patch("app.workers.lead_graduation_worker.get_supabase", return_value=db):
            summary = run_lead_graduation_check()

        # No leads should have been queried for graduation
        assert call_count["leads"] == 0, (
            "Worker must not query leads when sequence is empty"
        )
        # Warning notification must have been inserted
        assert call_count["notifications"] >= 1, (
            "Worker must insert a warning notification to the org owner"
        )
        # Summary should reflect no graduations
        assert summary["graduated"] == 0

    def test_graduates_normally_when_sequence_has_items(self):
        """Graduation proceeds as normal when sequence is non-empty."""
        from app.workers.lead_graduation_worker import run_lead_graduation_check

        db = _mock_db()
        orgs = [{
            "id": ORG_ID,
            "nurture_track_enabled": True,
            "conversion_attempt_days": 14,
            "nurture_sequence": [{"mode": "custom", "template": "Hi {{name}}"}],
        }]
        candidates: list[dict] = []

        def table_side_effect(name: str):
            mock = MagicMock()
            chain = MagicMock()
            chain.execute.return_value = MagicMock(data=[])
            for m in ("eq", "neq", "in_", "is_", "gte", "lte",
                      "maybe_single", "order", "range"):
                getattr(chain, m).return_value = chain
            if name == "organisations":
                chain.execute.return_value = MagicMock(data=orgs)
            elif name == "leads":
                chain.execute.return_value = MagicMock(data=candidates)
            mock.select.return_value = chain
            mock.insert.return_value = chain
            mock.update.return_value = chain
            return mock

        db.table.side_effect = table_side_effect

        with patch("app.workers.lead_graduation_worker.get_supabase", return_value=db):
            with patch("app.workers.lead_graduation_worker.check_human_activity_since",
                       return_value=False):
                summary = run_lead_graduation_check()

        # Worker processed the org (did not skip due to empty sequence)
        assert summary["orgs_processed"] == 1


# ===========================================================================
# GAP-4 — Unsubscribe signal detection
# ===========================================================================

class TestIsUnsubscribeSignal:

    @pytest.mark.parametrize("text", [
        "STOP",
        "stop",
        "unsubscribe",
        "remove me",
        "opt out",
        "opt-out",
        "don't message me",
        "no more messages",
        "stop messaging me",
        "leave me alone",
        "stop contacting me",
        "remove my number",
        "take me off",
        "I don't want messages",
        "abeg no dey message",
        "no dey disturb me",
    ])
    def test_matches_unsubscribe_phrase(self, text: str):
        from app.services.nurture_service import is_unsubscribe_signal
        assert is_unsubscribe_signal(text) is True, (
            f"Expected unsubscribe match for: {text!r}"
        )

    @pytest.mark.parametrize("text", [
        "I'm interested",
        "not ready",        # not-ready signal — different from unsubscribe
        "call me later",
        "send me more info",
        "ok",
        "hello",
        "",
        "   ",
        "what are your prices?",
    ])
    def test_no_match_for_normal_messages(self, text: str):
        from app.services.nurture_service import is_unsubscribe_signal
        assert is_unsubscribe_signal(text) is False, (
            f"Expected no unsubscribe match for: {text!r}"
        )


class TestMarkLeadUnsubscribed:

    def test_sets_nurture_opted_out_and_nurture_track_false(self):
        """mark_lead_unsubscribed must set nurture_opted_out=True, nurture_track=False."""
        from app.services.nurture_service import mark_lead_unsubscribed

        db = _mock_db()
        now_ts = "2026-04-13T10:00:00+00:00"

        update_chain = MagicMock()
        update_chain.eq.return_value = update_chain
        update_chain.execute.return_value = MagicMock(data=[])
        db.table.return_value.update.return_value = update_chain

        insert_chain = MagicMock()
        insert_chain.execute.return_value = MagicMock(data=[])
        db.table.return_value.insert.return_value = insert_chain

        mark_lead_unsubscribed(db=db, org_id=ORG_ID, lead_id=LEAD_ID, now_ts=now_ts)

        db.table.return_value.update.assert_called_once_with({
            "nurture_opted_out": True,
            "nurture_track":     False,
            "updated_at":        now_ts,
        })

    def test_logs_timeline_entry(self):
        """A nurture_unsubscribed timeline entry must be written."""
        from app.services import nurture_service

        db = _mock_db()
        db.table.return_value.update.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[])

        with patch.object(nurture_service, "_log_timeline") as mock_tl:
            nurture_service.mark_lead_unsubscribed(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID,
                now_ts="2026-04-13T10:00:00+00:00",
            )

        mock_tl.assert_called_once()
        _, kwargs = mock_tl.call_args
        assert kwargs["event_type"] == "nurture_unsubscribed"


class TestWebhookUnsubscribePath:

    def test_unsubscribe_signal_opts_out_and_returns_early(self):
        """
        When a nurture-track lead sends an unsubscribe signal,
        mark_lead_unsubscribed must be called and the handler must return early
        (no re-engagement, no qualification turn).
        Pattern 42: patch source module for lazy imports in webhook handler.
        """
        from app.routers import webhooks

        db = _mock_db()

        # Nurture check: lead is on nurture track
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"nurture_track": True}
            )

        with patch("app.routers.webhooks._lookup_record_by_phone",
                   return_value=(ORG_ID, None, LEAD_ID, USER_ID)):
            with patch(
                "app.services.nurture_service.is_unsubscribe_signal",
                return_value=True,
            ) as mock_unsub:
                with patch(
                    "app.services.nurture_service.mark_lead_unsubscribed"
                ) as mock_mark:
                    with patch(
                        "app.services.nurture_service.handle_re_engagement"
                    ) as mock_reengage:
                        with patch(
                            "app.routers.webhooks._handle_structured_qualification_turn"
                        ) as mock_qual:
                            webhooks._handle_inbound_message(
                                db=db,
                                message={
                                    "from": "+2348000000001",
                                    "id": "msg-unsub",
                                    "type": "text",
                                    "text": {"body": "stop"},
                                },
                                contact_name="Test Lead",
                                phone_number_id="phone-id-1",
                            )

        mock_unsub.assert_called_once_with("stop")
        mock_mark.assert_called_once()
        mock_reengage.assert_not_called()
        mock_qual.assert_not_called()

    def test_normal_reply_on_nurture_track_still_reengages(self):
        """Non-unsubscribe reply from nurture-track lead still triggers re-engagement."""
        from app.routers import webhooks

        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"nurture_track": True}
            )

        with patch("app.routers.webhooks._lookup_record_by_phone",
                   return_value=(ORG_ID, None, LEAD_ID, USER_ID)):
            with patch(
                "app.services.nurture_service.is_unsubscribe_signal",
                return_value=False,
            ):
                with patch(
                    "app.services.nurture_service.handle_re_engagement"
                ) as mock_reengage:
                    with patch("app.routers.webhooks._handle_structured_qualification_turn"):
                        webhooks._handle_inbound_message(
                            db=db,
                            message={
                                "from": "+2348000000001",
                                "id": "msg-normal",
                                "type": "text",
                                "text": {"body": "Hi I'm ready now"},
                            },
                            contact_name="Test Lead",
                            phone_number_id="phone-id-1",
                        )

        mock_reengage.assert_called_once()


class TestNurtureWorkerOptedOutFilter:

    def test_nurture_worker_query_includes_opted_out_false_filter(self):
        """
        run_lead_nurture_send must filter out leads where nurture_opted_out=True.
        Verified by checking the mock call chain includes .eq("nurture_opted_out", False).
        """
        from app.workers import lead_nurture_worker

        db = _mock_db()

        orgs = [{
            "id": ORG_ID,
            "nurture_track_enabled": True,
            "nurture_interval_days": 7,
            "nurture_sequence": [{"mode": "custom", "template": "Hi {{name}}"}],
            "whatsapp_phone_id": "phone-123",
            "name": "Test Org",
        }]

        calls_with_opted_out = []

        original_eq = MagicMock()

        class TrackingChain:
            """Chainable mock that records .eq("nurture_opted_out", False) calls."""
            def __getattr__(self, name):
                def method(*args, **kwargs):
                    if name == "eq" and args == ("nurture_opted_out", False):
                        calls_with_opted_out.append(True)
                    return TrackingChain()
                return method

            def execute(self):
                return MagicMock(data=[])

        def table_side(name: str):
            mock = MagicMock()
            if name == "organisations":
                chain = MagicMock()
                chain.eq.return_value = chain
                chain.execute.return_value = MagicMock(data=orgs)
                mock.select.return_value = chain
            else:
                mock.select.return_value = TrackingChain()
            mock.insert.return_value = MagicMock(execute=lambda: MagicMock(data=[]))
            mock.update.return_value = MagicMock(execute=lambda: MagicMock(data=[]))
            return mock

        db.table.side_effect = table_side

        with patch("app.workers.lead_nurture_worker.get_supabase", return_value=db):
            lead_nurture_worker.run_lead_nurture_send()

        assert len(calls_with_opted_out) >= 2, (
            "Both null and overdue lead queries must filter nurture_opted_out=False"
        )

    def test_graduation_worker_query_includes_opted_out_false_filter(self):
        """
        run_lead_graduation_check must filter out opted-out leads.
        """
        from app.workers import lead_graduation_worker

        db = _mock_db()
        orgs = [{
            "id": ORG_ID,
            "nurture_track_enabled": True,
            "conversion_attempt_days": 14,
            "nurture_sequence": [{"mode": "custom", "template": "Hi"}],
        }]

        calls_with_opted_out = []

        class TrackingChain:
            def __getattr__(self, name):
                def method(*args, **kwargs):
                    if name == "eq" and args == ("nurture_opted_out", False):
                        calls_with_opted_out.append(True)
                    return TrackingChain()
                return method

            def execute(self):
                return MagicMock(data=[])

        def table_side(name: str):
            mock = MagicMock()
            if name == "organisations":
                chain = MagicMock()
                chain.eq.return_value = chain
                chain.execute.return_value = MagicMock(data=orgs)
                mock.select.return_value = chain
            else:
                mock.select.return_value = TrackingChain()
            mock.insert.return_value = MagicMock(execute=lambda: MagicMock(data=[]))
            mock.update.return_value = MagicMock(execute=lambda: MagicMock(data=[]))
            return mock

        db.table.side_effect = table_side

        with patch("app.workers.lead_graduation_worker.get_supabase", return_value=db):
            lead_graduation_worker.run_lead_graduation_check()

        assert len(calls_with_opted_out) >= 1, (
            "Graduation candidate query must filter nurture_opted_out=False"
        )