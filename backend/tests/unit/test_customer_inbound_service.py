"""
tests/unit/test_customer_inbound_service.py
WH-1 unit tests — Customer Intent Classifier.

Covers:
  - detect_nps_score: numeric 0-10, written forms, out-of-range, None
  - classify_renewal_reply: cancel / confirm / other, S14 fallback
  - classify_customer_intent: all 4 branches, S14 fallback
  - classify_lead_stage_signal: all 4 branches per stage, S14 fallback
  - lookup_kb_answer: found informational, found action_required, not found, S14 fallback
  - handle_customer_inbound: NPS path, renewal path, drip path,
      KB informational, KB action_required, ticket intent, billing intent, general path
  - create_action_task: task inserted, rep + managers notified
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch, call

import pytest

from app.services.customer_inbound_service import (
    detect_nps_score,
    classify_renewal_reply,
    classify_customer_intent,
    classify_lead_stage_signal,
    lookup_kb_answer,
    handle_customer_inbound,
    create_action_task,
    handle_lead_stage_signal,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID      = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
ARTICLE_ID  = str(uuid.uuid4())
USER_ID     = str(uuid.uuid4())
MGR_ID      = str(uuid.uuid4())
NOW_TS      = "2026-04-15T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.in_.return_value = chain
    chain.is_.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.maybe_single.return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.execute.return_value = MagicMock(data=[], count=0)
    db.table.return_value = chain
    return db, chain


# ===========================================================================
# detect_nps_score
# ===========================================================================

class TestDetectNpsScore:
    def test_integer_0(self):
        assert detect_nps_score("0") == 0

    def test_integer_10(self):
        assert detect_nps_score("10") == 10

    def test_integer_7(self):
        assert detect_nps_score("7") == 7

    def test_written_ten(self):
        assert detect_nps_score("ten") == 10

    def test_written_zero(self):
        assert detect_nps_score("zero") == 0

    def test_written_seven(self):
        assert detect_nps_score("seven") == 7

    def test_out_of_range_11(self):
        assert detect_nps_score("11") is None

    def test_negative(self):
        assert detect_nps_score("-1") is None

    def test_free_text(self):
        assert detect_nps_score("great service!") is None

    def test_empty_string(self):
        assert detect_nps_score("") is None

    def test_none_input(self):
        assert detect_nps_score(None) is None

    def test_with_spaces(self):
        # "  8  " stripped → "8"
        assert detect_nps_score("  8  ") == 8


# ===========================================================================
# classify_renewal_reply
# ===========================================================================

class TestClassifyRenewalReply:
    def test_cancel_intent(self):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            return_value="cancel",
        ):
            assert classify_renewal_reply("I want to stop my subscription") == "cancel"

    def test_confirm_intent(self):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            return_value="confirm",
        ):
            assert classify_renewal_reply("Yes please renew") == "confirm"

    def test_other_intent(self):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            return_value="other",
        ):
            assert classify_renewal_reply("Just checking in") == "other"

    def test_s14_fallback_on_exception(self):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            side_effect=Exception("API down"),
        ):
            assert classify_renewal_reply("some message") == "other"

    def test_unexpected_response_returns_other(self):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            return_value="UNKNOWN_VALUE",
        ):
            assert classify_renewal_reply("hmm") == "other"


# ===========================================================================
# classify_customer_intent
# ===========================================================================

class TestClassifyCustomerIntent:
    @pytest.mark.parametrize("haiku_response,expected", [
        ("ticket",  "ticket"),
        ("billing", "billing"),
        ("renewal", "renewal"),
        ("general", "general"),
    ])
    def test_all_branches(self, haiku_response, expected):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            return_value=haiku_response,
        ):
            assert classify_customer_intent("some message") == expected

    def test_s14_fallback_on_exception(self):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            side_effect=RuntimeError("timeout"),
        ):
            assert classify_customer_intent("anything") == "general"

    def test_unexpected_response_returns_general(self):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            return_value="something_else",
        ):
            assert classify_customer_intent("msg") == "general"


# ===========================================================================
# classify_lead_stage_signal
# ===========================================================================

class TestClassifyLeadStageSignal:
    @pytest.mark.parametrize("stage", ["contacted", "demo_done", "proposal_sent"])
    @pytest.mark.parametrize("signal", ["buying", "stalling", "objection", "neutral"])
    def test_all_branches_all_stages(self, stage, signal):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            return_value=signal,
        ):
            assert classify_lead_stage_signal("some message", stage) == signal

    def test_s14_fallback_on_exception(self):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            side_effect=Exception("network error"),
        ):
            assert classify_lead_stage_signal("msg", "contacted") == "neutral"

    def test_unexpected_response_returns_neutral(self):
        with patch(
            "app.services.customer_inbound_service._call_haiku",
            return_value="random",
        ):
            assert classify_lead_stage_signal("msg", "demo_done") == "neutral"


# ===========================================================================
# lookup_kb_answer
# ===========================================================================

class TestLookupKbAnswer:
    def _article(self, action_type="informational"):
        return {
            "id": ARTICLE_ID,
            "title": "How to reset your password",
            "content": "Go to settings and click reset password.",
            "tags": ["password", "reset", "account"],
            "action_type": action_type,
        }

    def _sonnet_response_found(self, action_type="informational", action_label=""):
        return (
            f"FOUND: YES\n"
            f"ARTICLE_ID: {ARTICLE_ID}\n"
            f"ACTION_TYPE: {action_type}\n"
            f"ACTION_LABEL: {action_label}\n"
            f"REPLY: To reset your password, go to settings and click reset."
        )

    def test_found_informational(self):
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._article("informational")])
        with patch(
            "app.services.customer_inbound_service._call_sonnet",
            return_value=self._sonnet_response_found("informational"),
        ):
            result = lookup_kb_answer(db, ORG_ID, "how do I reset my password?")
        assert result is not None
        assert result["found"] is True
        assert result["action_type"] == "informational"
        assert result["article_id"] == ARTICLE_ID
        assert "reset" in result["answer"].lower()

    def test_found_action_required_with_label(self):
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._article("action_required")])
        with patch(
            "app.services.customer_inbound_service._call_sonnet",
            return_value=self._sonnet_response_found(
                "action_required", "Process refund in billing system"
            ),
        ):
            result = lookup_kb_answer(db, ORG_ID, "how do I reset my account password?")
        assert result is not None
        assert result["action_type"] == "action_required"
        assert result["action_label"] == "Process refund in billing system"

    def test_not_found(self):
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._article()])
        with patch(
            "app.services.customer_inbound_service._call_sonnet",
            return_value="FOUND: NO",
        ):
            result = lookup_kb_answer(db, ORG_ID, "something not in KB")
        assert result is None

    def test_no_articles_returns_none(self):
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[])
        result = lookup_kb_answer(db, ORG_ID, "any message")
        assert result is None

    def test_s14_fallback_on_exception(self):
        db, chain = _mock_db()
        chain.execute.side_effect = Exception("DB error")
        result = lookup_kb_answer(db, ORG_ID, "any message")
        assert result is None

    def test_s14_on_sonnet_failure(self):
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._article()])
        with patch(
            "app.services.customer_inbound_service._call_sonnet",
            side_effect=Exception("API failure"),
        ):
            result = lookup_kb_answer(db, ORG_ID, "any message")
        assert result is None


# ===========================================================================
# create_action_task
# ===========================================================================

class TestCreateActionTask:
    def test_task_inserted_and_rep_notified(self):
        db, chain = _mock_db()
        task_id = str(uuid.uuid4())
        chain.execute.return_value = MagicMock(data={"id": task_id})

        with patch(
            "app.services.customer_inbound_service._insert_notification"
        ) as mock_notif, patch(
            "app.services.customer_inbound_service._notify_managers"
        ) as mock_mgr:
            create_action_task(
                db=db,
                org_id=ORG_ID,
                customer_id=CUSTOMER_ID,
                customer_name="Amaka Obi",
                article_id=ARTICLE_ID,
                article_title="Refund Policy",
                action_label="Process refund in billing system",
                message_content="I want a refund please",
                assigned_to=USER_ID,
                now_ts=NOW_TS,
            )

        db.table.assert_any_call("tasks")
        mock_notif.assert_called_once()
        notif_kwargs = mock_notif.call_args[1]
        assert notif_kwargs["user_id"] == USER_ID
        assert "Process refund in billing system" in notif_kwargs["title"]
        assert "Amaka Obi" in notif_kwargs["title"]
        mock_mgr.assert_called_once()

    def test_task_title_uses_action_label(self):
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data={"id": str(uuid.uuid4())})
        captured_rows = []

        def capture_insert(row):
            captured_rows.append(row)
            return chain
        db.table.return_value.insert = capture_insert

        with patch("app.services.customer_inbound_service._insert_notification"), \
             patch("app.services.customer_inbound_service._notify_managers"):
            create_action_task(
                db=db,
                org_id=ORG_ID,
                customer_id=CUSTOMER_ID,
                customer_name="Chidi Eze",
                article_id=ARTICLE_ID,
                article_title="Plan Upgrade Process",
                action_label="Upgrade plan in admin panel",
                message_content="Can I upgrade my plan?",
                assigned_to=USER_ID,
                now_ts=NOW_TS,
            )

        if captured_rows:
            title = captured_rows[0].get("title", "")
            assert 'Action required: "Upgrade plan in admin panel"' in title
            assert "Chidi Eze" in title

    def test_task_title_falls_back_to_article_title_when_no_label(self):
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data={"id": str(uuid.uuid4())})
        captured_rows = []

        def capture_insert(row):
            captured_rows.append(row)
            return chain
        db.table.return_value.insert = capture_insert

        with patch("app.services.customer_inbound_service._insert_notification"), \
             patch("app.services.customer_inbound_service._notify_managers"):
            create_action_task(
                db=db,
                org_id=ORG_ID,
                customer_id=CUSTOMER_ID,
                customer_name="Tunde",
                article_id=ARTICLE_ID,
                article_title="Account Deletion Policy",
                action_label="",  # no label set
                message_content="Please delete my account",
                assigned_to=USER_ID,
                now_ts=NOW_TS,
            )

        if captured_rows:
            title = captured_rows[0].get("title", "")
            assert "Account Deletion Policy" in title

    def test_s14_no_raise_on_db_failure(self):
        db = MagicMock()
        db.table.side_effect = Exception("DB is down")
        create_action_task(
            db=db,
            org_id=ORG_ID,
            customer_id=CUSTOMER_ID,
            customer_name="Test",
            article_id=ARTICLE_ID,
            article_title="Some Article",
            action_label="Do something",
            message_content="help",
            assigned_to=USER_ID,
            now_ts=NOW_TS,
        )


# ===========================================================================
# handle_customer_inbound
# ===========================================================================

def _base_db():
    db, chain = _mock_db()
    # Default: customers.full_name lookup returns name
    chain.execute.return_value = MagicMock(data={"full_name": "Ngozi Adeyemi"})
    return db, chain


# ===========================================================================
# handle_customer_inbound
# ===========================================================================

class TestHandleCustomerInbound:

    def test_nps_context_score_written(self):
        db, chain = _base_db()
        # _get_last_outbound_context returns nps_survey
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value="nps_survey",
        ), patch(
            "app.services.customer_inbound_service._write_nps_score"
        ) as mock_nps:
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="8", msg_type="text", assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_nps.assert_called_once()
        assert mock_nps.call_args[1]["score"] == 8
        assert result is True

    def test_nps_context_non_numeric_falls_to_kb(self):
        db, chain = _base_db()
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value="nps_survey",
        ), patch(
            "app.services.customer_inbound_service.lookup_kb_answer",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.classify_customer_intent",
            return_value="general",
        ):
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="thanks for asking!", msg_type="text",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        assert result is False  # general path

    def test_renewal_context_handled(self):
        db, chain = _base_db()
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value="renewal_reminder",
        ), patch(
            "app.services.customer_inbound_service._handle_renewal_reply"
        ) as mock_renewal:
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="please cancel", msg_type="text",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_renewal.assert_called_once()
        assert result is True

    def test_drip_context_handled(self):
        db, chain = _base_db()
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value="drip",
        ), patch(
            "app.services.customer_inbound_service._handle_drip_reply"
        ) as mock_drip:
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="hey!", msg_type="text",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_drip.assert_called_once()
        assert result is True

    def test_kb_informational_auto_sends(self):
        db, chain = _base_db()
        kb_result = {
            "found": True,
            "answer": "To reset your password, go to settings.",
            "article_id": ARTICLE_ID,
            "action_type": "informational",
        }
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.lookup_kb_answer",
            return_value=kb_result,
        ), patch(
            "app.services.customer_inbound_service._send_whatsapp_reply"
        ) as mock_send, patch(
            "app.services.customer_inbound_service.create_action_task"
        ) as mock_task:
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="how do I reset my password?", msg_type="text",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_send.assert_called_once()
        mock_task.assert_not_called()
        assert result is True

    def test_kb_action_required_sends_and_creates_task(self):
        db, chain = _base_db()
        kb_result = {
            "found": True,
            "answer": "Our refund policy allows refunds within 14 days.",
            "article_id": ARTICLE_ID,
            "action_type": "action_required",
            "action_label": "Process refund in billing system",
        }
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.lookup_kb_answer",
            return_value=kb_result,
        ), patch(
            "app.services.customer_inbound_service._send_whatsapp_reply"
        ) as mock_send, patch(
            "app.services.customer_inbound_service.create_action_task"
        ) as mock_task:
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="I want a refund", msg_type="text",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_send.assert_called_once()
        mock_task.assert_called_once()
        # Verify action_label was passed through
        task_kwargs = mock_task.call_args[1]
        assert task_kwargs["action_label"] == "Process refund in billing system"
        assert result is True

    def test_no_kb_ticket_intent_creates_ticket(self):
        db, chain = _base_db()
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.lookup_kb_answer",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.classify_customer_intent",
            return_value="ticket",
        ), patch(
            "app.services.customer_inbound_service._auto_create_ticket"
        ) as mock_ticket:
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="my dashboard is broken", msg_type="text",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_ticket.assert_called_once()
        assert result is True

    def test_no_kb_billing_intent_notifies_finance(self):
        db, chain = _base_db()
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.lookup_kb_answer",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.classify_customer_intent",
            return_value="billing",
        ), patch(
            "app.services.customer_inbound_service._notify_finance"
        ) as mock_finance:
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="I have a question about my invoice", msg_type="text",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_finance.assert_called_once()
        assert result is True

    def test_no_kb_general_intent_returns_false(self):
        db, chain = _base_db()
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.lookup_kb_answer",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.classify_customer_intent",
            return_value="general",
        ):
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="just saying hello!", msg_type="text",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        assert result is False  # triggers standard rep notification in webhooks.py

    def test_non_text_message_returns_false(self):
        db, chain = _base_db()
        with patch(
            "app.services.customer_inbound_service._get_last_outbound_context",
            return_value=None,
        ):
            result = handle_customer_inbound(
                db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
                content="[Image]", msg_type="image",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        assert result is False

    def test_s14_exception_returns_false(self):
        db = MagicMock()
        db.table.side_effect = Exception("total failure")
        result = handle_customer_inbound(
            db=db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
            content="help", msg_type="text",
            assigned_to=USER_ID, now_ts=NOW_TS,
        )
        assert result is False


# ===========================================================================
# handle_lead_stage_signal
# ===========================================================================

class TestHandleLeadStageSignal:
    @pytest.mark.parametrize("signal,stage", [
        ("buying",    "contacted"),
        ("stalling",  "demo_done"),
        ("objection", "proposal_sent"),
    ])
    def test_signal_notifies_rep(self, signal, stage):
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data={"full_name": "Bola Tinubu"})
        with patch(
            "app.services.customer_inbound_service.classify_lead_stage_signal",
            return_value=signal,
        ), patch(
            "app.services.customer_inbound_service._insert_notification"
        ) as mock_notif:
            handle_lead_stage_signal(
                db=db, org_id=ORG_ID, lead_id=str(uuid.uuid4()),
                stage=stage, content="I'm ready to proceed",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_notif.assert_called_once()
        assert mock_notif.call_args[1]["user_id"] == USER_ID

    def test_neutral_no_notification(self):
        db, chain = _mock_db()
        with patch(
            "app.services.customer_inbound_service.classify_lead_stage_signal",
            return_value="neutral",
        ), patch(
            "app.services.customer_inbound_service._insert_notification"
        ) as mock_notif:
            handle_lead_stage_signal(
                db=db, org_id=ORG_ID, lead_id=str(uuid.uuid4()),
                stage="contacted", content="ok",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_notif.assert_not_called()

    def test_wrong_stage_skipped(self):
        db, chain = _mock_db()
        with patch(
            "app.services.customer_inbound_service.classify_lead_stage_signal"
        ) as mock_classify:
            handle_lead_stage_signal(
                db=db, org_id=ORG_ID, lead_id=str(uuid.uuid4()),
                stage="new", content="hello",
                assigned_to=USER_ID, now_ts=NOW_TS,
            )
        mock_classify.assert_not_called()

    def test_s14_no_raise_on_exception(self):
        db = MagicMock()
        db.table.side_effect = Exception("boom")
        # Should not raise
        handle_lead_stage_signal(
            db=db, org_id=ORG_ID, lead_id=str(uuid.uuid4()),
            stage="contacted", content="ready to buy",
            assigned_to=USER_ID, now_ts=NOW_TS,
        )
