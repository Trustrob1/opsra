"""
tests/integration/test_site_capture_routes.py
SITE-ADDONS A1-1 - the public form post, the tracked WhatsApp link, the owner's "Answer now" link, and the staff routes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.routers import public_site_capture
from app.services import lead_service
from app.services import site_capture_service as cap
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
FORM = {"name": "Ada Obi", "phone": "08031234567", "email": "", "message": "50 cakes please", "consent": "on",
        "src": "hero", "return_to": "https://alfacakes.ng/contact", "website": ""}


def _org(template="owner"):
    return {"id": "22222222-2222-2222-2222-222222222222", "org_id": ORG, "roles": {"template": template}}


@pytest.fixture
def api(monkeypatch):
    db = FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": {}}],
        sites=[{"id": "site-1", "org_id": ORG, "deleted_at": None, "client_business_name": "Alfa <b>Cakes</b>",
                "content": {"business": {"whatsapp_e164": "+2348090000001"}},
                "legal_owner": {"full_name": "Chidi", "phone": "08030000009"}},
               {"id": "site-x", "org_id": "org-2", "deleted_at": None, "client_business_name": "Other"}],
        site_addons=[{"id": "t1", "org_id": ORG, "site_id": "site-1", "kind": "tier", "key": "capture", "status": "active",
                      "source": "staff", "billing_mode": "link", "paid_until": None, "config": {}}],
        site_usage_counters=[], site_events=[], site_keys=[], site_workspaces=[], site_lead_events=[], organisations=[],
        roles=[], users=[], leads=[], site_domains=[{"org_id": ORG, "site_id": "site-1", "domain": "alfacakes.ng"}])
    holder = {"db": db, "role": "owner", "wa": [], "email": []}
    monkeypatch.setattr(cap, "_send_email", lambda to, s, t: holder["email"].append(to) or True)
    monkeypatch.setattr(cap, "_send_whatsapp", lambda db, o, phone, text, **kw: holder["wa"].append((phone, text)) or True)

    def fake_create(db, org_id, user_id, payload, **kw):
        row = {"org_id": org_id, "full_name": payload.full_name, "phone": lead_service._normalise_phone(payload.phone),
               "email": payload.email, "problem_stated": payload.problem_stated, "stage": "new", "assigned_to": user_id}
        return db.table("leads").insert(row).execute().data[0]
    monkeypatch.setattr(lead_service, "create_lead", fake_create)
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _org(holder["role"])
    cap._hits.clear()
    yield holder, TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def _key(h):
    return cap.get_or_create_key(h["db"], ORG, "site-1")["key"]


# -- the form -----------------------------------------------------------------------

def test_the_form_post_saves_a_lead_and_shows_a_thank_you_with_a_safe_back_link(api):
    h, c = api
    k = _key(h)
    r = c.post(f"/api/v1/public/site-leads/{k}", data=FORM)
    assert r.status_code == 200 and "Thank you" in r.text and "Alfa &lt;b&gt;Cakes&lt;/b&gt;" in r.text
    assert 'href="https://alfacakes.ng/contact"' in r.text and "<script" not in r.text
    assert r.headers["cache-control"] == "no-store"
    assert len(h["db"].rows("leads")) == 1 and h["db"].rows("leads")[0]["site_id"] == "site-1"
    assert h["wa"] and h["db"].rows("site_lead_events")[0]["kind"] == "form_submit"


def test_a_foreign_return_address_is_not_linked(api):
    h, c = api
    r = c.post(f"/api/v1/public/site-leads/{_key(h)}", data={**FORM, "return_to": "https://evil.example/"})
    assert r.status_code == 200 and "evil.example" not in r.text and "Back to the website" not in r.text


def test_field_problems_are_a_422_page_and_nothing_is_saved(api):
    h, c = api
    r = c.post(f"/api/v1/public/site-leads/{_key(h)}", data={**FORM, "consent": ""})
    assert r.status_code == 422 and "tick the box" in r.text and h["db"].rows("leads") == []
    r = c.post(f"/api/v1/public/site-leads/{_key(h)}", data={**FORM, "name": ""})
    assert r.status_code == 422 and "your name" in r.text


def test_the_honeypot_gets_a_thank_you_but_saves_nothing(api):
    h, c = api
    r = c.post(f"/api/v1/public/site-leads/{_key(h)}", data={**FORM, "website": "http://spam"})
    assert r.status_code == 200 and h["db"].rows("leads") == [] and h["wa"] == []


def test_unknown_key_and_plan_off(api):
    h, c = api
    assert c.post("/api/v1/public/site-leads/sk_nothing", data=FORM).status_code == 404
    k = _key(h)
    h["db"].rows("site_addons")[0]["status"] = "paused"
    r = c.post(f"/api/v1/public/site-leads/{k}", data=FORM)
    assert r.status_code == 200 and "not available" in r.text and "wa.me/2348090000001" in r.text
    assert h["db"].rows("leads") == []


def test_the_form_is_rate_limited_per_visitor(api):
    h, c = api
    k = _key(h)
    codes = [c.post(f"/api/v1/public/site-leads/{k}", data={**FORM, "phone": f"0803123{i:04d}"}).status_code for i in range(14)]
    assert codes.count(200) == cap.SUBMIT_PER_IP_PER_HOUR and codes[-1] == 429


# -- links ----------------------------------------------------------------------------

def test_the_whatsapp_link_redirects_and_counts(api):
    h, c = api
    r = c.get(f"/sl/{_key(h)}/wa", params={"src": "hero", "t": "Hello"})
    assert r.status_code == 302 and r.headers["location"] == "https://wa.me/2348090000001?text=Hello"
    assert h["db"].rows("site_lead_events")[0]["kind"] == "wa_click"


def test_the_whatsapp_link_with_a_bad_key_is_a_404_page(api):
    _, c = api
    r = c.get("/sl/sk_nothing/wa")
    assert r.status_code == 404 and "isn't valid" in r.text


def test_the_answer_link_marks_the_lead_and_redirects_to_whatsapp(api):
    h, c = api
    k = _key(h)
    c.post(f"/api/v1/public/site-leads/{k}", data=FORM)
    lead = h["db"].rows("leads")[0]
    r = c.get(f"/sl/{k}/l/{lead['id']}")
    assert r.status_code == 302 and r.headers["location"].startswith("https://wa.me/2348031234567")
    assert h["db"].rows("leads")[0]["answered_at"]
    assert c.get(f"/sl/{k}/l/not-a-lead").status_code == 404


# -- staff ------------------------------------------------------------------------------

def test_staff_see_the_key_and_counts_and_can_rotate(api):
    h, c = api
    r = c.get("/api/v1/sites/site-1/capture")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["key"].startswith("sk_") and d["workspace"] is False and d["features"]["form_instant_reply"] is True
    old = d["key"]
    r2 = c.post("/api/v1/sites/site-1/capture/rotate-key")
    assert r2.status_code == 200 and r2.json()["data"]["key"] != old
    assert c.post(f"/api/v1/public/site-leads/{old}", data=FORM).status_code == 404


def test_staff_roles_and_other_orgs(api):
    h, c = api
    h["role"] = "admin"
    assert c.get("/api/v1/sites/site-1/capture").status_code == 200
    assert c.post("/api/v1/sites/site-1/capture/rotate-key").status_code == 403
    h["role"] = "sales_agent"
    assert c.get("/api/v1/sites/site-1/capture").status_code == 403
    h["role"] = "owner"
    assert c.get("/api/v1/sites/site-x/capture").status_code == 404           # another org's site
    assert c.get("/api/v1/sites/nope/capture").status_code == 404
    h["db"].rows("site_builder_settings")[0]["enabled"] = False
    assert c.get("/api/v1/sites/site-1/capture").status_code == 404


def _token(h):
    key = _key(h)
    return key, cap.leads_token(h["db"], "site-1")


def test_my_leads_page_shows_leads_escaped_and_private(api):
    h, c = api
    key = _key(h)
    c.post(f"/api/v1/public/site-leads/{key}", data=dict(FORM, name="<script>alert(1)</script>"))
    tok = cap.leads_token(h["db"], "site-1")
    r = c.get(f"/my-leads/{tok}")
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text
    assert "<script" not in r.text.lower().replace("&lt;script", "")
    assert "noindex" in r.headers.get("x-robots-tag", "") + r.text and "no-store" in r.headers["cache-control"]
    assert f"/sl/{key}/l/" in r.text and "Alfa &lt;b&gt;Cakes&lt;/b&gt;" in r.text


def test_my_leads_with_a_wrong_link_is_a_404_page(api):
    _, c = api
    r = c.get("/my-leads/" + "z" * 32)
    assert r.status_code == 404 and "<script" not in r.text.lower()


def test_my_leads_empty_page_is_friendly(api):
    h, c = api
    key = _key(h)
    c.post(f"/api/v1/public/site-leads/{key}", data=FORM)
    h["db"].rows("leads").clear()
    r = c.get(f"/my-leads/{cap.leads_token(h['db'], 'site-1')}")
    assert r.status_code == 200 and "No enquiries yet" in r.text or "no enquiries" in r.text.lower()


def test_my_leads_unavailable_when_the_plan_lacks_it(api):
    h, c = api
    key = _key(h)
    c.post(f"/api/v1/public/site-leads/{key}", data=FORM)
    tok = cap.leads_token(h["db"], "site-1")
    h["db"].rows("site_builder_settings")[0]["pricing"] = {"tiers": {"capture": {"features": ["form_instant_reply"]}}}
    r = c.get(f"/my-leads/{tok}")
    assert r.status_code == 200 and "Alfa" in r.text and f"/sl/{key}/l/" not in r.text


def test_my_leads_is_rate_limited(api):
    _, c = api
    codes = [c.get("/my-leads/" + "q" * 32).status_code for _ in range(320)]
    assert 429 in codes
