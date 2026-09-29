"""
tests/integration/test_sites_ops_routes.py
---------------------------------------------
SITE-3 part 3 — the staff Orders / Hosting queue / Domains routes in
routers/sites.py, hit over real HTTP paths through TestClient with an
in-memory FakeDB (Pattern 3 / Pattern 32: override get_supabase and
get_current_org, pop the overrides in teardown).

Also carries the Pattern 53 regression: static GET paths (/sites/orders,
/sites/hosting-jobs, /sites/domains, /sites/forms) must not be swallowed by
GET /sites/{site_id}.
"""
from __future__ import annotations

import io
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.services import funnel_service, lead_service, pricing_service
from app.services import site_ops_service as ops
from app.services import site_order_service
from tests.funnel_fake_db import FakeDB
from tests.unit.test_site_ops_service import INSIDE, OUTSIDE, QUOTE, SETTINGS, _Resp, _Storage, _job, _order

@contextmanager
def _c():
    """A TestClient WITHOUT the app lifespan — `with TestClient(app)` runs startup hooks that
    take ~15 s each in this environment; nothing here needs them."""
    yield TestClient(app)


ORG = "org-1"
OTHER = "org-2"
USER = "22222222-2222-2222-2222-222222222222"
BASE = "/api/v1/sites"


def _org(template="owner", org_id=ORG):
    return {"id": USER, "org_id": org_id, "roles": {"template": template}}


def _seed(**over):
    tables = {
        "site_builder_settings": [dict(SETTINGS)],
        "site_builders": [{"id": "b-1", "org_id": ORG, "lead_id": "lead-1", "approved_orders_count": 0, "full_name": "Chioma",
                           "business_name": "Adaeze Styles", "phone_number": "+2348030000000"}],
        "sites": [{"id": "site-1", "org_id": ORG, "builder_id": "b-1", "preset_id": "p1", "client_business_name": "Adaeze Styles",
                   "slug": "adaeze-styles-abc123", "status": "hosting_checkout", "live_url": None, "deleted_at": None,
                   "content": {}, "recipe": {}}],
        "site_orders": [_order()],
        "site_hosting_jobs": [],
        "site_domains": [],
        "site_events": [],
        "users": [{"id": USER, "org_id": ORG, "full_name": "Trust", "is_active": True}],
    }
    tables.update(over)
    return FakeDB(**tables)


class _Base:
    db: FakeDB

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.db = self.make_db()
        self.template = "owner"
        self.messages, self.converted = [], []
        monkeypatch.setattr(site_order_service, "_message_builder", lambda db, org, order, text: self.messages.append(text))
        monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: None)
        monkeypatch.setattr(lead_service, "convert_lead", lambda db, org_id, lead_id, user_id: self.converted.append(lead_id) or {})
        monkeypatch.setattr(ops, "_now", lambda: INSIDE)   # deterministic approval window
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[get_current_org] = lambda: _org(self.template)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def make_db(self):
        return _seed()


# ═══════════════════════════ Orders ═══════════════════════════

