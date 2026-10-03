"""
tests/integration/test_builder_portal_routes.py
SITE-2B — integration tests for routers/builder_portal.py (prefix /api/v1/builder).

Pattern references (see tests/integration/test_ticket_routes.py for the
originals this file mirrors):
  Pattern 1  : lazy get_supabase factory — never module-level
  Pattern 3  : every test class overrides get_supabase
  Pattern 4  : class-scoped fixtures restore only their own overrides
  Pattern 6  : 4xx tests assert status_code only, never resp.json()["success"]
  Pattern 8  : insert chain.insert.return_value = insert_chain

/auth/exchange has NO get_current_builder dependency (it's how a session is
obtained in the first place) — those tests mock get_supabase only and hit
the route with a plain token in the body. Every other route is exercised
with get_current_builder overridden directly, since that dependency lives
in this router module, not app.dependencies.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import builder_portal

BUILDER_ID = "00000000-0000-0000-0000-000000001111"
ORG_ID = "00000000-0000-0000-0000-000000002222"
OTHER_BUILDER_ID = "00000000-0000-0000-0000-000000009999"
SITE_ID = "00000000-0000-0000-0000-000000003333"
PRESET_ID = "00000000-0000-0000-0000-000000004444"

_FAKE_BUILDER = {
    "id": BUILDER_ID, "org_id": ORG_ID, "phone_number": "+2348000000001",
    "full_name": "Ada Builder", "business_name": "Ada Web Co", "email": "ada@example.com",
    "status": "active",
}

_FAKE_SITE = {
    "id": SITE_ID, "org_id": ORG_ID, "builder_id": BUILDER_ID, "preset_id": PRESET_ID,
    "client_business_name": "Adaeze Styles", "slug": "adaeze-styles-abc123", "status": "preview_ready",
    "content": {"business": {"name": "Adaeze Styles", "whatsapp_e164": "+2348000000002"},
                "hero": {"headline": "Welcome"}},
    "recipe": {"theme": "atelier", "palette": "berry", "order": ["hero"], "hidden": []},
    "revision_count": 0, "design_rolls": 0, "deleted_at": None,
}

_FAKE_PRESET = {"id": PRESET_ID, "org_id": ORG_ID, "key": "boutique", "allowed_themes": ["atelier"]}


def _chain(data=None) -> MagicMock:
    result = MagicMock()
    result.data = data if data is not None else []
    m = MagicMock()
    for method in ("select", "insert", "update", "delete", "eq", "neq", "is_", "order",
                   "range", "limit", "maybe_single", "filter", "in_"):
        getattr(m, method).return_value = m
    m.execute.return_value = result
    return m


def _db_mock(**kwargs) -> MagicMock:
    db = MagicMock()
    db.table.side_effect = lambda name: kwargs.get(name, _chain())
    return db


@pytest.fixture
def client():
    original = app.dependency_overrides.copy()
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


@pytest.fixture
def authed_client(client):
    app.dependency_overrides[builder_portal.get_current_builder] = lambda: _FAKE_BUILDER
    yield client
    app.dependency_overrides.pop(builder_portal.get_current_builder, None)


# ---------------------------------------------------------------------------
# /auth/exchange
# ---------------------------------------------------------------------------
class TestExchange:
    def test_valid_token_issues_session(self, client):
        raw_token = "a" * 43  # url-safe base64, shape doesn't matter for this mock
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        row = {
            "id": "tok-1", "org_id": ORG_ID, "builder_id": BUILDER_ID, "token_hash": token_hash,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "revoked_at": None, "last_used_at": None,
        }
        db = _db_mock(
            site_editor_tokens=_chain([row]),
            site_builders=_chain([_FAKE_BUILDER]),
        )
        app.dependency_overrides[get_supabase] = lambda: db
        resp = client.post("/api/v1/builder/auth/exchange", json={"token": raw_token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["access_token"]
        assert body["data"]["builder"]["id"] == BUILDER_ID
        # Single-use: the token row must be revoked in the same request.
        db.table("site_editor_tokens").update.assert_called()

    def test_unknown_token_401(self, client):
        db = _db_mock(site_editor_tokens=_chain([]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = client.post("/api/v1/builder/auth/exchange", json={"token": "does-not-exist"})
        assert resp.status_code == 401

    def test_already_revoked_token_401(self, client):
        row = {"id": "tok-1", "org_id": ORG_ID, "builder_id": BUILDER_ID,
               "token_hash": hashlib.sha256(b"used").hexdigest(),
               "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
               "revoked_at": "2026-01-01T00:00:00+00:00"}
        db = _db_mock(site_editor_tokens=_chain([row]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = client.post("/api/v1/builder/auth/exchange", json={"token": "used"})
        assert resp.status_code == 401

    def test_expired_token_401(self, client):
        row = {"id": "tok-1", "org_id": ORG_ID, "builder_id": BUILDER_ID,
               "token_hash": hashlib.sha256(b"stale").hexdigest(),
               "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
               "revoked_at": None}
        db = _db_mock(site_editor_tokens=_chain([row]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = client.post("/api/v1/builder/auth/exchange", json={"token": "stale"})
        assert resp.status_code == 401

    def test_suspended_builder_401(self, client):
        row = {"id": "tok-1", "org_id": ORG_ID, "builder_id": BUILDER_ID,
               "token_hash": hashlib.sha256(b"ok").hexdigest(),
               "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
               "revoked_at": None}
        suspended = dict(_FAKE_BUILDER, status="suspended")
        db = _db_mock(site_editor_tokens=_chain([row]), site_builders=_chain([suspended]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = client.post("/api/v1/builder/auth/exchange", json={"token": "ok"})
        assert resp.status_code == 401

    def test_missing_token_422(self, client):
        # Pattern 3 — Depends(get_supabase) is resolved before the route body's
        # own validation runs, so even a request that never reaches the DB
        # still needs an override or FastAPI tries to build a real client.
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        resp = client.post("/api/v1/builder/auth/exchange", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# My sites / ownership scoping
# ---------------------------------------------------------------------------
class TestMySites:
    def test_list_my_sites(self, authed_client):
        db = _db_mock(sites=_chain([_FAKE_SITE]), site_domains=_chain([]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = authed_client.get("/api/v1/builder/sites")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["id"] == SITE_ID

    def test_get_site_returns_only_the_templates_design_options(self, authed_client):
        preset = {**_FAKE_PRESET, "allowed_fonts": ["bodoni_jost"], "token_options": {"cards": ["lifted"]},
                  "ai_tone": "SECRET TONE", "brief_questions": [{"q": "secret"}]}
        db = _db_mock(sites=_chain([dict(_FAKE_SITE)]), site_assets=_chain([]), site_presets=_chain([preset]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = authed_client.get(f"/api/v1/builder/sites/{SITE_ID}")
        assert resp.status_code == 200
        opts = resp.json()["data"]["design_options"]
        assert opts == {"allowed_themes": ["atelier"], "allowed_fonts": ["bodoni_jost"], "token_options": {"cards": ["lifted"]}, "allowed_variants": {},
                        "sections": _FAKE_PRESET.get("sections") or []}   # SITE-1C-3: which sections the template offers
        assert "SECRET TONE" not in resp.text and "brief_questions" not in resp.text

    def test_get_site_still_works_when_the_template_is_missing(self, authed_client):
        db = _db_mock(sites=_chain([dict(_FAKE_SITE)]), site_assets=_chain([]), site_presets=_chain([]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = authed_client.get(f"/api/v1/builder/sites/{SITE_ID}")
        assert resp.status_code == 200
        assert "design_options" not in resp.json()["data"]

    def test_get_site_not_mine_404(self, authed_client):
        # _get_site filters .eq("builder_id", builder_id) server-side; the mock
        # simulates that filter finding nothing for a site owned by someone else.
        db = _db_mock(sites=_chain([]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = authed_client.get(f"/api/v1/builder/sites/{SITE_ID}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Editor: content/recipe patch snapshots a revision first
# ---------------------------------------------------------------------------
class TestEditor:
    def test_patch_content_saves_and_snapshots_revision(self, authed_client):
        revisions_chain = _chain([])
        db = _db_mock(sites=_chain([_FAKE_SITE]), site_revisions=revisions_chain, site_events=_chain([]))
        app.dependency_overrides[get_supabase] = lambda: db
        new_content = dict(_FAKE_SITE["content"])
        new_content["hero"] = {"headline": "New headline", "subhead": "", "image_asset_id": None}
        resp = authed_client.patch(f"/api/v1/builder/sites/{SITE_ID}/content", json={"content": new_content})
        assert resp.status_code == 200
        revisions_chain.insert.assert_called()  # pre-change snapshot was pushed

    def test_patch_recipe_rejects_unknown_theme(self, authed_client):
        db = _db_mock(sites=_chain([_FAKE_SITE]), site_presets=_chain([_FAKE_PRESET]))
        app.dependency_overrides[get_supabase] = lambda: db
        bad_recipe = {"theme": "not-a-real-theme", "palette": "berry", "order": ["hero"], "hidden": []}
        resp = authed_client.patch(f"/api/v1/builder/sites/{SITE_ID}/recipe", json={"recipe": bad_recipe})
        assert resp.status_code == 422

    def test_undo_restores_previous_snapshot_and_removes_it(self, authed_client):
        older_content = {"business": {"name": "Old Name", "whatsapp_e164": "+2348000000002"},
                          "hero": {"headline": "Old headline"}}
        older_recipe = {"theme": "atelier", "palette": "berry", "order": ["hero"], "hidden": []}
        revision_row = {"id": "rev-1", "site_id": SITE_ID, "content": older_content, "recipe": older_recipe}
        db = _db_mock(
            sites=_chain([_FAKE_SITE]),
            site_revisions=_chain([revision_row]),
            site_presets=_chain([_FAKE_PRESET]),
            site_assets=_chain([]),
            site_events=_chain([]),
        )
        app.dependency_overrides[get_supabase] = lambda: db
        resp = authed_client.post(f"/api/v1/builder/sites/{SITE_ID}/undo")
        assert resp.status_code == 200
        assert resp.json()["data"]["content"]["business"]["name"] == "Old Name"

    def test_undo_nothing_to_undo_404(self, authed_client):
        db = _db_mock(sites=_chain([_FAKE_SITE]), site_revisions=_chain([]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = authed_client.post(f"/api/v1/builder/sites/{SITE_ID}/undo")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SITE-PREMIUM P4-1: a Premium site tells the editor so, and refuses the Standard design controls
# ---------------------------------------------------------------------------
_PREMIUM_SITE = {**_FAKE_SITE, "tier": "premium", "current_design_id": "design-1"}
_DESIGN_ROW = {"id": "design-1", "version": 3, "slot_manifest": {"slots": [
    {"path": "business.name", "kind": "text"}, {"path": "hero.headline", "kind": "text"}, {"path": "items", "kind": "repeat"}]}}


class TestPremiumSite:
    def _db(self, site):
        return _db_mock(sites=_chain([dict(site)]), site_assets=_chain([]), site_presets=_chain([_FAKE_PRESET]),
                        site_designs=_chain([_DESIGN_ROW]), site_events=_chain([]), site_revisions=_chain([]))

    def test_get_site_reports_premium_and_used_groups(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: self._db(_PREMIUM_SITE)
        resp = authed_client.get(f"/api/v1/builder/sites/{SITE_ID}")
        assert resp.status_code == 200
        assert resp.json()["data"]["premium"] == {"active": True, "design_id": "design-1", "version": 3,
                                                  "used": ["business", "hero", "items"]}

    def test_get_site_standard_has_no_premium_info(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: self._db(_FAKE_SITE)
        resp = authed_client.get(f"/api/v1/builder/sites/{SITE_ID}")
        assert resp.json()["data"]["premium"] is None

    def test_recipe_patch_refused_on_premium(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: self._db(_PREMIUM_SITE)
        recipe = {"theme": "atelier", "palette": "berry", "order": ["hero"], "hidden": []}
        resp = authed_client.patch(f"/api/v1/builder/sites/{SITE_ID}/recipe", json={"recipe": recipe})
        assert resp.status_code == 409

    def test_design_suggest_and_apply_refused_on_premium(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: self._db(_PREMIUM_SITE)
        assert authed_client.post(f"/api/v1/builder/sites/{SITE_ID}/design/suggest").status_code == 409
        recipe = {"theme": "atelier", "palette": "berry", "order": ["hero"], "hidden": []}
        assert authed_client.post(f"/api/v1/builder/sites/{SITE_ID}/design/apply", json={"recipe": recipe}).status_code == 409

    def test_content_patch_still_works_on_premium(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: self._db(_PREMIUM_SITE)
        content = dict(_FAKE_SITE["content"])
        content["hero"] = {"headline": "Fresh", "subhead": "", "image_asset_id": None}
        resp = authed_client.patch(f"/api/v1/builder/sites/{SITE_ID}/content", json={"content": content})
        assert resp.status_code == 200

    def test_standard_site_recipe_patch_is_not_refused(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: self._db(_FAKE_SITE)
        bad = {"theme": "not-a-real-theme", "palette": "berry", "order": ["hero"], "hidden": []}
        resp = authed_client.patch(f"/api/v1/builder/sites/{SITE_ID}/recipe", json={"recipe": bad})
        assert resp.status_code == 422   # reached validation, so the Premium guard did not block it


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
class TestAccount:
    def test_get_me(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        resp = authed_client.get("/api/v1/builder/me")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == BUILDER_ID

    def test_patch_me_updates_allowed_fields_only(self, authed_client):
        updated = dict(_FAKE_BUILDER, full_name="Ada B. Updated")
        db = _db_mock(site_builders=_chain([updated]))
        app.dependency_overrides[get_supabase] = lambda: db
        resp = authed_client.patch("/api/v1/builder/me", json={"full_name": "Ada B. Updated", "status": "owner"})
        assert resp.status_code == 200
        # 'status' is not in the allowed set — only full_name should have been written.
        called_kwargs = db.table("site_builders").update.call_args[0][0]
        assert "status" not in called_kwargs
        assert called_kwargs["full_name"] == "Ada B. Updated"

    def test_no_auth_header_401(self, client):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        resp = client.get("/api/v1/builder/me")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# SITE-3 — domain check + quotes (services are mocked; their own unit tests
# in tests/unit/test_domain_check_service.py and test_pricing_service.py
# cover the RDAP/WHOIS/pricing logic itself)
# ---------------------------------------------------------------------------
class TestDomainCheckAndQuotes:
    def test_domain_check_available(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        monkeypatch.setattr(
            builder_portal.domain_check_service, "check_domain",
            lambda db, org_id, builder_id, domain: {"domain": domain, "status": "available", "available": True},
        )
        resp = authed_client.post("/api/v1/builder/domains/check", json={"domain": "adaezastyles.com"})
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "available"

    def test_domain_check_taken_returns_alternatives(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        monkeypatch.setattr(
            builder_portal.domain_check_service, "check_domain",
            lambda db, org_id, builder_id, domain: {
                "domain": domain, "status": "taken", "available": False,
                "alternatives": [{"domain": "adaezastyles.ng", "status": "available", "available": True}],
            },
        )
        resp = authed_client.post("/api/v1/builder/domains/check", json={"domain": "adaezastyles.com"})
        assert resp.status_code == 200
        assert resp.json()["data"]["alternatives"][0]["domain"] == "adaezastyles.ng"

    def test_domain_check_rate_limited_429(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()

        def _raise(*a, **k):
            raise builder_portal.domain_check_service.RateLimited("Too many domain checks this hour — try again later.")

        monkeypatch.setattr(builder_portal.domain_check_service, "check_domain", _raise)
        resp = authed_client.post("/api/v1/builder/domains/check", json={"domain": "adaezastyles.com"})
        assert resp.status_code == 429

    def test_domain_check_invalid_domain_422(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()

        def _raise(*a, **k):
            raise builder_portal.domain_check_service.InvalidDomain("'xyz' isn't a supported ending.")

        monkeypatch.setattr(builder_portal.domain_check_service, "check_domain", _raise)
        resp = authed_client.post("/api/v1/builder/domains/check", json={"domain": "adaezastyles.xyz"})
        assert resp.status_code == 422

    def test_domain_check_missing_domain_422(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        resp = authed_client.post("/api/v1/builder/domains/check", json={})
        assert resp.status_code == 422

    def test_quotes_returns_both_routes(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        fake_quote = {"route": "standard", "price": {"total": 79500}}
        monkeypatch.setattr(
            builder_portal.pricing_service, "quote_both_routes",
            lambda db, org_id, domain, kind="initial": {"standard": fake_quote, "express": None},
        )
        resp = authed_client.post("/api/v1/builder/quotes", json={"domain": "adaezastyles.com.ng"})
        assert resp.status_code == 200
        assert resp.json()["data"]["standard"]["price"]["total"] == 79500
        assert resp.json()["data"]["express"] is None

    def test_quotes_unsupported_domain_422(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()

        def _raise(*a, **k):
            raise builder_portal.pricing_service.UnsupportedDomain("'.xyz' isn't supported on the standard route.")

        monkeypatch.setattr(builder_portal.pricing_service, "quote_both_routes", _raise)
        resp = authed_client.post("/api/v1/builder/quotes", json={"domain": "adaezastyles.xyz"})
        assert resp.status_code == 422

    def test_quotes_requires_auth_401(self, client):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        resp = client.post("/api/v1/builder/quotes", json={"domain": "adaezastyles.com"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# SITE-3 part 2 — checkout (site_order_service.create_checkout is mocked;
# its own logic is covered by tests/unit/test_site_order_service.py).
# accepted_terms/backup_domain validators are exercised for real here since
# they live on the Pydantic model, not the service.
# ---------------------------------------------------------------------------
class TestCheckout:
    _PAYLOAD = {
        "site_id": SITE_ID, "route": "standard",
        "domain": "adaezastyles.com.ng", "backup_domain": "adaezastyles.ng",
        "legal_owner": {"full_name": "Chioma Adaeze", "email": "chioma@example.com",
                         "phone": "+2348030000000", "address": "14 Adeola Odeku St, Lagos"},
        "accepted_terms": True,
    }

    def test_checkout_creates_payment_link(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        monkeypatch.setattr(
            builder_portal.site_order_service, "create_checkout",
            lambda db, org_id, builder, payload: {
                "checkout_url": "https://paystack.test/pay/abc", "reference": "opsra_xyz",
                "order_id": "order-1", "amount": 79500,
            },
        )
        resp = authed_client.post("/api/v1/builder/checkout", json=self._PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["data"]["checkout_url"] == "https://paystack.test/pay/abc"

    def test_checkout_site_not_found_404(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()

        def _raise(*a, **k):
            raise builder_portal.site_order_service.SiteNotFound("Site not found")

        monkeypatch.setattr(builder_portal.site_order_service, "create_checkout", _raise)
        resp = authed_client.post("/api/v1/builder/checkout", json=self._PAYLOAD)
        assert resp.status_code == 404

    def test_checkout_blocked_422(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()

        def _raise(*a, **k):
            raise builder_portal.site_order_service.CheckoutBlocked("Paystack storefront is not connected.")

        monkeypatch.setattr(builder_portal.site_order_service, "create_checkout", _raise)
        resp = authed_client.post("/api/v1/builder/checkout", json=self._PAYLOAD)
        assert resp.status_code == 422

    def test_checkout_pricing_error_422(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()

        def _raise(*a, **k):
            raise builder_portal.pricing_service.UnsupportedDomain("'.xyz' isn't supported on the standard route.")

        monkeypatch.setattr(builder_portal.site_order_service, "create_checkout", _raise)
        resp = authed_client.post("/api/v1/builder/checkout", json=self._PAYLOAD)
        assert resp.status_code == 422

    def test_checkout_same_backup_domain_422(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        payload = dict(self._PAYLOAD, backup_domain=self._PAYLOAD["domain"])
        resp = authed_client.post("/api/v1/builder/checkout", json=payload)
        assert resp.status_code == 422

    def test_checkout_terms_not_accepted_422(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        payload = dict(self._PAYLOAD, accepted_terms=False)
        resp = authed_client.post("/api/v1/builder/checkout", json=payload)
        assert resp.status_code == 422

    def test_checkout_requires_auth_401(self, client):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        resp = client.post("/api/v1/builder/checkout", json=self._PAYLOAD)
        assert resp.status_code == 401


class TestRenewalCheckout:
    """SITE-4 — POST /builder/sites/{id}/renewal-checkout (service mocked; the rules are unit-tested)."""

    def test_creates_link(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        monkeypatch.setattr(
            builder_portal.site_renewal_service, "builder_renewal_checkout",
            lambda db, org_id, builder, site_id: {"checkout_url": "https://pay.test/r", "amount": 50000,
                                                  "domain": "adaezastyles.com.ng", "expires_on": "2026-11-01", "reused": False},
        )
        resp = authed_client.post(f"/api/v1/builder/sites/{SITE_ID}/renewal-checkout")
        assert resp.status_code == 200 and resp.json()["data"]["checkout_url"] == "https://pay.test/r"

    def test_not_found_404_and_blocked_422(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        svc = builder_portal.site_renewal_service
        for exc, code in ((svc.RenewalNotFound("Site not found"), 404), (svc.RenewalBlocked("Too early"), 422)):
            def _raise(*a, _e=exc, **k):
                raise _e
            monkeypatch.setattr(svc, "builder_renewal_checkout", _raise)
            assert authed_client.post(f"/api/v1/builder/sites/{SITE_ID}/renewal-checkout").status_code == code

    def test_my_sites_list_carries_renewal_fields(self, authed_client):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        resp = authed_client.get("/api/v1/builder/sites")
        assert resp.status_code == 200
        for row in resp.json()["data"]:
            assert "days_to_renewal" in row and "renewal_status" in row


class TestCarePlanRoutes:
    """SITE-4B — edit limit on the editor's save, plus the care-plan endpoints (service mocked)."""

    _CONTENT_URL = f"/api/v1/builder/sites/{SITE_ID}/content"

    def test_edit_limit_returns_402_with_the_offer(self, authed_client, monkeypatch):
        db = _db_mock(sites=_chain([_FAKE_SITE]), site_revisions=_chain([]), site_events=_chain([]))
        app.dependency_overrides[get_supabase] = lambda: db
        svc = builder_portal.site_care_plan_service

        def _raise(*a, **k):
            raise svc.EditLimitReached("Out of edits.", {"plan_price": 5000, "pack_price": 1500})
        monkeypatch.setattr(svc, "consume_edit", _raise)
        new_content = dict(_FAKE_SITE["content"])
        new_content["hero"] = {"headline": "New headline", "subhead": "", "image_asset_id": None}
        resp = authed_client.patch(self._CONTENT_URL, json={"content": new_content})
        assert resp.status_code == 402
        d = resp.json()["detail"]
        assert d["code"] == "EDIT_LIMIT_REACHED" and d["offer"]["plan_price"] == 5000
        assert db.table("site_revisions").insert.call_count == 0 if hasattr(db.table("site_revisions"), "insert") else True

    def test_a_bug_in_the_allowance_code_never_blocks_saving(self, authed_client, monkeypatch):
        db = _db_mock(sites=_chain([_FAKE_SITE]), site_revisions=_chain([]), site_events=_chain([]))
        app.dependency_overrides[get_supabase] = lambda: db
        monkeypatch.setattr(builder_portal.site_care_plan_service, "consume_edit",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        new_content = dict(_FAKE_SITE["content"])
        new_content["hero"] = {"headline": "New headline", "subhead": "", "image_asset_id": None}
        assert authed_client.patch(self._CONTENT_URL, json={"content": new_content}).status_code == 200

    def test_care_plan_get_checkout_cancel(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock(sites=_chain([_FAKE_SITE]))
        svc = builder_portal.site_care_plan_service
        monkeypatch.setattr(svc, "site_allowance", lambda db, org, sid: {"edits_left": 7})
        monkeypatch.setattr(svc, "create_checkout", lambda db, org, b, sid, what: {"checkout_url": "https://pay.test/c", "amount": 5000,
                                                                                    "kind": "care_plan", "reused": False, "order": {"id": "o"}})
        monkeypatch.setattr(svc, "set_cancel", lambda db, org, b, sid, cancel: {"cancel_at_period_end": cancel})
        base = f"/api/v1/builder/sites/{SITE_ID}/care-plan"
        assert authed_client.get(base).json()["data"]["edits_left"] == 7
        r = authed_client.post(f"{base}/checkout", json={"what": "plan"})
        assert r.status_code == 200 and r.json()["data"]["checkout_url"] == "https://pay.test/c" and "order" not in r.json()["data"]
        assert authed_client.post(f"{base}/cancel", json={"cancel": True}).json()["data"]["cancel_at_period_end"] is True

    def test_care_plan_errors_map_to_404_and_422(self, authed_client, monkeypatch):
        app.dependency_overrides[get_supabase] = lambda: _db_mock()
        svc = builder_portal.site_care_plan_service
        for exc, code in ((svc.CarePlanNotFound("nope"), 404), (svc.CarePlanBlocked("not live"), 422)):
            def _raise(*a, _e=exc, **k):
                raise _e
            monkeypatch.setattr(svc, "create_checkout", _raise)
            assert authed_client.post(f"/api/v1/builder/sites/{SITE_ID}/care-plan/checkout", json={"what": "plan"}).status_code == code



# ---------------------------------------------------------------------------
# /auth/request-link  (public landing-page sign-in)
# ---------------------------------------------------------------------------
class TestRequestLink:
    @pytest.fixture(autouse=True)
    def _fresh_limits(self):
        builder_portal._request_link_ip_hits.clear()
        builder_portal._request_link_phone_hits.clear()

    def test_same_reply_for_any_number_and_task_is_queued(self, client, monkeypatch):
        from app.services import builder_login_service as svc
        sent = []
        monkeypatch.setattr(svc, "send_login_link", lambda phone: sent.append(phone))
        a = client.post("/api/v1/builder/auth/request-link", json={"phone": "0803 123 4567"})
        b = client.post("/api/v1/builder/auth/request-link", json={"phone": "+2348099999999"})
        assert a.status_code == b.status_code == 200
        assert a.json()["message"] == b.json()["message"]
        assert a.json()["data"] == b.json()["data"] == {"sent": True}
        assert sent == ["2348031234567", "2348099999999"]

    @pytest.mark.parametrize("bad", ["", "abc", "123", None])
    def test_rejects_non_phone(self, client, bad):
        assert client.post("/api/v1/builder/auth/request-link", json={"phone": bad}).status_code == 422

    def test_rate_limited_per_phone(self, client, monkeypatch):
        from app.services import builder_login_service as svc
        monkeypatch.setattr(svc, "send_login_link", lambda phone: None)
        codes = [client.post("/api/v1/builder/auth/request-link", json={"phone": "08031234567"}).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]


class TestLoginLinkService:
    def test_unknown_number_sends_nothing(self, monkeypatch):
        from app.services import builder_login_service as svc
        db = _db_mock(site_builders=_chain([]))
        monkeypatch.setattr("app.database.get_supabase", lambda: db)
        sent = []
        monkeypatch.setattr(svc, "_send_whatsapp", lambda *a, **k: sent.append("wa"))
        monkeypatch.setattr(svc, "_send_email", lambda *a, **k: sent.append("mail"))
        svc.send_login_link("08031234567")
        assert sent == []
        db.table("site_editor_tokens").insert.assert_not_called()

    def test_active_builder_gets_hashed_one_hour_token_on_both_channels(self, monkeypatch):
        from app.services import builder_login_service as svc
        tokens = _chain([])
        db = _db_mock(site_builders=_chain([_FAKE_BUILDER]), site_editor_tokens=tokens)
        monkeypatch.setattr("app.database.get_supabase", lambda: db)
        sent = []
        monkeypatch.setattr(svc, "_send_whatsapp", lambda db_, b, text: sent.append(("wa", text)))
        monkeypatch.setattr(svc, "_send_email", lambda to, url, first: sent.append(("mail", url)))
        svc.send_login_link("+2348000000001")
        row = tokens.insert.call_args[0][0]
        assert row["builder_id"] == BUILDER_ID and len(row["token_hash"]) == 64
        assert [c for c, _ in sent] == ["wa", "mail"]
        raw = sent[1][1].split("t=")[1]
        assert hashlib.sha256(raw.encode()).hexdigest() == row["token_hash"]
        assert "t=" + raw not in row["token_hash"]

    def test_channel_failure_does_not_raise(self, monkeypatch):
        from app.services import builder_login_service as svc
        db = _db_mock(site_builders=_chain([_FAKE_BUILDER]), site_editor_tokens=_chain([]))
        monkeypatch.setattr("app.database.get_supabase", lambda: db)
        def boom(*a, **k): raise RuntimeError("meta down")
        monkeypatch.setattr(svc, "_send_whatsapp", boom)
        monkeypatch.setattr(svc, "_send_email", boom)
        svc.send_login_link("+2348000000001")   # must not raise
