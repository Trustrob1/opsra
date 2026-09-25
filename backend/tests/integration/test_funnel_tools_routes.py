"""
tests/integration/test_funnel_tools_routes.py
FUNNEL-1B — HTTP tests for /api/v1/funnels/{id}/… tool routes (TestClient + FakeDB).
Pattern 32: pop overrides. Pattern 44: override get_current_org.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from tests.unit.test_funnel_service import FUNNEL_ID, NOW, ORG_ID, OTHER_ORG, base_db, make_reg
from tests.unit.test_funnel_tools_service import ORG_ROW, reg

USER_ID = "22222222-2222-2222-2222-222222222222"
BASE = f"/api/v1/funnels/{FUNNEL_ID}"


def _org(template="owner", org_id=ORG_ID):
    return {"id": USER_ID, "org_id": org_id, "roles": {"template": template}}


class TestFunnelToolRoutes:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.db = base_db(
            funnel_registrations=[reg(1), reg(2, status="paid", email="p@gmail.com", amount_paid=5000,
                                                paid_at=NOW.isoformat())],
            funnel_ad_spend=[], funnel_broadcasts=[], organisations=[dict(ORG_ROW)])
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[get_current_org] = lambda: _org()
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_FUN_T_01_ad_spend_put_get_and_overview(self):
        with TestClient(app) as c:
            r = c.put(f"{BASE}/ad-spend", json={"rows": [{"date": "2026-10-01", "ad_code": "b1", "amount": 7000}]})
            assert r.status_code == 200 and r.json()["data"]["saved"] == 1
            assert c.get(f"{BASE}/ad-spend?from=2026-10-01&to=2026-10-31").json()["data"][0]["ad_code"] == "B1"
            ov = c.get(f"{BASE}/overview").json()["data"]
            assert ov["ad_spend"] == 7000.0 and ov["paid"] == 1
            assert c.put(f"{BASE}/ad-spend", json={"rows": [{"date": "2026-10-01", "ad_code": "B 1", "amount": 1}]}).status_code == 422
            assert c.put(f"{BASE}/ad-spend", json={"rows": [{"date": "2026-10-01", "ad_code": "B1", "amount": -5}]}).status_code == 422

    def test_FUN_T_02_preview(self):
        with TestClient(app) as c:
            r = c.post(f"{BASE}/preview", json={"message_key": "greeting", "sample": {"name": "Ada"}})
            assert r.status_code == 200 and r.json()["data"]["button"].startswith("Pay ")
            assert c.post(f"{BASE}/preview", json={}).status_code == 422
            assert c.post(f"{BASE}/preview", json={"step_key": "nope"}).status_code == 404

    def test_FUN_T_03_reset_test_lead(self):
        paid_id, unpaid_id = reg(2)["id"], reg(1)["id"]
        with TestClient(app) as c:
            assert c.delete(f"{BASE}/registrations/{paid_id}").status_code == 409
            assert c.delete(f"{BASE}/registrations/{unpaid_id}").status_code == 200
        assert [r["id"] for r in self.db.rows("funnel_registrations")] == [paid_id]

    def test_FUN_T_04_duplicate_gmail_ask(self):
        with TestClient(app) as c:
            r = c.post(f"{BASE}/duplicate-as-test")
            assert r.status_code == 201 and r.json()["data"]["status"] == "draft"
            g = c.get(f"{BASE}/gmail-list").json()["data"]
            assert g["emails"] == ["p@gmail.com"] and g["missing"] == []
            with patch("app.services.funnel_messaging._call_meta_send", return_value={}) as meta:
                assert c.post(f"{BASE}/registrations/{reg(2)['id']}/ask-gmail").status_code == 200
                assert "Gmail" in meta.call_args.args[1]["text"]["body"]

    def test_FUN_T_05_broadcast_dry_run_create_list_cancel(self):
        body = {"template_name": "class_tomorrow", "template_params": ["{pay_link}"], "audience": "unpaid"}
        with TestClient(app) as c:
            d = c.post(f"{BASE}/broadcasts", json=dict(body, dry_run=True)).json()["data"]
            assert d["recipients"] == 1 and self.db.rows("funnel_broadcasts") == []
            r = c.post(f"{BASE}/broadcasts", json=body)
            assert r.status_code == 200 and r.json()["data"]["status"] == "queued"
            bid = r.json()["data"]["id"]
            assert len(c.get(f"{BASE}/broadcasts").json()["data"]) == 1
            assert c.post(f"{BASE}/broadcasts/{bid}/cancel").status_code == 200
            assert c.post(f"{BASE}/broadcasts/{bid}/cancel").status_code == 409
            assert c.post(f"{BASE}/broadcasts", json=dict(body, template_name="Bad Name")).status_code == 422

    def test_FUN_T_06_budget_cap_returns_422_with_message(self):
        self.db.tables["event_funnels"][0]["settings"] = {"template_cost_estimate": 100, "template_budget_cap": 50}
        with TestClient(app) as c:
            r = c.post(f"{BASE}/broadcasts", json={"template_name": "t", "audience": "all"})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "BUDGET_CAP"

    def test_FUN_T_07_settings_validation_on_funnel_patch(self):
        with TestClient(app) as c:
            ok_ = c.patch(BASE, json={"settings": {"template_cost_estimate": 55, "template_budget_cap": 20000,
                                                   "pause_spend_threshold": 15000}})
            assert ok_.status_code == 200
            assert c.patch(BASE, json={"settings": {"template_budget_cap": -1}}).status_code == 422

    def test_FUN_T_08_rbac_and_cross_org(self):
        app.dependency_overrides[get_current_org] = lambda: _org("admin")
        with TestClient(app) as c:
            assert c.get(f"{BASE}/overview").status_code == 200
            assert c.put(f"{BASE}/ad-spend", json={"rows": [{"date": "2026-10-01", "ad_code": "B1", "amount": 1}]}).status_code == 403
            assert c.post(f"{BASE}/broadcasts", json={"template_name": "t"}).status_code == 403
        app.dependency_overrides[get_current_org] = lambda: _org("sales_agent")
        with TestClient(app) as c:
            assert c.get(f"{BASE}/overview").status_code == 403
        app.dependency_overrides[get_current_org] = lambda: _org(org_id=OTHER_ORG)
        with TestClient(app) as c:
            assert c.get(f"{BASE}/gmail-list").status_code == 404
            assert c.delete(f"{BASE}/registrations/{reg(1)['id']}").status_code == 404

    def test_FUN_T_09_events_timeline(self):
        self.db.tables["funnel_events"] = [
            {"org_id": ORG_ID, "funnel_id": FUNNEL_ID, "registration_id": reg(1)["id"], "type": "lead_created",
             "step_key": None, "detail": {}, "created_at": "2026-10-01T10:00:00+00:00"},
            {"org_id": ORG_ID, "funnel_id": FUNNEL_ID, "registration_id": reg(1)["id"], "type": "step_sent",
             "step_key": "checkin_3h", "detail": {}, "created_at": "2026-10-01T13:00:00+00:00"},
            {"org_id": ORG_ID, "funnel_id": FUNNEL_ID, "registration_id": reg(2)["id"], "type": "lead_created",
             "step_key": None, "detail": {}, "created_at": "2026-10-01T10:00:00+00:00"}]
        with TestClient(app) as c:
            ev = c.get(f"{BASE}/registrations/{reg(1)['id']}/events").json()["data"]
        assert [e["type"] for e in ev] == ["step_sent", "lead_created"]
