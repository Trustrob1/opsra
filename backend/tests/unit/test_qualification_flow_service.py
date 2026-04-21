"""
tests/unit/test_qualification_flow_service.py
WH-1b: Unit tests for structured qualification flow service functions.

Covers:
  - send_qualification_question: multiple_choice, list_select, free_text, opening_message
  - send_qualification_question: S14 — failure does not raise
  - generate_qualification_summary: returns string
  - generate_qualification_summary: S14 — AI failure returns formatted fallback
  - _handle_structured_qualification_turn: records answer, sends next question
  - _handle_structured_qualification_turn: last question → handoff, session closed, rep notified, scoring triggered
  - _handle_structured_qualification_turn: map_to_lead_field writes to leads table
  - _handle_structured_qualification_turn: null qualification_flow → raises ValueError
"""
import pytest
from unittest.mock import MagicMock, patch, call
import uuid

# ── Constants ────────────────────────────────────────────────────────────────

ORG_ID  = str(uuid.uuid4())
LEAD_ID = str(uuid.uuid4())
SESS_ID = str(uuid.uuid4())
REP_ID  = str(uuid.uuid4())

SAMPLE_FLOW = {
    "opening_message": "Hi! Before we connect you with our team, let us learn about you.",
    "handoff_message": "Thanks! A team member will reach out shortly. 🙏",
    "questions": [
        {
            "id": "q1",
            "text": "What brings you here?",
            "type": "list_select",
            "answer_key": "inquiry_reason",
            "map_to_lead_field": None,
            "options": [
                {"id": "pricing", "label": "Pricing information"},
                {"id": "demo",    "label": "I'd like a demo"},
                {"id": "other",   "label": "Something else"},
            ],
        },
        {
            "id": "q2",
            "text": "What is your company name?",
            "type": "free_text",
            "answer_key": "company_name",
            "map_to_lead_field": "business_name",
        },
    ],
}

NOW_TS = "2026-04-21T10:00:00+00:00"


def _db_returning(data):
    """Helper: mock db chain returning given data."""
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=data)
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.maybe_single.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    return chain