class TestOrdersRoutes(_Base):
    def test_list_orders_returns_items_and_approval_window(self):
        with _c() as c:
            r = c.get(f"{BASE}/orders")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 1 and data["items"][0]["client_business_name"] == "Adaeze Styles"
        assert data["approval"]["window_start"] == "08:00" and data["approval"]["in_window"] is True

    def test_status_filter_and_search(self):
        with _c() as c:
            assert c.get(f"{BASE}/orders?status=live").json()["data"]["total"] == 0
            assert c.get(f"{BASE}/orders?status=awaiting_approval&search=adaeza").json()["data"]["total"] == 1

    def test_approve_creates_the_hosting_job(self):
        with _c() as c:
            r = c.post(f"{BASE}/orders/ord-1/approve")
        assert r.status_code == 200, r.text
        body = r.json()["data"]
        assert body["order"]["status"] == "fulfilling" and body["hosting_job"]["order_id"] == "ord-1"
        assert self.converted == ["lead-1"]
        assert len(self.db.rows("site_hosting_jobs")) == 1

    def test_approve_outside_window_is_409_with_a_clear_message(self, monkeypatch):
        monkeypatch.setattr(ops, "_now", lambda: OUTSIDE)
        with _c() as c:
            r = c.post(f"{BASE}/orders/ord-1/approve")
        assert r.status_code == 409
        assert "08:00" in r.json()["detail"]["message"]
        assert self.db.rows("site_orders")[0]["status"] == "awaiting_approval"

    def test_approve_twice_second_is_409(self):
        with _c() as c:
            assert c.post(f"{BASE}/orders/ord-1/approve").status_code == 200
            assert c.post(f"{BASE}/orders/ord-1/approve").status_code == 409
        assert len(self.db.rows("site_hosting_jobs")) == 1

    def test_reject_needs_a_reason(self):
        with _c() as c:
            assert c.post(f"{BASE}/orders/ord-1/reject", json={}).status_code == 422
            assert c.post(f"{BASE}/orders/ord-1/reject", json={"reason": "ab"}).status_code == 422
            r = c.post(f"{BASE}/orders/ord-1/reject", json={"reason": "Suspicious client"})
        assert r.status_code == 200 and r.json()["data"]["status"] == "refund_pending"
        assert r.json()["data"]["refund_amount"] == 61000.0

    def test_refund_recorded_flow(self):
        with _c() as c:
            assert c.post(f"{BASE}/orders/ord-1/refund-recorded", json={}).status_code == 409   # not refund_pending yet
            c.post(f"{BASE}/orders/ord-1/reject", json={"reason": "Suspicious client"})
            assert c.post(f"{BASE}/orders/ord-1/refund-recorded", json={"amount": -5}).status_code == 422
            assert c.post(f"{BASE}/orders/ord-1/refund-recorded", json={"amount": 999999}).status_code == 422
            r = c.post(f"{BASE}/orders/ord-1/refund-recorded", json={})
        assert r.status_code == 200 and r.json()["data"]["status"] == "refunded"

    def test_unknown_order_is_404(self):
        with _c() as c:
            assert c.post(f"{BASE}/orders/nope/approve").status_code == 404

    def test_other_orgs_order_is_404(self):
        self.db.tables["site_orders"][0]["org_id"] = OTHER
        with _c() as c:
            assert c.post(f"{BASE}/orders/ord-1/approve").status_code == 404
            assert c.get(f"{BASE}/orders").json()["data"]["total"] == 0

    def test_set_domain_needs_needs_builder_choice(self):
        with _c() as c:
            assert c.post(f"{BASE}/orders/ord-1/set-domain", json={"domain": "x.com.ng"}).status_code == 409
            assert c.post(f"{BASE}/orders/ord-1/set-domain", json={}).status_code == 422


# ═══════════════════════════ Hosting queue ═══════════════════════════

class _JobBase(_Base):
    def make_db(self):
        return _seed(site_orders=[_order(status="fulfilling", hosting_job_id="job-1")], site_hosting_jobs=[_job()],
                     tasks=[{"id": "t1", "org_id": ORG, "source_record_id": "job-1", "status": "pending"}])


