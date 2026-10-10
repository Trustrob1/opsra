"""
tests/integration/test_site_addon_routes.py
SITE-ADDONS A0-2 - the client's private pay page, the staff and builder routes that set up a purchase and send the link,
and the order kind staying out of a builder's "first site order" check.
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.routers import builder_portal, public_site_pay
from app.services import funnel_service, paystack_storefront_service
from app.services import site_addon_billing_service as billing
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
SITE = "site-1"
PRICING = {"tiers": {"capture": {"monthly_ngn": 15000, "setup_fee_ngn": 5000}, "convert": {"monthly_ngn": 40000}}}


def _org(template="owner"):
    return {"id": "22222222-2222-2222-2222-222222222222", "org_id": ORG, "roles": {"template": template}}


@pytest.fixture
def api(monkeypatch):
    db = FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": copy.deepcopy(PRICING)}],
        sites=[{"id": SITE, "org_id": ORG, "builder_id": "b-1", "client_business_name": "Alfa <b>Diva</b>", "deleted_at": None,
                "legal_owner": {"full_name": "Ada Obi", "phone": "08030000001", "email": "ada@example.com"}},
               {"id": "site-2", "org_id": ORG, "builder_id": "b-2", "client_business_name": "Other", "deleted_at": None,
                "legal_owner": {"email": "o@example.com"}}],
        site_builders=[{"id": "b-1", "org_id": ORG, "full_name": "Chidi", "phone_number": "2348030000009", "lead_id": "lead-1",
                        "status": "active"},
                       {"id": "b-2", "org_id": ORG, "full_name": "Bola", "phone_number": "2348030000008", "lead_id": "lead-2",
                        "status": "active"}],
        site_addons=[], site_usage_counters=[], site_events=[], site_orders=[], payment_links=[])
    holder = {"db": db, "role": "owner", "sent": []}
    n = {"i": 0}

    def link(db=None, org_id=None, lead_id=None, amount=None, **kw):
        n["i"] += 1
        db.table("payment_links").insert({"id": f"pl-{n['i']}", "org_id": org_id,
                                          "checkout_url": f"https://checkout.paystack.com/{n['i']}"}).execute()
        return {"payment_link_id": f"pl-{n['i']}", "reference": f"ref-{n['i']}",
                "checkout_url": f"https://checkout.paystack.com/{n['i']}"}

    monkeypatch.setattr(paystack_storefront_service, "generate_payment_link", link)
    monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: None)
    monkeypatch.setattr(billing, "_notify_payer", lambda db, org, row, site, builder, text, url, params=None:
                        holder["sent"].append((text, url)) or True)
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _org(holder["role"])
    public_site_pay._rate_store.clear()
    yield holder, TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def _start(c, **over):
    body = {"kind": "tier", "key": "capture", **over}
    return c.post(f"/api/v1/sites/{SITE}/addons/checkout", json=body)


def _token(h):
    return h["db"].rows("site_addons")[0]["config"]["pay_token"]


# -- staff: set up a purchase and send the link --------------------------------------

def test_staff_sets_up_a_purchase_and_gets_the_private_link(api):
    h, c = api
    r = _start(c)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["pay_url"].endswith("/site-pay/" + _token(h)) and d["quote"]["total"] == 20000 and d["scheduled"] is False
    assert "sent" not in d and h["sent"] == []


def test_send_true_also_sends_the_link_to_the_client(api):
    h, c = api
    d = _start(c, send=True).json()["data"]
    assert d["sent"] is True and "₦20,000" in h["sent"][0][0] and h["sent"][0][1] == d["pay_url"]
    again = c.post(f"/api/v1/sites/{SITE}/addons/{d['addon_id']}/send-link")
    assert again.status_code == 200 and len(h["sent"]) == 2


def test_bad_purchases_are_plain_errors(api):
    h, c = api
    assert _start(c, key="platinum").status_code == 422
    assert _start(c, key="grow").status_code == 422                                      # price 0 = not for sale
    assert _start(c, kind="bogus").status_code == 422
    assert c.post("/api/v1/sites/nope/addons/checkout", json={"kind": "tier", "key": "capture"}).status_code == 404
    assert h["db"].rows("site_addons") == []


def test_only_owner_or_ops_manager_can_set_up_a_purchase(api):
    h, c = api
    h["role"] = "admin"
    assert _start(c).status_code == 403
    h["role"] = "ops_manager"
    assert _start(c).status_code == 200


# -- the public pay page --------------------------------------------------------------

def test_the_pay_page_shows_the_plan_and_price_and_escapes_names(api):
    h, c = api
    _start(c)
    r = c.get("/site-pay/" + _token(h))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.text
    assert "Capture" in body and "₦20,000" in body and "One-time set-up" in body and "/go" in body
    assert "Alfa &lt;b&gt;Diva&lt;/b&gt;" in body and "<b>Diva</b>" not in body
    assert "noindex" in body and "<script" not in body


def test_unknown_or_cancelled_links_get_the_same_not_valid_page(api):
    h, c = api
    assert c.get("/site-pay/nonsense").status_code == 404
    assert c.get("/site-pay/nonsense/go").status_code == 404
    _start(c)
    tok = _token(h)
    h["db"].rows("site_addons")[0]["status"] = "cancelled"
    assert c.get("/site-pay/" + tok).status_code == 404 and c.get("/site-pay/" + tok + "/go").status_code == 404


def test_go_redirects_to_paystack_and_reuses_the_link(api):
    h, c = api
    _start(c)
    r = c.get("/site-pay/" + _token(h) + "/go")
    assert r.status_code == 302 and r.headers["location"] == "https://checkout.paystack.com/1"
    assert c.get("/site-pay/" + _token(h) + "/go").headers["location"] == "https://checkout.paystack.com/1"
    assert len(h["db"].rows("site_orders")) == 1 and h["db"].rows("site_orders")[0]["kind"] == "site_addon"


def test_go_refuses_when_the_plan_is_taken_off_sale(api):
    h, c = api
    _start(c)
    h["db"].rows("site_builder_settings")[0]["pricing"] = {}
    r = c.get("/site-pay/" + _token(h) + "/go")
    assert r.status_code == 422 and "<h1>" in r.text and h["db"].rows("site_orders") == []


def test_the_pay_pages_are_rate_limited(api):
    h, c = api
    codes = [c.get("/site-pay/nonsense").status_code for _ in range(35)]
    assert 429 in codes and codes[0] == 404


# -- builder routes -------------------------------------------------------------------

@pytest.fixture
def as_builder(api):
    h, c = api
    holder = {"builder": {"id": "b-1", "org_id": ORG, "status": "active", "full_name": "Chidi"}}
    app.dependency_overrides[builder_portal.get_current_builder] = lambda: holder["builder"]
    yield h, c, holder
    app.dependency_overrides.pop(builder_portal.get_current_builder, None)


def test_builder_sees_only_plans_that_are_for_sale(as_builder):
    h, c, _ = as_builder
    r = c.get(f"/api/v1/builder/sites/{SITE}/addons")
    assert r.status_code == 200
    d = r.json()["data"]
    assert [p["key"] for p in d["plans"]] == ["capture", "convert"] and d["addon_plans"] == []
    assert d["plans"][0]["monthly_ngn"] == 15000 and "Speed-to-lead alerts" in d["plans"][0]["includes"]
    assert d["tier"] is None and d["features"] == []


def test_builder_sets_up_a_purchase_and_sends_the_link_for_their_own_site(as_builder):
    h, c, _ = as_builder
    r = c.post(f"/api/v1/builder/sites/{SITE}/addons/checkout", json={"kind": "tier", "key": "capture", "send": True})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["sent"] is True and d["pay_url"].endswith("/site-pay/" + _token(h))
    assert h["db"].rows("site_events")[0]["actor"] == "builder:b-1"


def test_builder_cannot_touch_another_builders_site(as_builder):
    h, c, _ = as_builder
    assert c.get("/api/v1/builder/sites/site-2/addons").status_code == 404
    assert c.post("/api/v1/builder/sites/site-2/addons/checkout", json={"kind": "tier", "key": "capture"}).status_code == 404
    assert h["db"].rows("site_addons") == []


def test_builder_bad_requests_are_plain_errors(as_builder):
    _, c, _ = as_builder
    assert c.post(f"/api/v1/builder/sites/{SITE}/addons/checkout", json={"kind": "tier", "key": "grow"}).status_code == 422
    assert c.post(f"/api/v1/builder/sites/{SITE}/addons/checkout", json={"kind": "nope"}).status_code == 422
    assert c.post(f"/api/v1/builder/sites/{SITE}/addons/checkout", json={}).status_code == 422
