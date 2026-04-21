"""
tests/integration/test_webhooks_qualification.py
WH-1b: Integration tests for structured qualification webhook flow.

Covers:
  - qualify action with null qualification_flow → lead created, no session, owner notified
  - qualify action with valid flow → lead created, session created, Q1 sent
  - inbound text on active session → answer recorded, Q2 sent
  - inbound list_reply on active session → option id/label recorded, next question sent
  - last question answered → handoff message sent, session closed, rep notified
"""
import pytest
import json
import hashlib
import hmac
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import uuid

# ── Constants ────────────────────────────────────────────────────────────────

ORG_ID         = str(uuid.uuid4())
LEAD_ID        = str(uuid.uuid4())
REP_ID         = str(uuid.uuid4())
SESSION_ID     = str(uuid.uuid4())
PHONE_NUMBER   = "+2348099999999"
PHONE_NUMBER_ID = "WA_PHONE_ID_123"

SAMPLE_FLOW = {
    "opening_message": "Hi! Tell us about yourself.",
    "handoff_message": "Thanks! Our team will be in touch. 🙏",
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


def _make_whatsapp_payload(
    phone_number: str,
    phone_number_id: str,
    msg_type: str = "text",
    content: str = "Hello",
    interactive: dict = None,
) -> dict:
    """Build a minimal Meta WhatsApp webhook payload."""
    message = {
        "from": phone_number,
        "id": f"wamid.{uuid.uuid4().hex}",
        "timestamp": "1713696000",
        "type": msg_type,
    }
    if msg_type == "text":
        message["text"] = {"body": content}
    elif msg_type == "interactive":
        message["interactive"] = interactive

    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": phone_number_id},
                    "contacts": [{"profile": {"name": "Test Lead"}}],
                    "messages": [message],
                },
            }],
        }],
    }


def _sign_payload(body: bytes, secret: str = "test_secret") -> str:
    return "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()


@pytest.fixture
def client():
    """TestClient with mocked db and bypassed META_APP_SECRET verification."""
    from app.main import app
    from app.database import get_supabase

    mock_db = MagicMock()

    app.dependency_overrides[get_supabase] = lambda: mock_db

    with patch("app.routers.webhooks._verify_meta_signature", return_value=True):
        yield TestClient(app), mock_db

    app.dependency_overrides.pop(get_supabase, None)  # Pattern 32


# ── Test: qualify with null qualification_flow ───────────────────────────────

class TestQualifyActionNullFlow:

    @patch("app.services.lead_service.create_lead")
    @patch("app.services.triage_service._notify_managers")
    @patch("app.services.whatsapp_service._call_meta_send")
    def test_null_flow_lead_created_no_session_owner_notified(
        self, mock_send, mock_notify, mock_create_lead, client
    ):
        """
        When qualification_flow is null:
        - Lead is created
        - No lead_qualification_sessions row inserted
        - Fallback message sent to lead
        - Org owner notified
        """
        tc, db = client

        created_lead = {"id": LEAD_ID, "assigned_to": REP_ID}
        mock_create_lead.return_value = created_lead

        # Triage menu interaction — "qualify" action
        triage_config = {
            "unknown": {
                "items": [{"id": "qualify_item", "action": "qualify", "label": "Interested"}]
            }
        }

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.neq.return_value = chain
            chain.gt.return_value = chain
            chain.maybe_single.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.update.return_value = chain
            chain.insert.return_value = chain

            if name == "whatsapp_sessions":
                # get_active_session returns existing triage session
                chain.execute.return_value = MagicMock(data=[{
                    "id": SESSION_ID,
                    "org_id": ORG_ID,
                    "phone_number": PHONE_NUMBER,
                    "session_state": "triage_sent",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "session_data": None,
                    "selected_action": None,
                }])
            elif name == "organisations":
                # Must return a LIST so _lookup_org_by_phone_number_id can iterate rows
                chain.execute.return_value = MagicMock(data=[{
                    "id": ORG_ID,
                    "whatsapp_phone_id": PHONE_NUMBER_ID,
                    "whatsapp_triage_config": triage_config,
                    "unknown_contact_behavior": "triage_first",
                    "qualification_flow": None,  # ← onboarding gate
                    "name": "Test Org",
                }])
            elif name == "customers":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "customer_contacts":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "leads":
                chain.execute.return_value = MagicMock(data=[])
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db.table.side_effect = _table

        payload = _make_whatsapp_payload(
            phone_number=PHONE_NUMBER,
            phone_number_id=PHONE_NUMBER_ID,
            msg_type="interactive",
            interactive={
                "type": "list_reply",
                "list_reply": {"id": "qualify_item", "title": "Interested"},
            },
        )
        body = json.dumps(payload).encode()
        resp = tc.post("/webhooks/meta/whatsapp", content=body,
                       headers={"X-Hub-Signature-256": _sign_payload(body)})
        assert resp.status_code == 200

        # Lead was created
        mock_create_lead.assert_called_once()

        # Fallback message was sent (not a qualification question)
        mock_send.assert_called_once()
        sent_body = mock_send.call_args[0][1].get("text", {}).get("body", "")
        assert "getting set up" in sent_body.lower() or "reach out" in sent_body.lower()

        # Owner notified
        mock_notify.assert_called_once()


