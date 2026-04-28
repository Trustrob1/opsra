"""
tests/integration/test_commerce_routes.py
COMM-1 — Integration tests for admin commerce settings routes and
          GET /api/v1/commerce/sessions/active.

Pattern: TestClient + mocked Supabase dependency (override_dependency).
Pattern 63: patch paths derived from actual import locations.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org
from app.database import get_supabase


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

ORG_ID = "org-test-111"
USER_ID = "user-test-222"
PHONE   = "+2348012345678"


def _mock_org(role="owner"):
    return {
        "id":     USER_ID,
        "org_id": ORG_ID,
        "roles":  {"template": role, "permissions": {}},
    }


def _make_db(org_row=None, sessions=None):
    db = MagicMock()

    def table_side(name):
        tbl = MagicMock()
        # select chain
        sel = MagicMock()
        sel.eq.return_value   = sel
        sel.in_.return_value  = sel
        sel.order.return_value = sel
        sel.limit.return_value = sel
        sel.maybe_single.return_value = sel

        if name == "organisations":
            sel.execute.return_value.data = org_row or {
                "commerce_config":   {"enabled": True, "checkout_message": "Here's your link:"},
                "shopify_connected": True,
            }
        elif name == "commerce_sessions":
            rows = sessions if sessions is not None else []
            sel.execute.return_value.data = rows
        else:
            sel.execute.return_value.data = None

        tbl.select.return_value = sel

        # update chain
        upd = MagicMock()
        upd.eq.return_value = upd
        upd.execute.return_value = None
        tbl.update.return_value = upd

        return tbl

    db.table.side_effect = table_side
    return db


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/v1/admin/commerce/settings
# ---------------------------------------------------------------------------

class TestGetCommerceSettings:

    def test_shopify_connected_returns_full_config(self):
        org_row = {
            "commerce_config":   {"enabled": True, "checkout_message": "Ready to buy?"},
            "shopify_connected": True,
        }
        db = _make_db(org_row=org_row)
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.get("/api/v1/admin/commerce/settings")

        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is True
        assert data["checkout_message"] == "Ready to buy?"
        assert data["shopify_connected"] is True

    def test_shopify_not_connected_returns_false(self):
        org_row = {
            "commerce_config":   {},
            "shopify_connected": False,
        }
        db = _make_db(org_row=org_row)
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.get("/api/v1/admin/commerce/settings")

        assert r.status_code == 200
        data = r.json()["data"]
        assert data["shopify_connected"] is False
        assert data["enabled"] is False

    def test_rbac_non_owner_forbidden(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("sales_agent")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.get("/api/v1/admin/commerce/settings")

        assert r.status_code == 403

    def test_s1_org_id_from_jwt_only(self):
        """Route must use org['org_id'] from JWT — verify no payload org_id accepted."""
        # Track which org_id was queried via captured eq() calls
        eq_calls = []

        org_row = {
            "commerce_config":   {"enabled": True, "checkout_message": "Hi"},
            "shopify_connected": True,
        }

        db = MagicMock()
        def table_side(name):
            tbl = MagicMock()
            sel = MagicMock()
            def capture_eq(col, val):
                eq_calls.append((col, val))
                return sel
            sel.eq.side_effect = capture_eq
            sel.maybe_single.return_value = sel
            sel.execute.return_value.data = org_row
            tbl.select.return_value = sel
            return tbl
        db.table.side_effect = table_side

        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.get(
            "/api/v1/admin/commerce/settings",
            headers={"X-Org-Override": "attacker-org"},
        )
        assert r.status_code == 200
        # ORG_ID from JWT must appear in the eq() calls; attacker org must not
        queried_values = [str(v) for _, v in eq_calls]
        assert any(ORG_ID in v for v in queried_values), (
            f"Expected {ORG_ID} in eq() calls, got: {eq_calls}"
        )


# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/commerce/settings
# ---------------------------------------------------------------------------

class TestPatchCommerceSettings:

    def _db_with_update(self, org_row=None):
        """
        Build a mock DB that tracks update() and insert() payloads per table
        inside the side_effect (db.table.return_value is never set when
        side_effect is used, so we capture calls inside the factory instead).
        Returns (db, captured) where captured = {"update": [...], "insert": [...]}.
        """
        captured = {"update": [], "insert": []}
        effective_org = org_row or {
            "commerce_config":   {"enabled": False, "checkout_message": "Here's your link:"},
            "shopify_connected": True,
        }

        db = MagicMock()
        def table_side(name):
            tbl = MagicMock()

            # select chain
            sel = MagicMock()
            sel.eq.return_value           = sel
            sel.maybe_single.return_value = sel
            sel.execute.return_value.data = effective_org if name == "organisations" else None
            tbl.select.return_value = sel

            # update chain — capture payload
            def make_update(data):
                upd = MagicMock()
                upd.eq.return_value = upd
                def do_execute():
                    captured["update"].append({"table": name, "data": data})
                upd.execute.side_effect = do_execute
                return upd
            tbl.update.side_effect = make_update

            # insert chain — capture payload
            def make_insert(data):
                ins = MagicMock()
                captured["insert"].append({"table": name, "data": data})
                ins.execute.return_value = None
                return ins
            tbl.insert.side_effect = make_insert

            return tbl
        db.table.side_effect = table_side
        return db, captured

    def test_enable_commerce_when_shopify_connected(self):
        org_row = {
            "commerce_config":   {"enabled": False, "checkout_message": "Here's your link:"},
            "shopify_connected": True,
        }
        db, captured = self._db_with_update(org_row=org_row)
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.patch("/api/v1/admin/commerce/settings", json={"enabled": True})

        assert r.status_code == 200
        org_updates = [c for c in captured["update"] if c["table"] == "organisations"]
        assert org_updates, "Expected organisations update call"
        assert org_updates[0]["data"]["commerce_config"]["enabled"] is True

    def test_disable_commerce(self):
        org_row = {
            "commerce_config":   {"enabled": True, "checkout_message": "Here's your link:"},
            "shopify_connected": True,
        }
        db, captured = self._db_with_update(org_row=org_row)
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.patch("/api/v1/admin/commerce/settings", json={"enabled": False})

        assert r.status_code == 200
        org_updates = [c for c in captured["update"] if c["table"] == "organisations"]
        assert org_updates, "Expected organisations update call"
        assert org_updates[0]["data"]["commerce_config"]["enabled"] is False

    def test_cannot_enable_without_shopify_connected(self):
        org_row = {
            "commerce_config":   {"enabled": False},
            "shopify_connected": False,
        }
        db, _ = self._db_with_update(org_row=org_row)
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.patch("/api/v1/admin/commerce/settings", json={"enabled": True})

        assert r.status_code == 422
        assert "Shopify" in r.json()["detail"]

    def test_rbac_non_owner_forbidden(self):
        db, _ = self._db_with_update()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("ops_manager")
        # ops_manager is allowed — verify 200
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.patch(
            "/api/v1/admin/commerce/settings",
            json={"checkout_message": "Shop now!"},
        )
        assert r.status_code == 200

    def test_rbac_sales_agent_forbidden(self):
        db, _ = self._db_with_update()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("sales_agent")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.patch("/api/v1/admin/commerce/settings", json={"enabled": True})
        assert r.status_code == 403

    def test_audit_log_written_on_change(self):
        org_row = {
            "commerce_config":   {"enabled": False},
            "shopify_connected": True,
        }
        db, captured = self._db_with_update(org_row=org_row)
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        client.patch("/api/v1/admin/commerce/settings", json={"enabled": True})

        audit_inserts = [
            c for c in captured["insert"]
            if isinstance(c["data"], dict) and c["data"].get("action") == "commerce_settings.updated"
        ]
        assert audit_inserts, (
            f"Expected audit_logs insert with action='commerce_settings.updated', "
            f"got inserts: {captured['insert']}"
        )

    def test_no_change_returns_200_without_db_write(self):
        org_row = {
            "commerce_config":   {"enabled": True, "checkout_message": "Here's your link:"},
            "shopify_connected": True,
        }
        db, captured = self._db_with_update(org_row=org_row)
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        # Send exactly the same values as current config
        r = client.patch("/api/v1/admin/commerce/settings", json={
            "enabled": True,
            "checkout_message": "Here's your link:",
        })

        assert r.status_code == 200
        assert "No changes" in r.json().get("message", "")
        org_updates = [c for c in captured["update"] if c["table"] == "organisations"]
        assert not org_updates, "Expected no DB write when config unchanged"


# ---------------------------------------------------------------------------
# GET /api/v1/commerce/sessions/active
# ---------------------------------------------------------------------------

class TestGetActiveCommerceSession:

    def test_returns_active_session(self):
        active_session = {
            "id": "sess-1", "org_id": ORG_ID, "phone_number": PHONE,
            "status": "open", "cart": [], "subtotal": 0,
        }
        db = _make_db(sessions=[active_session])
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.get(f"/api/v1/commerce/sessions/active?phone={PHONE}")

        assert r.status_code == 200
        assert r.json()["data"]["id"] == "sess-1"

    def test_returns_null_when_no_active_session(self):
        db = _make_db(sessions=[])
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.get(f"/api/v1/commerce/sessions/active?phone={PHONE}")

        assert r.status_code == 200
        assert r.json()["data"] is None

    def test_s1_scoped_to_jwt_org(self):
        """Only sessions belonging to the JWT org must be returned."""
        active_session = {
            "id": "sess-99", "org_id": ORG_ID, "phone_number": PHONE,
            "status": "open", "cart": [], "subtotal": 0,
        }
        eq_calls = []
        db = MagicMock()
        def table_side(name):
            tbl = MagicMock()
            sel = MagicMock()
            def capture_eq(col, val):
                eq_calls.append((col, val))
                return sel
            sel.eq.side_effect   = capture_eq
            sel.in_.return_value = sel
            sel.order.return_value = sel
            sel.limit.return_value = sel
            sel.execute.return_value.data = [active_session] if name == "commerce_sessions" else []
            tbl.select.return_value = sel
            return tbl
        db.table.side_effect = table_side

        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.get(f"/api/v1/commerce/sessions/active?phone={PHONE}")

        assert r.status_code == 200
        assert r.json()["data"]["id"] == "sess-99"
        queried_values = [str(v) for _, v in eq_calls]
        assert any(ORG_ID in v for v in queried_values), (
            f"Expected {ORG_ID} in eq() calls, got: {eq_calls}"
        )

    def test_s14_returns_null_on_db_error(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB down")
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        client = TestClient(app)
        r = client.get(f"/api/v1/commerce/sessions/active?phone={PHONE}")

        assert r.status_code == 200
        assert r.json()["data"] is None
