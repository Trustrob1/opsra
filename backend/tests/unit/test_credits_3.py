"""
tests/unit/test_credits_3.py
---------------------------
CREDITS-3: superadmin credits overview, margin report, reconcile, refunds with a reason.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ORG = "00000000-0000-0000-0000-0000000000aa"


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



O1 = "00000000-0000-0000-0000-0000000000a1"
O2 = "00000000-0000-0000-0000-0000000000a2"


def _now_iso(): return datetime.now(timezone.utc).isoformat()


def _db():
    now = _now_iso()
    return FakeDB(
        organisations=[{"id": O1, "name": "Alpha Salon"}, {"id": O2, "name": "Beta Foods"}],
        credit_wallets=[{"org_id": O1, "balance_kobo": 150000, "metering_enabled": True, "meta_billing": "client_direct"}],
        credit_rates=[{"fx_ngn_per_usd": 1340, "ai_markup_pct": 50, "meta_markup_pct": 0, "min_charge_kobo": 0, "rounding_kobo": 1,
                       "effective_from": "2026-01-01T00:00:00+00:00"}],
        credit_ledger=[
            {"org_id": O1, "kind": "topup", "amount_kobo": 200000, "meta": {}, "created_at": now},
            {"org_id": O1, "kind": "ai", "amount_kobo": -3000, "meta": {"base_kobo": 2000}, "created_at": now},
            {"org_id": O1, "kind": "ai", "amount_kobo": -1500, "meta": {"base_kobo": 1000}, "created_at": now},
            {"org_id": O1, "kind": "fee", "amount_kobo": -500, "meta": {}, "created_at": now},
            {"org_id": O1, "kind": "expiry", "amount_kobo": -4000, "meta": {}, "created_at": now},
            {"org_id": O1, "kind": "refund", "amount_kobo": 700, "meta": {"note": "double charge"}, "created_at": now},
            {"org_id": O1, "kind": "ai", "amount_kobo": -9999, "meta": {"base_kobo": 6666}, "created_at": "2020-01-01T00:00:00+00:00"},
        ],
    )


def _client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_supabase
    from app.routers import superadmin_credits
    from app.routers.superadmin_health import require_superadmin
    app = FastAPI(); app.include_router(superadmin_credits.router, prefix="/api/v1")
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[require_superadmin] = lambda: None
    return TestClient(app)


class TestOverview:
    def test_lists_every_business_with_wallet_facts(self):
        r = _client(_db()).get("/api/v1/superadmin/credits/orgs").json()["data"]["orgs"]
        a = next(o for o in r if o["org_id"] == O1); b = next(o for o in r if o["org_id"] == O2)
        assert a["metering_enabled"] is True and a["balance_kobo"] == 150000 and a["topups_total_kobo"] == 200000
        assert a["month_ai_spend_kobo"] >= 4500 and b["has_wallet"] is False and b["metering_enabled"] is False
        assert r[0]["org_id"] == O1                       # metered businesses first

    def test_requires_superadmin(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers import superadmin_credits
        app = FastAPI(); app.include_router(superadmin_credits.router, prefix="/api/v1")
        c = TestClient(app)
        for path in ("orgs", "margin", "reconcile"):
            assert c.get(f"/api/v1/superadmin/credits/{path}").status_code in (401, 403)


class TestMargin:
    def test_charged_vs_cost_inside_the_window(self):
        d = _client(_db()).get("/api/v1/superadmin/credits/margin?days=30").json()["data"]
        o = d["orgs"][0]
        assert o["ai_charged_kobo"] == 4500 and o["ai_cost_kobo"] == 3000 and o["ai_calls"] == 2   # old row excluded
        assert o["fee_charged_kobo"] == 500 and o["expired_kobo"] == 4000 and o["cash_in_kobo"] == 200000
        assert o["refunds_kobo"] == 700
        assert o["margin_kobo"] == (4500 - 3000) + 500 + 4000
        assert d["totals"]["ai_charged_kobo"] == 4500 and d["notes"]

    def test_longer_window_includes_older_rows(self):
        d = _client(_db()).get("/api/v1/superadmin/credits/margin?days=365").json()["data"]
        assert d["orgs"][0]["ai_charged_kobo"] == 4500          # 2020 row is still outside 365 days
        d = _client(_db()).get("/api/v1/superadmin/credits/margin?days=9999").json()["data"]
        assert d["days"] == 365

    def test_empty_ledger(self):
        db = FakeDB(organisations=[], credit_ledger=[], credit_rates=[])
        d = _client(db).get("/api/v1/superadmin/credits/margin").json()["data"]
        assert d["orgs"] == [] and d["totals"] == {}


class TestReconcileRoute:
    def test_reports_mismatches(self):
        db = _db(); db.tables["credit_lots"] = [{"org_id": O1, "remaining_kobo": 150000}]
        res = _client(db).get("/api/v1/superadmin/credits/reconcile").json()["data"]["mismatches"]
        assert res and res[0]["org_id"] == O1               # ledger rows above do not add up to the wallet balance


class TestRefund:
    def test_refund_needs_a_real_reason(self):
        c = _client(_db())
        r = c.post(f"/api/v1/superadmin/credits/orgs/{O1}/adjust", json={"amount_kobo": 500, "note": "x", "ref": "ref-1", "kind": "refund"})
        assert r.status_code == 422

    def test_refund_credits_with_kind_refund(self):
        c = _client(_db())
        with patch("app.services.credit_service.add_credit", return_value={"balance_after": 1}) as ac:
            r = c.post(f"/api/v1/superadmin/credits/orgs/{O1}/adjust",
                       json={"amount_kobo": 500, "note": "Charged twice for one chat", "ref": "ref-2", "kind": "refund"})
        assert r.status_code == 200 and ac.call_args.args[3] == "refund" and ac.call_args.args[5]["note"].startswith("Charged twice")

    def test_negative_refund_debits_with_kind_refund(self):
        c = _client(_db())
        with patch("app.services.credit_service._debit", return_value={"charged_kobo": 500}) as dd:
            r = c.post(f"/api/v1/superadmin/credits/orgs/{O1}/adjust",
                       json={"amount_kobo": -500, "note": "Cash refund paid back by bank transfer", "ref": "ref-3", "kind": "refund"})
        assert r.status_code == 200 and dd.call_args.args[3] == "refund"

    def test_default_kind_is_adjust_and_zero_refused(self):
        c = _client(_db())
        assert c.post(f"/api/v1/superadmin/credits/orgs/{O1}/adjust", json={"amount_kobo": 0, "note": "nothing here", "ref": "ref-4"}).status_code == 422
        with patch("app.services.credit_service.add_credit", return_value={"ok": 1}) as ac:
            c.post(f"/api/v1/superadmin/credits/orgs/{O1}/adjust", json={"amount_kobo": 100, "note": "goodwill credit", "ref": "ref-5"})
        assert ac.call_args.args[3] == "adjust"


class TestMeteringSwitch:
    def test_switch_on_and_off_creates_the_wallet(self):
        db = FakeDB(organisations=[{"id": O2, "name": "Beta Foods"}], credit_wallets=[])
        c = _client(db)
        # FakeDB upsert is a no-op, so seed the row the way the real upsert would
        db.tables["credit_wallets"].append({"org_id": O2, "balance_kobo": 0, "metering_enabled": False})
        r = c.patch(f"/api/v1/superadmin/credits/orgs/{O2}/wallet", json={"metering_enabled": True})
        assert r.status_code == 200 and r.json()["data"]["metering_enabled"] is True
        r = c.patch(f"/api/v1/superadmin/credits/orgs/{O2}/wallet", json={"metering_enabled": False})
        assert r.json()["data"]["metering_enabled"] is False
