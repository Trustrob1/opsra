"""
tests/unit/test_account_plans_1.py
----------------------------------
ACCOUNT-PLANS AP-1: account-level plans (Capture / Convert / Grow for an organisation).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import account_entitlement_service as acc
from app.services import site_feature_registry as reg

PLATFORM = "00000000-0000-0000-0000-0000000000aa"
BIZ = "00000000-0000-0000-0000-0000000000b1"
OTHER = "00000000-0000-0000-0000-0000000000b2"
WS = "00000000-0000-0000-0000-0000000000c1"
SITE = "00000000-0000-0000-0000-0000000000d1"


class _Q:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.filters, self.op, self.payload, self._limit = [], "select", None, None
        self._order = None

    def select(self, *_a, **_k): return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def update(self, row): self.op, self.payload = "update", row; return self
    def upsert(self, row, **_k): self.op, self.payload = "upsert", row; return self
    def _f(self, k, c, v): self.filters.append((k, c, v)); return self
    def eq(self, c, v): return self._f("eq", c, v)
    def neq(self, c, v): return self._f("neq", c, v)
    def lt(self, c, v): return self._f("lt", c, v)
    def gt(self, c, v): return self._f("gt", c, v)
    def lte(self, c, v): return self._f("lte", c, v)
    def gte(self, c, v): return self._f("gte", c, v)
    def in_(self, c, v): return self._f("in", c, v)
    def is_(self, c, v): return self._f("is", c, v)
    def order(self, col, desc=False, **_k): self._order = (col, desc); return self
    def limit(self, n): self._limit = n; return self
    def range(self, a, b): self._range = (a, b); return self

    def _match(self, r):
        for k, c, v in self.filters:
            x = r.get(c)
            if k == "eq" and x != v: return False
            if k == "neq" and x == v: return False
            if k == "in" and x not in v: return False
            if k == "is" and not ((x is None) if v == "null" else (x is not None)): return False
            if k == "lt" and not (x is not None and str(x) < str(v)): return False
            if k == "gt" and not (x is not None and str(x) > str(v)): return False
            if k == "lte" and not (x is not None and str(x) <= str(v)): return False
            if k == "gte" and not (x is not None and str(x) >= str(v)): return False
        return True

    def execute(self):
        self.db.calls.append((self.name, self.op, self.payload))
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for it in items:
                it = dict(it)
                it.setdefault("id", str(uuid.uuid4()))
                rows.append(it)
                out.append(dict(it))
            return SimpleNamespace(data=out)
        if self.op == "update":
            hit = [r for r in rows if self._match(r)]
            for r in hit:
                r.update(self.payload)
            return SimpleNamespace(data=[dict(r) for r in hit])
        if self.op == "upsert":
            return SimpleNamespace(data=[])
        hit = [dict(r) for r in rows if self._match(r)]
        if self._order:
            hit.sort(key=lambda r: str(r.get(self._order[0]) or ""), reverse=self._order[1])
        if getattr(self, '_range', None):
            hit = hit[self._range[0]: self._range[1] + 1]
        if self._limit:
            hit = hit[: self._limit]
        return SimpleNamespace(data=hit)


class FakeDB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.calls = []

    def table(self, name): return _Q(self, name)

    def rows(self, name): return self.tables.get(name, [])


def _now(d=0):
    return datetime.now(timezone.utc) + timedelta(days=d)


def _db(enforced=False, plans=None, **extra):
    settings = {"org_id": PLATFORM, "pricing": {"tiers": {
        "capture": {"monthly_ngn": 15000, "features": ["webchat_basic", "webchat_insights", "wa_leads", "form_instant_reply"], "caps": {}},
        "convert": {"monthly_ngn": 30000, "features": ["webchat_basic", "webchat_insights", "wa_leads", "ai_assistant", "webchat_followups"],
                    "caps": {"ai_messages": 3}},
        "grow": {"monthly_ngn": 0},
    }}}
    return FakeDB(
        site_builder_settings=[settings],
        organisations=[{"id": BIZ, "name": "Glow", "slug": "glow", "subscription_status": "active", "plans_enforced": enforced},
                       {"id": OTHER, "name": "Other", "slug": "other", "subscription_status": "active", "plans_enforced": True},
                       {"id": WS, "name": "Client WS", "slug": "ws", "subscription_status": "site_workspace", "plans_enforced": False}],
        org_plans=plans or [], org_usage_counters=[], org_plan_events=[], site_addons=[], site_usage_counters=[], sites=[{"id": SITE, "org_id": PLATFORM}],
        **extra)


def _plan(org=BIZ, key="capture", kind="tier", status="active", source="paid", until=None, **kw):
    return {"id": str(uuid.uuid4()), "org_id": org, "kind": kind, "key": key, "status": status, "source": source,
            "paid_until": (until or _now(10)).isoformat() if until != "none" else None, "grace_until": None, "config": {}, **kw}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


# -- registry scope ----------------------------------------------------------

def test_scope_of_features():
    assert reg.scope_of("form_instant_reply") == "site" and reg.scope_of("my_leads_page") == "site"
    assert reg.scope_of("webchat_basic") == "account" and reg.scope_of("webchat_followups") == "account"
    assert reg.scope_of("ai_assistant") == "both"
    assert reg.FEATURES["webchat_basic"]["scope"] == "account"


# -- the safety switch -------------------------------------------------------

def test_not_enforced_means_everything_on_and_nothing_counted():
    db = _db(enforced=False)
    assert acc.has_feature(db, "ai_assistant", org_id=BIZ) is True
    assert acc.has_feature(db, "webchat_basic", org_id=BIZ) is True
    assert acc.consume(db, "ai_assistant", org_id=BIZ, n=5) is True
    assert db.rows("org_usage_counters") == []


def test_not_enforced_even_with_a_paused_plan_row():
    db = _db(enforced=False, plans=[_plan(status="paused")])
    assert acc.has_feature(db, "webchat_basic", org_id=BIZ) is True


def test_enforced_with_no_plan_means_off():
    db = _db(enforced=True)
    assert acc.has_feature(db, "webchat_basic", org_id=BIZ) is False


def test_enforced_plan_switches_its_features_on_only():
    db = _db(enforced=True, plans=[_plan(key="capture")])
    assert acc.has_feature(db, "webchat_basic", org_id=BIZ) is True
    assert acc.has_feature(db, "ai_assistant", org_id=BIZ) is False


def test_lookup_error_on_the_switch_counts_as_not_enforced():
    class Boom(FakeDB):
        def table(self, name):
            if name == "organisations":
                raise RuntimeError("down")
            return super().table(name)
    db = Boom(org_plans=[])
    assert acc.is_enforced(db, BIZ) is False
    assert acc.has_feature(db, "webchat_basic", org_id=BIZ) is True


def test_error_while_computing_an_enforced_plan_fails_closed():
    class Boom(FakeDB):
        def table(self, name):
            if name == "org_plans":
                raise RuntimeError("down")
            return super().table(name)
    db = Boom(organisations=[{"id": BIZ, "plans_enforced": True}], site_builder_settings=[])
    assert acc.has_feature(db, "webchat_basic", org_id=BIZ) is False
    assert acc.consume(db, "ai_assistant", org_id=BIZ) is False


# -- status rules ------------------------------------------------------------

def test_status_active_grace_paused_and_staff_no_end_date():
    live = _db(True, [_plan(until=_now(5))])
    assert acc.has_feature(live, "webchat_basic", org_id=BIZ)
    grace = _db(True, [_plan(until=_now(-3))])
    assert acc.has_feature(grace, "webchat_basic", org_id=BIZ)
    assert acc.get_entitlements(grace, BIZ)["tier"]["status"] == "grace"
    over = _db(True, [_plan(until=_now(-30))])
    assert not acc.has_feature(over, "webchat_basic", org_id=BIZ)
    staff = _db(True, [_plan(source="staff", until="none")])
    assert acc.has_feature(staff, "webchat_basic", org_id=BIZ)
    unpaid = _db(True, [_plan(source="paid", until="none")])
    assert not acc.has_feature(unpaid, "webchat_basic", org_id=BIZ)
    for st in ("paused", "pending", "cancelled"):
        assert not acc.has_feature(_db(True, [_plan(status=st)]), "webchat_basic", org_id=BIZ)


# -- org isolation -----------------------------------------------------------

def test_another_organisations_plan_never_counts():
    db = _db(True, [_plan(org=OTHER, key="convert")])
    assert acc.has_feature(db, "webchat_basic", org_id=BIZ) is False
    assert acc.get_entitlements(db, BIZ)["tier"] is None


# -- caps --------------------------------------------------------------------

def test_cap_counts_stops_and_a_missing_cap_means_no_allowance():
    db = _db(True, [_plan(key="convert", source="staff", until="none")])
    assert acc.consume(db, "ai_assistant", org_id=BIZ, n=2) is True
    assert acc.consume(db, "ai_assistant", org_id=BIZ, n=1) is True
    assert acc.consume(db, "ai_assistant", org_id=BIZ, n=1) is False       # 3 of 3 used
    assert acc.get_entitlements(db, BIZ)["usage"]["ai_messages"] == {"used": 3, "cap": 3}
    nocap = _db(True, [_plan(key="capture", source="staff", until="none")])
    assert acc.consume(nocap, "ai_assistant", org_id=BIZ) is False         # feature not in the tier


def test_cap_does_not_leak_to_another_org_and_rejects_bad_n():
    db = _db(True, [_plan(key="convert", source="staff", until="none"), _plan(org=OTHER, key="convert", source="staff", until="none")])
    assert acc.consume(db, "ai_assistant", org_id=BIZ, n=3) is True
    assert acc.consume(db, "ai_assistant", org_id=OTHER, n=3) is True
    assert acc.consume(db, "ai_assistant", org_id=BIZ, n=-1) is False
    assert acc.consume(db, "nonsense", org_id=BIZ) is False


# -- site context ------------------------------------------------------------

def test_site_only_feature_needs_a_site_and_a_site_tier_not_a_free_pass():
    db = _db(False)
    assert acc.has_feature(db, "form_instant_reply", org_id=WS) is False                    # no site given
    assert acc.has_feature(db, "form_instant_reply", org_id=WS, site_id=SITE, site_org_id=PLATFORM) is False   # no site tier
    db.tables["site_addons"].append({"id": "a1", "org_id": PLATFORM, "site_id": SITE, "kind": "tier", "key": "capture",
                                     "status": "active", "source": "staff", "paid_until": None, "config": {}})
    assert acc.has_feature(db, "form_instant_reply", org_id=WS, site_id=SITE, site_org_id=PLATFORM) is True


def test_owner_account_plan_covers_its_own_site_only_when_enforced():
    site_owner_plan = [_plan(org=BIZ, key="capture")]
    off = _db(False, site_owner_plan)
    assert acc.has_feature(off, "form_instant_reply", org_id=WS, site_id=SITE, site_org_id=BIZ) is False
    on = _db(True, site_owner_plan)
    on.tables["organisations"][0]["plans_enforced"] = True
    assert acc.has_feature(on, "form_instant_reply", org_id=WS, site_id=SITE, site_org_id=BIZ) is True


def test_unenforced_workspace_does_not_turn_site_features_on_for_free():
    db = _db(False)
    assert acc.has_feature(db, "wa_leads", org_id=WS, site_id=SITE, site_org_id=PLATFORM) is False


# -- staff actions -----------------------------------------------------------

def test_grant_tier_then_replace_and_audit():
    db = _db(True)
    out = acc.grant(db, BIZ, "sa", "tier", "capture", source="grandfathered")
    assert out["tier"]["key"] == "capture" and out["tier"]["source"] == "grandfathered"
    out = acc.grant(db, BIZ, "sa", "tier", "convert", until=_now(30))
    assert out["tier"]["key"] == "convert"
    assert len([r for r in db.rows("org_plans") if r["kind"] == "tier" and r["status"] != "cancelled"]) == 1
    assert [e["event"] for e in db.rows("org_plan_events")] == ["plan_granted", "plan_changed"]


def test_grant_rejects_bad_input_and_workspaces():
    db = _db(True)
    for args, kw in ((("tier", "nonsense"), {}), (("nope", "capture"), {}), (("tier", "capture"), {"until": _now(-1)}),
                     (("tier", "capture"), {"source": "paid"})):
        with pytest.raises(acc.EntitlementError):
            acc.grant(db, BIZ, "sa", *args, **kw)
    with pytest.raises(acc.EntitlementError):
        acc.grant(db, WS, "sa", "tier", "capture")
    with pytest.raises(acc.EntitlementNotFound):
        acc.grant(db, "00000000-0000-0000-0000-00000000ffff", "sa", "tier", "capture")


def test_pause_resume_cancel_and_conditional_updates():
    db = _db(True)
    acc.grant(db, BIZ, "sa", "tier", "capture", source="staff")
    pid = db.rows("org_plans")[0]["id"]
    assert acc.set_status(db, BIZ, pid, "pause", "sa")["tier"]["status"] == "paused"
    with pytest.raises(acc.EntitlementError):
        acc.set_status(db, BIZ, pid, "pause", "sa")                     # already paused: nothing changes twice
    assert acc.set_status(db, BIZ, pid, "resume", "sa")["tier"]["status"] == "active"
    assert acc.set_status(db, BIZ, pid, "cancel", "sa")["tier"] is None
    with pytest.raises(acc.EntitlementNotFound):
        acc.set_status(db, OTHER, pid, "pause", "sa")                    # another organisation's row


def test_set_enforced_toggles_and_refuses_workspaces():
    db = _db(False)
    assert acc.set_enforced(db, BIZ, True, "sa")["enforced"] is True
    assert acc.set_enforced(db, BIZ, False, "sa")["enforced"] is False
    with pytest.raises(acc.EntitlementError):
        acc.set_enforced(db, WS, True, "sa")


def test_overview_lists_businesses_leaves_out_workspaces_and_totals_paid_value():
    db = _db(True, [_plan(org=BIZ, key="capture"), _plan(org=OTHER, key="convert", source="grandfathered", until="none")])
    out = acc.overview(db)
    ids = {o["org_id"] for o in out["orgs"]}
    assert WS not in ids and {BIZ, OTHER} <= ids
    assert out["totals"]["monthly_value_ngn"] == 15000           # only the paid Capture counts
    assert out["totals"]["enforced"] >= 1


# -- tier definitions --------------------------------------------------------

def test_platform_org_from_env_then_first_settings_row(monkeypatch):
    db = _db()
    assert acc.platform_org_id(db) == PLATFORM
    monkeypatch.delenv("PLATFORM_ORG_ID")
    assert acc.platform_org_id(db) == PLATFORM
    assert acc.plan_config(db)["tiers"]["capture"]["monthly_ngn"] == 15000


# -- routes ------------------------------------------------------------------

def test_routes_grant_status_enforce_and_error_mapping():
    from fastapi import HTTPException
    from app.routers import superadmin_plans as r
    db = _db(True)
    out = r.grant(BIZ, r.GrantBody(kind="tier", key="capture"), db=db, sa=None)
    assert out.data["tier"]["key"] == "capture"
    pid = db.rows("org_plans")[0]["id"]
    assert r.status(BIZ, r.StatusBody(plan_id=pid, action="pause"), db=db, sa=None).data["tier"]["status"] == "paused"
    assert r.enforce(BIZ, r.EnforceBody(enforced=False), db=db, sa=None).data["enforced"] is False
    assert r.list_orgs(db=db, sa=None).data["totals"]["businesses"] == 2
    with pytest.raises(HTTPException) as e:
        r.grant(BIZ, r.GrantBody(kind="tier", key="nonsense"), db=db, sa=None)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        r.grant("00000000-0000-0000-0000-00000000ffff", r.GrantBody(kind="tier", key="capture"), db=db, sa=None)
    assert e.value.status_code == 404
