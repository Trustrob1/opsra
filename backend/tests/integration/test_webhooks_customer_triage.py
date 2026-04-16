"""
tests/integration/test_webhooks_customer_triage.py
---------------------------------------------------
WH-2: Integration tests for the known-customer triage routing added to
_handle_inbound_message in webhooks.py.

Scenarios:
  1. Known customer + active triage session → handle_session_message called w/ section="customer"
  2. Known customer + no session + customer menu configured → menu sent, session created, return
  3. Known customer + no session + no customer menu items → falls through to handle_customer_inbound
  4. Known customer + no session + empty customer config → falls through to handle_customer_inbound
  5. Customer triage menu check exception → logs warning, falls through to handle_customer_inbound
"""
import pytest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# UUIDs and fixtures
# ---------------------------------------------------------------------------

ORG_ID    = "00000000-0000-0000-0000-000000000001"
CUST_ID   = "00000000-0000-0000-0000-000000000002"
USER_ID   = "00000000-0000-0000-0000-000000000003"
SESS_ID   = "00000000-0000-0000-0000-000000000004"
PHONE     = "+2348012345678"
PHONE_ID  = "111222333"

META_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "changes": [{
            "value": {
                "metadata": {"phone_number_id": PHONE_ID},
                "contacts": [{"profile": {"name": "Test Customer"}, "wa_id": PHONE.lstrip("+")}],
                "messages": [{
                    "from": PHONE,
                    "id": "wamid.test",
                    "type": "text",
                    "text": {"body": "Hi there"},
                    "timestamp": "1700000000",
                }],
            }
        }]
    }],
}

CUSTOMER_TRIAGE_CONFIG = {
    "unknown": {"greeting": "Hi!", "section_title": "Choose", "items": []},
    "customer": {
        "greeting": "Welcome back!",
        "section_title": "How can we help?",
        "items": [
            {"id": "support", "label": "Support", "action": "create_ticket", "contact_type": "support_contact"},
        ],
    },
}

EMPTY_CUSTOMER_CONFIG = {
    "unknown": {"greeting": "Hi!", "section_title": "Choose", "items": []},
    "customer": {"greeting": "Hi!", "section_title": "Choose", "items": []},
}


