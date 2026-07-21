"""
tests/unit/test_ai_agent_service.py
AI-AGENT-1B — unit tests for app/services/ai_agent_service.py

Follows the conventions established in test_lead_assignment_service.py:
  - No shared conftest fixtures — self-contained MagicMock chains per test.
  - db.table.side_effect keyed by table name where multiple tables are hit.
  - Lazy `from X import Y` imports inside function bodies are patched at
    their SOURCE module (Pattern 63) — e.g. patch
    "app.services.whatsapp_service.send_agent_text_message", not the
    ai_agent_service reference to it.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

ORG_ID = "11111111-1111-1111-1111-111111111111"
LEAD_ID = "22222222-2222-2222-2222-222222222222"
REP_ID = "33333333-3333-3333-3333-333333333333"
ROLE_ID = "44444444-4444-4444-4444-444444444444"
AGENT_USER_ID = "55555555-5555-5555-5555-555555555555"
SESSION_ID = "66666666-6666-6666-6666-666666666666"


def _chain(data):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.limit.return_value = chain
    chain.order.return_value = chain
    chain.maybe_single.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.execute.return_value = MagicMock(data=data)
    return chain


# ═══════════════════════════════════════════════════════════════════════════
# _get_or_create_ai_agent_user
# ═══════════════════════════════════════════════════════════════════════════

class TestGetOrCreateAiAgentUser:

    def test_AI_U_01_returns_existing_system_user(self):
        """AI-U-01: existing is_system_user row found → returns its id."""
        from app.services.ai_agent_service import _get_or_create_ai_agent_user
        db = MagicMock()
        db.table.return_value = _chain([{"id": AGENT_USER_ID}])
        result = _get_or_create_ai_agent_user(db, ORG_ID)
        assert result == AGENT_USER_ID

    def test_AI_U_02_creates_new_user_when_none_exists(self):
        """AI-U-02: no existing system user → creates one with sales_agent role_id."""
        from app.services.ai_agent_service import _get_or_create_ai_agent_user

        def table_side(name):
            if name == "users":
                return _chain([])  # no existing system user
            if name == "roles":
                return _chain([{"id": ROLE_ID}])
            return _chain([])

        db = MagicMock()
        db.table.side_effect = table_side
        result = _get_or_create_ai_agent_user(db, ORG_ID)
        assert result is not None
        # Confirm an insert into "users" was attempted
        insert_calls = [c for c in db.table.call_args_list if c[0][0] == "users"]
        assert len(insert_calls) >= 1

    def test_AI_U_03_no_sales_agent_role_returns_none(self):
        """AI-U-03: org has no sales_agent role template → returns None, does not insert."""
        from app.services.ai_agent_service import _get_or_create_ai_agent_user

        def table_side(name):
            if name == "users":
                return _chain([])
            if name == "roles":
                return _chain([])  # no sales_agent role found
            return _chain([])

        db = MagicMock()
        db.table.side_effect = table_side
        result = _get_or_create_ai_agent_user(db, ORG_ID)
        assert result is None

    def test_AI_U_04_s14_db_error_never_raises(self):
        """AI-U-04: S14 — DB exception on lookup returns None, never raises."""
        from app.services.ai_agent_service import _get_or_create_ai_agent_user
        db = MagicMock()
        db.table.side_effect = Exception("DB connection lost")
        result = _get_or_create_ai_agent_user(db, ORG_ID)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# parse_agent_action
# ═══════════════════════════════════════════════════════════════════════════

class TestParseAgentAction:

    def test_AI_U_05_valid_json_parses(self):
        """AI-U-05: well-formed action contract parses correctly."""
        from app.services.ai_agent_service import parse_agent_action
        raw = json.dumps({"action": "respond", "message": "Hi there!", "data": {}})
        result = parse_agent_action(raw)
        assert result == {"action": "respond", "message": "Hi there!", "data": {}}

    def test_AI_U_06_strips_markdown_fences(self):
        """AI-U-06: ```json ... ``` fences are stripped before parsing."""
        from app.services.ai_agent_service import parse_agent_action
        raw = '```json\n{"action": "respond", "message": "Hi", "data": {}}\n```'
        result = parse_agent_action(raw)
        assert result is not None
        assert result["action"] == "respond"

    def test_AI_U_07_invalid_action_returns_none(self):
        """AI-U-07: action outside the 7 allowed values → None."""
        from app.services.ai_agent_service import parse_agent_action
        raw = json.dumps({"action": "do_anything", "message": "hi", "data": {}})
        assert parse_agent_action(raw) is None

    def test_AI_U_08_empty_message_returns_none(self):
        """AI-U-08: empty/missing message → None."""
        from app.services.ai_agent_service import parse_agent_action
        raw = json.dumps({"action": "respond", "message": "", "data": {}})
        assert parse_agent_action(raw) is None

    def test_AI_U_09_data_not_dict_returns_none(self):
        """AI-U-09: 'data' field not a dict → None."""
        from app.services.ai_agent_service import parse_agent_action
        raw = json.dumps({"action": "respond", "message": "hi", "data": "oops"})
        assert parse_agent_action(raw) is None

    def test_AI_U_10_malformed_json_returns_none(self):
        """AI-U-10: JSONDecodeError → None, never raises."""
        from app.services.ai_agent_service import parse_agent_action
        assert parse_agent_action("{not valid json") is None

    def test_AI_U_11_non_dict_json_returns_none(self):
        """AI-U-11: valid JSON but not an object (e.g. a list) → None."""
        from app.services.ai_agent_service import parse_agent_action
        assert parse_agent_action("[1, 2, 3]") is None


# ═══════════════════════════════════════════════════════════════════════════
# build_agent_system_prompt
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildAgentSystemPrompt:

    def test_AI_U_12_includes_org_name_and_business_model(self):
        """AI-U-12: prompt includes org name and business_model."""
        from app.services.ai_agent_service import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            org={"name": "Royal Rest"},
            ai_agent_config={"business_model": "physical_product", "qualifying_criteria": "wants a mattress"},
            catalog_config={},
            kb_articles=[],
            cart=None,
            conversation_history=[],
        )
        assert "Royal Rest" in prompt
        assert "physical_product" in prompt

    def test_AI_U_13_skips_disqualification_block_when_absent(self):
        """AI-U-13: no disqualification_criteria → block omitted."""
        from app.services.ai_agent_service import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            org={"name": "Royal Rest"},
            ai_agent_config={"qualifying_criteria": "x"},
            catalog_config={},
            kb_articles=[],
            cart=None,
            conversation_history=[],
        )
        assert "disqualification_criteria" not in prompt

    def test_AI_U_14_includes_disqualification_when_present(self):
        """AI-U-14: disqualification_criteria set → block included."""
        from app.services.ai_agent_service import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            org={"name": "Royal Rest"},
            ai_agent_config={
                "qualifying_criteria": "x",
                "disqualification_criteria": "just browsing, no budget",
            },
            catalog_config={},
            kb_articles=[],
            cart=None,
            conversation_history=[],
        )
        assert "disqualification_criteria" in prompt
        assert "just browsing" in prompt

    def test_AI_U_15_includes_action_contract_instruction(self):
        """AI-U-15: action contract JSON schema instruction always present."""
        from app.services.ai_agent_service import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            org={"name": "Royal Rest"},
            ai_agent_config={"qualifying_criteria": "x"},
            catalog_config={},
            kb_articles=[],
            cart=None,
            conversation_history=[],
        )
        assert "respond | recommend_product | request_variant" in prompt

    def test_AI_U_16_s14_never_raises_on_bad_input(self):
        """AI-U-16: S14 — malformed inputs return a safe fallback prompt, never raise."""
        from app.services.ai_agent_service import build_agent_system_prompt
        prompt = build_agent_system_prompt(
            org=None, ai_agent_config=None, catalog_config=None,
            kb_articles=None, cart=None, conversation_history=None,
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ═══════════════════════════════════════════════════════════════════════════
# run_agent_turn
# ═══════════════════════════════════════════════════════════════════════════

class TestRunAgentTurn:

    def _base_org_row(self):
        return {
            "name": "Royal Rest",
            "ai_agent_config": {"qualifying_criteria": "x", "max_turns_before_escalation": 20},
            "commerce_config": {},
        }

    def test_AI_U_17_happy_path_returns_action_dict(self):
        """AI-U-17: successful call_claude + valid JSON → returns parsed action."""
        from app.services.ai_agent_service import run_agent_turn

        db = MagicMock()

        def table_side(name):
            if name == "organisations":
                return _chain(self._base_org_row())
            if name == "kb_articles":
                return _chain([])
            if name == "products":
                return _chain([])
            if name == "commerce_sessions":
                return _chain(None)
            if name == "whatsapp_sessions":
                return _chain(None)
            return _chain([])

        db.table.side_effect = table_side

        session = {"id": SESSION_ID, "phone_number": "+2348000000000",
                   "session_data": {}, "conversation_history": []}
        lead = {"id": LEAD_ID}

        raw_response = json.dumps({"action": "respond", "message": "Hello!", "data": {}})
        with patch("app.services.ai_agent_service.call_claude", return_value=raw_response):
            result = run_agent_turn(db, ORG_ID, session, lead, "Hi, I need a mattress")

        assert result is not None
        assert result["action"] == "respond"

    def test_AI_U_18_empty_claude_response_returns_none(self):
        """AI-U-18: call_claude returns "" (hard limit / API error) → None."""
        from app.services.ai_agent_service import run_agent_turn

        db = MagicMock()

        def table_side(name):
            if name == "organisations":
                return _chain(self._base_org_row())
            return _chain([])

        db.table.side_effect = table_side

        session = {"id": SESSION_ID, "phone_number": "+2348000000000",
                   "session_data": {}, "conversation_history": []}

        with patch("app.services.ai_agent_service.call_claude", return_value=""):
            result = run_agent_turn(db, ORG_ID, session, {"id": LEAD_ID}, "hi")

        assert result is None

    def test_AI_U_19_turn_limit_exceeded_overrides_to_escalate(self):
        """AI-U-19: turn count >= max_turns_before_escalation → action forced to escalate."""
        from app.services.ai_agent_service import run_agent_turn

        org_row = self._base_org_row()
        org_row["ai_agent_config"]["max_turns_before_escalation"] = 1

        db = MagicMock()

        def table_side(name):
            if name == "organisations":
                return _chain(org_row)
            return _chain([])

        db.table.side_effect = table_side

        session = {
            "id": SESSION_ID, "phone_number": "+2348000000000",
            "session_data": {"agent_turn_count": 0}, "conversation_history": [],
        }
        raw_response = json.dumps({"action": "respond", "message": "still chatting", "data": {}})

        with patch("app.services.ai_agent_service.call_claude", return_value=raw_response):
            result = run_agent_turn(db, ORG_ID, session, {"id": LEAD_ID}, "hi")

        assert result is not None
        assert result["action"] == "escalate"
        assert result["data"]["reason"] == "turn_limit_exceeded"

    def test_AI_U_20_s14_db_error_never_raises(self):
        """AI-U-20: S14 — unexpected DB exception returns None, never raises."""
        from app.services.ai_agent_service import run_agent_turn
        db = MagicMock()
        db.table.side_effect = Exception("DB down")
        session = {"id": SESSION_ID, "phone_number": "+2348000000000",
                   "session_data": {}, "conversation_history": []}
        result = run_agent_turn(db, ORG_ID, session, {"id": LEAD_ID}, "hi")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# _execute_agent_action
# ═══════════════════════════════════════════════════════════════════════════

class TestExecuteAgentAction:

    def _session(self):
        return {"id": SESSION_ID, "phone_number": "+2348000000000", "session_data": {}}

    def _number_row(self):
        return {"phone_id": "phone-123", "access_token": "token-abc"}

    def test_AI_U_21_respond_calls_send_agent_text_message(self):
        """AI-U-21: 'respond' action → send_agent_text_message called with the message."""
        from app.services.ai_agent_service import _execute_agent_action
        db = MagicMock()
        action_dict = {"action": "respond", "message": "Sure thing!", "data": {}}

        with patch("app.services.whatsapp_service.send_agent_text_message") as mock_send:
            _execute_agent_action(db, ORG_ID, self._number_row(), self._session(), {"id": LEAD_ID}, action_dict)
            mock_send.assert_called_once()
            assert mock_send.call_args.kwargs["message"] == "Sure thing!"

    def test_AI_U_22_recommend_product_found_calls_send_recommendation(self):
        """AI-U-22: 'recommend_product' with a real product_id → send_recommendation_message."""
        from app.services.ai_agent_service import _execute_agent_action
        db = MagicMock()
        db.table.return_value = _chain({"id": "prod-1", "title": "Queen Mattress", "price": 150000})
        action_dict = {
            "action": "recommend_product",
            "message": "This one fits your needs",
            "data": {"product_id": "prod-1"},
        }

        with patch("app.services.whatsapp_service.send_recommendation_message") as mock_send:
            _execute_agent_action(db, ORG_ID, self._number_row(), self._session(), {"id": LEAD_ID}, action_dict)
            mock_send.assert_called_once()
            assert mock_send.call_args.kwargs["wa_credentials"] == ("phone-123", "token-abc", None)

    def test_AI_U_23_confirm_add_to_cart_persists_pending_confirmation(self):
        """AI-U-23: 'confirm_add_to_cart' saves pending_agent_confirmation to session_data
        BEFORE sending buttons — model never adds to cart directly."""
        from app.services.ai_agent_service import _execute_agent_action
        db = MagicMock()
        action_dict = {
            "action": "confirm_add_to_cart",
            "message": "Add the Queen Mattress to your cart?",
            "data": {"product_id": "prod-1", "variant_id": "var-1"},
        }

        with patch("app.services.whatsapp_service.send_agent_confirm_buttons"):
            _execute_agent_action(db, ORG_ID, self._number_row(), self._session(), {"id": LEAD_ID}, action_dict)

        update_calls = [c for c in db.table.call_args_list if c[0][0] == "whatsapp_sessions"]
        assert len(update_calls) >= 1

    def test_AI_U_24_mark_qualified_calls_qualification_outcome_and_sends_message(self):
        """AI-U-24: 'mark_qualified' triggers _handle_qualification_outcome and sends the message."""
        from app.services.ai_agent_service import _execute_agent_action
        db = MagicMock()
        action_dict = {
            "action": "mark_qualified",
            "message": "Great, someone will follow up shortly!",
            "data": {"ready_to_close": True, "extracted_fields": {}},
        }

        with patch("app.services.ai_agent_service._handle_qualification_outcome") as mock_outcome, \
             patch("app.services.whatsapp_service.send_agent_text_message") as mock_send:
            _execute_agent_action(db, ORG_ID, self._number_row(), self._session(), {"id": LEAD_ID}, action_dict)
            mock_outcome.assert_called_once()
            mock_send.assert_called_once()

    def test_AI_U_25_escalate_calls_escalate_to_rep(self):
        """AI-U-25: 'escalate' action → _escalate_to_rep called with the model's reason."""
        from app.services.ai_agent_service import _execute_agent_action
        db = MagicMock()
        action_dict = {
            "action": "escalate",
            "message": "Let me get a team member for you.",
            "data": {"reason": "complaint"},
        }

        with patch("app.services.ai_agent_service._escalate_to_rep") as mock_escalate, \
             patch("app.services.whatsapp_service.send_agent_text_message"):
            _execute_agent_action(db, ORG_ID, self._number_row(), self._session(), {"id": LEAD_ID}, action_dict)
            mock_escalate.assert_called_once()
            assert mock_escalate.call_args.kwargs["reason"] == "complaint"

    def test_AI_U_26_variant_match_fails_twice_escalates(self):
        """AI-U-26: request_variant with low confidence, 2nd consecutive failure → escalates
        instead of sending another variant prompt (Escalation Trigger Catalog)."""
        from app.services.ai_agent_service import _execute_agent_action
        db = MagicMock()
        session = {
            "id": SESSION_ID, "phone_number": "+2348000000000",
            "session_data": {"variant_match_failures": 1},
        }
        action_dict = {
            "action": "request_variant",
            "message": "Did you mean the King size?",
            "data": {"product_id": "prod-1", "confidence": "low"},
        }

        with patch("app.services.ai_agent_service._escalate_to_rep") as mock_escalate, \
             patch("app.services.whatsapp_service.send_agent_confirm_buttons") as mock_buttons:
            _execute_agent_action(db, ORG_ID, self._number_row(), session, {"id": LEAD_ID}, action_dict)
            mock_escalate.assert_called_once()
            assert mock_escalate.call_args.kwargs["reason"] == "variant_match_failed_twice"
            mock_buttons.assert_not_called()

    def test_AI_U_27_s14_exception_in_branch_never_raises(self):
        """AI-U-27: S14 — exception inside a branch is caught, function returns normally."""
        from app.services.ai_agent_service import _execute_agent_action
        db = MagicMock()
        action_dict = {"action": "respond", "message": "hi", "data": {}}

        with patch(
            "app.services.whatsapp_service.send_agent_text_message",
            side_effect=Exception("Meta API down"),
        ):
            # Must not raise
            _execute_agent_action(db, ORG_ID, self._number_row(), self._session(), {"id": LEAD_ID}, action_dict)