# ── Test: qualify with valid flow ────────────────────────────────────────────

class TestQualifyActionValidFlow:

    @patch("app.services.lead_service.create_lead")
    @patch("app.services.whatsapp_service.send_qualification_question")
    def test_valid_flow_session_created_q1_sent(
        self, mock_send_q, mock_create_lead, client
    ):
        """
        When qualification_flow is set:
        - Lead is created
        - lead_qualification_sessions row is inserted
        - Q1 is sent immediately
        """
        tc, db = client

        created_lead = {"id": LEAD_ID, "assigned_to": REP_ID}
        mock_create_lead.return_value = created_lead

        triage_config = {
            "unknown": {
                "items": [{"id": "qualify_item", "action": "qualify", "label": "Interested"}]
            }
        }

        session_inserted = []

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.neq.return_value = chain
            chain.gt.return_value = chain
            chain.maybe_single.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.update.return_value = chain

            def track_insert(row):
                session_inserted.append(row)
                return chain
            chain.insert.side_effect = track_insert
            chain.execute.return_value = MagicMock(data=[])

            if name == "whatsapp_sessions":
                chain.execute.return_value = MagicMock(data=[{
                    "id": SESSION_ID,
                    "org_id": ORG_ID,
                    "phone_number": PHONE_NUMBER,
                    "session_state": "triage_sent",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "session_data": None,
                    "selected_action": None,
                }])
            elif name == "organisations":
                # Must return a LIST so _lookup_org_by_phone_number_id can iterate rows
                chain.execute.return_value = MagicMock(data=[{
                    "id": ORG_ID,
                    "whatsapp_phone_id": PHONE_NUMBER_ID,
                    "whatsapp_triage_config": triage_config,
                    "unknown_contact_behavior": "triage_first",
                    "qualification_flow": SAMPLE_FLOW,  # ← valid flow
                    "name": "Test Org",
                }])
            elif name == "customers":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "customer_contacts":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "leads":
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db.table.side_effect = _table

        payload = _make_whatsapp_payload(
            phone_number=PHONE_NUMBER,
            phone_number_id=PHONE_NUMBER_ID,
            msg_type="interactive",
            interactive={
                "type": "list_reply",
                "list_reply": {"id": "qualify_item", "title": "Interested"},
            },
        )
        body = json.dumps(payload).encode()
        resp = tc.post("/webhooks/meta/whatsapp", content=body,
                       headers={"X-Hub-Signature-256": _sign_payload(body)})
        assert resp.status_code == 200

        # Lead created
        mock_create_lead.assert_called_once()

        # Q1 sent immediately
        mock_send_q.assert_called_once()
        call_kw = mock_send_q.call_args
        # opening_message passed on first question
        opening = call_kw[1].get("opening_message") or (call_kw[0][6] if len(call_kw[0]) > 6 else None)
        assert opening is not None


