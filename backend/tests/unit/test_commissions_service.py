"""
backend/tests/unit/test_commissions_service.py
Unit tests for commissions_service.py — Phase 9C.

Classes:
  TestAutoCreateCommission  (4 tests)
  TestListCommissions       (5 tests)
  TestGetCommissionSummary  (4 tests)
  TestUpdateCommission      (5 tests)

Total: 18 tests

Patterns:
  Pattern 8  — separate mock chains per table
  Pattern 24 — valid UUID constants
  Pattern 37 — role fixtures use org["roles"]["template"]
"""
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.services.commissions_service import (
    auto_create_commission,
    list_commissions,
    get_commission_summary,
    update_commission,
)

# ── UUID constants (Pattern 24) ───────────────────────────────────────────────
ORG_ID        = "00000000-0000-0000-0000-000000000001"
AFFILIATE_ID  = "00000000-0000-0000-0000-000000000002"
MANAGER_ID    = "00000000-0000-0000-0000-000000000003"
LEAD_ID       = "00000000-0000-0000-0000-000000000004"
CUSTOMER_ID   = "00000000-0000-0000-0000-000000000005"
COMMISSION_ID = "00000000-0000-0000-0000-000000000006"


def _affiliate_org():
    return {
        "id":     AFFILIATE_ID,
        "org_id": ORG_ID,
        "roles":  {"template": "affiliate_partner", "permissions": {}},
    }


def _manager_org():
    return {
        "id":     MANAGER_ID,
        "org_id": ORG_ID,
        "roles":  {"template": "owner", "permissions": {"is_admin": True}},
    }


def _sample_commission(affiliate_id=None, status="pending"):
    return {
        "id":                COMMISSION_ID,
        "org_id":            ORG_ID,
        "affiliate_user_id": affiliate_id or AFFILIATE_ID,
        "event_type":        "lead_converted",
        "amount_ngn":        0,
        "status":            status,
        "created_at":        "2026-04-06T10:00:00Z",
    }


def _list_db(rows):
    db = MagicMock()
    db.table.return_value.select.return_value \
        .eq.return_value.order.return_value \
        .execute.return_value.data = rows
    return db


# ============================================================
# TestAutoCreateCommission
# ============================================================

class TestAutoCreateCommission:
    def test_inserts_commission_row(self):
        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value.data = [
            _sample_commission()
        ]
        auto_create_commission(
            db=db, org_id=ORG_ID, affiliate_user_id=AFFILIATE_ID,
            event_type="lead_converted", lead_id=LEAD_ID, customer_id=CUSTOMER_ID,
        )
        db.table.assert_called_with("commissions")

    def test_silent_noop_when_affiliate_user_id_blank(self):
        db = MagicMock()
        auto_create_commission(db=db, org_id=ORG_ID, affiliate_user_id="",
                               event_type="lead_converted")
        db.table.assert_not_called()

    def test_silent_noop_when_org_id_blank(self):
        db = MagicMock()
        auto_create_commission(db=db, org_id="", affiliate_user_id=AFFILIATE_ID,
                               event_type="lead_converted")
        db.table.assert_not_called()

    def test_swallows_db_exception(self):
        db = MagicMock()
        db.table.side_effect = Exception("DB error")
        # S14: must not raise
        auto_create_commission(
            db=db, org_id=ORG_ID, affiliate_user_id=AFFILIATE_ID,
            event_type="lead_converted",
        )


# ============================================================
# TestListCommissions
# ============================================================

class TestListCommissions:
    def test_manager_sees_all_commissions(self):
        rows = [_sample_commission(AFFILIATE_ID), _sample_commission("other-affiliate")]
        db   = _list_db(rows)
        result = list_commissions(org=_manager_org(), db=db)
        assert result["total"] == 2

    def test_affiliate_sees_only_own(self):
        rows = [
            _sample_commission(AFFILIATE_ID),
            _sample_commission("other-affiliate"),
        ]
        db   = _list_db(rows)
        result = list_commissions(org=_affiliate_org(), db=db)
        assert result["total"] == 1
        assert result["items"][0]["affiliate_user_id"] == AFFILIATE_ID

    def test_manager_can_filter_by_affiliate(self):
        rows = [
            _sample_commission(AFFILIATE_ID),
            _sample_commission("other-affiliate"),
        ]
        db   = _list_db(rows)
        result = list_commissions(
            org=_manager_org(), db=db, affiliate_user_id=AFFILIATE_ID
        )
        assert result["total"] == 1

    def test_status_filter_applied(self):
        rows = [
            _sample_commission(AFFILIATE_ID, status="pending"),
            _sample_commission(AFFILIATE_ID, status="approved"),
        ]
        db   = _list_db(rows)
        result = list_commissions(
            org=_manager_org(), db=db, comm_status="approved"
        )
        assert result["total"] == 1
        assert result["items"][0]["status"] == "approved"

    def test_pagination(self):
        rows = [_sample_commission(AFFILIATE_ID) for _ in range(25)]
        db   = _list_db(rows)
        result = list_commissions(
            org=_manager_org(), db=db, page=2, page_size=10
        )
        assert len(result["items"]) == 10
        assert result["has_more"] is True