class TestHostingRoutes(_JobBase):
    def test_list_all_and_mine(self):
        with _c() as c:
            assert len(c.get(f"{BASE}/hosting-jobs").json()["data"]) == 1
            assert c.get(f"{BASE}/hosting-jobs?mine=true").json()["data"] == []
            c.patch(f"{BASE}/hosting-jobs/job-1", json={"assigned_to": USER})
            mine = c.get(f"{BASE}/hosting-jobs?mine=true").json()["data"]
        assert [j["id"] for j in mine] == ["job-1"] and mine[0]["assigned_name"] == "Trust"

    def test_patch_only_touches_fields_that_were_sent(self):
        with _c() as c:
            c.patch(f"{BASE}/hosting-jobs/job-1", json={"assigned_to": USER})
            c.patch(f"{BASE}/hosting-jobs/job-1", json={"notes": "called QServers"})          # assignment must survive
            assert self.db.rows("site_hosting_jobs")[0]["assigned_to"] == USER
            c.patch(f"{BASE}/hosting-jobs/job-1", json={"assigned_to": None})                 # explicit null unassigns
        assert self.db.rows("site_hosting_jobs")[0]["assigned_to"] is None
        assert self.db.rows("site_hosting_jobs")[0]["notes"] == "called QServers"

    def test_patch_validation(self):
        with _c() as c:
            assert c.patch(f"{BASE}/hosting-jobs/job-1", json={"status": "done"}).status_code == 422
            assert c.patch(f"{BASE}/hosting-jobs/job-1", json={"status": "weird"}).status_code == 422
            assert c.patch(f"{BASE}/hosting-jobs/job-1", json={"step": "nonsense"}).status_code == 422
            assert c.patch(f"{BASE}/hosting-jobs/job-1", json={"assigned_to": "not-a-user"}).status_code == 422
            assert c.patch(f"{BASE}/hosting-jobs/job-1", json={"notes": "x" * 5001}).status_code == 422
            assert c.patch(f"{BASE}/hosting-jobs/nope", json={"notes": "x"}).status_code == 404

    def test_checklist_step(self):
        with _c() as c:
            r = c.patch(f"{BASE}/hosting-jobs/job-1", json={"step": "buy_hosting", "step_done": True})
        assert r.status_code == 200
        assert next(s for s in r.json()["data"]["checklist"] if s["key"] == "buy_hosting")["done"] is True

    def test_recheck_and_backup(self, monkeypatch):
        from app.services import domain_check_service as dcs
        table = {"adaezastyles.com.ng": False, "adaezastyles.ng": True}
        monkeypatch.setattr(dcs, "check_availability_fresh", lambda db, org, d: (d, table.get(d)))
        with _c() as c:
            r = c.post(f"{BASE}/hosting-jobs/job-1/recheck-domain")
            assert r.status_code == 200 and r.json()["data"]["available"] is False
            r = c.post(f"{BASE}/hosting-jobs/job-1/use-backup")
            assert r.status_code == 200 and r.json()["data"]["job"]["domain_used"] == "adaezastyles.ng"

    def test_mark_live_validates_then_publishes(self, monkeypatch):
        monkeypatch.setattr(pricing_service, "quote", lambda *a, **k: {"cost": {"domain": 1, "hosting": 2}})
        monkeypatch.setattr(ops, "_default_http_get", lambda url: _Resp(200))
        with _c() as c:
            assert c.post(f"{BASE}/hosting-jobs/job-1/mark-live", json={}).status_code == 422
            assert c.post(f"{BASE}/hosting-jobs/job-1/mark-live", json={"live_url": "http://adaezastyles.com.ng"}).status_code == 422
            assert c.post(f"{BASE}/hosting-jobs/job-1/mark-live", json={"live_url": "https://elsewhere.com"}).status_code == 422
            r = c.post(f"{BASE}/hosting-jobs/job-1/mark-live", json={"live_url": "https://adaezastyles.com.ng"})
            assert r.status_code == 200 and r.json()["data"]["order_status"] == "live"
            assert c.post(f"{BASE}/hosting-jobs/job-1/mark-live", json={"live_url": "https://adaezastyles.com.ng"}).status_code == 409
        assert self.db.rows("sites")[0]["status"] == "live" and len(self.db.rows("site_domains")) == 1
        assert self.messages == ["Your client's website is live: https://adaezastyles.com.ng"]

    def test_mark_live_non_200_is_422(self, monkeypatch):
        monkeypatch.setattr(ops, "_default_http_get", lambda url: _Resp(502))
        with _c() as c:
            r = c.post(f"{BASE}/hosting-jobs/job-1/mark-live", json={"live_url": "https://adaezastyles.com.ng"})
        assert r.status_code == 422 and "502" in r.json()["detail"]["message"]
        assert self.db.rows("site_orders")[0]["status"] == "fulfilling"


# ═══════════════════════════ Renewals (SITE-4) ═══════════════════════════

class TestRenewalRoutes(_JobBase):
    def test_mark_renewed_rejects_non_renewal_job_and_checks_roles(self):
        with _c() as c:
            r = c.post(f"{BASE}/hosting-jobs/job-1/mark-renewed")
            assert r.status_code == 409 and "not a renewal" in r.json()["detail"]["message"]
            self.template = "admin"
            assert c.post(f"{BASE}/hosting-jobs/job-1/mark-renewed").status_code == 403
            assert c.post(f"{BASE}/domains/d-1/renewal-link").status_code == 403
            self.template = "owner"
            assert c.post(f"{BASE}/hosting-jobs/nope/mark-renewed").status_code == 404
            assert c.post(f"{BASE}/domains/nope/renewal-link").status_code == 404


