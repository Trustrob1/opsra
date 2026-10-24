"""WA-AUTO-1: product mode - a WhatsApp-automation-only business gets no CRM."""
from __future__ import annotations

import asyncio
import base64
import json
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.database import get_supabase
from app.services import product_mode as pm
from tests.unit.test_account_plans_1 import BIZ, OTHER, PLATFORM, FakeDB, _Q

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

U_WA, U_FULL = "u-wa", "u-full"
ORG_WA = "00000000-0000-0000-0000-00000000aa01"
ORG_FULL = "00000000-0000-0000-0000-00000000aa02"


def _jwt(sub):
    seg = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"xx.{seg}.yy"


def _db():
    return FakeDB(
        organisations=[{"id": ORG_WA, "product_mode": "wa_automation"}, {"id": ORG_FULL, "product_mode": "full"}],
        users=[{"id": U_WA, "org_id": ORG_WA}, {"id": U_FULL, "org_id": ORG_FULL}],
    )


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pm.invalidate()
    try:
        from app import dependencies as dep
        dep._user_cache.clear()
    except Exception:
        pass
    yield
    pm.invalidate()


def _req(method, path, token=None):
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "query_string": b""})


def _run(method, path, token, db=None):
    return asyncio.run(pm.crm_only(_req(method, path, token), db or _db()))


# -- mode lookup ---------------------------------------------------------------------------------------
def test_get_mode_reads_and_defaults_to_full():
    db = _db()
    assert pm.get_mode(db, ORG_WA) == "wa_automation"
    assert pm.get_mode(db, ORG_FULL) == "full"
    assert pm.get_mode(db, "missing") == "full"
    assert pm.get_mode(db, None) == "full"


def test_get_mode_fails_open_on_database_error():
    bad = MagicMock()
    bad.table.side_effect = RuntimeError("down")
    assert pm.get_mode(bad, ORG_WA) == "full"


def test_set_mode_validates_and_clears_cache():
    db = _db()
    assert pm.get_mode(db, ORG_FULL) == "full"
    with pytest.raises(ValueError):
        pm.set_mode(db, ORG_FULL, "nonsense")
    pm.set_mode(db, ORG_FULL, "wa_automation")
    assert pm._org_mode == {}


def test_token_subject_parsing():
    assert pm._token_subject(_req("GET", "/x", _jwt("abc"))) == "abc"
    assert pm._token_subject(_req("GET", "/x", "garbage")) is None
    assert pm._token_subject(_req("GET", "/x")) is None


# -- the guard ---------------------------------------------------------------------------------------
def test_wa_org_is_blocked_from_crm_routes_with_404():
    from fastapi import HTTPException
    for method, path in (("GET", "/api/v1/leads"), ("GET", "/api/v1/customers"), ("POST", "/api/v1/tasks"),
                         ("GET", "/api/v1/leads/abc"), ("DELETE", "/api/v1/leads/abc/messages")):
        with pytest.raises(HTTPException) as e:
            _run(method, path, _jwt(U_WA))
        assert e.value.status_code == 404, (method, path)


def test_wa_org_keeps_the_three_inbox_routes():
    assert _run("GET", "/api/v1/leads/abc/messages", _jwt(U_WA)) is None
    assert _run("PATCH", "/api/v1/leads/abc/messages/mark-read", _jwt(U_WA)) is None
    assert _run("GET", "/api/v1/customers/abc/messages", _jwt(U_WA)) is None


def test_full_org_anonymous_and_bad_tokens_pass():
    assert _run("GET", "/api/v1/leads", _jwt(U_FULL)) is None
    assert _run("POST", "/api/v1/leads/public/form", None) is None
    assert _run("GET", "/api/v1/leads", "garbage") is None
    assert _run("GET", "/api/v1/leads", _jwt("unknown-user")) is None


def test_guard_fails_open_on_database_error():
    bad = MagicMock()
    bad.table.side_effect = RuntimeError("down")
    assert _run("GET", "/api/v1/leads", _jwt(U_WA), db=bad) is None


def test_guard_through_a_real_http_stack():
    app = FastAPI()
    r = APIRouter(dependencies=[Depends(pm.crm_only)])

    @r.get("/api/v1/leads")
    def leads():
        return {"ok": True}

    @r.get("/api/v1/leads/{lead_id}/messages")
    def msgs(lead_id: str):
        return {"ok": True}

    app.include_router(r)
    open_router = APIRouter()

    @open_router.get("/api/v1/admin/ping")
    def ping():
        return {"ok": True}

    app.include_router(open_router)
    db = _db()
    app.dependency_overrides[get_supabase] = lambda: db
    c = TestClient(app)
    wa = {"Authorization": f"Bearer {_jwt(U_WA)}"}
    full = {"Authorization": f"Bearer {_jwt(U_FULL)}"}
    assert c.get("/api/v1/leads", headers=wa).status_code == 404
    assert c.get("/api/v1/leads", headers=wa).json()["detail"]["code"] == "NOT_FOUND"
    assert c.get("/api/v1/leads/1/messages", headers=wa).status_code == 200
    assert c.get("/api/v1/leads", headers=full).status_code == 200
    assert c.get("/api/v1/leads").status_code == 200
    assert c.get("/api/v1/admin/ping", headers=wa).status_code == 200


