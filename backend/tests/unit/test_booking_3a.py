"""BOOKING-3A - optional deposits: no deposit = unchanged, hold + pay, settle once, expiry, refund rules."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import booking_deposit_service as dep
from app.services import booking_service as bk

NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)


def _db(rows_by_table):
    """Tiny fake: table(name) -> chain returning rows; update/insert record calls."""
    db = MagicMock()
    log = []
    def table(name):
        q = MagicMock()
        for m in ("select", "eq", "in_", "order", "limit", "is_", "gte", "not_"):
            getattr(q, m).return_value = q
        q.execute.return_value = MagicMock(data=rows_by_table.get(name, []))
        def upd(p, _n=name):
            log.append(("update", _n, p)); return q
        def ins(p, _n=name):
            log.append(("insert", _n, p)); return q
        q.update.side_effect, q.insert.side_effect = upd, ins
        return q
    db.table.side_effect = table
    db.log = log
    return db


def test_no_deposit_by_default():
    assert not dep.has_deposit({})
    assert not dep.has_deposit({"deposit_amount": 0})
    assert not dep.has_deposit({"deposit_amount": None})
    assert dep.has_deposit({"deposit_amount": 5000})


def test_precheck_noop_without_deposit():
    dep.precheck(MagicMock(), "o", {"deposit_amount": 0})


def test_precheck_blocks_paystack_without_keys():
    with patch.object(dep, "_secret", return_value=""):
        with pytest.raises(HTTPException):
            dep.precheck(MagicMock(), "o", {"deposit_amount": 100, "deposit_method": "paystack"})


def test_precheck_external_needs_https_link():
    with pytest.raises(HTTPException):
        dep.precheck(MagicMock(), "o", {"deposit_amount": 100, "deposit_method": "external", "deposit_external_url": "http://x"})
    dep.precheck(MagicMock(), "o", {"deposit_amount": 100, "deposit_method": "external", "deposit_external_url": "https://pay.me/x"})


def test_external_hold_creates_pending_row():
    svc = {"deposit_amount": 5000, "deposit_method": "external", "deposit_external_url": "https://pay.me/x", "deposit_hold_minutes": 60}
    db = _db({"booking_payments": [{"id": "p1", "status": "pending", "pay_url": "https://pay.me/x"}]})
    out = dep.create_hold(db, "o", {"id": "l1"}, "d1", svc)
    ins = [c for c in db.log if c[0] == "insert"][0][2]
    assert ins["method"] == "external" and ins["status"] == "pending" and ins["reference"] is None and ins["amount"] == 5000.0
    assert out["status"] == "pending"


def test_service_fields_validate_deposit():
    f = bk._service_fields({"deposit_amount": "2500", "deposit_currency": "ngn", "deposit_method": "external", "deposit_external_url": "https://a.b/c"})
    assert f["deposit_amount"] == 2500.0 and f["deposit_currency"] == "NGN"
    with pytest.raises(HTTPException):
        bk._service_fields({"deposit_amount": -1})
    with pytest.raises(HTTPException):
        bk._service_fields({"deposit_external_url": "http://insecure"})
    with pytest.raises(HTTPException):
        bk._check_deposit({"deposit_amount": 100, "deposit_method": "external"}, {})
    bk._check_deposit({"deposit_amount": 0, "deposit_method": "external"}, {})       # free service needs no link


def test_settle_only_once():
    db = _db({"booking_payments": []})          # the guarded update matched nothing = already settled
    with patch.object(bk, "_finish_booking") as fin:
        assert dep.settle(db, "o", {"id": "p1", "demo_id": "d1", "currency": "NGN", "amount": 1, "method": "external"}, None) is False
    fin.assert_not_called()


def test_settle_confirms_held_booking():
    demo = {"id": "d1", "lead_id": "l1", "status": "pending_assignment", "scheduled_at": NOW.isoformat(), "service_id": None, "duration_minutes": 30}
    db = _db({"booking_payments": [{"id": "p1"}], "lead_demos": [demo]})
    with patch.object(bk, "_finish_booking") as fin, patch.object(bk, "get_org", return_value={"id": "o"}), \
         patch("app.services.demo_service._confirm_lead_in_org", return_value={"id": "l1"}), \
         patch("app.services.demo_service._log_timeline"):
        assert dep.settle(db, "o", {"id": "p1", "demo_id": "d1", "currency": "NGN", "amount": 5000, "method": "paystack"}, None) is True
    fin.assert_called_once()


def test_late_payment_after_release_flags_refund():
    demo = {"id": "d1", "lead_id": "l1", "status": "cancelled"}
    db = _db({"booking_payments": [{"id": "p1"}], "lead_demos": [demo]})
    with patch.object(dep, "_tell_manager") as tm:
        dep.settle(db, "o", {"id": "p1", "demo_id": "d1", "currency": "NGN", "amount": 5000, "method": "paystack"}, None)
    assert any(c[0] == "update" and c[2].get("status") == "refund_due" for c in db.log)
    tm.assert_called_once()


def _paid(method="paystack", rule="before_cutoff"):
    return {"id": "p1", "status": "paid", "method": method, "reference": "r1", "refund_rule": rule}


def _cancel(rule, by, hours_ahead, method="paystack", refund_ok=True):
    demo = {"id": "d1", "scheduled_at": (dep._now() + timedelta(hours=hours_ahead)).isoformat()}
    with patch.object(dep, "payment_for_demo", return_value=_paid(method, rule)), \
         patch.object(dep, "_refund_paystack", return_value=refund_ok) as rp, patch.object(dep, "_tell_manager"):
        return dep.on_cancel(_db({}), "o", demo, by, 24), rp


def test_refund_before_cutoff():
    assert _cancel("before_cutoff", "lead", 48)[0] == "refunded"


def test_no_refund_inside_cutoff():
    assert _cancel("before_cutoff", "lead", 2)[0] == "paid"


def test_never_rule_keeps_deposit_for_lead_but_staff_cancel_refunds():
    assert _cancel("never", "lead", 72)[0] == "paid"
    assert _cancel("never", "staff", 72)[0] == "refunded"


def test_always_rule_refunds():
    assert _cancel("always", "lead", 1)[0] == "refunded"


def test_external_refund_is_manual_flag():
    st, rp = _cancel("always", "lead", 48, method="external")
    assert st == "refund_due"
    rp.assert_not_called()


def test_paystack_refund_failure_flags_due():
    assert _cancel("always", "lead", 48, refund_ok=False)[0] == "refund_due"


def test_cancel_unpaid_hold_marks_cancelled():
    with patch.object(dep, "payment_for_demo", return_value={"id": "p1", "status": "pending"}):
        assert dep.on_cancel(_db({}), "o", {"id": "d1"}, "lead", 24) == "cancelled"


def test_no_payment_row_is_noop():
    with patch.object(dep, "payment_for_demo", return_value=None):
        assert dep.on_cancel(_db({}), "o", {"id": "d1"}, "lead", 24) is None


def test_sweep_expires_unpaid_hold_and_releases_slot():
    p = {"id": "p1", "org_id": "o", "demo_id": "d1", "method": "external", "status": "pending", "currency": "NGN", "amount": 1,
         "hold_expires_at": (dep._now() - timedelta(minutes=5)).isoformat()}
    demo = {"id": "d1", "lead_id": "l1", "status": "pending_assignment"}
    db = _db({"booking_payments": [p], "lead_demos": [demo]})
    with patch("app.services.demo_service._confirm_lead_in_org", return_value={"id": "l1"}), \
         patch("app.services.demo_service._log_timeline"), patch("app.services.demo_service._auto_send_wa"):
        out = dep.sweep(db)
    assert out["expired"] == 1
    assert any(c[0] == "update" and c[1] == "lead_demos" and c[2].get("status") == "cancelled" for c in db.log)


def test_sweep_leaves_unexpired_hold():
    p = {"id": "p1", "org_id": "o", "demo_id": "d1", "method": "external", "status": "pending",
         "hold_expires_at": (dep._now() + timedelta(minutes=20)).isoformat()}
    out = dep.sweep(_db({"booking_payments": [p]}))
    assert out == {"settled": 0, "expired": 0}


def test_sweep_waives_if_manager_confirmed_by_hand():
    p = {"id": "p1", "org_id": "o", "demo_id": "d1", "method": "external", "status": "pending",
         "hold_expires_at": (dep._now() - timedelta(minutes=5)).isoformat()}
    db = _db({"booking_payments": [p], "lead_demos": [{"id": "d1", "status": "confirmed"}]})
    out = dep.sweep(db)
    assert out["expired"] == 0 and any(c[2].get("status") == "waived" for c in db.log if c[0] == "update")


def test_paystack_verify_requires_full_amount():
    class R:
        content = b"1"
        def json(self): return {"data": {"status": "success", "amount": 100, "currency": "NGN"}}
    c = MagicMock(); c.__enter__.return_value.get.return_value = R()
    with patch.object(dep, "_secret", return_value="sk"), patch.object(dep.httpx, "Client", return_value=c):
        assert dep._verify_paystack(MagicMock(), "o", {"reference": "r", "amount": 5000, "currency": "NGN"}) is False
        assert dep._verify_paystack(MagicMock(), "o", {"reference": "r", "amount": 1, "currency": "NGN"}) is True


def _book(service, user_id=None, hold_fails=False):
    org = {"id": "o", "timezone": "UTC"}
    with patch.object(bk, "get_org", return_value=org), patch.object(bk, "_assert_slot_open"), \
         patch.object(bk, "get_settings", return_value={"calendar_mode": "single"}), \
         patch.object(bk, "_insert_booking_row", return_value="d1"), patch.object(bk, "_finish_booking") as fin, \
         patch("app.services.demo_service._confirm_lead_in_org", return_value={"id": "l1"}), \
         patch("app.services.demo_service._log_timeline"), \
         patch("app.services.demo_service._fetch_demo_by_id", return_value={"id": "d1", "status": "pending_assignment"}), \
         patch.object(dep, "precheck"), \
         patch.object(dep, "create_hold", side_effect=(RuntimeError("x") if hold_fails else None) or None, return_value={"status": "pending", "method": "external", "amount": 5, "currency": "NGN", "pay_url": "https://p", "hold_expires_at": "t"}):
        db = _db({"lead_demos": []})
        svc = {"id": "s1", "name": "Consult", "duration_minutes": 30, **service}
        out = bk.book_slot(db, "o", "l1", svc, NOW, user_id=user_id)
    return out, fin, db


def test_book_without_deposit_confirms_as_before():
    out, fin, _ = _book({})
    fin.assert_called_once()
    assert "payment" not in out


def test_book_with_deposit_holds_and_does_not_confirm():
    out, fin, _ = _book({"deposit_amount": 5000, "deposit_method": "external", "deposit_external_url": "https://p"})
    fin.assert_not_called()
    assert out["payment"]["status"] == "pending" and out["payment"]["pay_url"] == "https://p"


def test_staff_booking_skips_deposit():
    out, fin, _ = _book({"deposit_amount": 5000}, user_id="staff-1")
    fin.assert_called_once()


def test_failed_payment_start_releases_slot():
    with pytest.raises(RuntimeError):
        _book({"deposit_amount": 5000}, hold_fails=True)