class TestCareLinkRoute(_Base):
    def test_care_link_roles_and_errors(self, monkeypatch):
        from app.services import site_care_plan_service as care
        monkeypatch.setattr(care, "send_care_link", lambda db, org, sid, what: {"checkout_url": "https://pay.test/c", "amount": 5000,
                                                                                  "kind": "care_plan", "sent": True})
        with _c() as c:
            r = c.post(f"{BASE}/site-1/care-link", json={"what": "plan"})
            assert r.status_code == 200 and r.json()["data"]["checkout_url"] == "https://pay.test/c"
            self.template = "admin"
            assert c.post(f"{BASE}/site-1/care-link", json={"what": "plan"}).status_code == 403
            self.template = "owner"

            def _blocked(*a, **k):
                raise care.CarePlanBlocked("not live")
            monkeypatch.setattr(care, "send_care_link", _blocked)
            assert c.post(f"{BASE}/site-1/care-link", json={"what": "plan"}).status_code == 422

    def test_staff_site_list_carries_care_columns(self):
        with _c() as c:
            items = c.get(f"{BASE}").json()["data"]["items"]
        assert items and all("edits_left" in i and "care_plan_status" in i for i in items)


# ═══════════════════════════ Domains ═══════════════════════════

class TestDomainsRoutes(_Base):
    def make_db(self):
        d = lambda i, dom, days: {"id": i, "org_id": ORG, "site_id": "site-1", "domain": dom, "registrar": "qservers", "route": "standard",
                                  "renews_on": (INSIDE.date() + timedelta(days=days)).isoformat(),
                                  "hosting_renews_on": (INSIDE.date() + timedelta(days=days)).isoformat(),
                                  "registrar_cost_renewal": 6000, "hosting_cost_renewal": 37000, "status": "active"}
        return _seed(site_domains=[d("d1", "a.com", 200), d("d2", "b.com", 6), d("d3", "c.com", 13)])

    def test_list_and_expiring_filters(self):
        with _c() as c:
            assert [r["domain"] for r in c.get(f"{BASE}/domains").json()["data"]] == ["b.com", "c.com", "a.com"]
            assert [r["domain"] for r in c.get(f"{BASE}/domains?expiring_within=7").json()["data"]] == ["b.com"]
            assert [r["domain"] for r in c.get(f"{BASE}/domains?expiring_within=14").json()["data"]] == ["b.com", "c.com"]
            assert c.get(f"{BASE}/domains?expiring_within=-1").status_code == 422
            assert c.get(f"{BASE}/domains?expiring_within=abc").status_code == 422


# ═══════════════════════════ Guards ═══════════════════════════