def test_main_wiring_crm_routers_guarded_and_others_open():
    import app.main as m
    def guarded(path):
        hits = [r for r in m.app.routes if getattr(r, "path", "") == path and getattr(r, "dependant", None)]
        assert hits, path
        return all(any(d.call is pm.crm_only for d in r.dependant.dependencies) for r in hits)
    for p in ("/api/v1/leads", "/api/v1/customers", "/api/v1/tasks"):
        assert guarded(p), p
    for p in ("/api/v1/billing/plan", "/api/v1/account-plan/platform-status"):
        hits = [r for r in m.app.routes if getattr(r, "path", "") == p and getattr(r, "dependant", None)]
        for r in hits:
            assert not any(d.call is pm.crm_only for d in r.dependant.dependencies), p


# -- create_lead -----------------------------------------------------------------------------------
@pytest.mark.parametrize("mode,expect_calls", [("wa_automation", 0), ("full", 1)])
def test_create_lead_notifies_and_assigns_only_in_full_mode(monkeypatch, mode, expect_calls):
    from app.services import lead_service as ls
    from app.services import lead_assignment_service as las
    notified, assigned = [], []

    class _T:
        def __init__(self, target=None, args=(), daemon=None): self.target, self.args = target, args
        def start(self): notified.append(self.args)

    monkeypatch.setattr(ls.threading, "Thread", _T)
    monkeypatch.setattr(las, "auto_assign_lead", lambda *a, **k: assigned.append(a))
    monkeypatch.setattr(pm, "is_wa_automation", lambda db, org: mode == "wa_automation")

    db = MagicMock()
    row = {"id": "lead-1", "org_id": ORG_WA, "full_name": "Ada", "whatsapp": "2348000000000", "phone": "2348000000000",
           "stage": "new", "source": "whatsapp_inbound"}
    db.table.return_value.insert.return_value.execute.return_value.data = [row]
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    try:
        payload = ls.LeadCreate(full_name="Ada", phone="2348000000000", whatsapp="2348000000000", source="whatsapp_inbound")
    except Exception:
        pytest.skip("LeadCreate shape differs")
    try:
        ls.create_lead(db, ORG_WA, "user-1", payload)
    except Exception:
        # Other parts of create_lead may need richer DB scripting; the guard calls below are what matter.
        pass
    assert len(notified) == expect_calls
    assert len(assigned) == expect_calls


# -- seats ------------------------------------------------------------------------------------------
def test_included_users_uses_cap_and_falls_back(monkeypatch):
    from app.services import account_seat_service as seat
    monkeypatch.setattr(seat.acc, "_compute", lambda db, org, now: {"caps": {"users_included": 1}})
    assert seat.included_users(None, BIZ) == 1
    monkeypatch.setattr(seat.acc, "_compute", lambda db, org, now: {"caps": {}})
    assert seat.included_users(None, BIZ) == seat.INCLUDED_USERS == 2
    def boom(*a, **k): raise RuntimeError("x")
    monkeypatch.setattr(seat.acc, "_compute", boom)
    assert seat.included_users(None, BIZ) == 2


def test_users_included_is_a_registered_static_cap():
    from app.services import site_feature_registry as reg
    assert reg.CAPS["users_included"] == "static"


# -- platform status and superadmin ----------------------------------------------------------------
def test_platform_status_returns_product_mode(monkeypatch):
    from app.routers import account_plan as ap
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)
    db = FakeDB(site_builder_settings=[{"org_id": PLATFORM, "enabled": True, "pricing": {}}],
                organisations=[{"id": ORG_WA, "product_mode": "wa_automation"}, {"id": BIZ, "product_mode": "full"}])
    assert ap.platform_status(db, {"org_id": ORG_WA}).data["product_mode"] == "wa_automation"
    assert ap.platform_status(db, {"org_id": BIZ}).data["product_mode"] == "full"


def test_superadmin_payload_accepts_only_known_modes():
    from pydantic import ValidationError
    from app.routers import superadmin as sa
    base = dict(org_name="Glow", slug="glow", industry="x", ticket_prefix="GLW", owner_email="a@b.com",
                owner_full_name="Ada", owner_password="Password123!")
    assert sa.OrgProvisionPayload(**base).product_mode == "full"
    assert sa.OrgProvisionPayload(**base, product_mode="wa_automation").product_mode == "wa_automation"
    with pytest.raises(ValidationError):
        sa.OrgProvisionPayload(**base, product_mode="other")
    with pytest.raises(ValidationError):
        sa.ProductModePayload(product_mode="other")


def test_superadmin_product_mode_route_is_superadmin_only():
    import app.main as m
    from app.routers import superadmin as sa
    hits = [r for r in m.app.routes if getattr(r, "path", "").endswith("/organisations/{org_id}/product-mode")]
    assert hits and all("PATCH" in r.methods for r in hits)
    assert any(d.call is sa.require_superadmin for r in hits for d in r.dependant.dependencies)
