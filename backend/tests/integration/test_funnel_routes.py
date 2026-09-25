"""
tests/integration/test_funnel_routes.py
FUNNEL-1A — HTTP-level tests (TestClient, real routes, FakeDB via get_supabase override):
  • GET /f/{token}                         (public pay link)
  • POST /webhooks/payment/paystack-storefront  (mark_paid + funnel hook, generic message suppressed)
  • webhooks._handle_inbound_message       (event_funnel intercept)
  • /api/v1/funnels/*                      (internal CRUD, RBAC, actions, export)

Pattern 32: pop overrides in teardown. Pattern 44: override get_current_org.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.routers import public_funnels
from tests.funnel_fake_db import FakeDB
from tests.unit.test_funnel_service import (
    FUNNEL_ID, LEAD_ID, NOW, NUMBER, NUMBER_ID, ORG_ID, OTHER_ORG, PHONE, base_db, make_funnel, make_reg,
)

USER_ID = "22222222-2222-2222-2222-222222222222"
SECRET = "sk_test_funnel"


def _org(template="owner", org_id=ORG_ID):
    return {"id": USER_ID, "org_id": org_id, "roles": {"template": template}}


class _Base:
    db: FakeDB

    @pytest.fixture(autouse=True)
    def _setup(self):
        public_funnels._rate_store.clear()
        self.db = self.make_db()
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[get_current_org] = lambda: _org()
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def make_db(self):
        return base_db(funnel_registrations=[make_reg()])


# ═══════════════════════════ Public pay link ═══════════════════════════

class TestPublicPayLink(_Base):
    def test_FUN_I_01_redirects_to_paystack(self):
        with patch("app.services.paystack_storefront_service.generate_payment_link",
                   return_value={"checkout_url": "https://checkout.paystack.com/abc", "reference": "r1"}), \
             patch("app.services.funnel_service._now", return_value=NOW):
            with TestClient(app) as c:
                r = c.get("/f/tok_abc", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "https://checkout.paystack.com/abc"
        assert self.db.rows("funnel_payments")[0]["amount"] == 5000.0

    def test_FUN_I_02_closed_page_escaped_no_redirect(self):
        self.db.tables["event_funnels"][0]["event_title"] = "<script>x</script>"
        with patch("app.services.funnel_service._now", return_value=NOW + timedelta(days=30)):
            with TestClient(app) as c:
                r = c.get("/f/tok_abc", follow_redirects=False)
        assert r.status_code == 200 and "Registration has closed" in r.text
        assert "<script>x" not in r.text and "&lt;script&gt;" in r.text
        assert "<script" not in r.text  # global CSP middleware also blocks inline script

    def test_FUN_I_03_unknown_token_404_and_rate_limit(self):
        with TestClient(app) as c:
            assert c.get("/f/unknown").status_code == 404
            with patch.object(public_funnels, "_RATE_LIMIT", 2):
                public_funnels._rate_store.clear()
                c.get("/f/unknown"); c.get("/f/unknown")
                assert c.get("/f/unknown").status_code == 429


# ═══════════════════════════ Paystack storefront webhook ═══════════════════════════

class TestStorefrontWebhook(_Base):
    def make_db(self):
        return base_db(
            funnel_registrations=[make_reg()],
            leads=[{"id": LEAD_ID, "org_id": ORG_ID, "full_name": "Ada Obi", "whatsapp": PHONE, "phone": PHONE,
                    "assigned_to": None, "deal_value": None}],
            payment_links=[{"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "org_id": ORG_ID, "lead_id": LEAD_ID,
                            "reference": "ref1", "amount": 5000.0, "currency": "NGN", "status": "pending",
                            "payment_type": "full", "created_at": NOW.isoformat()}],
            funnel_payments=[{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "org_id": ORG_ID, "funnel_id": FUNNEL_ID,
                              "registration_id": make_reg()["id"], "reference": "ref1", "amount": 5000.0,
                              "tier": "early", "seats": 1, "status": "pending", "created_at": NOW.isoformat()}],
            integrations=[{"org_id": ORG_ID, "provider": "paystack_storefront", "status": "connected",
                           "credentials": {"secret_key": SECRET}}],
            webhook_request_log=[], organisations=[{"id": ORG_ID, "payment_link_config": {}}],
        )

    def _post(self, body: dict, sig: str | None = None):
        raw = json.dumps(body).encode()
        sig = sig or hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
        with TestClient(app) as c:
            return c.post("/webhooks/payment/paystack-storefront", content=raw,
                          headers={"X-Paystack-Signature": sig, "Content-Type": "application/json"})

    def test_FUN_I_04_charge_success_seats_buyer_and_suppresses_generic_message(self):
        body = {"event": "charge.success", "data": {"reference": "ref1", "amount": 500000}}
        with patch("app.services.paystack_storefront_service.verify_transaction",
                   return_value={"verified": True, "data": {"status": "success", "amount": 500000}}), \
             patch("app.services.funnel_messaging._call_meta_send", return_value={}) as meta, \
             patch("app.services.whatsapp_service.send_payment_received_message") as generic:
            r = self._post(body)
        assert r.status_code == 200
        assert self.db.rows("payment_links")[0]["status"] == "paid"
        assert self.db.rows("funnel_registrations")[0]["status"] == "paid"
        assert generic.call_count == 0
        assert meta.call_count == 1 and "Payment received" in meta.call_args.args[1]["text"]["body"]

    def test_FUN_I_05_bad_signature_rejected_nothing_paid(self):
        body = {"event": "charge.success", "data": {"reference": "ref1"}}
        r = self._post(body, sig="bad")
        assert r.status_code == 401
        assert self.db.rows("funnel_registrations")[0]["status"] == "new"


# ═══════════════════════════ Inbound intercept ═══════════════════════════

class TestInboundIntercept:
    def test_FUN_I_06_event_funnel_number_routes_to_funnel_only(self):
        from app.routers import webhooks
        db = base_db(customers=[], customer_contacts=[], organisations=[{"id": ORG_ID}])
        msg = {"from": PHONE, "id": "wamid.1", "type": "text", "text": {"body": "Hi (B1)"},
               "referral": {"ctwa_clid": "C1"}}
        with patch("app.routers.webhooks._is_org_owner", return_value=False), \
             patch("app.services.funnel_service.handle_inbound") as h, \
             patch("app.routers.webhooks._route_to_ai_agent") as ai:
            webhooks._handle_inbound_message(db, msg, "Ada", NUMBER["phone_id"])
        assert h.call_count == 1 and ai.call_count == 0
        kw = h.call_args.kwargs
        assert kw["number_row"]["org_id"] == ORG_ID and kw["referral"] == {"ctwa_clid": "C1"}
        assert kw["content"] == "Hi (B1)"

    def test_FUN_I_07_other_modes_unaffected(self):
        from app.routers import webhooks
        db = base_db(customers=[], customer_contacts=[], organisations=[{"id": ORG_ID}])
        db.tables["whatsapp_numbers"][0]["wa_sales_mode"] = "ai_agent"
        msg = {"from": PHONE, "id": "wamid.2", "type": "text", "text": {"body": "Hi"}}
        with patch("app.routers.webhooks._is_org_owner", return_value=False), \
             patch("app.services.funnel_service.handle_inbound") as h, \
             patch("app.routers.webhooks._route_to_ai_agent") as ai:
            webhooks._handle_inbound_message(db, msg, "Ada", NUMBER["phone_id"])
        assert h.call_count == 0 and ai.call_count == 1


# ═══════════════════════════ Internal routes ═══════════════════════════

CREATE_BODY = {
    "name": "Website class 10 Oct", "event_title": "Build a Professional Website with ChatGPT",
    "event_starts_at": "2026-10-10T19:00:00Z", "registration_closes_at": "2026-10-10T17:00:00Z",
    "pricing_mode": "window", "early_price": 5000, "regular_price": 7500,
    "group_size": 3, "group_price": 12000, "ad_codes": [{"code": "b1"}, {"code": "S2"}],
}


class TestFunnelRoutes(_Base):
    def test_FUN_I_08_create_draft_and_list(self):
        with TestClient(app) as c:
            r = c.post("/api/v1/funnels", json=CREATE_BODY)
            assert r.status_code == 201, r.text
            data = r.json()["data"]
            assert data["org_id"] == ORG_ID and data["status"] == "draft"
            assert data["ad_codes"][0]["code"] == "B1"
            assert len(c.get("/api/v1/funnels").json()["data"]) == 2

    def test_FUN_I_09_validation_errors(self):
        with TestClient(app) as c:
            bad = dict(CREATE_BODY, pricing_mode="deadline")
            assert c.post("/api/v1/funnels", json=bad).status_code == 422
            bad2 = dict(CREATE_BODY, registration_closes_at="2026-10-11T00:00:00Z")
            assert c.post("/api/v1/funnels", json=bad2).status_code == 422
            bad3 = dict(CREATE_BODY, paid_group_link="http://insecure")
            assert c.post("/api/v1/funnels", json=bad3).status_code == 422

    def test_FUN_I_10_rbac(self):
        app.dependency_overrides[get_current_org] = lambda: _org("sales_agent")
        with TestClient(app) as c:
            assert c.get("/api/v1/funnels").status_code == 403
            assert c.post("/api/v1/funnels", json=CREATE_BODY).status_code == 403
        app.dependency_overrides[get_current_org] = lambda: _org("admin")
        with TestClient(app) as c:
            assert c.get("/api/v1/funnels").status_code == 200
            assert c.patch(f"/api/v1/funnels/{FUNNEL_ID}", json={"name": "x"}).status_code == 403

    def test_FUN_I_11_cross_org_is_404(self):
        app.dependency_overrides[get_current_org] = lambda: _org(org_id=OTHER_ORG)
        with TestClient(app) as c:
            assert c.get(f"/api/v1/funnels/{FUNNEL_ID}").status_code == 404
            assert c.get(f"/api/v1/funnels/{FUNNEL_ID}/stats").status_code == 404

    def test_FUN_I_12_activation_requires_event_funnel_number(self):
        self.db.tables["whatsapp_numbers"][0]["wa_sales_mode"] = "human"
        with TestClient(app) as c:
            r = c.patch(f"/api/v1/funnels/{FUNNEL_ID}", json={"status": "active"})
            assert r.status_code == 422
            self.db.tables["whatsapp_numbers"][0]["wa_sales_mode"] = "event_funnel"
            assert c.patch(f"/api/v1/funnels/{FUNNEL_ID}", json={"status": "active"}).status_code == 200

    def test_FUN_I_13_switch_pricing_mode(self):
        with TestClient(app) as c:
            r = c.patch(f"/api/v1/funnels/{FUNNEL_ID}", json={"pricing_mode": "deadline"})
            assert r.status_code == 422      # needs early_deadline_at
            r = c.patch(f"/api/v1/funnels/{FUNNEL_ID}", json={"pricing_mode": "deadline",
                                                               "early_deadline_at": "2026-10-04T22:59:00Z"})
            assert r.status_code == 200
        assert self.db.rows("event_funnels")[0]["pricing_mode"] == "deadline"

    def test_FUN_I_14_stats_registrations_actions_export(self):
        with TestClient(app) as c:
            st = c.get(f"/api/v1/funnels/{FUNNEL_ID}/stats").json()["data"]
            assert st["leads"] == 1 and st["paid"] == 0 and st["by_ad_code"][0]["code"] == "B1"
            regs = c.get(f"/api/v1/funnels/{FUNNEL_ID}/registrations?search=ada").json()["data"]
            assert regs["total"] == 1
            rid = regs["items"][0]["id"]
            assert c.post(f"/api/v1/funnels/{FUNNEL_ID}/registrations/{rid}/grant-early",
                          json={"hours": 72}).status_code == 422
            assert c.post(f"/api/v1/funnels/{FUNNEL_ID}/registrations/{rid}/grant-early",
                          json={"hours": 24}).status_code == 200
            with patch("app.services.funnel_messaging._call_meta_send", return_value={}) as meta:
                r = c.post(f"/api/v1/funnels/{FUNNEL_ID}/registrations/{rid}/mark-paid",
                           json={"amount": 5000, "note": "bank transfer"})
                assert r.status_code == 200 and meta.call_count == 1
            self.db.tables["funnel_registrations"][0]["name"] = "=HYPERLINK(evil)"
            csv_text = c.get(f"/api/v1/funnels/{FUNNEL_ID}/export.csv").text
            assert "'=HYPERLINK" in csv_text and PHONE in csv_text
            assert c.patch(f"/api/v1/funnels/{FUNNEL_ID}/registrations/{rid}",
                           json={"email": "not-an-email"}).status_code == 422