class TestGuards(_JobBase):
    def test_pattern_53_static_paths_are_not_swallowed_by_site_id(self):
        """GET /sites/orders etc. must hit their own handlers, never get_site('orders')."""
        with _c() as c:
            for path, key in (("orders", "items"), ("forms", None), ("hosting-jobs", None), ("domains", None)):
                r = c.get(f"{BASE}/{path}")
                assert r.status_code == 200, (path, r.text)
                data = r.json()["data"]
                assert not (isinstance(data, dict) and "client_business_name" in data), f"/{path} was routed to get_site"
                if key:
                    assert key in data
            # …and a real site id still resolves.
            assert c.get(f"{BASE}/site-1").json()["data"]["client_business_name"] == "Adaeze Styles"

    def test_rbac_matrix(self):
        def status(template, method, path, **kw):
            self.template = template
            with _c() as c:
                return getattr(c, method)(f"{BASE}{path}", **kw).status_code

        # reading: owner, admin, ops_manager
        for t in ("owner", "admin", "ops_manager"):
            for p in ("/orders", "/hosting-jobs", "/domains"):
                assert status(t, "get", p) == 200, (t, p)
        assert status("sales_agent", "get", "/orders") == 403
        assert status("sales_agent", "get", "/hosting-jobs") == 403
        assert status("sales_agent", "get", "/domains") == 403
        # money actions: owner only (spec §17)
        for t in ("admin", "ops_manager", "sales_agent"):
            assert status(t, "post", "/orders/ord-1/approve") == 403, t
            assert status(t, "post", "/orders/ord-1/reject", json={"reason": "nope nope"}) == 403, t
            assert status(t, "post", "/orders/ord-1/refund-recorded", json={}) == 403, t
        # hosting-job work: owner + ops_manager write, admin read-only
        assert status("ops_manager", "patch", "/hosting-jobs/job-1", json={"notes": "x"}) == 200
        assert status("admin", "patch", "/hosting-jobs/job-1", json={"notes": "x"}) == 403
        assert status("admin", "post", "/hosting-jobs/job-1/recheck-domain") == 403
        assert status("admin", "post", "/hosting-jobs/job-1/mark-live", json={"live_url": "https://adaezastyles.com.ng"}) == 403
        assert status("admin", "post", "/orders/ord-1/set-domain", json={"domain": "x.com.ng"}) == 403

    def test_whole_feature_404s_when_site_builder_is_off(self):
        self.db.tables["site_builder_settings"][0]["enabled"] = False
        with _c() as c:
            for method, path, kw in (("get", "/orders", {}), ("get", "/hosting-jobs", {}), ("get", "/domains", {}),
                                     ("post", "/orders/ord-1/approve", {}), ("patch", "/hosting-jobs/job-1", {"json": {"notes": "x"}}),
                                     ("get", "/site-1/export.zip", {})):
                assert getattr(c, method)(f"{BASE}{path}", **kw).status_code == 404, path
        assert self.db.rows("site_orders")[0]["status"] == "fulfilling"   # nothing was touched


# ═══════════════════════════ Export ═══════════════════════════

class TestExportRoute(_Base):
    def make_db(self):
        from app.routers import sites as sites_router
        db = _seed(
            sites=[{"id": "site-1", "org_id": ORG, "builder_id": "b-1", "preset_id": "p1", "client_business_name": "Adaeze Styles",
                    "slug": "adaeze-styles-abc123", "status": "live", "deleted_at": None, "content": sites_router._SAMPLE_CONTENT,
                    "recipe": {"theme": "atelier", "palette": "berry", "order": ["hero", "items", "order"], "hidden": []}}],
            site_presets=[{"id": "p1", "org_id": ORG, "key": "boutique"}],
            site_assets=[{"id": "as1", "site_id": "site-1", "slot": "hero", "storage_path": "site-1/hero.jpg", "mime_type": "image/jpeg"}],
        )
        db.storage = _Storage({"site-1/hero.jpg": b"JPEG"})
        return db

    def test_download(self):
        with _c() as c:
            r = c.get(f"{BASE}/site-1/export.zip")
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        assert 'filename="adaeze-styles-abc123-export.zip"' in r.headers["content-disposition"]
        assert "index.html" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assert self.db.rows("site_events")[-1]["event"] == "export_downloaded"

    def test_unknown_site_404_and_export_is_not_confused_with_get_site(self):
        with _c() as c:
            assert c.get(f"{BASE}/nope/export.zip").status_code == 404

    def test_sales_agent_cannot_download(self):
        self.template = "sales_agent"
        with _c() as c:
            assert c.get(f"{BASE}/site-1/export.zip").status_code == 403


# ═══════════════════════════ Overview ═══════════════════════════

class TestOverview(_Base):
    def test_overview_includes_order_kpis(self):
        with _c() as c:
            r = c.get(f"{BASE}/overview")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["sites_total"] == 1 and d["orders"]["orders_awaiting_approval"] == 1 and d["orders"]["orders_paid"] == 1

    def test_overview_survives_a_kpi_failure(self, monkeypatch):
        monkeypatch.setattr(ops, "order_kpis", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with _c() as c:
            r = c.get(f"{BASE}/overview")
        assert r.status_code == 200 and r.json()["data"]["orders"] is None and r.json()["data"]["sites_total"] == 1