# ============================================================
# TestGetCommissionSummary
# ============================================================

class TestGetCommissionSummary:
    def _make_db(self, rows):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value.data = rows
        return db

    def test_manager_sees_org_totals(self):
        rows = [
            {"affiliate_user_id": AFFILIATE_ID, "status": "pending",  "amount_ngn": 0},
            {"affiliate_user_id": AFFILIATE_ID, "status": "approved", "amount_ngn": 50000},
            {"affiliate_user_id": "other",       "status": "paid",     "amount_ngn": 20000},
        ]
        db = self._make_db(rows)
        result = get_commission_summary(org=_manager_org(), db=db)
        assert result["total_count"] == 3
        assert result["by_status"]["approved"]["count"] == 1

    def test_affiliate_sees_own_totals_only(self):
        rows = [
            {"affiliate_user_id": AFFILIATE_ID, "status": "pending",  "amount_ngn": 0},
            {"affiliate_user_id": "other",       "status": "approved", "amount_ngn": 50000},
        ]
        db = self._make_db(rows)
        result = get_commission_summary(org=_affiliate_org(), db=db)
        assert result["total_count"] == 1
        assert result["by_status"]["approved"]["count"] == 0

    def test_empty_returns_zeros(self):
        db = self._make_db([])
        result = get_commission_summary(org=_affiliate_org(), db=db)
        assert result["total_count"] == 0
        assert result["total_amount_ngn"] == 0

    def test_amount_totals_summed_correctly(self):
        rows = [
            {"affiliate_user_id": AFFILIATE_ID, "status": "approved", "amount_ngn": 30000},
            {"affiliate_user_id": AFFILIATE_ID, "status": "approved", "amount_ngn": 20000},
        ]
        db = self._make_db(rows)
        result = get_commission_summary(org=_affiliate_org(), db=db)
        assert result["by_status"]["approved"]["amount_ngn"] == 50000


# ============================================================
# TestUpdateCommission
# ============================================================

class TestUpdateCommission:
    def _make_db(self, found=True, current_status="pending"):
        db       = MagicMock()
        existing = _sample_commission(AFFILIATE_ID, status=current_status) if found else None
        tracker  = {"n": 0}
        chain    = MagicMock()

        chain.select.return_value.eq.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = existing
        chain.update.return_value.eq.return_value.eq.return_value \
            .execute.return_value.data = [{**existing, "status": "approved"}] if existing else []

        def _tbl(name):
            if name == "commissions":
                return chain
            return MagicMock()

        db.table.side_effect = _tbl
        return db

    def test_manager_can_set_amount(self):
        db = self._make_db()
        result = update_commission(
            commission_id=COMMISSION_ID,
            org=_manager_org(),
            db=db,
            amount_ngn=50000,
        )
        assert result is not None

    def test_manager_can_approve(self):
        db = self._make_db()
        result = update_commission(
            commission_id=COMMISSION_ID,
            org=_manager_org(),
            db=db,
            comm_status="approved",
        )
        assert result is not None

    def test_affiliate_cannot_update(self):
        db = self._make_db()
        with pytest.raises(HTTPException) as exc_info:
            update_commission(
                commission_id=COMMISSION_ID,
                org=_affiliate_org(),
                db=db,
                comm_status="approved",
            )
        assert exc_info.value.status_code == 403

    def test_raises_404_when_not_found(self):
        db = self._make_db(found=False)
        with pytest.raises(HTTPException) as exc_info:
            update_commission(
                commission_id=COMMISSION_ID,
                org=_manager_org(),
                db=db,
                comm_status="approved",
            )
        assert exc_info.value.status_code == 404

    def test_raises_422_for_invalid_status(self):
        db = self._make_db()
        with pytest.raises(HTTPException) as exc_info:
            update_commission(
                commission_id=COMMISSION_ID,
                org=_manager_org(),
                db=db,
                comm_status="refunded",  # not a valid status
            )
        assert exc_info.value.status_code == 422
