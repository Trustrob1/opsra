"""
tests/integration/test_erasure_route.py
----------------------------------------
9E-I — Integration tests for the right-to-erasure endpoint.

Route: DELETE /api/v1/admin/contacts/{phone_number}/erase

Coverage:
  - Successful erasure — all records removed, erasure_log written
  - Non-owner role → 403
  - Missing / false confirmation param → 422
  - org_id scoping — cannot erase contacts from other orgs

Fix: FastAPI dependency injection requires app.dependency_overrides,
not unittest.mock.patch(), to override Depends() parameters.
"""
from __future__ import annotations

import ast
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_org
from app.routers.erasure import router


# T3: self-validate
with open(__file__) as _f:
    ast.parse(_f.read())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture
def owner_org():
    return {
        "id":     "user-owner-1",
        "org_id": "org-1",
        "role":   {"name": "owner"},
    }


@pytest.fixture
def non_owner_org():
    return {
        "id":     "user-staff-1",
        "org_id": "org-1",
        "role":   {"name": "sales_rep"},
    }


def _make_db():
    db = MagicMock()
    m = MagicMock()
    m.eq.return_value = m
    m.or_.return_value = m
    m.execute.return_value.data = []
    m.insert.return_value.execute.return_value.data = [{}]
    db.table.return_value = m
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEraseContactRoute:

    def test_successful_erasure_returns_erased_true(self, app, owner_org):
        app.dependency_overrides[get_current_org] = lambda: owner_org
        db = _make_db()

        with patch("app.routers.erasure.get_supabase", return_value=db):
            with patch("app.routers.erasure.write_audit_log"):
                resp = TestClient(app).request(
                    "DELETE",
                    "/api/v1/admin/contacts/%2B2348001234567/erase",
                    json={"confirmation": True},
                )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["erased"] is True
        assert isinstance(body["records_removed"], int)

    def test_erasure_writes_erasure_log(self, app, owner_org):
        app.dependency_overrides[get_current_org] = lambda: owner_org
        inserts = []

        db = MagicMock()

        def table_side(name):
            m = MagicMock()
            m.eq.return_value = m
            m.or_.return_value = m
            m.execute.return_value.data = []

            def capture_insert(row):
                inserts.append((name, row))
                ins_m = MagicMock()
                ins_m.execute.return_value.data = [{}]
                return ins_m

            m.insert.side_effect = capture_insert
            return m

        db.table.side_effect = table_side

        with patch("app.routers.erasure.get_supabase", return_value=db):
            with patch("app.routers.erasure.write_audit_log"):
                resp = TestClient(app).request(
                    "DELETE",
                    "/api/v1/admin/contacts/%2B2348001234567/erase",
                    json={"confirmation": True},
                )

        assert resp.status_code == 200

        log_inserts = [(n, row) for n, row in inserts if n == "erasure_log"]
        assert log_inserts, "erasure_log must be written"
        _, log_row = log_inserts[0]
        assert len(log_row["phone_hash"]) == 64, "phone_hash must be 64-char SHA-256 hex"
        assert "+234" not in log_row["phone_hash"], "Raw phone must not appear in phone_hash"
        assert log_row["org_id"] == owner_org["org_id"]
        assert log_row["requested_by"] == owner_org["id"]

    def test_non_owner_role_returns_403(self, app, non_owner_org):
        app.dependency_overrides[get_current_org] = lambda: non_owner_org

        resp = TestClient(app).request(
            "DELETE",
            "/api/v1/admin/contacts/%2B2348001234567/erase",
            json={"confirmation": True},
        )

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"

    def test_missing_confirmation_returns_422(self, app, owner_org):
        app.dependency_overrides[get_current_org] = lambda: owner_org

        resp = TestClient(app).request(
            "DELETE",
            "/api/v1/admin/contacts/%2B2348001234567/erase",
            json={},
        )

        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

    def test_false_confirmation_returns_422(self, app, owner_org):
        app.dependency_overrides[get_current_org] = lambda: owner_org
        db = _make_db()

        with patch("app.routers.erasure.get_supabase", return_value=db):
            resp = TestClient(app).request(
                "DELETE",
                "/api/v1/admin/contacts/%2B2348001234567/erase",
                json={"confirmation": False},
            )

        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

    def test_org_scoping_all_deletes_use_correct_org_id(self, app, owner_org):
        app.dependency_overrides[get_current_org] = lambda: owner_org
        eq_calls: list = []

        db = MagicMock()

        def table_side(name):
            m = MagicMock()

            def capture_eq(field, value):
                eq_calls.append((name, field, value))
                return m

            m.eq.side_effect = capture_eq
            # delete() must return m so that .delete().eq(...) also hits capture_eq
            m.delete.return_value = m
            m.or_.return_value = m
            m.execute.return_value.data = []
            m.insert.return_value.execute.return_value.data = [{}]
            return m

        db.table.side_effect = table_side

        with patch("app.routers.erasure.get_supabase", return_value=db):
            with patch("app.routers.erasure.write_audit_log"):
                TestClient(app).request(
                    "DELETE",
                    "/api/v1/admin/contacts/%2B2348001234567/erase",
                    json={"confirmation": True},
                )

        org_id_values = [v for (_, f, v) in eq_calls if f == "org_id"]
        assert org_id_values, "At least one org_id filter must be applied"
        assert all(v == "org-1" for v in org_id_values), \
            f"All org_id filters must be 'org-1', got: {org_id_values}"