def _chain(**kwargs):
    execute_mock = MagicMock()
    execute_mock.data = kwargs.get("data", [])
    chain = MagicMock()
    for m in ("select", "insert", "update", "delete", "eq", "neq",
              "gt", "lt", "is_", "maybe_single"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = execute_mock
    return chain


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestWebhooksCustomerTriage:
    """
    All tests patch _handle_inbound_message dependencies so the full
    FastAPI app is not required — we call the private function directly.
    """

    def _make_db(self, customer_data=None, cc_data=None, lead_data=None,
                  session_data=None, org_triage_data=None,
                  wa_msg_data=None):
        """
        Build a db mock with table calls in the order _handle_inbound_message
        accesses them for a known-customer path:
          1. customers   (lookup)
          2. customer_contacts (lookup — returns empty so customer direct-match wins)
          3. whatsapp_sessions (get_active_session for customer)
          4. organisations (triage config check)
          5. whatsapp_messages (insert)
        Additional calls depend on the branch taken.
        """
        db = MagicMock()

        chains = [
            _chain(data=customer_data or [{"id": CUST_ID, "org_id": ORG_ID,
                                            "whatsapp": PHONE, "phone": PHONE,
                                            "assigned_to": USER_ID}]),
            _chain(data=cc_data or []),                        # customer_contacts lookup
            _chain(data=session_data or []),                   # get_active_session
            _chain(data=org_triage_data or [{"whatsapp_triage_config": CUSTOMER_TRIAGE_CONFIG}]),
            _chain(data=wa_msg_data or [{"id": "msg1"}]),      # whatsapp_messages insert
        ]

        db.table.side_effect = chains
        return db

    # ── Test 1: Active session → handle_session_message ─────────────────────

    def test_active_customer_session_routes_to_session_handler(self):
        from app.routers.webhooks import _handle_inbound_message

        active_sess = {
            "id": SESS_ID, "session_state": "triage_sent",
            "session_data": {"customer_id": CUST_ID},
        }
        db = MagicMock()
        # Lookup chains
        cust_chain = _chain(data=[{"id": CUST_ID, "org_id": ORG_ID,
                                    "whatsapp": PHONE, "phone": PHONE,
                                    "assigned_to": USER_ID}])
        cc_chain   = _chain(data=[])
        sess_chain = _chain(data=[active_sess])

        db.table.side_effect = [cust_chain, cc_chain, sess_chain]

        msg = {
            "from": PHONE, "id": "wamid.1", "type": "text",
            "text": {"body": "hello"}, "timestamp": "1700000000",
        }

        with patch("app.services.triage_service.handle_session_message") as mock_hsm, \
             patch("app.services.triage_service.get_active_session",
                   return_value=active_sess):
            _handle_inbound_message(db, msg, "Test Customer", PHONE_ID)
            mock_hsm.assert_called_once()
            call_kwargs = mock_hsm.call_args[1]
            assert call_kwargs["section"] == "customer"

    # ── Test 2: No session + customer menu configured → send menu + create session ──

    def test_no_session_with_customer_menu_sends_menu_and_returns(self):
        from app.routers.webhooks import _handle_inbound_message

        db = MagicMock()
        # DB call sequence for a known-customer text message:
        #   1. customers          — _lookup_record_by_phone (match found, returns early)
        #   2. whatsapp_messages  — message save
        #   3. organisations      — WH-2 triage config check
        # customer_contacts and leads are NOT queried (customer matched directly).
        # get_active_session is patched — no DB call.
        cust_chain = _chain(data=[{"id": CUST_ID, "org_id": ORG_ID,
                                    "whatsapp": PHONE, "phone": PHONE,
                                    "assigned_to": USER_ID}])
        wa_chain   = _chain(data=[{"id": "msg1"}])
        org_chain  = _chain(data=[{"whatsapp_triage_config": CUSTOMER_TRIAGE_CONFIG}])

        db.table.side_effect = [cust_chain, wa_chain, org_chain]

        msg = {
            "from": PHONE, "id": "wamid.1", "type": "text",
            "text": {"body": "hello"}, "timestamp": "1700000000",
        }

        with patch("app.services.triage_service.get_active_session", return_value=None), \
             patch("app.services.whatsapp_service.send_triage_menu") as mock_send, \
             patch("app.services.triage_service.create_customer_session") as mock_create, \
             patch("app.services.customer_inbound_service.handle_customer_inbound") as mock_ci:

            _handle_inbound_message(db, msg, "Test Customer", PHONE_ID)

            mock_send.assert_called_once_with(
                db=db, org_id=ORG_ID, phone_number=PHONE, section="customer",
            )
            mock_create.assert_called_once_with(
                db=db, org_id=ORG_ID, phone_number=PHONE, customer_id=CUST_ID,
            )
            mock_ci.assert_not_called()

    # ── Test 3: No session + empty customer items → falls through to intent classifier ──

    def test_no_session_empty_customer_items_falls_through(self):
        from app.routers.webhooks import _handle_inbound_message

        db = MagicMock()
        # Sequence: customers, whatsapp_messages, organisations
        cust_chain = _chain(data=[{"id": CUST_ID, "org_id": ORG_ID,
                                    "whatsapp": PHONE, "phone": PHONE,
                                    "assigned_to": USER_ID}])
        wa_chain  = _chain(data=[{"id": "msg1"}])
        org_chain = _chain(data=[{"whatsapp_triage_config": EMPTY_CUSTOMER_CONFIG}])

        db.table.side_effect = [cust_chain, wa_chain, org_chain]

        msg = {
            "from": PHONE, "id": "wamid.1", "type": "text",
            "text": {"body": "hello"}, "timestamp": "1700000000",
        }

        with patch("app.services.triage_service.get_active_session", return_value=None), \
             patch("app.services.whatsapp_service.send_triage_menu") as mock_send, \
             patch("app.services.triage_service.create_customer_session") as mock_create, \
             patch("app.services.customer_inbound_service.handle_customer_inbound",
                   return_value=True) as mock_ci:

            _handle_inbound_message(db, msg, "Test Customer", PHONE_ID)

            mock_send.assert_not_called()
            mock_create.assert_not_called()
            mock_ci.assert_called_once()

    # ── Test 4: No session + no triage config at all → falls through ────────

    def test_no_session_no_triage_config_falls_through(self):
        from app.routers.webhooks import _handle_inbound_message

        db = MagicMock()
        # Sequence: customers, whatsapp_messages, organisations
        cust_chain = _chain(data=[{"id": CUST_ID, "org_id": ORG_ID,
                                    "whatsapp": PHONE, "phone": PHONE,
                                    "assigned_to": USER_ID}])
        wa_chain  = _chain(data=[{"id": "msg1"}])
        org_chain = _chain(data=[{"whatsapp_triage_config": None}])

        db.table.side_effect = [cust_chain, wa_chain, org_chain]

        msg = {
            "from": PHONE, "id": "wamid.1", "type": "text",
            "text": {"body": "hello"}, "timestamp": "1700000000",
        }

        with patch("app.services.triage_service.get_active_session", return_value=None), \
             patch("app.services.whatsapp_service.send_triage_menu") as mock_send, \
             patch("app.services.customer_inbound_service.handle_customer_inbound",
                   return_value=True) as mock_ci:

            _handle_inbound_message(db, msg, "Test Customer", PHONE_ID)

            mock_send.assert_not_called()
            mock_ci.assert_called_once()

    # ── Test 5: Triage config check raises → falls through gracefully ────────

    def test_triage_config_exception_falls_through(self):
        from app.routers.webhooks import _handle_inbound_message

        db = MagicMock()
        # Sequence: customers, whatsapp_messages, organisations(explodes)
        cust_chain = _chain(data=[{"id": CUST_ID, "org_id": ORG_ID,
                                    "whatsapp": PHONE, "phone": PHONE,
                                    "assigned_to": USER_ID}])
        wa_chain  = _chain(data=[{"id": "msg1"}])
        # Make org triage config lookup explode
        bad_chain = MagicMock()
        bad_chain.select.return_value = bad_chain
        bad_chain.eq.return_value = bad_chain
        bad_chain.maybe_single.return_value = bad_chain
        bad_chain.execute.side_effect = Exception("db timeout")

        db.table.side_effect = [cust_chain, wa_chain, bad_chain]

        msg = {
            "from": PHONE, "id": "wamid.1", "type": "text",
            "text": {"body": "hello"}, "timestamp": "1700000000",
        }

        with patch("app.services.triage_service.get_active_session", return_value=None), \
             patch("app.services.customer_inbound_service.handle_customer_inbound",
                   return_value=True) as mock_ci:

            # Must not raise — exception is caught and falls through
            _handle_inbound_message(db, msg, "Test Customer", PHONE_ID)
            mock_ci.assert_called_once()