# ═══════════════════════════════════════════════════════════════════════════
# _handle_qualification_outcome
# ═══════════════════════════════════════════════════════════════════════════

class TestHandleQualificationOutcome:

    def _session(self):
        return {"id": SESSION_ID, "conversation_history": [
            {"role": "user", "content": "I need a queen mattress"},
            {"role": "assistant", "content": "Great choice!"},
        ]}

    def test_AI_U_28_ready_to_close_advances_stage_and_creates_high_priority_task(self):
        """AI-U-28: ready_to_close=True → move_stage called, high-priority task created."""
        from app.services.ai_agent_service import _handle_qualification_outcome
        db = MagicMock()

        def table_side(name):
            if name == "organisations":
                return _chain({"ai_agent_config": {"fields_to_extract": []}, "name": "Royal Rest"})
            return _chain([])

        db.table.side_effect = table_side

        with patch("app.services.ai_agent_service.call_claude", return_value="Summary text"), \
             patch("app.services.ai_agent_service.auto_assign_lead", return_value=REP_ID) as mock_assign, \
             patch("app.services.lead_service.move_stage") as mock_move_stage, \
             patch("app.services.lead_service.write_timeline_event"):
            _handle_qualification_outcome(
                db, ORG_ID, LEAD_ID, ready_to_close=True,
                extracted_fields={}, session=self._session(),
            )
            mock_assign.assert_called_once()
            mock_move_stage.assert_called_once()

        task_inserts = [c for c in db.table.call_args_list if c[0][0] == "tasks"]
        assert len(task_inserts) >= 1

    def test_AI_U_29_not_ready_creates_medium_priority_task_no_stage_advance(self):
        """AI-U-29: ready_to_close=False → no move_stage call, task still created."""
        from app.services.ai_agent_service import _handle_qualification_outcome
        db = MagicMock()

        def table_side(name):
            if name == "organisations":
                return _chain({"ai_agent_config": {"fields_to_extract": []}, "name": "Royal Rest"})
            return _chain([])

        db.table.side_effect = table_side

        with patch("app.services.ai_agent_service.call_claude", return_value="Summary text"), \
             patch("app.services.ai_agent_service.auto_assign_lead", return_value=REP_ID), \
             patch("app.services.lead_service.move_stage") as mock_move_stage, \
             patch("app.services.lead_service.write_timeline_event"):
            _handle_qualification_outcome(
                db, ORG_ID, LEAD_ID, ready_to_close=False,
                extracted_fields={}, session=self._session(),
            )
            mock_move_stage.assert_not_called()

    def test_AI_U_30_extracted_fields_written_per_mapping(self):
        """AI-U-30: extracted_fields written to leads per fields_to_extract mapping."""
        from app.services.ai_agent_service import _handle_qualification_outcome
        db = MagicMock()

        def table_side(name):
            if name == "organisations":
                return _chain({
                    "ai_agent_config": {
                        "fields_to_extract": [
                            {"answer_key": "product_interest", "map_to_lead_field": "product_interest"},
                        ],
                    },
                    "name": "Royal Rest",
                })
            return _chain([])

        db.table.side_effect = table_side

        with patch("app.services.ai_agent_service.call_claude", return_value="Summary text"), \
             patch("app.services.ai_agent_service.auto_assign_lead", return_value=None), \
             patch("app.services.lead_service.write_timeline_event"):
            _handle_qualification_outcome(
                db, ORG_ID, LEAD_ID, ready_to_close=False,
                extracted_fields={"product_interest": "Queen Mattress"},
                session=self._session(),
            )

        leads_updates = [
            c for c in db.table.call_args_list if c[0][0] == "leads"
        ]
        assert len(leads_updates) >= 1

    def test_AI_U_31_s14_never_raises_on_db_error(self):
        """AI-U-31: S14 — exception anywhere in the pipeline never raises."""
        from app.services.ai_agent_service import _handle_qualification_outcome
        db = MagicMock()
        db.table.side_effect = Exception("DB down")
        # Must not raise
        _handle_qualification_outcome(
            db, ORG_ID, LEAD_ID, ready_to_close=True,
            extracted_fields={}, session=self._session(),
        )


