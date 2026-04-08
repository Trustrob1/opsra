"""
tests/integration/test_subscription_routes.py
Integration tests for Module 04 — Renewal & Upsell Engine routes.

Patterns used:
  - Pattern 3: always override get_supabase, even for 422 tests
  - Pattern 4: restore class fixture override, never clear all
  - Pattern 6: assert only status_code on error paths — not resp.json()["success"]
  - Pattern 24: all IDs are valid UUID format
  - Pattern 28: routes use get_current_org — mock must return dict with org_id + id + role
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app

# ---------------------------------------------------------------------------
# Test constants — all valid UUIDs (Pattern 24)
# ---------------------------------------------------------------------------
ORG_ID      = "00000000-0000-0000-0000-000000000001"
USER_ID     = "00000000-0000-0000-0000-000000000002"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000003"
SUB_ID      = "00000000-0000-0000-0000-000000000004"
PAYMENT_ID  = "00000000-0000-0000-0000-000000000005"

ACTIVE_SUB = {
    "id": SUB_ID,
    "org_id": ORG_ID,
    "customer_id": CUSTOMER_ID,
    "plan_name": "Starter Plan",
    "plan_tier": "starter",
    "amount": 150000.0,
    "currency": "NGN",
    "billing_cycle": "monthly",
    "status": "active",
    "current_period_start": "2026-03-01",
    "current_period_end": "2026-04-01",
    "grace_period_ends_at": None,
    "created_at": "2026-03-01T00:00:00+00:00",
}

# ---------------------------------------------------------------------------
# Auth stubs — Pattern 28: get_current_org returns dict
# ---------------------------------------------------------------------------
def _org_member():
    return {"id": USER_ID, "org_id": ORG_ID, "roles": {"template": "support_agent", "permissions": {}}}

def _org_admin():
    return {"id": USER_ID, "org_id": ORG_ID, "roles": {"template": "ops_manager", "permissions": {}}}

def _org_owner():
    return {"id": USER_ID, "org_id": ORG_ID, "roles": {"template": "owner", "permissions": {"is_admin": True}}}


def _make_chain(data=None, count=0):
    chain = MagicMock()
    chain.select.return_value   = chain
    chain.eq.return_value       = chain
    chain.neq.return_value      = chain
    chain.is_.return_value      = chain
    chain.gte.return_value      = chain
    chain.lte.return_value      = chain
    chain.order.return_value    = chain
    chain.range.return_value    = chain
    chain.limit.return_value    = chain
    chain.maybe_single.return_value = chain
    chain.update.return_value   = chain
    chain.insert.return_value   = chain
    chain.execute.return_value  = MagicMock(data=data, count=count)
    return chain


# ===========================================================================
# TestListSubscriptionsRoute
# ===========================================================================
class TestListSubscriptionsRoute:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        self.mock_db.table.return_value = _make_chain(data=[ACTIVE_SUB], count=1)
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _org_member
        self.client = TestClient(app)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_paginated_envelope(self):
        resp = self.client.get("/api/v1/subscriptions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_accepts_status_filter(self):
        resp = self.client.get("/api/v1/subscriptions?status=trial")
        assert resp.status_code == 200

    def test_accepts_plan_tier_filter(self):
        resp = self.client.get("/api/v1/subscriptions?plan_tier=pro")
        assert resp.status_code == 200

    def test_accepts_renewal_window_filter(self):
        resp = self.client.get("/api/v1/subscriptions?renewal_window_days=30")
        assert resp.status_code == 200

    def test_page_size_above_500_returns_422(self):
        """Pattern 3 — even 422 tests must have get_supabase overridden."""
        resp = self.client.get("/api/v1/subscriptions?page_size=501")
        assert resp.status_code == 422

   


# ===========================================================================
# TestGetSubscriptionRoute
# ===========================================================================
class TestGetSubscriptionRoute:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()

        def tbl(name):
            if name == "subscriptions":
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                return _make_chain(data=[])
            return _make_chain(data=None)

        self.mock_db.table.side_effect = tbl
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _org_member
        self.client = TestClient(app)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_subscription_data(self):
        resp = self.client.get(f"/api/v1/subscriptions/{SUB_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == SUB_ID

    def test_returns_404_for_unknown_subscription(self):
        self.mock_db.table.side_effect = None
        self.mock_db.table.return_value = _make_chain(data=None)
        resp = self.client.get(f"/api/v1/subscriptions/{SUB_ID}")
        assert resp.status_code == 404

    def test_response_includes_payments_key(self):
        resp = self.client.get(f"/api/v1/subscriptions/{SUB_ID}")
        assert resp.status_code == 200
        assert "payments" in resp.json()["data"]


# ===========================================================================
# TestUpdateSubscriptionRoute
# ===========================================================================
class TestUpdateSubscriptionRoute:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        calls = {"n": 0}

        def tbl(name):
            if name == "subscriptions":
                calls["n"] += 1
                return _make_chain(data=[ACTIVE_SUB])
            return _make_chain(data=None)

        self.mock_db.table.side_effect = tbl
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _org_admin
        self.client = TestClient(app)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_admin_can_update_plan_name(self):
        resp = self.client.patch(
            f"/api/v1/subscriptions/{SUB_ID}",
            json={"plan_name": "Pro Plan"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_non_admin_gets_403(self):
        app.dependency_overrides[get_current_org] = _org_member
        resp = self.client.patch(
            f"/api/v1/subscriptions/{SUB_ID}",
            json={"plan_name": "Pro Plan"},
        )
        assert resp.status_code == 403
        app.dependency_overrides[get_current_org] = _org_admin

    def test_invalid_plan_tier_returns_422(self):
        resp = self.client.patch(
            f"/api/v1/subscriptions/{SUB_ID}",
            json={"plan_tier": "diamond"},
        )
        assert resp.status_code == 422

    def test_invalid_billing_cycle_returns_422(self):
        resp = self.client.patch(
            f"/api/v1/subscriptions/{SUB_ID}",
            json={"billing_cycle": "weekly"},
        )
        assert resp.status_code == 422


# ===========================================================================
# TestConfirmPaymentRoute
# ===========================================================================
class TestConfirmPaymentRoute:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        sub_calls = {"n": 0}
        pay_calls = {"n": 0}

        def tbl(name):
            if name == "subscriptions":
                sub_calls["n"] += 1
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                pay_calls["n"] += 1
                if pay_calls["n"] == 1:
                    return _make_chain(data=[])          # no duplicate
                return _make_chain(data=[{"id": PAYMENT_ID}])
            return _make_chain(data=None)

        self.mock_db.table.side_effect = tbl
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _org_member
        self.client = TestClient(app)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def _valid_payload(self, reference="TXN_001"):
        return {
            "amount": 150000,
            "payment_date": "2026-04-01",
            "payment_channel": "bank_transfer",
            "reference": reference,
        }

    def test_confirms_payment_returns_200(self):
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/confirm-payment",
            json=self._valid_payload(),
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_missing_amount_returns_422(self):
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/confirm-payment",
            json={"payment_date": "2026-04-01", "payment_channel": "cash"},
        )
        assert resp.status_code == 422

    def test_invalid_payment_channel_returns_422(self):
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/confirm-payment",
            json={
                "amount": 150000,
                "payment_date": "2026-04-01",
                "payment_channel": "cheque",
            },
        )
        assert resp.status_code == 422

    def test_duplicate_reference_returns_409(self):
        # Override DB so payments duplicate check returns existing row
        dup_db = MagicMock()
        sub_c = {"n": 0}
        pay_c = {"n": 0}

        def tbl(name):
            if name == "subscriptions":
                sub_c["n"] += 1
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                pay_c["n"] += 1
                return _make_chain(data=[{"id": PAYMENT_ID}])   # always duplicate
            return _make_chain(data=None)

        dup_db.table.side_effect = tbl
        app.dependency_overrides[get_supabase] = lambda: dup_db
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/confirm-payment",
            json=self._valid_payload(reference="DUPE"),
        )
        assert resp.status_code == 409
        app.dependency_overrides[get_supabase] = lambda: self.mock_db

    def test_subscription_not_found_returns_404(self):
        not_found_db = MagicMock()
        not_found_db.table.return_value = _make_chain(data=None)
        app.dependency_overrides[get_supabase] = lambda: not_found_db
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/confirm-payment",
            json=self._valid_payload(),
        )
        assert resp.status_code == 404
        app.dependency_overrides[get_supabase] = lambda: self.mock_db


# ===========================================================================
# TestBulkConfirmRoute
# ===========================================================================
class TestBulkConfirmRoute:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        self.mock_db.table.return_value = _make_chain(data=[ACTIVE_SUB], count=1)
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _org_member
        self.client = TestClient(app)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_csv_upload_returns_202_with_job_id(self):
        csv_content = (
            b"subscription_id,amount,payment_date,payment_channel\n"
            b"00000000-0000-0000-0000-000000000004,150000,2026-04-01,bank_transfer\n"
        )
        resp = self.client.post(
            "/api/v1/subscriptions/bulk-confirm",
            files={"file": ("payments.csv", csv_content, "text/csv")},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["success"] is True
        assert "job_id" in body["data"]
        assert "total_rows" in body["data"]

    def test_unsupported_mime_type_returns_422(self):
        resp = self.client.post(
            "/api/v1/subscriptions/bulk-confirm",
            files={"file": ("payments.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert resp.status_code == 422

    def test_empty_csv_returns_202(self):
        resp = self.client.post(
            "/api/v1/subscriptions/bulk-confirm",
            files={"file": ("empty.csv", b"subscription_id,amount\n", "text/csv")},
        )
        assert resp.status_code == 202


# ===========================================================================
# TestBulkConfirmJobPollRoute
# ===========================================================================
class TestBulkConfirmJobPollRoute:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()

        # bulk_confirm_jobs needs to be stateful:
        #   create_bulk_confirm_job  → INSERT  (captures the row)
        #   get_bulk_confirm_job     → SELECT  (returns the captured row)
        #   _update_bulk_job         → UPDATE  (no-op in mock)
        # All other tables use the generic empty chain.
        stored: dict = {}   # job_id → row dict

        bj_chain = MagicMock()
        bj_chain.select.return_value      = bj_chain
        bj_chain.eq.return_value          = bj_chain
        bj_chain.maybe_single.return_value = bj_chain
        bj_chain.update.return_value      = bj_chain

        def _bj_insert(row):
            stored[row["job_id"]] = row   # remember the inserted job
            return bj_chain
        bj_chain.insert.side_effect = _bj_insert

        def _bj_execute():
            # SELECT path: return the most recently stored row (or None)
            row = list(stored.values())[-1] if stored else None
            return MagicMock(data=row)
        bj_chain.execute.side_effect = _bj_execute

        def tbl(name):
            if name == "bulk_confirm_jobs":
                return bj_chain
            return _make_chain(data=[], count=0)

        self.mock_db.table.side_effect    = tbl
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _org_member
        self.client = TestClient(app)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_polling_known_job_returns_200(self):
        # Create a job first via the upload endpoint
        csv_content = b"subscription_id,amount,payment_date,payment_channel\n"
        create_resp = self.client.post(
            "/api/v1/subscriptions/bulk-confirm",
            files={"file": ("p.csv", csv_content, "text/csv")},
        )
        assert create_resp.status_code == 202
        job_id = create_resp.json()["data"]["job_id"]

        poll_resp = self.client.get(
            f"/api/v1/subscriptions/bulk-confirm/{job_id}"
        )
        assert poll_resp.status_code == 200
        assert poll_resp.json()["data"]["job_id"] == job_id

    def test_polling_unknown_job_returns_404(self):
        resp = self.client.get(
            "/api/v1/subscriptions/bulk-confirm/nonexistent-job"
        )
        assert resp.status_code == 404

    def test_bulk_confirm_route_takes_priority_over_subscription_id_route(self):
        """
        Verify 'bulk-confirm' is not consumed as a subscription_id UUID.
        GET /subscriptions/bulk-confirm/<job_id> must route to the job poll handler,
        not the get_subscription handler.
        """
        csv_content = b"subscription_id,amount,payment_date,payment_channel\n"
        create_resp = self.client.post(
            "/api/v1/subscriptions/bulk-confirm",
            files={"file": ("p.csv", csv_content, "text/csv")},
        )
        job_id = create_resp.json()["data"]["job_id"]
        poll_resp = self.client.get(f"/api/v1/subscriptions/bulk-confirm/{job_id}")
        # If routing was wrong this would 404 from subscription lookup
        assert poll_resp.status_code == 200


# ===========================================================================
# TestCancelSubscriptionRoute
# ===========================================================================
class TestCancelSubscriptionRoute:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        calls = {"n": 0}

        def tbl(name):
            if name == "subscriptions":
                calls["n"] += 1
                return _make_chain(data=[ACTIVE_SUB])
            return _make_chain(data=None)

        self.mock_db.table.side_effect = tbl
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _org_owner
        self.client = TestClient(app)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_owner_can_cancel_subscription(self):
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/cancel",
            json={"reason": "too_expensive"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_non_owner_gets_403(self):
        app.dependency_overrides[get_current_org] = _org_admin
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/cancel",
            json={"reason": "too_expensive"},
        )
        assert resp.status_code == 403
        app.dependency_overrides[get_current_org] = _org_owner

    def test_member_gets_403(self):
        app.dependency_overrides[get_current_org] = _org_member
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/cancel",
            json={"reason": "too_expensive"},
        )
        assert resp.status_code == 403
        app.dependency_overrides[get_current_org] = _org_owner

    def test_invalid_reason_returns_422(self):
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/cancel",
            json={"reason": "not_a_valid_reason"},
        )
        assert resp.status_code == 422

    def test_missing_reason_returns_422(self):
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/cancel",
            json={},
        )
        assert resp.status_code == 422

    def test_subscription_not_found_returns_404(self):
        not_found_db = MagicMock()
        not_found_db.table.return_value = _make_chain(data=None)
        app.dependency_overrides[get_supabase] = lambda: not_found_db
        resp = self.client.post(
            f"/api/v1/subscriptions/{SUB_ID}/cancel",
            json={"reason": "business_closed"},
        )
        assert resp.status_code == 404
        app.dependency_overrides[get_supabase] = lambda: self.mock_db