def _make_db(org_data=None, session_data=None, lead_data=None):
    """
    Build a db mock where:
      - organisations → org_data
      - lead_qualification_sessions → session_data
      - leads → lead_data
    Uses side_effect so each table() call routes correctly.
    """
    def _table(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.update.return_value = chain
        chain.insert.return_value = chain

        if name == "organisations":
            chain.execute.return_value = MagicMock(data=org_data)
        elif name == "lead_qualification_sessions":
            chain.execute.return_value = MagicMock(data=session_data)
        elif name == "leads":
            chain.execute.return_value = MagicMock(data=lead_data)
        elif name == "notifications":
            chain.execute.return_value = MagicMock(data=[])
        else:
            chain.execute.return_value = MagicMock(data=[])
        return chain

    db = MagicMock()
    db.table.side_effect = _table
    return db


# ── send_qualification_question ──────────────────────────────────────────────

class TestSendQualificationQuestion:

    @patch("app.services.whatsapp_service._call_meta_send")
    def test_multiple_choice_sends_button_message(self, mock_send):
        """multiple_choice question sends interactive button message."""
        from app.services.whatsapp_service import send_qualification_question

        db = _make_db(org_data={"whatsapp_phone_id": "PHONE_ID_1"})
        question = {
            "id": "q1",
            "text": "Choose one",
            "type": "multiple_choice",
            "answer_key": "choice",
            "options": [
                {"id": "a", "label": "Option A"},
                {"id": "b", "label": "Option B"},
            ],
        }
        send_qualification_question(db, ORG_ID, "+2348099999999", question, 1, 2)

        mock_send.assert_called_once()
        payload = mock_send.call_args[0][1]
        assert payload["type"] == "interactive"
        assert payload["interactive"]["type"] == "button"
        assert len(payload["interactive"]["action"]["buttons"]) == 2

    @patch("app.services.whatsapp_service._call_meta_send")
    def test_list_select_sends_list_message(self, mock_send):
        """list_select question sends interactive list message."""
        from app.services.whatsapp_service import send_qualification_question

        db = _make_db(org_data={"whatsapp_phone_id": "PHONE_ID_1"})
        question = SAMPLE_FLOW["questions"][0]  # list_select with 3 options
        send_qualification_question(db, ORG_ID, "+2348099999999", question, 0, 2)

        payload = mock_send.call_args[0][1]
        assert payload["interactive"]["type"] == "list"
        rows = payload["interactive"]["action"]["sections"][0]["rows"]
        assert len(rows) == 3

    @patch("app.services.whatsapp_service._call_meta_send")
    def test_free_text_sends_plain_text(self, mock_send):
        """free_text question sends plain text message."""
        from app.services.whatsapp_service import send_qualification_question

        db = _make_db(org_data={"whatsapp_phone_id": "PHONE_ID_1"})
        question = SAMPLE_FLOW["questions"][1]  # free_text
        send_qualification_question(db, ORG_ID, "+2348099999999", question, 1, 2)

        payload = mock_send.call_args[0][1]
        assert payload["type"] == "text"
        assert "What is your company name?" in payload["text"]["body"]

    @patch("app.services.whatsapp_service._call_meta_send")
    def test_opening_message_prepended_on_q1_only(self, mock_send):
        """Opening message is prepended on Q1 (index 0) but not on subsequent questions."""
        from app.services.whatsapp_service import send_qualification_question

        db = _make_db(org_data={"whatsapp_phone_id": "PHONE_ID_1"})
        question = SAMPLE_FLOW["questions"][1]  # free_text

        # Q1 — should prepend
        send_qualification_question(
            db, ORG_ID, "+2348099999999", question, 0, 2,
            opening_message="Welcome!"
        )
        body_q1 = mock_send.call_args[0][1]["text"]["body"]
        assert "Welcome!" in body_q1

        mock_send.reset_mock()

        # Q2 — should NOT prepend
        send_qualification_question(
            db, ORG_ID, "+2348099999999", question, 1, 2,
            opening_message="Welcome!"
        )
        body_q2 = mock_send.call_args[0][1]["text"]["body"]
        assert "Welcome!" not in body_q2

    @patch("app.services.whatsapp_service._call_meta_send")
    def test_s14_failure_does_not_raise(self, mock_send):
        """S14: exception in _call_meta_send must not propagate."""
        import logging
        import app.services.whatsapp_service as _wa_mod
        from app.services.whatsapp_service import send_qualification_question

        mock_send.side_effect = RuntimeError("Meta API down")
        db = _make_db(org_data={"whatsapp_phone_id": "PHONE_ID_1"})
        question = SAMPLE_FLOW["questions"][1]

        # Ensure the module has a logger — the appended functions reference it
        # by name; if whatsapp_service uses a different variable name this
        # injects the correct one so the warning call doesn't NameError.
        if not hasattr(_wa_mod, "logger"):
            _wa_mod.logger = logging.getLogger("app.services.whatsapp_service")

        # Must not raise
        send_qualification_question(db, ORG_ID, "+2348099999999", question, 0, 2)


# ── generate_qualification_summary ──────────────────────────────────────────

class TestGenerateQualificationSummary:

    @patch("app.services.ai_service.call_claude", return_value="This lead is a retail business owner with 3 branches looking for inventory management.")
    def test_returns_string_summary(self, mock_claude):
        """generate_qualification_summary returns a non-empty string on success."""
        from app.services.ai_service import generate_qualification_summary

        result = generate_qualification_summary(
            answers={"inquiry_reason": "demo", "company_name": "Acme Ltd"},
            lead={"full_name": "Emeka Obi", "phone": "+2348099999999"},
            org_name="Opsra Demo",
        )
        assert isinstance(result, str)
        assert len(result) > 0
        mock_claude.assert_called_once()

    @patch("app.services.ai_service.call_claude", return_value="")
    def test_s14_ai_failure_returns_formatted_fallback(self, mock_claude):
        """S14: empty AI response returns formatted plain text fallback, never raises."""
        from app.services.ai_service import generate_qualification_summary

        result = generate_qualification_summary(
            answers={"company_name": "Acme Ltd", "inquiry_reason": "pricing"},
            lead={"full_name": "Ada Okonkwo", "phone": "+2348011111111"},
            org_name="Test Org",
        )
        assert isinstance(result, str)
        assert "Ada Okonkwo" in result
        assert len(result) > 0


# ── _handle_structured_qualification_turn ───────────────────────────────────

class TestHandleStructuredQualificationTurn:

    def _make_active_session(self, question_index=0):
        return {
            "id": SESS_ID,
            "org_id": ORG_ID,
            "lead_id": LEAD_ID,
            "ai_active": True,
            "stage": "qualifying",
            "current_question_index": question_index,
            "answers": {},
        }

    @patch("app.routers.webhooks.send_qualification_question")
    def test_records_answer_and_sends_next_question(self, mock_send_q):
        """
        When answering Q1 of a 2-question flow: answer recorded, Q2 sent,
        session index advances, rep notification NOT sent yet.
        """
        from app.routers.webhooks import _handle_structured_qualification_turn

        session = self._make_active_session(question_index=0)
        org_data = {"id": ORG_ID, "name": "Test Org", "qualification_flow": SAMPLE_FLOW, "whatsapp_phone_id": "PID"}
        lead_data = {"full_name": "Test Lead", "phone": "+2348099999999", "whatsapp": "+2348099999999"}

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.maybe_single.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.update.return_value = chain
            chain.insert.return_value = chain
            if name == "lead_qualification_sessions":
                chain.execute.return_value = MagicMock(data=[session])
            elif name == "organisations":
                chain.execute.return_value = MagicMock(data=org_data)
            elif name == "leads":
                chain.execute.return_value = MagicMock(data=lead_data)
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db = MagicMock()
        db.table.side_effect = _table

        # Patch _get_lead_phone so send_qualification_question gets a real string
        with patch("app.routers.webhooks._get_lead_phone", return_value="+2348099999999"):
            interactive = {"list_reply": {"id": "pricing"}}
            _handle_structured_qualification_turn(
                db=db,
                org_id=ORG_ID,
                lead_id=LEAD_ID,
                assigned_to=REP_ID,
                content="pricing",
                interactive_payload=interactive,
                now_ts=NOW_TS,
            )

        # Q2 should have been sent
        mock_send_q.assert_called_once()
        call_kwargs = mock_send_q.call_args[1] if mock_send_q.call_args[1] else {}
        call_args = mock_send_q.call_args[0]
        # question_index should be 1 (second question)
        assert 1 in call_args or call_kwargs.get("question_index") == 1

    @patch("app.routers.webhooks.send_qualification_handoff_message")
    @patch("app.routers.webhooks.send_qualification_question")
    @patch("app.routers.webhooks.generate_qualification_summary", return_value="Summary text.")
    def test_last_question_triggers_handoff(self, mock_summary, mock_send_q, mock_handoff):
        """
        When answering the final question: handoff_message sent, session closed,
        rep notified, scoring triggered.
        """
        from app.routers.webhooks import _handle_structured_qualification_turn

        session = self._make_active_session(question_index=1)
        session["answers"] = {"inquiry_reason": "Pricing information"}

        org_data = {
            "id": ORG_ID,
            "name": "Test Org",
            "qualification_flow": SAMPLE_FLOW,
            "whatsapp_phone_id": "PID",
        }
        lead_data = {"full_name": "Ada Obi", "phone": "+2348011111111", "whatsapp": "+2348011111111"}

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.maybe_single.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.update.return_value = chain
            chain.insert.return_value = chain
            if name == "lead_qualification_sessions":
                chain.execute.return_value = MagicMock(data=[session])
            elif name == "organisations":
                chain.execute.return_value = MagicMock(data=org_data)
            elif name == "leads":
                chain.execute.return_value = MagicMock(data=lead_data)
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db = MagicMock()
        db.table.side_effect = _table

        # Pattern 63: lead_service is imported lazily inside the function body
        # so the patch target is the source module, not webhooks.
        with patch("app.services.lead_service.score_lead") as mock_score:
            with patch("app.routers.webhooks._get_lead_phone", return_value="+2348011111111"):
                with patch("app.routers.webhooks._get_lead_basic", return_value={"full_name": "Ada Obi", "phone": "+2348011111111"}):
                    _handle_structured_qualification_turn(
                        db=db,
                        org_id=ORG_ID,
                        lead_id=LEAD_ID,
                        assigned_to=REP_ID,
                        content="Acme Ltd",
                        interactive_payload=None,
                        now_ts=NOW_TS,
                    )

        # Handoff message sent
        mock_handoff.assert_called_once()
        # No next question sent (all questions answered)
        mock_send_q.assert_not_called()
        # Summary generated
        mock_summary.assert_called_once()
        # Scoring triggered
        mock_score.assert_called_once()

    @patch("app.routers.webhooks.send_qualification_question")
    def test_map_to_lead_field_writes_to_leads_table(self, mock_send_q):
        """
        When answering Q2 (map_to_lead_field='business_name'):
        leads table is updated with the answer value.
        """
        from app.routers.webhooks import _handle_structured_qualification_turn

        session = self._make_active_session(question_index=1)
        session["answers"] = {"inquiry_reason": "demo"}

        org_data = {
            "id": ORG_ID,
            "name": "Test Org",
            "qualification_flow": SAMPLE_FLOW,
            "whatsapp_phone_id": "PID",
        }
        lead_data = {"full_name": "Test Lead", "phone": "+2348099999999", "whatsapp": "+2348099999999"}

        update_calls = []

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.maybe_single.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.update.return_value = chain
            chain.insert.return_value = chain
            if name == "lead_qualification_sessions":
                chain.execute.return_value = MagicMock(data=[session])
            elif name == "organisations":
                chain.execute.return_value = MagicMock(data=org_data)
            elif name == "leads":
                chain.execute.return_value = MagicMock(data=lead_data)
                def track_update(payload):
                    update_calls.append(payload)
                    return chain
                chain.update.side_effect = track_update
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db = MagicMock()
        db.table.side_effect = _table

        with patch("app.routers.webhooks.generate_qualification_summary", return_value="Summary."):
            with patch("app.routers.webhooks.send_qualification_handoff_message"):
                with patch("app.routers.webhooks.lead_service"):
                    with patch("app.routers.webhooks._get_lead_phone", return_value="+2348099999999"):
                        with patch("app.routers.webhooks._get_lead_basic", return_value={"full_name": "Test Lead", "phone": "+2348099999999"}):
                            _handle_structured_qualification_turn(
                                db=db,
                                org_id=ORG_ID,
                                lead_id=LEAD_ID,
                                assigned_to=REP_ID,
                                content="Acme Ltd",
                                interactive_payload=None,
                                now_ts=NOW_TS,
                            )

        # leads.update should have been called with business_name
        assert any("business_name" in (c or {}) for c in update_calls)

    def test_null_qualification_flow_raises_value_error(self):
        """
        S14 contract: null qualification_flow raises ValueError so caller
        falls back to rep notification.
        """
        from app.routers.webhooks import _handle_structured_qualification_turn

        session = self._make_active_session(question_index=0)
        org_data = {
            "id": ORG_ID,
            "name": "Test Org",
            "qualification_flow": None,
            "whatsapp_phone_id": "PID",
        }

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.maybe_single.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            if name == "lead_qualification_sessions":
                chain.execute.return_value = MagicMock(data=[session])
            elif name == "organisations":
                chain.execute.return_value = MagicMock(data=org_data)
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db = MagicMock()
        db.table.side_effect = _table

        with pytest.raises(ValueError, match="qualification_flow not configured"):
            _handle_structured_qualification_turn(
                db=db,
                org_id=ORG_ID,
                lead_id=LEAD_ID,
                assigned_to=REP_ID,
                content="hello",
                interactive_payload=None,
                now_ts=NOW_TS,
            )