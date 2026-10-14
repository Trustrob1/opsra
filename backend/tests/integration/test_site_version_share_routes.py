"""
tests/integration/test_site_version_share_routes.py
SITE-OPTIONS OPT-3 - the client's version page (/v/{token}), the builder routes and the staff routes, through real HTTP
routes with a FakeDB. Message senders are recorded; the page renderer is stubbed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.routers import builder_portal
from app.services import site_capture_service as cap
from app.services import site_premium_service
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
B1, B2 = "builder-1", "builder-2"
NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _site(sid, builder=B1, **kw):
    r = {"id": sid, "org_id": ORG, "builder_id": builder, "deleted_at": None, "status": "preview_ready", "tier": "premium",
         "slug": f"slug-{sid}", "client_business_name": f"Biz {sid}", "current_design_id": f"{sid}-d1",
         "preview_expires_at": _iso(NOW + timedelta(days=5))}
    r.update(kw)
    return r


def _designs(sid, n=3):
    return [{"id": f"{sid}-d{i}", "org_id": ORG, "site_id": sid, "version": i, "kind": "generate", "status": "ready",
             "staged": False, "created_at": _iso(NOW - timedelta(days=10 - i)), "checks": {}} for i in range(1, n + 1)]


def _builder(bid=B1):
    return {"id": bid, "org_id": ORG, "business_name": "Pixel Co", "full_name": "Ada", "phone_number": "2348030000001",
            "email": "ada@example.com"}


def _org(template="owner"):
    return {"id": "22222222-2222-2222-2222-222222222222", "org_id": ORG, "roles": {"template": template}}


@pytest.fixture
def api(monkeypatch):
    db = FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": {}}],
        site_builders=[_builder(B1), _builder(B2) | {"business_name": "Other"}],
        sites=[_site("s1", client_business_name="Alfa <b>Cakes</b>"), _site("x1", builder=B2), _site("st", tier="standard")],
        site_designs=_designs("s1") + _designs("x1"), site_version_shares=[], site_version_items=[], site_orders=[],
        site_events=[], site_assets=[])
    holder = {"db": db, "role": "owner", "builder": _builder(B1), "wa": []}
    monkeypatch.setattr(cap, "_send_whatsapp", lambda d, o, phone, text, **kw: holder["wa"].append((phone, text)) or True)
    monkeypatch.setattr(cap, "_send_email", lambda to, s, t: True)
    monkeypatch.setattr(site_premium_service, "preview_design",
                        lambda d, org, site, design_id, assets: f"<html><body>design {design_id}</body></html>")
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _org(holder["role"])
    app.dependency_overrides[builder_portal.get_current_builder] = lambda: holder["builder"]
    cap._hits.clear()
    yield holder, TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def _make(c, ids=("s1-d2", "s1-d3")):
    r = c.post("/api/v1/builder/version-shares", json={"site_id": "s1", "client_name": "Mrs <i>Obi</i>", "design_ids": list(ids)})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    return d, d["link"].rsplit("/", 1)[1]


# -- the client's page ----------------------------------------------------------------

def test_the_page_lists_the_versions_safely(api):
    h, c = api
    d, tok = _make(c)
    r = c.get(f"/v/{tok}")
    assert r.status_code == 200 and "Version 2" in r.text and "Version 3" in r.text
    assert "Mrs &lt;i&gt;Obi&lt;/i&gt;" in r.text and "Alfa &lt;b&gt;Cakes&lt;/b&gt;" in r.text and "<b>Cakes" not in r.text
    assert "<script" not in r.text and "<iframe" not in r.text and "Pixel Co" in r.text
    assert "noindex" in r.headers["x-robots-tag"] and r.headers["cache-control"] == "no-store"
    assert f'href="/v/{tok}/view/{d["items"][0]["id"]}"' in r.text


def test_each_version_opens_as_a_full_page(api):
    h, c = api
    d, tok = _make(c)
    r = c.get(f"/v/{tok}/view/{d['items'][1]['id']}")
    assert r.status_code == 200 and "design s1-d3" in r.text and "noindex" in r.headers["x-robots-tag"]
    assert c.get(f"/v/{tok}/view/nope").status_code == 404
    assert c.get(f"/v/{'x' * 40}/view/{d['items'][1]['id']}").status_code == 404


def test_unknown_link_is_a_plain_404_page(api):
    h, c = api
    assert c.get("/v/" + "z" * 40).status_code == 404


def test_choosing_confirms_first_then_applies_and_notifies(api):
    h, c = api
    d, tok = _make(c)
    item = d["items"][1]["id"]
    first = c.post(f"/v/{tok}/choose", data={"item_id": item})
    assert first.status_code == 200 and "Confirm your choice" in first.text
    assert h["db"].rows("site_version_shares")[0]["status"] == "open"
    done = c.post(f"/v/{tok}/choose", data={"item_id": item, "confirm": "1"})
    assert done.status_code == 200 and "Thank you" in done.text and "Version 3" in done.text
    assert next(s for s in h["db"].rows("sites") if s["id"] == "s1")["current_design_id"] == "s1-d3"
    assert h["wa"] and "Version 3" in h["wa"][0][1]
    page = c.get(f"/v/{tok}")
    assert "Your choice" in page.text and "can still change" in page.text


def test_a_paid_site_cannot_be_chosen_from(api):
    h, c = api
    d, tok = _make(c)
    h["db"].rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "paid"})
    r = c.post(f"/v/{tok}/choose", data={"item_id": d["items"][0]["id"], "confirm": "1"})
    assert r.status_code == 409 and next(s for s in h["db"].rows("sites") if s["id"] == "s1")["current_design_id"] == "s1-d1"


def test_a_closed_link_gives_a_plain_page(api):
    h, c = api
    d, tok = _make(c)
    c.post(f"/api/v1/builder/version-shares/{d['id']}/close")
    assert c.get(f"/v/{tok}").status_code == 410
    assert c.get(f"/v/{tok}/view/{d['items'][0]['id']}").status_code == 404


def test_the_page_is_rate_limited(api):
    h, c = api
    d, tok = _make(c)
    codes = [c.get(f"/v/{tok}").status_code for _ in range(130)]
    assert 429 in codes


# -- builder routes ------------------------------------------------------------------

def test_builder_lists_sites_and_versions(api):
    h, c = api
    r = c.get("/api/v1/builder/version-shares/sites")
    assert r.status_code == 200 and [s["site_id"] for s in r.json()["data"]] == ["s1"]
    v = c.get("/api/v1/builder/version-shares/sites/s1/versions")
    assert [x["version"] for x in v.json()["data"]] == [3, 2, 1]
    assert c.get("/api/v1/builder/version-shares/sites/x1/versions").status_code == 404       # someone else's site


def test_builder_full_flow(api):
    h, c = api
    d, tok = _make(c)
    sid = d["id"]
    assert [x["id"] for x in c.get("/api/v1/builder/version-shares").json()["data"]] == [sid]
    assert c.get(f"/api/v1/builder/version-shares/{sid}").json()["data"]["link"].endswith(tok)
    added = c.post(f"/api/v1/builder/version-shares/{sid}/versions", json={"design_id": "s1-d1", "label": "Original"})
    assert added.status_code == 200 and [i["label"] for i in added.json()["data"]["items"]][-1] == "Original"
    item = added.json()["data"]["items"][0]["id"]
    chosen = c.post(f"/api/v1/builder/version-shares/{sid}/choose", json={"item_id": item})
    assert chosen.status_code == 200 and chosen.json()["data"]["set"]["status"] == "chosen" and h["wa"] == []
    assert c.delete(f"/api/v1/builder/version-shares/{sid}/versions/{item}").status_code == 409      # picked one stays
    assert c.post(f"/api/v1/builder/version-shares/{sid}/close").status_code == 200


def test_builder_cannot_touch_another_builders_link_or_site(api):
    h, c = api
    d, tok = _make(c)
    h["builder"] = _builder(B2)
    assert c.get(f"/api/v1/builder/version-shares/{d['id']}").status_code == 404
    assert c.post(f"/api/v1/builder/version-shares/{d['id']}/close").status_code == 404
    assert c.post("/api/v1/builder/version-shares", json={"site_id": "s1", "design_ids": ["s1-d1"]}).status_code == 404
    assert c.get("/api/v1/builder/version-shares").json()["data"] == []


def test_standard_site_and_duplicates_are_refused(api):
    h, c = api
    assert c.post("/api/v1/builder/version-shares", json={"site_id": "st", "design_ids": ["x"]}).status_code == 422
    _make(c)
    assert c.post("/api/v1/builder/version-shares", json={"site_id": "s1", "design_ids": ["s1-d1"]}).status_code == 409


# -- staff routes ---------------------------------------------------------------------

def test_staff_can_do_everything_for_any_builder(api):
    h, c = api
    sites = c.get(f"/api/v1/site-version-shares/sites?builder_id={B2}")
    assert sites.status_code == 200 and [s["site_id"] for s in sites.json()["data"]] == ["x1"]
    every = c.get("/api/v1/site-version-shares/sites")                                         # no builder = every builder's sites
    assert every.status_code == 200 and sorted(s["site_id"] for s in every.json()["data"]) == ["s1", "x1"]
    assert {s["site_id"]: s["builder_name"] for s in every.json()["data"]} == {"s1": "Pixel Co", "x1": "Other"}
    assert [v["version"] for v in c.get("/api/v1/site-version-shares/sites/x1/versions").json()["data"]] == [3, 2, 1]
    r = c.post("/api/v1/site-version-shares", json={"site_id": "x1", "design_ids": ["x1-d1", "x1-d2"]})
    assert r.status_code == 201 and r.json()["data"]["builder_id"] == B2
    sid = r.json()["data"]["id"]
    assert [x["id"] for x in c.get(f"/api/v1/site-version-shares?builder_id={B2}").json()["data"]] == [sid]
    assert c.get(f"/api/v1/site-version-shares?builder_id={B1}").json()["data"] == []
    assert c.get(f"/api/v1/site-version-shares/{sid}").status_code == 200
    item = r.json()["data"]["items"][0]["id"]
    assert c.post(f"/api/v1/site-version-shares/{sid}/choose", json={"item_id": item}).status_code == 200
    assert c.post(f"/api/v1/site-version-shares/{sid}/versions", json={"design_id": "x1-d3"}).status_code == 200
    assert c.post(f"/api/v1/site-version-shares/{sid}/close").status_code == 200


def test_staff_roles_that_cannot_write_are_read_only(api):
    h, c = api
    h["role"] = "admin"
    assert c.get(f"/api/v1/site-version-shares/sites?builder_id={B1}").status_code == 200
    assert c.post("/api/v1/site-version-shares", json={"site_id": "s1", "design_ids": ["s1-d1"]}).status_code == 403
    h["role"] = "agent"
    assert c.get(f"/api/v1/site-version-shares/sites?builder_id={B1}").status_code == 403
