"""
tests/integration/test_demo_queue_routes.py
M01-7a — Integration tests for:
  GET /api/v1/leads/demos/pending
  GET /api/v1/leads/attention-summary
  GET /api/v1/customers/attention-summary

Pattern 24: all UUIDs valid format.
Pattern 32: override AND pop dependency overrides in teardown — use direct imports.
Pattern 42: patch at app.services.demo_service (where functions are DEFINED).
            Routers import demo_service lazily inside function bodies, so
            app.routers.leads.demo_service does NOT exist as a module attribute.
            Always patch the source module, not the importer.
Pattern 44: override get_current_org directly.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from uuid import uuid4

ORG_ID  = str(uuid4())
USER_ID = str(uuid4())
LEAD_A  = str(uuid4())
DEMO_1  = str(uuid4())
CUST_A  = str(uuid4())

ADMIN_ORG = {
    "id": USER_ID,
    "org_id": ORG_ID,
    "roles": {"template": "admin"},
    "is_active": True,
}

SCOPED_ORG = {
    "id": USER_ID,
    "org_id": ORG_ID,
    "roles": {"template": "sales_agent"},
    "is_active": True,
}

AFFILIATE_ORG = {
    "id": USER_ID,
    "org_id": ORG_ID,
    "roles": {"template": "affiliate_partner"},
    "is_active": True,
}


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def db_mock():
    return MagicMock()


def _override(app, org_dict, db_mock):
    from app.dependencies import get_current_org
    from app.database import get_supabase
    app.dependency_overrides[get_current_org] = lambda: org_dict
    app.dependency_overrides[get_supabase]    = lambda: db_mock


def _clear(app):
    from app.dependencies import get_current_org
    from app.database import get_supabase
    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/leads/demos/pending
# Pattern 42: patch app.services.demo_service.list_pending_demos_org_wide
# ─────────────────────────────────────────────────────────────────────────────

class TestGetPendingDemosRoute:

    def test_admin_gets_200(self, client, db_mock):
        from app.main import app
        _override(app, ADMIN_ORG, db_mock)
        try:
            with patch(
                'app.services.demo_service.list_pending_demos_org_wide',
                return_value=[],
            ) as mock_fn:
                res = client.get('/api/v1/leads/demos/pending')
            assert res.status_code == 200
            assert res.json()['success'] is True
            mock_fn.assert_called_once()
        finally:
            _clear(app)

    def test_sales_agent_gets_403(self, client, db_mock):
        from app.main import app
        _override(app, SCOPED_ORG, db_mock)
        try:
            res = client.get('/api/v1/leads/demos/pending')
            assert res.status_code == 403
        finally:
            _clear(app)

    def test_affiliate_gets_403(self, client, db_mock):
        from app.main import app
        _override(app, AFFILIATE_ORG, db_mock)
        try:
            res = client.get('/api/v1/leads/demos/pending')
            assert res.status_code == 403
        finally:
            _clear(app)

    def test_returns_demo_list(self, client, db_mock):
        from app.main import app
        _override(app, ADMIN_ORG, db_mock)
        demo_row = {
            "id": DEMO_1,
            "lead_id": LEAD_A,
            "lead_full_name": "Amara Osei",
            "lead_phone": "+2348012345678",
            "lead_preferred_time": "Monday afternoon",
            "medium": "virtual",
            "status": "pending_assignment",
            "created_at": "2026-04-10T10:00:00Z",
        }
        try:
            with patch(
                'app.services.demo_service.list_pending_demos_org_wide',
                return_value=[demo_row],
            ):
                res = client.get('/api/v1/leads/demos/pending')
            assert res.status_code == 200
            data = res.json()['data']
            assert len(data) == 1
            assert data[0]['lead_full_name'] == 'Amara Osei'
        finally:
            _clear(app)

    def test_empty_queue_returns_empty_list(self, client, db_mock):
        from app.main import app
        _override(app, ADMIN_ORG, db_mock)
        try:
            with patch(
                'app.services.demo_service.list_pending_demos_org_wide',
                return_value=[],
            ):
                res = client.get('/api/v1/leads/demos/pending')
            assert res.status_code == 200
            assert res.json()['data'] == []
        finally:
            _clear(app)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/leads/attention-summary
# Pattern 42: patch app.services.demo_service.get_lead_attention_summary
# ─────────────────────────────────────────────────────────────────────────────

class TestGetLeadAttentionSummaryRoute:

    def test_admin_gets_200(self, client, db_mock):
        from app.main import app
        _override(app, ADMIN_ORG, db_mock)
        try:
            with patch(
                'app.services.demo_service.get_lead_attention_summary',
                return_value={},
            ) as mock_fn:
                res = client.get('/api/v1/leads/attention-summary')
            assert res.status_code == 200
            assert res.json()['success'] is True
            mock_fn.assert_called_once()
        finally:
            _clear(app)

    def test_scoped_role_passes_lead_ids(self, client, db_mock):
        from app.main import app
        _override(app, SCOPED_ORG, db_mock)
        db_mock.table.return_value.select.return_value \
            .eq.return_value.eq.return_value \
            .is_.return_value.execute.return_value.data = [{"id": LEAD_A}]
        try:
            with patch(
                'app.services.demo_service.get_lead_attention_summary',
                return_value={},
            ) as mock_fn:
                res = client.get('/api/v1/leads/attention-summary')
            assert res.status_code == 200
            called_kwargs = mock_fn.call_args[1]
            assert called_kwargs['lead_ids'] is not None
            assert LEAD_A in called_kwargs['lead_ids']
        finally:
            _clear(app)

    def test_returns_summary_dict(self, client, db_mock):
        from app.main import app
        _override(app, ADMIN_ORG, db_mock)
        summary = {
            LEAD_A: {
                "has_attention": True,
                "unread_messages": 2,
                "pending_demos": 1,
                "open_tickets": 0,
                "reasons": ["2 unread messages", "Demo awaiting confirmation"],
            }
        }
        try:
            with patch(
                'app.services.demo_service.get_lead_attention_summary',
                return_value=summary,
            ):
                res = client.get('/api/v1/leads/attention-summary')
            assert res.status_code == 200
            data = res.json()['data']
            assert data[LEAD_A]['has_attention'] is True
            assert data[LEAD_A]['unread_messages'] == 2
        finally:
            _clear(app)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/customers/attention-summary
# Pattern 42: patch app.services.demo_service.get_customer_attention_summary
# The customers router imports from demo_service inside the function body, so
# app.routers.customers.get_customer_attention_summary does not exist as an attr.
# ─────────────────────────────────────────────────────────────────────────────

class TestGetCustomerAttentionSummaryRoute:

    def test_admin_gets_200(self, client, db_mock):
        from app.main import app
        _override(app, ADMIN_ORG, db_mock)
        try:
            with patch(
                'app.services.demo_service.get_customer_attention_summary',
                return_value={},
            ) as mock_fn:
                res = client.get('/api/v1/customers/attention-summary')
            assert res.status_code == 200
            assert res.json()['success'] is True
            mock_fn.assert_called_once()
        finally:
            _clear(app)

    def test_scoped_role_passes_customer_ids(self, client, db_mock):
        from app.main import app
        _override(app, SCOPED_ORG, db_mock)
        db_mock.table.return_value.select.return_value \
            .eq.return_value.eq.return_value \
            .is_.return_value.execute.return_value.data = [{"id": CUST_A}]
        try:
            with patch(
                'app.services.demo_service.get_customer_attention_summary',
                return_value={},
            ) as mock_fn:
                res = client.get('/api/v1/customers/attention-summary')
            assert res.status_code == 200
            called_kwargs = mock_fn.call_args[1]
            assert called_kwargs['customer_ids'] is not None
            assert CUST_A in called_kwargs['customer_ids']
        finally:
            _clear(app)

    def test_returns_summary_dict(self, client, db_mock):
        from app.main import app
        _override(app, ADMIN_ORG, db_mock)
        summary = {
            CUST_A: {
                "has_attention": True,
                "unread_messages": 1,
                "open_tickets": 1,
                "churn_risk": "high",
                "reasons": ["1 unread message", "1 open ticket", "High churn risk"],
            }
        }
        try:
            with patch(
                'app.services.demo_service.get_customer_attention_summary',
                return_value=summary,
            ):
                res = client.get('/api/v1/customers/attention-summary')
            assert res.status_code == 200
            data = res.json()['data']
            assert data[CUST_A]['has_attention'] is True
            assert "High churn risk" in data[CUST_A]['reasons']
        finally:
            _clear(app)
