"""
tests/integration/test_site_giveaways_routes.py
GIVEAWAY-1 — public + staff routes, and the real form-submit route taking (or refusing) a slot.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.routers import public_forms, site_giveaways as router_mod
from app.services import site_partner_service
from tests.funnel_fake_db import FakeDB

ORG = "00000000-0000-0000-0000-0000000000aa"


def _org(t="owner"):
    return {"id": "u1", "org_id": ORG, "role": t, "roles": {"template": t}}


@pytest.fixture
def ctx():
    db = FakeDB(site_builders=[], site_partners=[], site_giveaways=[], site_giveaway_entries=[], site_brief_forms=[],
                sites=[], site_presets=[{"id": "pr1", "org_id": ORG, "key": "services", "name": "General Services", "is_active": True,
                                         "sections": ["hero"], "brief_questions": [], "labels": {}}],
                site_assets=[], site_builder_settings=[], whatsapp_numbers=[], site_events=[], site_orders=[], notifications=[])
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _org("owner")
    router_mod._hits.clear()
    yield TestClient(app), db
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


_k = {"i": 0}


def _who(**over):
    _k["i"] += 1
    d = {"consent": True, "name": "Ada Obi", "phone": f"0803{_k['i']:07d}", "email": "ada@example.com"}
    d.update(over)
    return d


def _create(client, db, slots=2):
    p = site_partner_service.create_partner(db, ORG, "Group Owner", "08030000001", None, "Hub")
    r = client.post("/api/v1/giveaways", json={"partner_id": p["id"], "title": "Free Website Giveaway", "total_slots": slots})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def test_public_status_and_open(ctx):
    client, db = ctx
    g = _create(client, db)
    s = client.get(f"/api/v1/giveaways/{g['slug']}").json()["data"]
    assert s["left"] == 2 and s["open"] is True
    assert client.post(f"/api/v1/giveaways/{g['slug']}/open", json={}).status_code == 422
    r = client.post(f"/api/v1/giveaways/{g['slug']}/open", json=_who())
    assert r.status_code == 200 and "/f/" in r.json()["data"]["url"]
    assert client.get("/api/v1/giveaways/does-not-exist").status_code == 404


def test_staff_routes_and_role_gate(ctx):
    client, db = ctx
    g = _create(client, db)
    assert len(client.get("/api/v1/giveaways").json()["data"]) == 1
    assert client.post(f"/api/v1/giveaways/{g['id']}/close").status_code == 200
    assert client.post(f"/api/v1/giveaways/{g['slug']}/open", json=_who()).status_code == 410
    assert client.post(f"/api/v1/giveaways/{g['id']}/reopen").status_code == 200
    app.dependency_overrides[get_current_org] = lambda: _org("sales_agent")
    assert client.get("/api/v1/giveaways").status_code == 403
    assert client.post("/api/v1/giveaways", json={"partner_id": "x" * 12, "title": "Valid title"}).status_code == 403


def _token_for(client, g):
    """open a giveaway form through the public route and return its raw token"""
    url = client.post(f"/api/v1/giveaways/{g['slug']}/open", json=_who()).json()["data"]["url"]
    return url.rsplit("/", 1)[1]


def _choose_preset(db):
    for f in db.rows("site_brief_forms"):
        if not f.get("preset_id"):
            f["preset_id"] = "pr1"


def test_submit_takes_a_slot_then_the_next_is_refused(ctx):
    client, db = ctx
    g = _create(client, db, slots=1)
    t1, t2 = _token_for(client, g), _token_for(client, g)
    _choose_preset(db)
    body = {"client_business_name": "Zed Shop", "answers": {}}
    r1 = client.post(f"/api/v1/forms/{t1}/submit", json=body)
    assert r1.status_code == 200, r1.text
    assert client.get(f"/api/v1/giveaways/{g['slug']}").json()["data"]["left"] == 0
    r2 = client.post(f"/api/v1/forms/{t2}/submit", json={**body, "client_business_name": "Late Shop"})
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "GIVEAWAY_FULL"
    assert [s["client_business_name"] for s in db.rows("sites")] == ["Zed Shop"]       # no site made for the late one
    assert db.rows("site_giveaway_entries")[0]["site_id"] == db.rows("sites")[0]["id"]


def test_full_giveaway_stops_new_forms(ctx):
    client, db = ctx
    g = _create(client, db, slots=1)
    t1 = _token_for(client, g)
    _choose_preset(db)
    client.post(f"/api/v1/forms/{t1}/submit", json={"client_business_name": "Zed Shop", "answers": {}})
    r = client.post(f"/api/v1/giveaways/{g['slug']}/open", json=_who())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FULL"


def test_open_needs_contact_and_refuses_a_second_slot_for_one_number(ctx):
    client, db = ctx
    g = _create(client, db, slots=3)
    assert client.post(f"/api/v1/giveaways/{g['slug']}/open", json={"consent": True}).status_code == 422
    assert client.post(f"/api/v1/giveaways/{g['slug']}/open", json=_who(email="bad")).status_code == 422
    me = _who(phone="08031234567")
    t1 = client.post(f"/api/v1/giveaways/{g['slug']}/open", json=me).json()["data"]["url"].rsplit("/", 1)[1]
    t2 = client.post(f"/api/v1/giveaways/{g['slug']}/open", json=me).json()["data"]["url"].rsplit("/", 1)[1]
    _choose_preset(db)
    body = {"client_business_name": "Zed Shop", "answers": {}}
    assert client.post(f"/api/v1/forms/{t1}/submit", json=body).status_code == 200
    again = client.post(f"/api/v1/giveaways/{g['slug']}/open", json=me)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "ALREADY_ENTERED"
    late = client.post(f"/api/v1/forms/{t2}/submit", json={**body, "client_business_name": "Dup"})
    assert late.status_code == 409 and late.json()["detail"]["code"] == "ALREADY_ENTERED"
    assert [x["client_business_name"] for x in db.rows("sites")] == ["Zed Shop"]


def test_create_with_custom_fee_and_renewal_and_public_terms(ctx):
    client, db = ctx
    p = site_partner_service.create_partner(db, ORG, "Group Owner", "08030000001", None, "Hub")
    r = client.post("/api/v1/giveaways", json={"partner_id": p["id"], "title": "Free Website Giveaway", "total_slots": 4,
                                               "fee_ngn": 30000, "renewal_ngn": 27000})
    assert r.status_code == 201
    pub = client.get(f"/api/v1/giveaways/{r.json()['data']['slug']}").json()["data"]
    assert pub["fee_ngn"] == 30000 and pub["renewal_ngn"] == 27000 and pub["terms"]["free_edits"] == 5
    assert client.post("/api/v1/giveaways", json={"partner_id": p["id"], "title": "Valid title", "fee_ngn": 10}).status_code == 422


def test_winner_flow_submit_view_pay_and_void(ctx, monkeypatch):
    client, db = ctx
    from app.services import site_order_service, site_access_service
    g = _create(client, db, slots=2)
    t1 = client.post(f"/api/v1/giveaways/{g['slug']}/open", json=_who()).json()["data"]["url"].rsplit("/", 1)[1]
    _choose_preset(db)
    r = client.post(f"/api/v1/forms/{t1}/submit", json={"client_business_name": "Zed Shop", "answers": {}})
    assert r.status_code == 200, r.text
    wurl = r.json()["data"]["winner_url"]
    tok = wurl.rsplit("/", 1)[1]
    assert "/w/" in wurl

    v = client.get(f"/api/v1/giveaway-winner/{tok}").json()["data"]
    assert v["business_name"] == "Zed Shop" and v["fee_ngn"] == 24500 and v["position"] == 1
    assert client.get("/api/v1/giveaway-winner/not-a-real-token").status_code == 404

    body = {"domain": "zedshop.ng", "backup_domain": "zedshop.com.ng", "accepted_terms": True, "amount": 5,
            "legal_owner": {"full_name": "Ada Obi", "email": "ada@example.com", "phone": "08031234567", "address": "1 Allen Ave"}}
    assert client.post(f"/api/v1/giveaway-winner/{tok}/checkout", json=body).status_code == 409      # preview not ready yet

    site = db.rows("sites")[0]
    db.table("sites").update({"status": "preview_ready", "rendered_html": "<html/>"}).eq("id", site["id"]).execute()
    seen = []
    monkeypatch.setattr(site_access_service, "ensure_lead", lambda db_, org, b: "lead-1")
    monkeypatch.setattr(site_order_service, "create_checkout",
                        lambda db_, org, b, payload, fixed_amount=None: seen.append(fixed_amount) or
                        {"checkout_url": "https://pay.test/x", "reference": "r", "order_id": "o", "amount": fixed_amount})
    pay = client.post(f"/api/v1/giveaway-winner/{tok}/checkout", json=body)
    assert pay.status_code == 200 and pay.json()["data"]["amount"] == 24500 and seen == [24500]

    assert client.post(f"/api/v1/giveaways/{g['id']}/entries/1/void").status_code == 200
    assert client.get(f"/api/v1/giveaway-winner/{tok}").status_code == 404
    assert client.get(f"/api/v1/giveaways/{g['slug']}").json()["data"]["left"] == 2
    app.dependency_overrides[get_current_org] = lambda: _org("sales_agent")
    assert client.post(f"/api/v1/giveaways/{g['id']}/entries/1/void").status_code == 403


def test_pay_by_days_and_winner_catalog_route(ctx, monkeypatch):
    client, db = ctx
    p = site_partner_service.create_partner(db, ORG, "Group Owner", "08030000001", None, "Hub")
    r = client.post("/api/v1/giveaways", json={"partner_id": p["id"], "title": "Free Website Giveaway", "total_slots": 2, "pay_by_days": 5})
    assert r.status_code == 201 and r.json()["data"]["pay_by_days"] == 5
    assert client.post("/api/v1/giveaways", json={"partner_id": p["id"], "title": "Free Website Giveaway", "pay_by_days": 99}).status_code == 422
    g = r.json()["data"]
    t1 = client.post(f"/api/v1/giveaways/{g['slug']}/open", json=_who()).json()["data"]["url"].rsplit("/", 1)[1]
    _choose_preset(db)
    tok = client.post(f"/api/v1/forms/{t1}/submit", json={"client_business_name": "Zed Shop", "answers": {}}).json()["data"]["winner_url"].rsplit("/", 1)[1]
    assert client.post(f"/api/v1/giveaway-winner/{tok}/catalog-checkout").status_code == 409        # not paid yet
    from app.services import site_access_service, site_catalog_service
    monkeypatch.setattr(site_access_service, "ensure_lead", lambda *a: "lead-1")
    monkeypatch.setattr(site_catalog_service, "create_checkout",
                        lambda *a: {"checkout_url": "https://pay.test/c", "amount": 5000, "items": 30, "reused": False})
    db.table("site_orders").insert({"id": "o1", "site_id": db.rows("sites")[0]["id"], "kind": "initial", "status": "fulfilling"}).execute()
    r = client.post(f"/api/v1/giveaway-winner/{tok}/catalog-checkout")
    assert r.status_code == 200 and r.json()["data"]["items"] == 30


def test_lost_link_routes(ctx, monkeypatch):
    client, db = ctx
    from app.services import site_giveaway_service as svc
    sent = []
    monkeypatch.setattr(svc, "_send_to_contact", lambda db_, e, subj, text: sent.append(text) or True)
    g = _create(client, db, slots=2)
    me = _who(phone="08031234567")
    t1 = client.post(f"/api/v1/giveaways/{g['slug']}/open", json=me).json()["data"]["url"].rsplit("/", 1)[1]
    _choose_preset(db)
    first = client.post(f"/api/v1/forms/{t1}/submit", json={"client_business_name": "Zed Shop", "answers": {}}).json()["data"]["winner_url"].rsplit("/", 1)[1]
    sent.clear()

    r = client.post(f"/api/v1/giveaways/{g['slug']}/lost-link", json={"phone": "08031234567"})
    assert r.status_code == 200 and len(sent) == 1
    assert client.get(f"/api/v1/giveaway-winner/{first}").status_code == 404            # old link dead
    new = sent[0].split("/w/")[1].split()[0]
    assert client.get(f"/api/v1/giveaway-winner/{new}").status_code == 200
    assert client.post("/api/v1/giveaways/nope-nope/lost-link", json={"phone": "08031234567"}).status_code == 404
    assert client.post(f"/api/v1/giveaways/{g['slug']}/lost-link", json={"phone": "08000000000"}).status_code == 200      # same answer, nothing sent
    assert len(sent) == 1

    sent.clear()
    assert client.post(f"/api/v1/giveaways/{g['id']}/entries/1/resend-link").status_code == 200 and len(sent) == 1
    assert client.post(f"/api/v1/giveaways/{g['id']}/entries/9/resend-link").status_code == 422
    app.dependency_overrides[get_current_org] = lambda: _org("sales_agent")
    assert client.post(f"/api/v1/giveaways/{g['id']}/entries/1/resend-link").status_code == 403


def test_campaign_fields_and_qr_endpoint(ctx):
    client, db = ctx
    p = site_partner_service.create_partner(db, ORG, "Group Owner", "08030000001", None, "Hub")
    r = client.post("/api/v1/giveaways", json={"partner_id": p["id"], "title": "Free Website Giveaway", "total_slots": 3,
                                               "campaign_name": "Launch Week", "ends_at": "2999-01-01T00:00:00Z"})
    assert r.status_code == 201, r.text
    slug = r.json()["data"]["slug"]
    pub = client.get(f"/api/v1/giveaways/{slug}").json()["data"]
    assert pub["campaign_name"] == "Launch Week" and pub["ended"] is False and pub["ends_at"]
    bad = client.post("/api/v1/giveaways", json={"partner_id": p["id"], "title": "Free Website Giveaway", "campaign_name": "ab"})
    assert bad.status_code == 422
    q = client.get(f"/api/v1/giveaways/{slug}/qr.svg")
    assert q.status_code == 200 and q.headers["content-type"].startswith("image/svg+xml") and b"<svg" in q.content
    assert client.get("/api/v1/giveaways/nope-nope/qr.svg").status_code == 404