# ═══════════════════════════════════════════════════════════════════════════
# _escalate_to_rep
# ═══════════════════════════════════════════════════════════════════════════

class TestEscalateToRep:

    def _session(self):
        return {"id": SESSION_ID}

    def test_AI_U_32_pauses_session_and_clears_ai_owned(self):
        """AI-U-32: session ai_paused=True/agent_state='escalated', lead.ai_owned=False."""
        from app.services.ai_agent_service import _escalate_to_rep
        db = MagicMock()
        db.table.return_value = _chain([])

        with patch("app.services.ai_agent_service.auto_assign_lead", return_value=None), \
             patch("app.services.lead_service.write_timeline_event"):
            _escalate_to_rep(
                db, ORG_ID, number_row={}, session=self._session(),
                lead={"id": LEAD_ID}, reason="customer_asked_for_human",
                task_priority="normal",
            )

        session_updates = [c for c in db.table.call_args_list if c[0][0] == "whatsapp_sessions"]
        leads_updates = [c for c in db.table.call_args_list if c[0][0] == "leads"]
        assert len(session_updates) >= 1
        assert len(leads_updates) >= 1

    def test_AI_U_33_rep_assigned_creates_task_and_notification(self):
        """AI-U-33: successful reassignment → task + notification created for the rep."""
        from app.services.ai_agent_service import _escalate_to_rep
        db = MagicMock()
        db.table.return_value = _chain([])

        with patch("app.services.ai_agent_service.auto_assign_lead", return_value=REP_ID), \
             patch("app.services.lead_service.write_timeline_event"):
            _escalate_to_rep(
                db, ORG_ID, number_row={}, session=self._session(),
                lead={"id": LEAD_ID}, reason="complaint", task_priority="urgent",
            )

        task_inserts = [c for c in db.table.call_args_list if c[0][0] == "tasks"]
        notif_inserts = [c for c in db.table.call_args_list if c[0][0] == "notifications"]
        assert len(task_inserts) >= 1
        assert len(notif_inserts) >= 1

    def test_AI_U_34_no_lead_returns_early_after_pausing_session(self):
        """AI-U-34: no lead available → session still paused, no lead-level writes attempted."""
        from app.services.ai_agent_service import _escalate_to_rep
        db = MagicMock()
        db.table.return_value = _chain([])

        with patch("app.services.ai_agent_service.auto_assign_lead") as mock_assign:
            _escalate_to_rep(
                db, ORG_ID, number_row={}, session=self._session(),
                lead=None, reason="parse_error", task_priority="low",
            )
            mock_assign.assert_not_called()

        session_updates = [c for c in db.table.call_args_list if c[0][0] == "whatsapp_sessions"]
        assert len(session_updates) >= 1

    def test_AI_U_35_s14_never_raises_on_db_error(self):
        """AI-U-35: S14 — exception anywhere never raises."""
        from app.services.ai_agent_service import _escalate_to_rep
        db = MagicMock()
        db.table.side_effect = Exception("DB down")
        # Must not raise
        _escalate_to_rep(
            db, ORG_ID, number_row={}, session=self._session(),
            lead={"id": LEAD_ID}, reason="complaint", task_priority="normal",
        )


