"""
tests/unit/test_commerce_shopify_comm1.py
COMM-1 — Tests for shopify_service.py COMM-1 additions and cart_abandonment_worker.py.

Pattern 63: lazy imports inside functions → patch source module directly.
  commerce_service imports inside handle_order_created → patch "app.services.commerce_service.X"
  send_checkout_link inside handle_abandoned_cart → patch "app.services.whatsapp_service.send_checkout_link"
  send_checkout_link inside worker → patch "app.services.whatsapp_service.send_checkout_link"
  mark_cart_abandoned inside worker → patch "app.services.commerce_service.mark_cart_abandoned"

Pre-write signature checks performed:
  handle_abandoned_cart(db, org_id, checkout) — existing, confirmed
  handle_order_created(db, org_id, order) — existing, confirmed
  run_cart_abandonment_check() — new, no args
  mark_cart_abandoned(db, session_id) — confirmed
  send_checkout_link(db, org_id, phone_number, checkout_url, commerce_config) — confirmed
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call


ORG_ID  = "org-comm1-test"
PHONE   = "+2348055443322"
CS_ID   = "cs-test-1"
ORDER_ID = 77001


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _db_with_tracking():
    """MagicMock DB that tracks update/insert calls in db._updates / db._inserts."""
    db = MagicMock()
    tracked_updates = []
    tracked_inserts = []

    def table_side(name):
        tbl = MagicMock()

        # select chain
        sel = MagicMock()
        sel.eq.return_value       = sel
        sel.in_.return_value      = sel
        sel.lt.return_value       = sel
        sel.order.return_value    = sel
        sel.limit.return_value    = sel
        sel.maybe_single.return_value = sel
        sel.execute.return_value.data = []
        tbl.select.return_value = sel

        # update chain — track payload
        def capture_update(data):
            upd = MagicMock()
            upd.eq.return_value = upd
            upd.execute.return_value = None
            tracked_updates.append({"table": name, "data": data})
            return upd
        tbl.update.side_effect = capture_update

        # insert chain — track payload
        def capture_insert(data):
            ins = MagicMock()
            ins.execute.return_value.data = [{"id": "new-id-1"}]
            tracked_inserts.append({"table": name, "data": data})
            return ins
        tbl.insert.side_effect = capture_insert

        return tbl

    db.table.side_effect = table_side
    db._updates = tracked_updates
    db._inserts = tracked_inserts
    return db


def _open_cs(status="open"):
    return {
        "id":           CS_ID,
        "org_id":       ORG_ID,
        "phone_number": PHONE,
        "status":       status,
        "checkout_url": "https://checkout.myshopify.com/old",
    }


def _checkout(phone=PHONE):
    return {
        "id":                   "chk-1",
        "phone":                phone,
        "abandoned_checkout_url": "https://checkout.myshopify.com/abandoned",
        "line_items": [
            {"title": "Test Bag", "quantity": 1, "price": "5000.00"}
        ],
    }


def _order(phone=PHONE, order_id=ORDER_ID):
    return {
        "id":            order_id,
        "name":          f"#{order_id}",
        "phone":         phone,
        "total_price":   "5000.00",
        "landing_site":  None,
        "billing_address": {"first_name": "Test", "last_name": "Buyer"},
        "customer":      {"first_name": "Test", "last_name": "Buyer", "email": "t@e.com"},
        "email":         "test@buyer.com",
    }


# ---------------------------------------------------------------------------
# handle_abandoned_cart — COMM-1 block
# ---------------------------------------------------------------------------

class TestHandleAbandonedCartComm1:

    def _make_db_with_cs(self, cs=None):
        db = _db_with_tracking()
        def table_side(name):
            tbl = MagicMock()
            sel = MagicMock()
            sel.eq.return_value       = sel
            sel.in_.return_value      = sel
            sel.order.return_value    = sel
            sel.limit.return_value    = sel
            sel.maybe_single.return_value = sel
            if name == "commerce_sessions":
                sel.execute.return_value.data = [cs] if cs else []
            else:
                sel.execute.return_value.data = []
            tbl.select.return_value = sel
            def capture_update(data):
                upd = MagicMock()
                upd.eq.return_value = upd
                upd.execute.return_value = None
                db._updates.append({"table": name, "data": data})
                return upd
            tbl.update.side_effect = capture_update
            def capture_insert(data):
                ins = MagicMock()
                ins.execute.return_value.data = [{"id": "new-id-1"}]
                db._inserts.append({"table": name, "data": data})
                return ins
            tbl.insert.side_effect = capture_insert
            return tbl
        db.table.side_effect = table_side
        return db

    def test_whatsapp_session_found_sends_recovery_not_lead(self):
        """
        Open commerce_session exists → send recovery message.
        Must NOT create a lead.
        """
        from app.services.shopify_service import handle_abandoned_cart

        cs = _open_cs()
        db = self._make_db_with_cs(cs=cs)

        with patch("app.services.whatsapp_service.send_checkout_link") as mock_send:
            handle_abandoned_cart(db, ORG_ID, _checkout())

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        assert PHONE in str(call_kwargs)
        assert "abandoned" in str(call_kwargs).lower() or "checkout" in str(call_kwargs).lower()

        # Must NOT have created a lead
        lead_inserts = [i for i in db._inserts if i["table"] == "leads"]
        assert not lead_inserts, f"Lead should not be created for WA session, got: {lead_inserts}"

    def test_whatsapp_session_found_updates_session_status(self):
        """commerce_session status updated to checkout_sent."""
        from app.services.shopify_service import handle_abandoned_cart

        cs = _open_cs()
        db = self._make_db_with_cs(cs=cs)

        with patch("app.services.whatsapp_service.send_checkout_link"):
            handle_abandoned_cart(db, ORG_ID, _checkout())

        cs_updates = [
            u for u in db._updates
            if u["table"] == "commerce_sessions"
        ]
        assert any(
            u["data"].get("status") == "checkout_sent"
            for u in cs_updates
        ), f"Expected checkout_sent update, got: {cs_updates}"

    def test_whatsapp_session_found_sets_commerce_state(self):
        """whatsapp_session.commerce_state set to commerce_checkout."""
        from app.services.shopify_service import handle_abandoned_cart

        cs = _open_cs()
        db = self._make_db_with_cs(cs=cs)

        with patch("app.services.whatsapp_service.send_checkout_link"):
            handle_abandoned_cart(db, ORG_ID, _checkout())

        ws_updates = [
            u for u in db._updates
            if u["table"] == "whatsapp_sessions"
            and u["data"].get("commerce_state") == "commerce_checkout"
        ]
        assert ws_updates, f"Expected commerce_checkout state update, got: {db._updates}"

    def test_no_whatsapp_session_falls_through_to_lead_creation(self):
        """No open commerce_session → existing lead creation path runs."""
        from app.services.shopify_service import handle_abandoned_cart

        db = self._make_db_with_cs(cs=None)  # no commerce_session

        # Patch _match_phone_to_record to return no match — simulates unknown contact.
        # This avoids the .is_() chain gap in the mock and focuses the test
        # on the _auto_create_lead_from_checkout branch being reached.
        with patch("app.services.whatsapp_service.send_abandoned_cart_message"), \
             patch("app.services.shopify_service._match_phone_to_record",
                   return_value=(None, None)), \
             patch("app.services.shopify_service._auto_create_lead_from_checkout",
                   return_value="lead-auto-1") as mock_create:
            handle_abandoned_cart(db, ORG_ID, _checkout())

        mock_create.assert_called_once()

    def test_no_phone_skips_everything(self):
        """Checkout with no phone → early return, no DB calls, no WA message."""
        from app.services.shopify_service import handle_abandoned_cart

        db = self._make_db_with_cs()
        checkout = _checkout(phone="")

        with patch("app.services.whatsapp_service.send_checkout_link") as mock_send:
            handle_abandoned_cart(db, ORG_ID, checkout)

        mock_send.assert_not_called()

    def test_s14_never_raises(self):
        """DB failure must not propagate."""
        from app.services.shopify_service import handle_abandoned_cart

        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")

        handle_abandoned_cart(db, ORG_ID, _checkout())  # must not raise


# ---------------------------------------------------------------------------
# handle_order_created — COMM-1 block
# ---------------------------------------------------------------------------

class TestHandleOrderCreatedComm1:

    def _make_db_with_cs(self, cs_row=None):
        """DB that returns a specific commerce_session row on select."""
        db = _db_with_tracking()
        cs_data = cs_row

        def table_side(name):
            tbl = MagicMock()
            sel = MagicMock()
            sel.eq.return_value       = sel
            sel.in_.return_value      = sel
            sel.order.return_value    = sel
            sel.limit.return_value    = sel
            sel.maybe_single.return_value = sel

            if name == "commerce_sessions":
                sel.execute.return_value.data = cs_data
            elif name == "leads":
                sel.execute.return_value.data = None
            else:
                sel.execute.return_value.data = None

            tbl.select.return_value = sel

            def capture_update(data):
                upd = MagicMock()
                upd.eq.return_value = upd
                upd.execute.return_value = None
                db._updates.append({"table": name, "data": data})
                return upd
            tbl.update.side_effect = capture_update

            def capture_insert(data):
                ins = MagicMock()
                ins.execute.return_value.data = [{"id": "cust-new-1"}]
                db._inserts.append({"table": name, "data": data})
                return ins
            tbl.insert.side_effect = capture_insert

            return tbl

        db.table.side_effect = table_side
        return db

    def test_mark_cart_completed_called(self):
        """mark_cart_completed fires with correct session_id and order_id."""
        from app.services.shopify_service import handle_order_created

        cs = {"id": CS_ID, "lead_id": None, "customer_id": None}
        db = self._make_db_with_cs(cs_row=cs)

        with patch("app.services.commerce_service.mark_cart_completed") as mock_mc, \
             patch("app.services.commerce_service.convert_lead_on_purchase"), \
             patch("app.services.whatsapp_service.send_order_confirmation_message"):
            handle_order_created(db, ORG_ID, _order())

        mock_mc.assert_called_once_with(db, CS_ID, ORDER_ID)

    def test_convert_lead_on_purchase_called_when_lead_id_set(self):
        """convert_lead_on_purchase fires when commerce_session.lead_id is present."""
        from app.services.shopify_service import handle_order_created

        cs = {"id": CS_ID, "lead_id": "lead-abc", "customer_id": None}
        db = self._make_db_with_cs(cs_row=cs)

        with patch("app.services.commerce_service.mark_cart_completed"), \
             patch("app.services.commerce_service.convert_lead_on_purchase") as mock_conv, \
             patch("app.services.whatsapp_service.send_order_confirmation_message"):
            handle_order_created(db, ORG_ID, _order())

        mock_conv.assert_called_once_with(db, ORG_ID, "lead-abc")

    def test_convert_lead_not_called_when_no_lead_id(self):
        """convert_lead_on_purchase NOT called when session has no lead_id."""
        from app.services.shopify_service import handle_order_created

        cs = {"id": CS_ID, "lead_id": None, "customer_id": None}
        db = self._make_db_with_cs(cs_row=cs)

        with patch("app.services.commerce_service.mark_cart_completed"), \
             patch("app.services.commerce_service.convert_lead_on_purchase") as mock_conv, \
             patch("app.services.whatsapp_service.send_order_confirmation_message"):
            handle_order_created(db, ORG_ID, _order())

        mock_conv.assert_not_called()

    def test_customer_record_created_when_no_customer_id(self):
        """New customer inserted when commerce_session.customer_id is None."""
        from app.services.shopify_service import handle_order_created

        cs = {"id": CS_ID, "lead_id": None, "customer_id": None}
        db = self._make_db_with_cs(cs_row=cs)

        with patch("app.services.commerce_service.mark_cart_completed"), \
             patch("app.services.commerce_service.convert_lead_on_purchase"), \
             patch("app.services.whatsapp_service.send_order_confirmation_message"):
            handle_order_created(db, ORG_ID, _order())

        cust_inserts = [i for i in db._inserts if i["table"] == "customers"]
        assert cust_inserts, f"Expected customers insert, got: {db._inserts}"
        assert cust_inserts[0]["data"]["whatsapp_number"] == PHONE

    def test_customer_not_created_when_already_linked(self):
        """No customers insert when commerce_session already has customer_id."""
        from app.services.shopify_service import handle_order_created

        cs = {"id": CS_ID, "lead_id": None, "customer_id": "cust-existing"}
        db = self._make_db_with_cs(cs_row=cs)

        with patch("app.services.commerce_service.mark_cart_completed"), \
             patch("app.services.commerce_service.convert_lead_on_purchase"), \
             patch("app.services.whatsapp_service.send_order_confirmation_message"):
            handle_order_created(db, ORG_ID, _order())

        cust_inserts = [i for i in db._inserts if i["table"] == "customers"]
        assert not cust_inserts, f"No customer insert expected, got: {cust_inserts}"

    def test_commerce_state_cleared_on_whatsapp_session(self):
        """whatsapp_session.commerce_state set to None after order."""
        from app.services.shopify_service import handle_order_created

        cs = {"id": CS_ID, "lead_id": None, "customer_id": None}
        db = self._make_db_with_cs(cs_row=cs)

        with patch("app.services.commerce_service.mark_cart_completed"), \
             patch("app.services.commerce_service.convert_lead_on_purchase"), \
             patch("app.services.whatsapp_service.send_order_confirmation_message"):
            handle_order_created(db, ORG_ID, _order())

        ws_clears = [
            u for u in db._updates
            if u["table"] == "whatsapp_sessions"
            and u["data"].get("commerce_state") is None
        ]
        assert ws_clears, f"Expected commerce_state=None update on whatsapp_sessions, got: {db._updates}"

    def test_confirmation_message_still_sent(self):
        """Existing send_order_confirmation_message still fires (no regression)."""
        from app.services.shopify_service import handle_order_created

        cs = {"id": CS_ID, "lead_id": None, "customer_id": None}
        db = self._make_db_with_cs(cs_row=cs)

        with patch("app.services.commerce_service.mark_cart_completed"), \
             patch("app.services.commerce_service.convert_lead_on_purchase"), \
             patch("app.services.whatsapp_service.send_order_confirmation_message") as mock_conf:
            handle_order_created(db, ORG_ID, _order())

        mock_conf.assert_called_once()

    def test_no_commerce_session_still_sends_confirmation(self):
        """No commerce_session → confirmation still fires, no crash."""
        from app.services.shopify_service import handle_order_created

        db = self._make_db_with_cs(cs_row=None)

        with patch("app.services.whatsapp_service.send_order_confirmation_message") as mock_conf:
            handle_order_created(db, ORG_ID, _order())

        mock_conf.assert_called_once()

    def test_s14_never_raises(self):
        """DB failure must not propagate."""
        from app.services.shopify_service import handle_order_created

        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")

        handle_order_created(db, ORG_ID, _order())  # must not raise


# ---------------------------------------------------------------------------
# cart_abandonment_worker
# ---------------------------------------------------------------------------

class TestCartAbandonmentWorker:

    def _now(self):
        return datetime.now(timezone.utc)

    def _session(self, hours_ago=3, status="checkout_sent", checkout_url="https://checkout.myshopify.com/inv/1"):
        updated_at = (self._now() - timedelta(hours=hours_ago)).isoformat()
        return {
            "id":           CS_ID,
            "org_id":       ORG_ID,
            "phone_number": PHONE,
            "status":       status,
            "checkout_url": checkout_url,
            "updated_at":   updated_at,
        }

    def _make_db(self, sessions=None):
        db = MagicMock()
        def table_side(name):
            tbl = MagicMock()
            sel = MagicMock()
            sel.eq.return_value    = sel
            sel.lt.return_value    = sel
            sel.execute.return_value.data = (sessions or [])
            tbl.select.return_value = sel
            upd = MagicMock()
            upd.eq.return_value = upd
            upd.execute.return_value = None
            tbl.update.return_value = upd
            return tbl
        db.table.side_effect = table_side
        return db

    def test_reminder_sent_for_2h_old_session(self):
        """Session updated 3h ago → reminder sent, not abandoned."""
        from app.workers.cart_abandonment_worker import run_cart_abandonment_check

        sessions = [self._session(hours_ago=3)]
        db = self._make_db(sessions=sessions)

        with patch("app.database.get_supabase", return_value=db), \
             patch("app.services.whatsapp_service.send_checkout_link") as mock_send, \
             patch("app.services.commerce_service.mark_cart_abandoned") as mock_ab:

            result = run_cart_abandonment_check()

        mock_send.assert_called_once()
        mock_ab.assert_not_called()
        assert result["reminded"] == 1
        assert result["abandoned"] == 0

    def test_abandoned_for_24h_old_session(self):
        """Session updated 25h ago → mark_cart_abandoned, no reminder."""
        from app.workers.cart_abandonment_worker import run_cart_abandonment_check

        sessions = [self._session(hours_ago=25)]
        db = self._make_db(sessions=sessions)

        with patch("app.database.get_supabase", return_value=db), \
             patch("app.services.whatsapp_service.send_checkout_link") as mock_send, \
             patch("app.services.commerce_service.mark_cart_abandoned") as mock_ab:

            result = run_cart_abandonment_check()

        mock_ab.assert_called_once_with(db, CS_ID)
        mock_send.assert_not_called()
        assert result["abandoned"] == 1
        assert result["reminded"] == 0

    def test_s14_one_session_failure_does_not_stop_loop(self):
        """Second session processed even if first raises."""
        from app.workers.cart_abandonment_worker import run_cart_abandonment_check

        s1 = self._session(hours_ago=3)
        s2 = dict(self._session(hours_ago=3), id="cs-2", phone_number="+2348099887766")
        db = self._make_db(sessions=[s1, s2])

        call_count = {"n": 0}
        def flaky_send(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("WA send failed")

        with patch("app.database.get_supabase", return_value=db), \
             patch("app.services.whatsapp_service.send_checkout_link",
                   side_effect=flaky_send), \
             patch("app.services.commerce_service.mark_cart_abandoned"):

            result = run_cart_abandonment_check()

        assert result["processed"] == 2
        assert result["failed"] == 1
        assert result["reminded"] == 1

    def test_s13_invalid_session_skipped(self):
        """Session with empty phone_number fails Pydantic validation → skipped."""
        from app.workers.cart_abandonment_worker import run_cart_abandonment_check

        bad_session = self._session(hours_ago=3)
        bad_session["phone_number"] = ""  # invalid
        db = self._make_db(sessions=[bad_session])

        with patch("app.database.get_supabase", return_value=db), \
             patch("app.services.whatsapp_service.send_checkout_link") as mock_send:

            result = run_cart_abandonment_check()

        mock_send.assert_not_called()
        assert result["failed"] == 1

    def test_s13_empty_checkout_url_skipped(self):
        """Session with no checkout_url fails Pydantic validation → skipped."""
        from app.workers.cart_abandonment_worker import run_cart_abandonment_check

        bad_session = self._session(hours_ago=3, checkout_url="")
        db = self._make_db(sessions=[bad_session])

        with patch("app.database.get_supabase", return_value=db), \
             patch("app.services.whatsapp_service.send_checkout_link") as mock_send:

            result = run_cart_abandonment_check()

        mock_send.assert_not_called()
        assert result["failed"] == 1

    def test_empty_session_list_returns_zero_summary(self):
        """No sessions → clean summary dict."""
        from app.workers.cart_abandonment_worker import run_cart_abandonment_check

        db = self._make_db(sessions=[])
        with patch("app.database.get_supabase", return_value=db):
            result = run_cart_abandonment_check()

        assert result == {"processed": 0, "reminded": 0, "abandoned": 0, "failed": 0}

    def test_db_fetch_failure_returns_empty_summary(self):
        """DB failure on session fetch → clean summary, no crash."""
        from app.workers.cart_abandonment_worker import run_cart_abandonment_check

        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")

        with patch("app.database.get_supabase", return_value=db):
            result = run_cart_abandonment_check()

        assert result["processed"] == 0

    def test_return_summary_keys_present(self):
        """Summary always has all 4 keys."""
        from app.workers.cart_abandonment_worker import run_cart_abandonment_check

        db = self._make_db(sessions=[])
        with patch("app.database.get_supabase", return_value=db):
            result = run_cart_abandonment_check()

        assert set(result.keys()) == {"processed", "reminded", "abandoned", "failed"}
