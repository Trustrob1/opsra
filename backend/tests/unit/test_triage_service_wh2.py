"""
tests/unit/test_triage_service_wh2.py
--------------------------------------
WH-2: Unit tests for customer triage dispatcher and session helpers.

Patch strategy (Pattern 42 + WH-0 convention):
  - dispatch_customer_triage_selection tests: patch the individual
    _customer_action_* functions at triage_service module level,
    exactly as WH-0 tests patch _action_qualify/_action_free_form etc.
  - _customer_action_* tests: patch app.services.triage_service._notify_managers
    (module-level function), exactly as WH-0 handle_awaiting_identifier tests do.
  - Never patch _insert_notification — it is lazily imported inside _notify_managers
    and is not a triage_service attribute.
  - send_triage_menu: patch at app.services.whatsapp_service.send_triage_menu
    (source module), same as WH-0 handle_session_message tests.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID    = "00000000-0000-0000-0000-000000000001"
PHONE     = "+2348012345678"
CUST_ID   = "00000000-0000-0000-0000-000000000002"
USER_ID   = "00000000-0000-0000-0000-000000000003"
SESS_ID   = "00000000-0000-0000-0000-000000000004"
TICKET_ID = "00000000-0000-0000-0000-000000000005"

NOW = datetime.now(timezone.utc).isoformat()

# Patch targets — verified against WH-0 passing tests
_NOTIFY_MANAGERS = "app.services.triage_service._notify_managers"
_SEND_MENU       = "app.services.whatsapp_service.send_triage_menu"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chain(**kwargs):
    execute_mock = MagicMock()
    execute_mock.data = kwargs.get("data", [])
    chain = MagicMock()
    for method in (
        "select", "insert", "update", "delete", "eq", "neq",
        "gt", "lt", "is_", "maybe_single",
    ):
        getattr(chain, method).return_value = chain
    chain.execute.return_value = execute_mock
    return chain


def _db(*chains):
    db = MagicMock()
    if len(chains) == 1:
        db.table.return_value = chains[0]
    else:
        db.table.side_effect = list(chains)
    return db


# ---------------------------------------------------------------------------
# create_customer_session
# ---------------------------------------------------------------------------

class TestCreateCustomerSession:

    def test_inserts_with_customer_id_in_session_data(self):
        from app.services.triage_service import create_customer_session

        row = {"id": SESS_ID, "session_state": "triage_sent",
               "session_data": {"customer_id": CUST_ID}}
        chain = _chain(data=[row])
        db = _db(chain)

        result = create_customer_session(db, ORG_ID, PHONE, CUST_ID)

        assert result == row
        insert_call = chain.insert.call_args[0][0]
        assert insert_call["session_data"]["customer_id"] == CUST_ID
        assert insert_call["session_state"] == "triage_sent"
        assert insert_call["org_id"] == ORG_ID

    def test_returns_none_on_exception(self):
        from app.services.triage_service import create_customer_session

        db = MagicMock()
        db.table.side_effect = Exception("db error")

        result = create_customer_session(db, ORG_ID, PHONE, CUST_ID)
        assert result is None


# ---------------------------------------------------------------------------
# dispatch_customer_triage_selection
# Patch the individual action functions at module level — same approach as
# WH-0 tests for dispatch_triage_selection.
# ---------------------------------------------------------------------------

class TestDispatchCustomerTriageSelection:

    def _session(self):
        return {
            "id": SESS_ID,
            "session_state": "triage_sent",
            "session_data": {"customer_id": CUST_ID},
        }

    def _org_config(self, action="create_ticket", role=None):
        item = {
            "id": "support",
            "label": "I need help",
            "action": action,
            "contact_type": "support_contact",
        }
        if role:
            item["role"] = role
        return {
            "whatsapp_triage_config": {
                "customer": {
                    "greeting": "Hi!",
                    "section_title": "Choose",
                    "items": [item],
                }
            }
        }

    def test_create_ticket_action_dispatches(self):
        from app.services.triage_service import dispatch_customer_triage_selection

        org_chain = _chain(data=[self._org_config("create_ticket")])
        db = _db(org_chain)

        with patch("app.services.triage_service._customer_action_create_ticket") as mock_act:
            dispatch_customer_triage_selection(
                db=db, org_id=ORG_ID, phone_number=PHONE,
                item_id="support", session=self._session(),
                contact_name="Test", now_ts=NOW,
            )
            mock_act.assert_called_once()

    def test_route_to_role_action_dispatches(self):
        from app.services.triage_service import dispatch_customer_triage_selection

        org_chain = _chain(data=[self._org_config("route_to_role", role="owner")])
        db = _db(org_chain)

        with patch("app.services.triage_service._customer_action_route_to_role") as mock_act:
            dispatch_customer_triage_selection(
                db=db, org_id=ORG_ID, phone_number=PHONE,
                item_id="support", session=self._session(),
                contact_name="Test", now_ts=NOW,
            )
            mock_act.assert_called_once()

    def test_free_form_action_dispatches(self):
        from app.services.triage_service import dispatch_customer_triage_selection

        org_chain = _chain(data=[self._org_config("free_form")])
        db = _db(org_chain)

        with patch("app.services.triage_service._customer_action_free_form") as mock_act:
            dispatch_customer_triage_selection(
                db=db, org_id=ORG_ID, phone_number=PHONE,
                item_id="support", session=self._session(),
                contact_name="Test", now_ts=NOW,
            )
            mock_act.assert_called_once()

    def test_unknown_item_id_falls_back_to_free_form(self):
        from app.services.triage_service import dispatch_customer_triage_selection

        org_chain = _chain(data=[self._org_config("create_ticket")])
        db = _db(org_chain)

        with patch("app.services.triage_service._customer_action_free_form") as mock_ff, \
             patch("app.services.triage_service._customer_action_create_ticket") as mock_ct:
            dispatch_customer_triage_selection(
                db=db, org_id=ORG_ID, phone_number=PHONE,
                item_id="nonexistent", session=self._session(),
                contact_name="Test", now_ts=NOW,
            )
            mock_ff.assert_called_once()
            mock_ct.assert_not_called()

    def test_s14_swallows_exception(self):
        from app.services.triage_service import dispatch_customer_triage_selection

        db = MagicMock()
        db.table.side_effect = Exception("db exploded")

        # Must not raise
        dispatch_customer_triage_selection(
            db=db, org_id=ORG_ID, phone_number=PHONE,
            item_id="support", session={"id": SESS_ID, "session_data": {}},
            contact_name="Test", now_ts=NOW,
        )


# ---------------------------------------------------------------------------
# _customer_action_create_ticket
# Patch _notify_managers at module level — same as WH-0 handle_awaiting_identifier.
# ---------------------------------------------------------------------------

class TestCustomerActionCreateTicket:

    def test_creates_ticket_and_notifies_assigned_rep(self):
        from app.services.triage_service import _customer_action_create_ticket

        cust_chain   = _chain(data=[{"assigned_to": USER_ID, "full_name": "Acme Corp"}])
        ticket_chain = _chain(data=[{"id": TICKET_ID}])
        sess_chain   = _chain(data=[{"id": SESS_ID}])

        db = MagicMock()
        db.table.side_effect = [cust_chain, ticket_chain, sess_chain]

        with patch("app.services.triage_service._notify_single_user") as mock_notif, \
             patch(_NOTIFY_MANAGERS) as mock_notify:
            _customer_action_create_ticket(
                db, ORG_ID, PHONE, SESS_ID,
                {"label": "Support request"}, CUST_ID, "Test", NOW,
            )
            # assigned rep notified via _notify_single_user, not _notify_managers
            mock_notif.assert_called_once()
            mock_notify.assert_not_called()

    def test_notifies_managers_when_no_assigned_to(self):
        from app.services.triage_service import _customer_action_create_ticket

        cust_chain   = _chain(data=[{"assigned_to": None, "full_name": "Acme"}])
        ticket_chain = _chain(data=[{"id": TICKET_ID}])
        sess_chain   = _chain(data=[{"id": SESS_ID}])

        db = MagicMock()
        db.table.side_effect = [cust_chain, ticket_chain, sess_chain]

        with patch(_NOTIFY_MANAGERS) as mock_notify:
            _customer_action_create_ticket(
                db, ORG_ID, PHONE, SESS_ID,
                {"label": "Help"}, CUST_ID, None, NOW,
            )
            mock_notify.assert_called_once()


# ---------------------------------------------------------------------------
# _customer_action_route_to_role
# ---------------------------------------------------------------------------

class TestCustomerActionRouteToRole:

    def test_notifies_matched_role_users(self):
        from app.services.triage_service import _customer_action_route_to_role

        users_chain = _chain(data=[
            {"id": USER_ID, "roles": {"template": "owner"}},
            {"id": "00000000-0000-0000-0000-000000000099", "roles": {"template": "sales_rep"}},
        ])
        sess_chain = _chain(data=[{"id": SESS_ID}])

        db = MagicMock()
        db.table.side_effect = [users_chain, sess_chain]

        with patch("app.services.triage_service._notify_single_user") as mock_notif, \
             patch(_NOTIFY_MANAGERS) as mock_managers:
            _customer_action_route_to_role(
                db, ORG_ID, PHONE, SESS_ID,
                {"role": "owner", "label": "Billing"}, CUST_ID, "Test", NOW,
            )
            # Only owner matched — one notification via _notify_single_user
            mock_notif.assert_called_once()
            mock_managers.assert_not_called()

    def test_falls_back_to_managers_when_no_role_match(self):
        from app.services.triage_service import _customer_action_route_to_role

        users_chain = _chain(data=[{"id": USER_ID, "roles": {"template": "sales_rep"}}])
        sess_chain  = _chain(data=[{"id": SESS_ID}])

        db = MagicMock()
        db.table.side_effect = [users_chain, sess_chain]

        with patch(_NOTIFY_MANAGERS) as mock_notify:
            _customer_action_route_to_role(
                db, ORG_ID, PHONE, SESS_ID,
                {"role": "finance", "label": "Finance query"}, CUST_ID, "Test", NOW,
            )
            mock_notify.assert_called_once()


# ---------------------------------------------------------------------------
# _customer_action_free_form
# ---------------------------------------------------------------------------

class TestCustomerActionFreeForm:

    def test_notifies_assigned_rep(self):
        from app.services.triage_service import _customer_action_free_form

        cust_chain = _chain(data=[{"assigned_to": USER_ID}])
        sess_chain = _chain(data=[{"id": SESS_ID}])

        db = MagicMock()
        db.table.side_effect = [cust_chain, sess_chain]

        with patch("app.services.triage_service._notify_single_user") as mock_notif, \
             patch(_NOTIFY_MANAGERS) as mock_managers:
            _customer_action_free_form(
                db, ORG_ID, PHONE, SESS_ID,
                {}, CUST_ID, "Test", NOW,
            )
            mock_notif.assert_called_once()
            mock_managers.assert_not_called()

    def test_notifies_managers_when_no_assigned_to(self):
        from app.services.triage_service import _customer_action_free_form

        cust_chain = _chain(data=[{"assigned_to": None}])
        sess_chain = _chain(data=[{"id": SESS_ID}])

        db = MagicMock()
        db.table.side_effect = [cust_chain, sess_chain]

        with patch(_NOTIFY_MANAGERS) as mock_notify:
            _customer_action_free_form(
                db, ORG_ID, PHONE, SESS_ID,
                {}, CUST_ID, None, NOW,
            )
            mock_notify.assert_called_once()


# ---------------------------------------------------------------------------
# handle_session_message with section="customer"
# ---------------------------------------------------------------------------

class TestHandleSessionMessageCustomer:

    def _session(self, state="triage_sent"):
        return {
            "id": SESS_ID,
            "session_state": state,
            "session_data": {"customer_id": CUST_ID},
        }

    def test_interactive_list_reply_dispatches_to_customer_dispatcher(self):
        from app.services.triage_service import handle_session_message

        db = MagicMock()
        interactive_payload = {"list_reply": {"id": "support"}}

        with patch("app.services.triage_service.dispatch_customer_triage_selection") as mock_dispatch:
            handle_session_message(
                db=db, org_id=ORG_ID, phone_number=PHONE,
                session=self._session(),
                msg_type="interactive",
                content="support",
                interactive_payload=interactive_payload,
                contact_name="Test",
                now_ts=NOW,
                section="customer",
            )
            mock_dispatch.assert_called_once()
            assert mock_dispatch.call_args[1]["item_id"] == "support"

    def test_free_text_resends_customer_menu(self):
        from app.services.triage_service import handle_session_message

        db = MagicMock()

        # Pattern 42: send_triage_menu lazily imported from whatsapp_service
        # inside handle_session_message — patch at source module.
        with patch(_SEND_MENU) as mock_send, \
             patch("app.services.triage_service.dispatch_customer_triage_selection") as mock_dispatch:
            handle_session_message(
                db=db, org_id=ORG_ID, phone_number=PHONE,
                session=self._session(),
                msg_type="text",
                content="hello",
                interactive_payload=None,
                contact_name="Test",
                now_ts=NOW,
                section="customer",
            )
            mock_send.assert_called_once_with(
                db=db, org_id=ORG_ID,
                phone_number=PHONE, section="customer",
            )
            mock_dispatch.assert_not_called()

    def test_unknown_section_dispatches_to_unknown_dispatcher(self):
        from app.services.triage_service import handle_session_message

        db = MagicMock()
        interactive_payload = {"list_reply": {"id": "interested"}}

        with patch("app.services.triage_service.dispatch_triage_selection") as mock_unknown, \
             patch("app.services.triage_service.dispatch_customer_triage_selection") as mock_customer:
            handle_session_message(
                db=db, org_id=ORG_ID, phone_number=PHONE,
                session=self._session(),
                msg_type="interactive",
                content=None,
                interactive_payload=interactive_payload,
                contact_name="Test",
                now_ts=NOW,
                section="unknown",
            )
            mock_unknown.assert_called_once()
            mock_customer.assert_not_called()

    def test_active_session_state_is_noop(self):
        from app.services.triage_service import handle_session_message

        db = MagicMock()

        with patch("app.services.triage_service.dispatch_customer_triage_selection") as mock_dispatch:
            handle_session_message(
                db=db, org_id=ORG_ID, phone_number=PHONE,
                session=self._session(state="active"),
                msg_type="text", content="hello",
                interactive_payload=None, contact_name="Test",
                now_ts=NOW, section="customer",
            )
            mock_dispatch.assert_not_called()

    def test_s14_swallows_exception(self):
        from app.services.triage_service import handle_session_message

        db = MagicMock()

        with patch("app.services.triage_service.dispatch_customer_triage_selection",
                   side_effect=Exception("boom")):
            # Must not raise
            handle_session_message(
                db=db, org_id=ORG_ID, phone_number=PHONE,
                session=self._session(),
                msg_type="interactive",
                content=None,
                interactive_payload={"list_reply": {"id": "x"}},
                contact_name=None,
                now_ts=NOW,
                section="customer",
            )