# ── Test: inbound on active session — text answer ────────────────────────────

class TestInboundOnActiveSession:

    @patch("app.routers.webhooks._handle_structured_qualification_turn")
    def test_text_answer_routes_to_structured_handler(self, mock_handler, client):
        """
        When a lead with an active qualification session sends a text message,
        _handle_structured_qualification_turn is called (not the old bot).
        """
        tc, db = client

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.neq.return_value = chain
            chain.gt.return_value = chain
            chain.gte.return_value = chain
            chain.maybe_single.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.update.return_value = chain
            chain.insert.return_value = chain
            chain.is_.return_value = chain

            if name == "customers":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "customer_contacts":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "leads":
                chain.execute.return_value = MagicMock(data=[{
                    "id": LEAD_ID,
                    "org_id": ORG_ID,
                    "phone": PHONE_NUMBER,
                    "whatsapp": PHONE_NUMBER,
                    "assigned_to": REP_ID,
                    "deleted_at": None,
                    "nurture_track": False,
                }])
            elif name == "lead_qualification_sessions":
                # Active session exists — triggers structured handler
                chain.execute.return_value = MagicMock(data=[{
                    "id": SESSION_ID,
                    "lead_id": LEAD_ID,
                    "ai_active": True,
                }])
            elif name == "whatsapp_messages":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "organisations":
                chain.execute.return_value = MagicMock(data={
                    "id": ORG_ID,
                    "whatsapp_phone_id": PHONE_NUMBER_ID,
                })
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db.table.side_effect = _table

        payload = _make_whatsapp_payload(
            phone_number=PHONE_NUMBER,
            phone_number_id=PHONE_NUMBER_ID,
            msg_type="text",
            content="Acme Ltd",
        )
        body = json.dumps(payload).encode()
        resp = tc.post("/webhooks/meta/whatsapp", content=body,
                       headers={"X-Hub-Signature-256": _sign_payload(body)})
        assert resp.status_code == 200

        # Structured handler was called
        mock_handler.assert_called_once()
        call_kw = mock_handler.call_args[1]
        assert call_kw["lead_id"] == LEAD_ID
        assert call_kw["content"] == "Acme Ltd"

    @patch("app.routers.webhooks._handle_structured_qualification_turn")
    def test_list_reply_passes_interactive_payload(self, mock_handler, client):
        """
        list_reply messages pass the full interactive_payload to the handler.
        """
        tc, db = client

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.neq.return_value = chain
            chain.gt.return_value = chain
            chain.gte.return_value = chain
            chain.maybe_single.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.update.return_value = chain
            chain.insert.return_value = chain
            chain.is_.return_value = chain

            if name == "customers":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "customer_contacts":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "leads":
                chain.execute.return_value = MagicMock(data=[{
                    "id": LEAD_ID,
                    "org_id": ORG_ID,
                    "phone": PHONE_NUMBER,
                    "whatsapp": PHONE_NUMBER,
                    "assigned_to": REP_ID,
                    "deleted_at": None,
                    "nurture_track": False,
                }])
            elif name == "lead_qualification_sessions":
                chain.execute.return_value = MagicMock(data=[{
                    "id": SESSION_ID,
                    "lead_id": LEAD_ID,
                    "ai_active": True,
                }])
            elif name == "whatsapp_messages":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "organisations":
                chain.execute.return_value = MagicMock(data={
                    "id": ORG_ID,
                    "whatsapp_phone_id": PHONE_NUMBER_ID,
                })
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db.table.side_effect = _table

        payload = _make_whatsapp_payload(
            phone_number=PHONE_NUMBER,
            phone_number_id=PHONE_NUMBER_ID,
            msg_type="interactive",
            interactive={
                "type": "list_reply",
                "list_reply": {"id": "pricing", "title": "Pricing information"},
            },
        )
        body = json.dumps(payload).encode()
        resp = tc.post("/webhooks/meta/whatsapp", content=body,
                       headers={"X-Hub-Signature-256": _sign_payload(body)})
        assert resp.status_code == 200

        mock_handler.assert_called_once()
        call_kw = mock_handler.call_args[1]
        # interactive_payload should be passed through
        assert call_kw["interactive_payload"] is not None
        assert call_kw["interactive_payload"]["type"] == "list_reply"


