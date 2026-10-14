"""
tests/integration/test_site_option_routes.py
SITE-OPTIONS OPT-1 - the client's page (/o/{token}), the builder routes, the staff routes, the brief-form exemption
from the free-sites limit and the checkout block for undecided designs. Real HTTP routes through TestClient with a
FakeDB; message senders are recorded.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.routers import builder_portal
from app.services import site_capture_service as cap
from app.services import site_option_service as opt
from app.services import site_order_service
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
B1, B2 = "builder-1", "builder-2"


def _site(sid, builder=B1, **kw):
    r = {"id": sid, "org_id": ORG, "builder_id": builder, "deleted_at": None, "status": "preview_ready",
         "slug": f"slug-{sid}", "client_business_name": f"Biz {sid}", "tier": "standard", "option_set_id": None,
         "option_offered": False, "preview_expires_at": None, "content": {"hero": {"headline": f"Headline {sid}"}}}
    r.update(kw)
    return r


def _org(template="owner"):
    return {"id": "22222222-2222-2222-2222-222222222222", "org_id": ORG, "roles": {"template": template}}


def _builder(bid=B1):
    return {"id": bid, "org_id": ORG, "business_name": "Pixel Co", "full_name": "Ada", "phone_number": "2348030000001",
            "email": "ada@example.com", "lead_id": "lead-1", "max_active_sites": None, "access_paid_until": None}


@pytest.fixture
def api(monkeypatch):
    db = FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": {}}],
        site_builders=[_builder(B1), _builder(B2) | {"business_name": "Other"}],
        sites=[_site("s1", client_business_name="Alfa <b>Cakes</b>"), _site("s2"), _site("s3"), _site("x1", builder=B2)],
        site_option_sets=[], site_option_items=[], site_orders=[], site_events=[], site_brief_forms=[], site_presets=[])
    holder = {"db": db, "role": "owner", "builder": _builder(B1), "wa": [], "email": []}
    monkeypatch.setattr(cap, "_send_whatsapp", lambda d, o, phone, text, **kw: holder["wa"].append((phone, text)) or True)
    monkeypatch.setattr(cap, "_send_email", lambda to, s, t: holder["email"].append(to) or True)
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _org(holder["role"])
    app.dependency_overrides[builder_portal.get_current_builder] = lambda: holder["builder"]
    cap._hits.clear()
    yield holder, TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def _make(h, c, sites=("s1", "s2")):
    r = c.post("/api/v1/builder/option-sets", json={"client_name": "Mrs <i>Obi</i>", "site_ids": list(sites)})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    return d, d["link"].rsplit("/", 1)[1]


# -- the client's page -----------------------------------------------------------------

def test_the_page_lists_the_designs_safely(api):
    h, c = api
    d, tok = _make(h, c)
    r = c.get(f"/o/{tok}")
    assert r.status_code == 200 and "Design A" in r.text and "Design B" in r.text and "Headline s2" in r.text
    assert "Alfa &lt;b&gt;Cakes&lt;/b&gt;" in r.text and "Mrs &lt;i&gt;Obi&lt;/i&gt;" in r.text and "<b>Cakes" not in r.text
    assert "<script" not in r.text and "<iframe" not in r.text and "Pixel Co" in r.text
    assert 'target="_blank" rel="noopener noreferrer"' in r.text and "/s/slug-s1" in r.text
    assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]
    assert "script-src" not in r.headers["content-security-policy"] and "'none'" in r.headers["content-security-policy"]


def test_an_unknown_link_gets_a_plain_not_valid_page(api):
    h, c = api
    r = c.get("/o/" + "x" * 30)
    assert r.status_code == 404 and "isn't valid" in r.text
    assert c.post("/o/nope/choose", data={"item_id": "1"}).status_code == 404


def test_choosing_asks_to_confirm_first_then_saves_and_tells_the_builder(api):
    h, c = api
    d, tok = _make(h, c)
    item = d["items"][1]["id"]
    r1 = c.post(f"/o/{tok}/choose", data={"item_id": item})
    assert r1.status_code == 200 and "Confirm your choice" in r1.text and "Design B" in r1.text
    assert h["db"].rows("site_option_sets")[0]["status"] == "open" and h["wa"] == []                 # nothing saved yet
    r2 = c.post(f"/o/{tok}/choose", data={"item_id": item, "confirm": "1"})
    assert r2.status_code == 200 and "Thank you" in r2.text and "Design B" in r2.text
    assert h["db"].rows("site_option_sets")[0]["chosen_site_id"] == "s2"
    assert len(h["wa"]) == 1 and "Mrs <i>Obi</i>" in h["wa"][0][1]
    page = c.get(f"/o/{tok}").text
    assert "Your choice" in page and "can still change it" in page


def test_the_client_can_change_the_pick_until_it_is_paid(api):
    h, c = api
    d, tok = _make(h, c)
    c.post(f"/o/{tok}/choose", data={"item_id": d["items"][0]["id"], "confirm": "1"})
    r = c.post(f"/o/{tok}/choose", data={"item_id": d["items"][1]["id"], "confirm": "1"})
    assert r.status_code == 200 and h["db"].rows("site_option_sets")[0]["chosen_site_id"] == "s2"
    h["db"].rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s2", "kind": "initial", "status": "fulfilling"})
    page = c.get(f"/o/{tok}").text
    assert "payment is received" in page and "Choose this one" not in page
    r = c.post(f"/o/{tok}/choose", data={"item_id": d["items"][0]["id"], "confirm": "1"})
    assert r.status_code == 409 and h["db"].rows("site_option_sets")[0]["chosen_site_id"] == "s2"


def test_a_bad_item_or_a_closed_set_cannot_be_chosen(api):
    h, c = api
    d, tok = _make(h, c)
    assert c.post(f"/o/{tok}/choose", data={"item_id": "not-an-item", "confirm": "1"}).status_code == 409
    h["db"].rows("site_option_sets")[0]["status"] = "closed"
    assert c.post(f"/o/{tok}/choose", data={"item_id": d["items"][0]["id"], "confirm": "1"}).status_code == 409


def test_an_expired_link_says_so(api):
    h, c = api
    d, tok = _make(h, c)
    h["db"].rows("site_option_sets")[0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = c.get(f"/o/{tok}")
    assert r.status_code == 410 and "expired" in r.text


def test_choosing_is_rate_limited(api):
    h, c = api
    d, tok = _make(h, c)
    codes = [c.post(f"/o/{tok}/choose", data={"item_id": d["items"][0]["id"]}).status_code for _ in range(32)]
    assert 429 in codes and codes[0] == 200


# -- the builder's routes ---------------------------------------------------------------------

def test_builder_makes_lists_and_reads_a_set(api):
    h, c = api
    d, tok = _make(h, c)
    assert d["status"] == "open" and [i["label"] for i in d["items"]] == ["Design A", "Design B"]
    listed = c.get("/api/v1/builder/option-sets").json()["data"]
    assert len(listed) == 1 and listed[0]["options"] == 2 and listed[0]["link"].endswith(tok)
    assert c.get(f"/api/v1/builder/option-sets/{d['id']}").json()["data"]["client_name"] == "Mrs <i>Obi</i>"


def test_another_builder_cannot_touch_my_set(api):
    h, c = api
    d, tok = _make(h, c)
    h["builder"] = _builder(B2)
    assert c.get("/api/v1/builder/option-sets").json()["data"] == []
    assert c.get(f"/api/v1/builder/option-sets/{d['id']}").status_code == 404
    assert c.post(f"/api/v1/builder/option-sets/{d['id']}/sites", json={"site_id": "x1"}).status_code == 404
    assert c.post(f"/api/v1/builder/option-sets/{d['id']}/choose", json={"item_id": d["items"][0]["id"]}).status_code == 404
    assert c.post(f"/api/v1/builder/option-sets/{d['id']}/close").status_code == 404


def test_a_builder_cannot_offer_someone_elses_site(api):
    h, c = api
    r = c.post("/api/v1/builder/option-sets", json={"site_ids": ["x1"]})
    assert r.status_code == 422


def test_builder_adds_removes_picks_for_the_client_and_closes(api):
    h, c = api
    d, tok = _make(h, c, ("s1",))
    r = c.post(f"/api/v1/builder/option-sets/{d['id']}/sites", json={"site_id": "s2", "label": "Bold one"})
    assert r.status_code == 200 and [i["label"] for i in r.json()["data"]["items"]] == ["Design A", "Bold one"]
    assert c.delete(f"/api/v1/builder/option-sets/{d['id']}/sites/s2").status_code == 200
    r = c.post(f"/api/v1/builder/option-sets/{d['id']}/close")
    assert r.status_code == 200 and r.json()["data"]["status"] == "closed"
    assert c.post(f"/api/v1/builder/option-sets/{d['id']}/close").status_code == 409


def test_builder_can_pick_on_the_clients_behalf_without_a_self_notice(api):
    h, c = api
    d, tok = _make(h, c)
    r = c.post(f"/api/v1/builder/option-sets/{d['id']}/choose", json={"item_id": d["items"][0]["id"]})
    assert r.status_code == 200 and r.json()["data"]["set"]["chosen_site_id"] == "s1" and h["wa"] == []


def test_the_eleventh_open_set_is_refused(api):
    h, c = api
    for _ in range(10):
        assert c.post("/api/v1/builder/option-sets", json={}).status_code == 201
    r = c.post("/api/v1/builder/option-sets", json={})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ACCESS_LIMIT"


# -- staff -------------------------------------------------------------------------------------------

def test_staff_can_make_and_read_sets_for_any_builder_in_the_org(api):
    h, c = api
    r = c.post("/api/v1/site-option-sets", json={"builder_id": B1, "client_name": "Mrs Obi", "site_ids": ["s1", "s2"]})
    assert r.status_code == 201
    sid = r.json()["data"]["id"]
    assert len(c.get("/api/v1/site-option-sets").json()["data"]) == 1
    assert len(c.get(f"/api/v1/site-option-sets?builder_id={B2}").json()["data"]) == 0
    assert c.get(f"/api/v1/site-option-sets/{sid}").json()["data"]["items"][0]["label"] == "Design A"
    assert c.post(f"/api/v1/site-option-sets/{sid}/sites", json={"site_id": "s3"}).status_code == 200
    assert c.post(f"/api/v1/site-option-sets/{sid}/choose", json={"item_id": r.json()["data"]["items"][0]["id"]}).status_code == 200


@pytest.mark.parametrize("role,method,path", [
    ("sales_agent", "get", "/api/v1/site-option-sets"), ("sales_agent", "post", "/api/v1/site-option-sets"),
    ("admin", "post", "/api/v1/site-option-sets")])
def test_staff_roles_are_enforced(api, role, method, path):
    h, c = api
    h["role"] = role
    r = getattr(c, method)(path, **({"json": {"builder_id": B1}} if method == "post" else {}))
    assert r.status_code == 403


def test_the_staff_routes_are_off_when_the_site_engine_is_off(api):
    h, c = api
    h["db"].rows("site_builder_settings")[0]["enabled"] = False
    assert c.get("/api/v1/site-option-sets").status_code == 404


# -- the free-sites limit and checkout ------------------------------------------------------------------

def _at_the_free_limit(h):
    h["db"].rows("sites").extend([_site(f"c{i}") for i in range(3)])      # three counted sites = the free limit


def test_a_form_link_for_a_set_is_not_blocked_by_the_free_limit(api):
    h, c = api
    d, tok = _make(h, c, ("s1",))
    _at_the_free_limit(h)
    blocked = c.post("/api/v1/builder/forms", json={"audience": "builder"})
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "ACCESS_LIMIT"
    ok = c.post("/api/v1/builder/forms", json={"audience": "builder", "option_set_id": d["id"]})
    assert ok.status_code == 201
    assert h["db"].rows("site_brief_forms")[0]["option_set_id"] == d["id"]


def test_a_full_or_foreign_set_does_not_unlock_extra_forms(api):
    h, c = api
    _at_the_free_limit(h)
    d, tok = _make(h, c, ("s1", "s2"))
    for i in range(3):
        h["db"].rows("sites").append(_site(f"f{i}"))
        opt.attach_site(h["db"], ORG, d["id"], f"f{i}", None, "u")
    full = c.post("/api/v1/builder/forms", json={"audience": "builder", "option_set_id": d["id"]})
    assert full.status_code == 422
    h["builder"] = _builder(B2)
    foreign = c.post("/api/v1/builder/forms", json={"audience": "builder", "option_set_id": d["id"]})
    assert foreign.status_code == 422


def test_checkout_is_blocked_until_the_client_has_picked_the_design(api):
    h, c = api
    d, tok = _make(h, c)
    payload = SimpleNamespace(site_id="s1", domain="a.ng", backup_domain="b.ng", route="a", legal_owner=None,
                              accepted_terms=True, discount_code=None)
    with pytest.raises(site_order_service.CheckoutBlocked):
        site_order_service.create_checkout(h["db"], ORG, _builder(B1), payload)
    c.post(f"/o/{tok}/choose", data={"item_id": d["items"][0]["id"], "confirm": "1"})
    assert h["db"].rows("sites")[0]["option_offered"] is False          # now past the option block (checkout itself is tested elsewhere)


# -- the picker list (OPT-2) -----------------------------------------------------------

def test_eligible_sites_lists_only_sites_that_can_be_added(api):
    h, c = api
    db = h["db"]
    db.rows("sites").extend([_site("live1", status="live"), _site("gone", status="cancelled"),
                             _site("paid1"), _site("del1", deleted_at="2026-01-01T00:00:00+00:00")])
    db.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "paid1", "kind": "initial", "status": "paid"})
    _make(h, c, ("s1",))                                   # s1 is now in a set
    r = c.get("/api/v1/builder/option-sets/eligible-sites")
    assert r.status_code == 200, r.text
    ids = sorted(x["site_id"] for x in r.json()["data"])
    assert ids == ["s2", "s3"]                              # not s1 (in a set), live1, gone, paid1, del1 or the other builder's x1
    assert r.json()["data"][0]["preview_url"].endswith("/s/slug-" + r.json()["data"][0]["site_id"])


def test_staff_eligible_sites_needs_a_builder_and_a_read_role(api):
    h, c = api
    assert c.get("/api/v1/site-option-sets/eligible-sites").status_code == 422
    r = c.get(f"/api/v1/site-option-sets/eligible-sites?builder_id={B2}")
    assert r.status_code == 200 and [x["site_id"] for x in r.json()["data"]] == ["x1"]
    h["role"] = "agent"
    assert c.get(f"/api/v1/site-option-sets/eligible-sites?builder_id={B2}").status_code == 403
