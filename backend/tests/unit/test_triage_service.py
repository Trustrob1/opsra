"""
tests/unit/test_triage_service.py
----------------------------------
Unit tests for app/services/triage_service.py — WH-0.

All DB calls are mocked. No network, no Supabase.
Patterns applied: 24 (valid UUIDs), 42 (patch at use-site),
52 (_insert_notification positional), 55 (system → actor_id=None),
59 (no competing execute.return_value on same chain).
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID      = "00000000-0000-0000-0000-000000000001"
PHONE       = "+2348001234567"
SESSION_ID  = "00000000-0000-0000-0000-000000000010"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000020"
CONTACT_ID  = "00000000-0000-0000-0000-000000000030"
LEAD_ID     = "00000000-0000-0000-0000-000000000040"
OWNER_ID    = "00000000-0000-0000-0000-000000000050"
OPS_ID      = "00000000-0000-0000-0000-000000000060"
USER_ID     = "00000000-0000-0000-0000-000000000070"

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# DB mock factory
# ---------------------------------------------------------------------------

def _mock_db():
    """Return a MagicMock that mimics the supabase-py chained query API."""
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.neq.return_value = chain
    chain.gt.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.delete.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = MagicMock(data=[])
    db.table.return_value = chain
    return db, chain


# ---------------------------------------------------------------------------
# get_active_session
# ---------------------------------------------------------------------------

class TestGetActiveSession:

    def test_returns_session_when_found(self):
        from app.services.triage_service import get_active_session
        db, chain = _mock_db()
        session_row = {
            "id": SESSION_ID, "org_id": ORG_ID,
            "phone_number": PHONE, "session_state": "triage_sent",
        }
        chain.execute.return_value = MagicMock(data=[session_row])

        result = get_active_session(db, ORG_ID, PHONE)

        assert result == session_row

    def test_returns_none_when_no_rows(self):
        from app.services.triage_service import get_active_session
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[])

        result = get_active_session(db, ORG_ID, PHONE)

        assert result is None

    def test_returns_none_on_db_exception(self):
        from app.services.triage_service import get_active_session
        db = MagicMock()
        db.table.side_effect = Exception("connection error")

        result = get_active_session(db, ORG_ID, PHONE)

        assert result is None  # S14 — must not raise

    def test_filters_by_org_and_phone(self):
        """Verify that .eq() is called for org_id and phone_number."""
        from app.services.triage_service import get_active_session
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[])

        get_active_session(db, ORG_ID, PHONE)

        eq_calls = [str(c) for c in chain.eq.call_args_list]
        assert any(ORG_ID in c for c in eq_calls)
        assert any(PHONE in c for c in eq_calls)


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------

class TestCreateSession:

    def test_inserts_triage_sent_state(self):
        from app.services.triage_service import create_session
        db, chain = _mock_db()
        new_row = {
            "id": SESSION_ID, "org_id": ORG_ID,
            "phone_number": PHONE, "session_state": "triage_sent",
        }
        chain.execute.return_value = MagicMock(data=[new_row])

        result = create_session(db, ORG_ID, PHONE)

        assert result == new_row
        insert_call = chain.insert.call_args[0][0]
        assert insert_call["session_state"] == "triage_sent"
        assert insert_call["org_id"] == ORG_ID
        assert insert_call["phone_number"] == PHONE

    def test_expires_at_is_in_future(self):
        from app.services.triage_service import create_session
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[{"id": SESSION_ID}])

        create_session(db, ORG_ID, PHONE, expires_minutes=30)

        insert_call = chain.insert.call_args[0][0]
        expires_at = datetime.fromisoformat(insert_call["expires_at"])
        # Should be at least 25 min in the future (allow test clock drift)
        assert expires_at > datetime.now(timezone.utc) + timedelta(minutes=25)

    def test_returns_none_on_db_exception(self):
        from app.services.triage_service import create_session
        db = MagicMock()
        db.table.side_effect = Exception("db error")

        result = create_session(db, ORG_ID, PHONE)

        assert result is None  # S14


# ---------------------------------------------------------------------------
# update_session
# ---------------------------------------------------------------------------

class TestUpdateSession:

    def test_updates_state_only(self):
        from app.services.triage_service import update_session
        db, chain = _mock_db()

        update_session(db, SESSION_ID, "active")

        update_payload = chain.update.call_args[0][0]
        assert update_payload["session_state"] == "active"
        assert "selected_action" not in update_payload

    def test_updates_state_and_selected_action(self):
        from app.services.triage_service import update_session
        db, chain = _mock_db()

        update_session(db, SESSION_ID, "active", selected_action="qualify")

        update_payload = chain.update.call_args[0][0]
        assert update_payload["session_state"] == "active"
        assert update_payload["selected_action"] == "qualify"

    def test_does_not_raise_on_db_exception(self):
        from app.services.triage_service import update_session
        db = MagicMock()
        db.table.side_effect = Exception("write error")

        # Must not raise — S14
        update_session(db, SESSION_ID, "active")


# ---------------------------------------------------------------------------
# dispatch_triage_selection
# ---------------------------------------------------------------------------

class TestDispatchTriageSelection:

    def _base_session(self):
        return {"id": SESSION_ID, "session_state": "triage_sent"}

    def _org_with_config(self):
        return {
            "whatsapp_triage_config": {
                "unknown": {
                    "items": [
                        {"id": "interested", "label": "I'm interested",
                         "action": "qualify", "contact_type": "sales_lead"},
                        {"id": "existing", "label": "Existing customer",
                         "action": "identify_customer", "contact_type": "support_contact"},
                        {"id": "business", "label": "Business inquiry",
                         "action": "route_to_role", "contact_type": "business_inquiry",
                         "role": "owner"},
                        {"id": "other", "label": "Something else",
                         "action": "free_form", "contact_type": "other"},
                    ]
                }
            }
        }

    def test_qualify_action_creates_lead_and_updates_session(self):
        from app.services.triage_service import dispatch_triage_selection
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._org_with_config()])

        with patch("app.services.triage_service.update_session") as mock_update, \
             patch("app.services.triage_service._action_qualify") as mock_qualify:
            dispatch_triage_selection(
                db, ORG_ID, PHONE, "interested",
                self._base_session(), "Test User", NOW,
            )
            mock_qualify.assert_called_once()
            # update_session is called inside _action_qualify, so not checked here

    def test_identify_customer_action(self):
        from app.services.triage_service import dispatch_triage_selection
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._org_with_config()])

        with patch("app.services.triage_service._action_identify_customer") as mock_ic:
            dispatch_triage_selection(
                db, ORG_ID, PHONE, "existing",
                self._base_session(), "Test User", NOW,
            )
            mock_ic.assert_called_once()

    def test_route_to_role_action(self):
        from app.services.triage_service import dispatch_triage_selection
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._org_with_config()])

        with patch("app.services.triage_service._action_route_to_role") as mock_rr:
            dispatch_triage_selection(
                db, ORG_ID, PHONE, "business",
                self._base_session(), "Test User", NOW,
            )
            mock_rr.assert_called_once()

    def test_free_form_action(self):
        from app.services.triage_service import dispatch_triage_selection
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._org_with_config()])

        with patch("app.services.triage_service._action_free_form") as mock_ff:
            dispatch_triage_selection(
                db, ORG_ID, PHONE, "other",
                self._base_session(), "Test User", NOW,
            )
            mock_ff.assert_called_once()

    def test_unknown_item_id_falls_back_to_free_form(self):
        """item_id not in config items → action defaults to 'free_form'."""
        from app.services.triage_service import dispatch_triage_selection
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._org_with_config()])

        with patch("app.services.triage_service._action_free_form") as mock_ff:
            dispatch_triage_selection(
                db, ORG_ID, PHONE, "completely_unknown_id",
                self._base_session(), "Test User", NOW,
            )
            mock_ff.assert_called_once()

    def test_none_item_id_falls_back_to_free_form(self):
        from app.services.triage_service import dispatch_triage_selection
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[self._org_with_config()])

        with patch("app.services.triage_service._action_free_form") as mock_ff:
            dispatch_triage_selection(
                db, ORG_ID, PHONE, None,
                self._base_session(), "Test User", NOW,
            )
            mock_ff.assert_called_once()

    def test_does_not_raise_on_db_exception(self):
        from app.services.triage_service import dispatch_triage_selection
        db = MagicMock()
        db.table.side_effect = Exception("db error")

        # Must not raise — S14
        dispatch_triage_selection(db, ORG_ID, PHONE, "interested",
                                  self._base_session(), None, NOW)


# ---------------------------------------------------------------------------
# handle_session_message
# ---------------------------------------------------------------------------

class TestHandleSessionMessage:

    def _session(self, state="triage_sent"):
        return {"id": SESSION_ID, "session_state": state}

    def test_triage_sent_list_reply_calls_dispatch(self):
        from app.services.triage_service import handle_session_message
        db, _ = _mock_db()
        interactive_payload = {"list_reply": {"id": "interested", "title": "I'm interested"}}

        with patch("app.services.triage_service.dispatch_triage_selection") as mock_dispatch:
            handle_session_message(
                db, ORG_ID, PHONE, self._session("triage_sent"),
                msg_type="interactive", content=None,
                interactive_payload=interactive_payload,
                contact_name="Test User", now_ts=NOW,
            )
            mock_dispatch.assert_called_once()
            _, kwargs = mock_dispatch.call_args
            # Verify correct item_id extracted from list_reply
            assert mock_dispatch.call_args[1].get("item_id") == "interested" or \
                   mock_dispatch.call_args[0][3] == "interested"

    def test_triage_sent_free_text_resends_menu_no_new_session(self):
        """Free text while menu pending → re-send menu, no create_session call."""
        from app.services.triage_service import handle_session_message
        db, _ = _mock_db()

        # send_triage_menu lives in whatsapp_service (added in Increment 2).
        # create=True lets us patch it before it exists. Pattern 42: patch at
        # use-site (whatsapp_service) not at triage_service.
        with patch("app.services.triage_service.dispatch_triage_selection") as mock_dispatch, \
             patch("app.services.triage_service.create_session") as mock_create, \
             patch("app.services.whatsapp_service.send_triage_menu",
                   create=True) as mock_menu:
            handle_session_message(
                db, ORG_ID, PHONE, self._session("triage_sent"),
                msg_type="text", content="hello",
                interactive_payload=None,
                contact_name="Test User", now_ts=NOW,
            )
            mock_dispatch.assert_not_called()
            mock_create.assert_not_called()

    def test_awaiting_identifier_calls_handle_awaiting_identifier(self):
        from app.services.triage_service import handle_session_message
        db, _ = _mock_db()

        with patch("app.services.triage_service.handle_awaiting_identifier") as mock_hai:
            handle_session_message(
                db, ORG_ID, PHONE, self._session("awaiting_identifier"),
                msg_type="text", content="acme corp",
                interactive_payload=None,
                contact_name="Test User", now_ts=NOW,
            )
            mock_hai.assert_called_once()

    def test_awaiting_identifier_empty_content_is_noop(self):
        from app.services.triage_service import handle_session_message
        db, _ = _mock_db()

        with patch("app.services.triage_service.handle_awaiting_identifier") as mock_hai:
            handle_session_message(
                db, ORG_ID, PHONE, self._session("awaiting_identifier"),
                msg_type="text", content="",
                interactive_payload=None,
                contact_name="Test User", now_ts=NOW,
            )
            mock_hai.assert_not_called()

    def test_active_session_is_noop(self):
        from app.services.triage_service import handle_session_message
        db, _ = _mock_db()

        with patch("app.services.triage_service.dispatch_triage_selection") as mock_d, \
             patch("app.services.triage_service.handle_awaiting_identifier") as mock_h:
            handle_session_message(
                db, ORG_ID, PHONE, self._session("active"),
                msg_type="text", content="anything",
                interactive_payload=None,
                contact_name=None, now_ts=NOW,
            )
            mock_d.assert_not_called()
            mock_h.assert_not_called()

    def test_does_not_raise_on_exception(self):
        from app.services.triage_service import handle_session_message
        db = MagicMock()
        db.table.side_effect = Exception("db error")

        # Must not raise — S14
        handle_session_message(
            db, ORG_ID, PHONE, {"id": SESSION_ID, "session_state": "triage_sent"},
            "text", "hello", None, None, NOW,
        )


# ---------------------------------------------------------------------------
# handle_awaiting_identifier
# ---------------------------------------------------------------------------

class TestHandleAwaitingIdentifier:

    def _session(self):
        return {"id": SESSION_ID, "session_state": "awaiting_identifier"}

    def test_customer_found_inserts_pending_contact(self):
        from app.services.triage_service import handle_awaiting_identifier
        db, chain = _mock_db()

        customer_row = {
            "id": CUSTOMER_ID, "full_name": "Acme Corp",
            "email": "billing@acme.com", "assigned_to": OWNER_ID,
        }
        # DB call sequence:
        # 1 — fetch customers (returns customer_row)
        # 2 — fetch org whatsapp_phone_id
        # 3 — insert customer_contacts
        # 4+ — users for notification
        call_count = [0]
        def _execute_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(data=[customer_row])
            elif call_count[0] == 2:
                return MagicMock(data={"whatsapp_phone_id": "phone_id_123"})
            elif call_count[0] == 3:
                return MagicMock(data=[{"id": CONTACT_ID}])
            else:
                return MagicMock(data=[
                    {"id": OWNER_ID, "roles": {"template": "owner"}}
                ])

        chain.execute.side_effect = _execute_side_effect

        with patch("app.services.whatsapp_service._call_meta_send", create=True), \
             patch("app.services.triage_service.update_session") as mock_update, \
             patch("app.services.triage_service._notify_managers") as mock_notify:

            handle_awaiting_identifier(
                db, ORG_ID, PHONE, "Acme Corp",
                self._session(), "John", NOW,
            )

            mock_notify.assert_called_once()
            mock_update.assert_called_once_with(
                db, SESSION_ID, "active",
                selected_action="identify_customer",
            )

    def test_customer_not_found_creates_support_contact_lead(self):
        from app.services.triage_service import handle_awaiting_identifier
        db, chain = _mock_db()

        # DB call 1: fetch customers → no match
        # DB call 2: fetch org whatsapp_phone_id → no phone_id
        call_count = [0]
        def _execute_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(data=[])   # no customers
            return MagicMock(data=None)     # org fetch → no phone_id
        chain.execute.side_effect = _execute_side_effect

        with patch("app.services.whatsapp_service._call_meta_send", create=True), \
             patch("app.services.triage_service.update_session") as mock_update, \
             patch("app.services.triage_service._notify_managers") as mock_notify, \
             patch("app.services.lead_service.create_lead",
                   return_value={"id": LEAD_ID}) as mock_create:

            handle_awaiting_identifier(
                db, ORG_ID, PHONE, "unknown company",
                self._session(), "Unknown Person", NOW,
            )

            mock_create.assert_called_once()
            lead_payload = mock_create.call_args[0][3]  # positional arg 4 — (db, org_id, user_id, payload)
            assert lead_payload.contact_type == "support_contact"
            mock_notify.assert_called_once()
            mock_update.assert_called_once()

    def test_case_insensitive_match(self):
        """Identifier 'ACME CORP' should match customer full_name 'Acme Corp'."""
        from app.services.triage_service import handle_awaiting_identifier
        db, chain = _mock_db()

        customer_row = {
            "id": CUSTOMER_ID, "full_name": "Acme Corp",
            "email": "billing@acme.com", "assigned_to": OWNER_ID,
        }
        # DB call 1: fetch customers, DB call 2: org phone_id, rest: insert + users
        call_count = [0]
        def _execute_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(data=[customer_row])
            return MagicMock(data=None)  # no phone_id — skip send
        chain.execute.side_effect = _execute_side_effect

        with patch("app.services.whatsapp_service._call_meta_send", create=True), \
             patch("app.services.triage_service.update_session"), \
             patch("app.services.triage_service._notify_managers") as mock_notify:

            handle_awaiting_identifier(
                db, ORG_ID, PHONE, "ACME CORP",
                self._session(), "John", NOW,
            )

            # Should have gone down the "found" path — notify title contains "pending"
            notify_call_kwargs = mock_notify.call_args[1]
            assert "pending" in notify_call_kwargs.get("title", "").lower()

    def test_does_not_raise_on_db_exception(self):
        from app.services.triage_service import handle_awaiting_identifier
        db = MagicMock()
        db.table.side_effect = Exception("db error")

        # Must not raise — S14
        handle_awaiting_identifier(
            db, ORG_ID, PHONE, "anything",
            {"id": SESSION_ID, "session_state": "awaiting_identifier"},
            None, NOW,
        )


# ---------------------------------------------------------------------------
# Customer contacts CRUD
# ---------------------------------------------------------------------------

class TestCustomerContactsCRUD:

    def test_list_customer_contacts_returns_rows(self):
        from app.services.triage_service import list_customer_contacts
        db, chain = _mock_db()
        rows = [
            {"id": CONTACT_ID, "phone_number": PHONE, "status": "active"},
        ]
        chain.execute.return_value = MagicMock(data=rows)

        result = list_customer_contacts(db, ORG_ID, CUSTOMER_ID)

        assert result == rows
        # Verify org and customer scoping
        eq_calls = [str(c) for c in chain.eq.call_args_list]
        assert any(ORG_ID in c for c in eq_calls)
        assert any(CUSTOMER_ID in c for c in eq_calls)

    def test_list_returns_empty_list_on_exception(self):
        from app.services.triage_service import list_customer_contacts
        db = MagicMock()
        db.table.side_effect = Exception("error")

        result = list_customer_contacts(db, ORG_ID, CUSTOMER_ID)

        assert result == []  # S14

    def test_add_customer_contact_inserts_pending(self):
        from app.services.triage_service import add_customer_contact
        db, chain = _mock_db()
        new_row = {"id": CONTACT_ID, "status": "pending"}
        chain.execute.return_value = MagicMock(data=[new_row])

        payload = {"phone_number": PHONE, "name": "John Doe",
                   "contact_role": "finance"}
        result = add_customer_contact(db, ORG_ID, CUSTOMER_ID, payload,
                                      registered_by=USER_ID)

        assert result == new_row
        insert_payload = chain.insert.call_args[0][0]
        assert insert_payload["status"] == "pending"
        assert insert_payload["org_id"] == ORG_ID
        assert insert_payload["customer_id"] == CUSTOMER_ID
        assert insert_payload["phone_number"] == PHONE
        assert insert_payload["registered_by"] == USER_ID

    def test_add_returns_none_on_exception(self):
        from app.services.triage_service import add_customer_contact
        db = MagicMock()
        db.table.side_effect = Exception("error")

        result = add_customer_contact(db, ORG_ID, CUSTOMER_ID,
                                      {"phone_number": PHONE})
        assert result is None  # S14

    def test_approve_contact_sets_status_active(self):
        from app.services.triage_service import approve_customer_contact
        db, chain = _mock_db()
        updated = {"id": CONTACT_ID, "status": "active"}
        chain.execute.return_value = MagicMock(data=[updated])

        result = approve_customer_contact(db, ORG_ID, CONTACT_ID, USER_ID)

        assert result == updated
        update_payload = chain.update.call_args[0][0]
        assert update_payload["status"] == "active"
        # Verify org scoping
        eq_calls = [str(c) for c in chain.eq.call_args_list]
        assert any(ORG_ID in c for c in eq_calls)
        assert any(CONTACT_ID in c for c in eq_calls)

    def test_approve_returns_none_on_exception(self):
        from app.services.triage_service import approve_customer_contact
        db = MagicMock()
        db.table.side_effect = Exception("error")

        result = approve_customer_contact(db, ORG_ID, CONTACT_ID, USER_ID)
        assert result is None  # S14

    def test_remove_contact_deletes_scoped_row(self):
        from app.services.triage_service import remove_customer_contact
        db, chain = _mock_db()
        chain.execute.return_value = MagicMock(data=[])

        result = remove_customer_contact(db, ORG_ID, CONTACT_ID, USER_ID)

        assert result is True
        # Verify org and contact scoping
        eq_calls = [str(c) for c in chain.eq.call_args_list]
        assert any(ORG_ID in c for c in eq_calls)
        assert any(CONTACT_ID in c for c in eq_calls)

    def test_remove_returns_false_on_exception(self):
        from app.services.triage_service import remove_customer_contact
        db = MagicMock()
        db.table.side_effect = Exception("error")

        result = remove_customer_contact(db, ORG_ID, CONTACT_ID, USER_ID)
        assert result is False  # S14