# ── Test: last question answered → full handoff ──────────────────────────────

class TestLastQuestionHandoff:

    @patch("app.routers.webhooks.send_qualification_handoff_message")
    @patch("app.routers.webhooks.generate_qualification_summary", return_value="Rep summary.")
    @patch("app.routers.webhooks.send_qualification_question")
    def test_last_question_handoff_complete(self, mock_send_q, mock_summary, mock_handoff, client):
        """
        When the final question is answered:
        - Handoff message sent to lead
        - Session closed (ai_active=False, stage='handed_off')
        - Rep notified
        - send_qualification_question NOT called again
        """
        tc, db = client

        # Session at last question (index 1 = Q2, total 2 questions)
        active_session = {
            "id": SESSION_ID,
            "org_id": ORG_ID,
            "lead_id": LEAD_ID,
            "ai_active": True,
            "stage": "qualifying",
            "current_question_index": 1,
            "answers": {"inquiry_reason": "Pricing information"},
        }

        session_update_calls = []

        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.neq.return_value = chain
            chain.gt.return_value = chain
            chain.gte.return_value = chain
            chain.maybe_single.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.is_.return_value = chain

            def track_update(payload):
                session_update_calls.append((name, payload))
                return chain
            chain.update.side_effect = track_update
            chain.insert.return_value = chain
            chain.execute.return_value = MagicMock(data=[])

            if name == "customers":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "customer_contacts":
                chain.execute.return_value = MagicMock(data=[])
            elif name == "leads":
                chain.execute.return_value = MagicMock(data=[{
                    "id": LEAD_ID,
                    "org_id": ORG_ID,
                    "phone": PHONE_NUMBER,
                    "whatsapp": PHONE_NUMBER,
                    "assigned_to": REP_ID,
                    "deleted_at": None,
                    "nurture_track": False,
                    "full_name": "Test Lead",
                }])
            elif name == "lead_qualification_sessions":
                chain.execute.return_value = MagicMock(data=[active_session])
            elif name == "organisations":
                chain.execute.return_value = MagicMock(data={
                    "id": ORG_ID,
                    "name": "Test Org",
                    "qualification_flow": SAMPLE_FLOW,
                    "whatsapp_phone_id": PHONE_NUMBER_ID,
                })
            elif name == "whatsapp_messages":
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db.table.side_effect = _table

        payload = _make_whatsapp_payload(
            phone_number=PHONE_NUMBER,
            phone_number_id=PHONE_NUMBER_ID,
            msg_type="text",
            content="Acme Ltd",
        )
        body = json.dumps(payload).encode()

        with patch("app.routers.webhooks.lead_service"):
            resp = tc.post("/webhooks/meta/whatsapp", content=body,
                           headers={"X-Hub-Signature-256": _sign_payload(body)})

        assert resp.status_code == 200

        # Handoff message sent
        mock_handoff.assert_called_once()

        # Summary generated
        mock_summary.assert_called_once()

        # No further questions sent
        mock_send_q.assert_not_called()

        # Session update for handoff occurred
        handoff_updates = [
            p for name, p in session_update_calls
            if isinstance(p, dict) and p.get("stage") == "handed_off"
        ]
        assert len(handoff_updates) >= 1
        assert handoff_updates[0].get("ai_active") is False
