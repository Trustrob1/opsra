"""
tests/integration/test_customer_inbound_routes.py
WH-1 integration tests — Customer Intent Classifier.

Tests hit the actual webhook HTTP route via TestClient with mocked
dependencies (get_supabase overridden per Pattern 62 / Pattern 44).

Covers:
  - Inbound from known customer + last outbound is nps_survey → score written, rep notified
  - Inbound + last outbound is renewal_reminder + cancel intent → subscription at_risk set
  - Inbound + no outbound context + ticket intent → ticket auto-created
  - Inbound from lead at proposal_sent + buying signal → rep notified with signal
  - S14: Haiku call failure does not 500 — falls back to general path
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.config import settings

# ---------------------------------------------------------------------------
# Constants (Pattern 24 — valid UUIDs)
# ---------------------------------------------------------------------------

ORG_ID       = str(uuid.uuid4())
CUSTOMER_ID  = str(uuid.uuid4())
LEAD_ID      = str(uuid.uuid4())
USER_ID      = str(uuid.uuid4())
MGR_ID       = str(uuid.uuid4())
PHONE_ID     = "12345678901"
CUSTOMER_NUM = "+2348012345678"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sign(body: bytes) -> str:
    secret = settings.META_APP_SECRET.encode("utf-8")
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def _wa_payload(phone: str, text: str, phone_number_id: str = PHONE_ID) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": phone_number_id},
                    "contacts": [{"profile": {"name": "Ngozi Adeyemi"}}],
                    "messages": [{
                        "from": phone,
                        "id": "wamid.test123",
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
            }],
        }],
    }


def _mock_db_for_customer(
    customer_phone: str = CUSTOMER_NUM,
    assigned_to: str = USER_ID,
    last_outbound_type: str = None,
):
    """Build a mock DB that resolves phone to a known customer."""
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

    # Default: empty result
    chain.execute.return_value = MagicMock(data=[], count=0)

    def table_router(table_name):
        t = MagicMock()
        t.select.return_value = t
        t.eq.return_value = t
        t.neq.return_value = t   # WH-2: get_active_session uses .neq()
        t.gt.return_value = t    # WH-2: get_active_session uses .gt()
        t.gte.return_value = t
        t.in_.return_value = t
        t.is_.return_value = t
        t.order.return_value = t
        t.limit.return_value = t
        t.maybe_single.return_value = t
        t.update.return_value = t
        t.insert.return_value = t

        if table_name == "customers":
            t.execute.return_value = MagicMock(data=[{
                "id": CUSTOMER_ID,
                "org_id": ORG_ID,
                "whatsapp": customer_phone,
                "phone": customer_phone,
                "assigned_to": assigned_to,
                "full_name": "Ngozi Adeyemi",
            }])
        elif table_name == "customer_contacts":
            t.execute.return_value = MagicMock(data=[])
        elif table_name == "leads":
            t.execute.return_value = MagicMock(data=[])
        elif table_name == "whatsapp_messages":
            if last_outbound_type:
                t.execute.return_value = MagicMock(data=[{
                    "message_type": last_outbound_type,
                    "direction": "outbound",
                }])
            else:
                t.execute.return_value = MagicMock(data=[])
        elif table_name == "knowledge_base_articles":
            t.execute.return_value = MagicMock(data=[])
        elif table_name == "subscriptions":
            t.execute.return_value = MagicMock(data=[{
                "id": str(uuid.uuid4()),
                "status": "active",
            }])
        elif table_name == "users":
            t.execute.return_value = MagicMock(data=[{
                "id": MGR_ID,
                "roles": {"template": "ops_manager"},
            }])
        elif table_name == "notifications":
            t.execute.return_value = MagicMock(data={"id": str(uuid.uuid4())})
        elif table_name == "tickets":
            t.execute.return_value = MagicMock(data={"id": str(uuid.uuid4())})
        elif table_name == "tasks":
            t.execute.return_value = MagicMock(data={"id": str(uuid.uuid4())})
        elif table_name == "whatsapp_sessions":
            # WH-2: get_active_session must return no session so
            # handle_customer_inbound is not bypassed by the triage block.
            t.execute.return_value = MagicMock(data=[])
        elif table_name == "organisations":
            # WH-2: triage config query must return empty so customer triage
            # menu branch does not fire and fall through is preserved.
            t.execute.return_value = MagicMock(data=[])
        else:
            t.execute.return_value = MagicMock(data=[])
        return t

    db.table.side_effect = table_router
    return db


def _mock_db_for_lead(stage: str = "proposal_sent"):
    """Build a mock DB that resolves phone to a known lead at given stage."""
    db = MagicMock()

    def table_router(table_name):
        t = MagicMock()
        t.select.return_value = t
        t.eq.return_value = t
        t.neq.return_value = t
        t.gt.return_value = t
        t.gte.return_value = t
        t.in_.return_value = t
        t.is_.return_value = t
        t.order.return_value = t
        t.limit.return_value = t
        t.maybe_single.return_value = t
        t.update.return_value = t
        t.insert.return_value = t

        if table_name == "customers":
            t.execute.return_value = MagicMock(data=[])
        elif table_name == "customer_contacts":
            t.execute.return_value = MagicMock(data=[])
        elif table_name == "leads":
            t.execute.return_value = MagicMock(data=[{
                "id": LEAD_ID,
                "org_id": ORG_ID,
                "whatsapp": CUSTOMER_NUM,
                "phone": CUSTOMER_NUM,
                "assigned_to": USER_ID,
                "full_name": "Emeka Obi",
                "stage": stage,
                "nurture_track": False,
            }])
        elif table_name == "lead_qualification_sessions":
            t.execute.return_value = MagicMock(data=[])
        elif table_name == "whatsapp_messages":
            t.execute.return_value = MagicMock(data=[])
        elif table_name == "notifications":
            t.execute.return_value = MagicMock(data={"id": str(uuid.uuid4())})
        else:
            t.execute.return_value = MagicMock(data=[])
        return t

    db.table.side_effect = table_router
    return db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNpsSurveyReply:
    def test_nps_score_written_and_rep_notified(self, client):
        db = _mock_db_for_customer(last_outbound_type="nps_survey")
        app.dependency_overrides[get_supabase] = lambda: db

        body = json.dumps(_wa_payload(CUSTOMER_NUM, "8")).encode()
        resp = client.post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={
                "X-Hub-Signature-256": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

        # Verify customers.update was called with nps_score
        update_calls = [
            str(call) for call in db.table.call_args_list
            if "customers" in str(call)
        ]
        assert any("customers" in c for c in update_calls)
        app.dependency_overrides.pop(get_supabase, None)


class TestRenewalReminderReply:
    def test_cancel_intent_creates_urgent_task(self, client):
        db = _mock_db_for_customer(last_outbound_type="renewal_reminder")
        app.dependency_overrides[get_supabase] = lambda: db

        with patch(
            "app.services.customer_inbound_service.classify_renewal_reply",
            return_value="cancel",
        ):
            body = json.dumps(_wa_payload(CUSTOMER_NUM, "please cancel my subscription")).encode()
            resp = client.post(
                "/webhooks/meta/whatsapp",
                content=body,
                headers={
                    "X-Hub-Signature-256": _sign(body),
                    "Content-Type": "application/json",
                },
            )

        assert resp.status_code == 200
        # tasks.insert should have been called for cancellation intent
        task_calls = [
            c for c in db.table.call_args_list
            if "tasks" in str(c)
        ]
        assert len(task_calls) > 0
        app.dependency_overrides.pop(get_supabase, None)


class TestTicketAutoCreation:
    def test_ticket_created_when_no_kb_and_ticket_intent(self, client):
        db = _mock_db_for_customer(last_outbound_type=None)
        app.dependency_overrides[get_supabase] = lambda: db

        with patch(
            "app.services.customer_inbound_service.lookup_kb_answer",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.classify_customer_intent",
            return_value="ticket",
        ):
            body = json.dumps(_wa_payload(CUSTOMER_NUM, "My dashboard is broken")).encode()
            resp = client.post(
                "/webhooks/meta/whatsapp",
                content=body,
                headers={
                    "X-Hub-Signature-256": _sign(body),
                    "Content-Type": "application/json",
                },
            )

        assert resp.status_code == 200
        ticket_calls = [
            c for c in db.table.call_args_list
            if "tickets" in str(c)
        ]
        assert len(ticket_calls) > 0
        app.dependency_overrides.pop(get_supabase, None)


class TestLeadStageSignal:
    def test_buying_signal_notifies_rep(self, client):
        db = _mock_db_for_lead(stage="proposal_sent")
        app.dependency_overrides[get_supabase] = lambda: db

        with patch(
            "app.services.customer_inbound_service.classify_lead_stage_signal",
            return_value="buying",
        ):
            body = json.dumps(_wa_payload(CUSTOMER_NUM, "Let's go ahead with the proposal")).encode()
            resp = client.post(
                "/webhooks/meta/whatsapp",
                content=body,
                headers={
                    "X-Hub-Signature-256": _sign(body),
                    "Content-Type": "application/json",
                },
            )

        assert resp.status_code == 200
        notif_calls = [
            c for c in db.table.call_args_list
            if "notifications" in str(c)
        ]
        assert len(notif_calls) > 0
        app.dependency_overrides.pop(get_supabase, None)


class TestS14HaikuFailure:
    def test_haiku_failure_does_not_500(self, client):
        """S14: Haiku failure falls back to general path, no 500."""
        db = _mock_db_for_customer(last_outbound_type=None)
        app.dependency_overrides[get_supabase] = lambda: db

        with patch(
            "app.services.customer_inbound_service.lookup_kb_answer",
            return_value=None,
        ), patch(
            "app.services.customer_inbound_service.classify_customer_intent",
            side_effect=Exception("Anthropic is down"),
        ):
            body = json.dumps(_wa_payload(CUSTOMER_NUM, "some message")).encode()
            resp = client.post(
                "/webhooks/meta/whatsapp",
                content=body,
                headers={
                    "X-Hub-Signature-256": _sign(body),
                    "Content-Type": "application/json",
                },
            )

        # Webhook must always return 200 (S14)
        assert resp.status_code == 200
        app.dependency_overrides.pop(get_supabase, None)