# ═══════════════════════════════════════════════════════════════════════════
# _handle_agent_confirmation
# ═══════════════════════════════════════════════════════════════════════════

class TestHandleAgentConfirmation:

    def _session_with_pending(self, action, data):
        return {
            "id": SESSION_ID,
            "session_data": {"pending_agent_confirmation": {"action": action, "data": data}},
        }

    def test_AI_U_36_cancel_sends_acknowledgement_and_clears_pending(self):
        """AI-U-36: agent_cancel (confirmed=False) → acknowledgement sent, pending cleared."""
        from app.services.ai_agent_service import _handle_agent_confirmation
        db = MagicMock()
        db.table.return_value = _chain([])
        session = self._session_with_pending("confirm_checkout", {})

        with patch("app.services.whatsapp_service.send_agent_text_message") as mock_send:
            _handle_agent_confirmation(
                db, ORG_ID, number_row={}, session=session,
                lead={"id": LEAD_ID}, confirmed=False,
            )
            mock_send.assert_called_once()

        session_updates = [c for c in db.table.call_args_list if c[0][0] == "whatsapp_sessions"]
        assert len(session_updates) >= 1

    def test_AI_U_37_confirm_add_to_cart_calls_add_to_cart(self):
        """AI-U-37: agent_confirm on confirm_add_to_cart → commerce_service.add_to_cart called."""
        from app.services.ai_agent_service import _handle_agent_confirmation
        db = MagicMock()

        def table_side(name):
            if name == "products":
                return _chain({"id": "prod-1", "title": "Queen Mattress"})
            return _chain([])

        db.table.side_effect = table_side
        session = self._session_with_pending(
            "confirm_add_to_cart", {"product_id": "prod-1", "variant_id": "var-1"}
        )

        with patch("app.services.commerce_service.get_or_create_commerce_session", return_value={"id": "cs-1"}), \
             patch("app.services.commerce_service.add_to_cart", return_value={"id": "cs-1"}) as mock_add, \
             patch("app.services.whatsapp_service.send_cart_summary"):
            _handle_agent_confirmation(
                db, ORG_ID, number_row={}, session=session,
                lead={"id": LEAD_ID}, confirmed=True,
            )
            mock_add.assert_called_once()

    def test_AI_U_38_confirm_checkout_calls_generate_checkout(self):
        """AI-U-38: agent_confirm on confirm_checkout → checkout link generated and sent."""
        from app.services.ai_agent_service import _handle_agent_confirmation
        db = MagicMock()
        db.table.return_value = _chain({"commerce_config": {}})
        session = self._session_with_pending("confirm_checkout", {})

        with patch("app.services.commerce_service.get_or_create_commerce_session", return_value={"id": "cs-1"}), \
             patch("app.services.commerce_service.generate_shopify_checkout", return_value="https://checkout.example/1") as mock_gen, \
             patch("app.services.whatsapp_service.send_checkout_link") as mock_send_link:
            _handle_agent_confirmation(
                db, ORG_ID, number_row={}, session=session,
                lead={"id": LEAD_ID}, confirmed=True,
            )
            mock_gen.assert_called_once()
            mock_send_link.assert_called_once()

    def test_AI_U_39_stale_tap_no_pending_action_logs_and_returns(self):
        """AI-U-39: button tap with no pending_agent_confirmation stored → no-op, never raises."""
        from app.services.ai_agent_service import _handle_agent_confirmation
        db = MagicMock()
        db.table.return_value = _chain([])
        session = {"id": SESSION_ID, "session_data": {}}
        # Must not raise
        _handle_agent_confirmation(
            db, ORG_ID, number_row={}, session=session,
            lead={"id": LEAD_ID}, confirmed=True,
        )

    def test_AI_U_40_s14_never_raises_on_db_error(self):
        """AI-U-40: S14 — exception anywhere never raises."""
        from app.services.ai_agent_service import _handle_agent_confirmation
        db = MagicMock()
        db.table.side_effect = Exception("DB down")
        session = self._session_with_pending("confirm_checkout", {})
        # Must not raise
        _handle_agent_confirmation(
            db, ORG_ID, number_row={}, session=session,
            lead={"id": LEAD_ID}, confirmed=True,
        )
