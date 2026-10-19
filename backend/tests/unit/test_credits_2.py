"""
tests/unit/test_credits_2.py
----------------------------
CREDITS-2: packs, checkout, payment -> credit (once), summary, usage, ledger, routes, webhook wiring.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ORG = "00000000-0000-0000-0000-0000000000aa"
OTHER = "00000000-0000-0000-0000-0000000000bb"


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
        if self._limit:
            hit = hit[: self._limit]
        return SimpleNamespace(data=hit)


class FakeDB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.calls = []
        self.rpcs = []
        self.credited = {}

    def table(self, name): return _Q(self, name)

    def rows(self, name): return self.tables.get(name, [])

    def rpc(self, fn, args):
        self.rpcs.append((fn, args))
        key = (args["p_org"], args["p_ref"])
        applied = key not in self.credited
        if applied:
            self.credited[key] = args["p_amount"]
        bal = sum(v for (o, _), v in self.credited.items() if o == args["p_org"])
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"applied": applied, "balance_kobo": bal}]))



def _iso(dt): return dt.astimezone(timezone.utc).isoformat()
def _now(): return datetime.now(timezone.utc)


PACKS = [
    {"id": "p5", "name": "N5,000", "price_kobo": 500000, "credit_kobo": 500000, "active": True, "sort_order": 1},
    {"id": "p10", "name": "N10,000", "price_kobo": 1000000, "credit_kobo": 1000000, "active": True, "sort_order": 2},
    {"id": "px", "name": "Old", "price_kobo": 100, "credit_kobo": 100, "active": False, "sort_order": 3},
]


def _db(**extra):
    return FakeDB(credit_packs=PACKS, **extra)


def _paystack(ok=True, status=200, url="https://checkout.paystack.com/abc", verify=None):
    """Patch httpx.Client so no network is used."""
    client = MagicMock()
    client.__enter__.return_value = client
    post = MagicMock(status_code=status)
    post.json.return_value = {"status": ok, "message": "nope", "data": {"authorization_url": url}}
    client.post.return_value = post
    get = MagicMock(status_code=200)
    get.json.return_value = {"status": True, "data": verify or {"status": "pending"}}
    client.get.return_value = get
    return patch("app.services.credit_order_service.httpx.Client", return_value=client), client


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_test_x")


# ═════════════════════════ packs and checkout ═══════════════════════════════

class TestCheckout:
    def test_only_active_packs_listed(self):
        from app.services import credit_order_service as s
        assert [p["id"] for p in s.list_packs(_db())] == ["p5", "p10"]

    def test_pack_order_uses_server_price_and_opsra_key(self):
        from app.services import credit_order_service as s
        db = _db()
        ctx, client = _paystack()
        with ctx:
            r = s.create_order(db, ORG, "a@b.com", pack_id="p10", callback_url="https://app/?credits=1")
        assert r["checkout_url"].startswith("https://checkout.paystack.com") and r["reference"].startswith("cr_")
        sent = client.post.call_args.kwargs
        assert sent["json"]["amount"] == 1000000 and sent["json"]["metadata"]["kind"] == "credit_topup"
        assert sent["json"]["metadata"]["org_id"] == ORG and sent["headers"]["Authorization"] == "Bearer sk_test_x"
        order = db.rows("credit_orders")[0]
        assert order["status"] == "pending" and order["credit_kobo"] == 1000000 and order["org_id"] == ORG

    def test_unknown_or_inactive_pack_rejected(self):
        from app.services import credit_order_service as s
        for pid in ("nope", "px"):
            with pytest.raises(s.CreditOrderError):
                s.create_order(_db(), ORG, "a@b.com", pack_id=pid)

    def test_custom_amount_limits(self):
        from app.services import credit_order_service as s
        ctx, _ = _paystack()
        with ctx:
            for bad in (199_900, 100_000_001, 250_050, None, "abc"):
                with pytest.raises(s.CreditOrderError):
                    s.create_order(_db(), ORG, "a@b.com", amount_kobo=bad)
            ok = s.create_order(_db(), ORG, "a@b.com", amount_kobo=200_000)
        assert ok["reference"]

    def test_custom_amount_credits_exactly_what_is_paid(self):
        from app.services import credit_order_service as s
        db = _db()
        ctx, _ = _paystack()
        with ctx:
            s.create_order(db, ORG, "a@b.com", amount_kobo=1_500_000)
        o = db.rows("credit_orders")[0]
        assert o["amount_kobo"] == 1_500_000 and o["credit_kobo"] == 1_500_000 and o["pack_id"] is None

    def test_no_paystack_key(self, monkeypatch):
        from app.services import credit_order_service as s
        monkeypatch.delenv("PAYSTACK_SECRET_KEY")
        with pytest.raises(s.CreditOrderError):
            s.create_order(_db(), ORG, "a@b.com", pack_id="p5")

    def test_paystack_failure_marks_order_failed(self):
        from app.services import credit_order_service as s
        db = _db()
        ctx, _ = _paystack(ok=False, status=400)
        with ctx, pytest.raises(s.CreditOrderError):
            s.create_order(db, ORG, "a@b.com", pack_id="p5")
        assert db.rows("credit_orders")[0]["status"] == "failed"


# ═════════════════════════ payment -> credit ════════════════════════════════

def _pending(db=None, **kw):
    row = {"id": "o1", "org_id": ORG, "amount_kobo": 500000, "credit_kobo": 500000, "status": "pending",
           "paystack_reference": "cr_aaaa_1", "pack_name": "N5,000"}
    row.update(kw)
    return (db or _db()) if False else FakeDB(credit_packs=PACKS, credit_orders=[row])


class TestMarkPaid:
    def test_credits_once_even_if_reported_twice(self):
        from app.services import credit_order_service as s
        db = _pending()
        r1 = s.mark_paid(db, "cr_aaaa_1", 500000)
        r2 = s.mark_paid(db, "cr_aaaa_1", 500000)
        assert r1 == {"credited": True, "reason": "ok"} and r2["credited"] is False and r2["reason"] == "already_credited"
        assert sum(db.credited.values()) == 500000
        assert db.rpcs[0][1]["p_kind"] == "topup" and db.rpcs[0][1]["p_ref"] == "order:cr_aaaa_1"
        o = db.rows("credit_orders")[0]
        assert o["status"] == "paid" and o["paid_at"]

    def test_underpayment_never_credits(self):
        from app.services import credit_order_service as s
        db = _pending()
        assert s.mark_paid(db, "cr_aaaa_1", 100)["reason"] == "underpaid"
        assert not db.rpcs and db.rows("credit_orders")[0]["status"] == "pending"

    def test_overpayment_credits_the_order_amount_only(self):
        from app.services import credit_order_service as s
        db = _pending()
        s.mark_paid(db, "cr_aaaa_1", 900000)
        assert sum(db.credited.values()) == 500000

    def test_unknown_or_foreign_references_ignored(self):
        from app.services import credit_order_service as s
        db = _pending()
        assert s.mark_paid(db, "cr_nothing", 500000)["reason"] == "unknown_reference"
        assert s.mark_paid(db, "opsra_site_order_1", 500000)["reason"] == "not_a_credit_order"
        assert s.mark_paid(db, None, 5)["credited"] is False and not db.rpcs

    def test_credit_failure_leaves_order_pending(self):
        from app.services import credit_order_service as s
        db = _pending()
        db.rpc = MagicMock(side_effect=RuntimeError("db down"))
        assert s.mark_paid(db, "cr_aaaa_1", 500000)["reason"] == "credit_failed"
        assert db.rows("credit_orders")[0]["status"] == "pending"

    def test_verify_credits_when_paystack_says_success(self):
        from app.services import credit_order_service as s
        db = _pending()
        ctx, _ = _paystack(verify={"status": "success", "amount": 500000})
        with ctx:
            assert s.verify(db, ORG, "cr_aaaa_1") == {"status": "paid"}
        assert sum(db.credited.values()) == 500000

    def test_verify_pending_failed_and_other_org(self):
        from app.services import credit_order_service as s
        db = _pending()
        ctx, _ = _paystack(verify={"status": "pending"})
        with ctx:
            assert s.verify(db, ORG, "cr_aaaa_1") == {"status": "pending"}
        ctx, _ = _paystack(verify={"status": "abandoned"})
        with ctx:
            assert s.verify(db, ORG, "cr_aaaa_1") == {"status": "failed"}
        with pytest.raises(s.CreditOrderError):
            s.verify(db, OTHER, "cr_aaaa_1")                       # someone else's order
        with pytest.raises(s.CreditOrderError):
            s.verify(db, ORG, "not-ours")


# ═════════════════════════ reads ════════════════════════════════════════════

def _ledger_db():
    t = _now()
    return FakeDB(
        credit_wallets=[{"org_id": ORG, "balance_kobo": 12345, "metering_enabled": True, "low_balance_kobo": 20000,
                         "ai_monthly_budget_kobo": None}],
        credit_lots=[{"org_id": ORG, "remaining_kobo": 5000, "expires_at": "2027-08-01T00:00:00+00:00"},
                     {"org_id": ORG, "remaining_kobo": 0, "expires_at": "2027-01-01T00:00:00+00:00"},
                     {"org_id": OTHER, "remaining_kobo": 9, "expires_at": "2026-12-01T00:00:00+00:00"}],
        credit_ledger=[
            {"id": "1", "org_id": ORG, "kind": "topup", "amount_kobo": 500000, "balance_after_kobo": 500000, "created_at": _iso(t - timedelta(days=2))},
            {"id": "2", "org_id": ORG, "kind": "ai", "amount_kobo": -300, "balance_after_kobo": 499700, "created_at": _iso(t - timedelta(days=1))},
            {"id": "3", "org_id": ORG, "kind": "ai", "amount_kobo": -200, "balance_after_kobo": 499500, "created_at": _iso(t - timedelta(hours=3))},
            {"id": "4", "org_id": ORG, "kind": "meta", "amount_kobo": -1400, "balance_after_kobo": 498100, "created_at": _iso(t - timedelta(hours=2))},
            {"id": "5", "org_id": OTHER, "kind": "ai", "amount_kobo": -99999, "balance_after_kobo": 0, "created_at": _iso(t)},
        ])


class TestReads:
    def test_summary_scoped_to_org(self):
        from app.services import credit_order_service as s
        out = s.summary(_ledger_db(), ORG)
        assert out["balance_kobo"] == 12345 and out["expiring"]["kobo"] == 5000
        assert out["min_custom_kobo"] == 200000

    def test_summary_for_org_with_no_wallet(self):
        from app.services import credit_order_service as s
        out = s.summary(FakeDB(), ORG)
        assert out["balance_kobo"] == 0 and out["expiring"] is None and out["month_spend_total_kobo"] == 0

    def test_usage_totals_and_series_length(self):
        from app.services import credit_order_service as s
        u = s.usage(_ledger_db(), ORG, 30)
        assert len(u["series"]) == 30 and u["totals_kobo"] == {"ai": 500, "meta": 1400, "fee": 0}
        assert u["spent_kobo"] == 1900 and u["topped_up_kobo"] == 500000
        assert s.usage(_ledger_db(), ORG, 999)["days"] == 90 and s.usage(_ledger_db(), ORG, 0)["days"] == 30

    def test_ledger_newest_first_and_no_other_org(self):
        from app.services import credit_order_service as s
        out = s.ledger(_ledger_db(), ORG)
        assert [e["id"] for e in out["entries"]] == ["4", "3", "2", "1"] and out["next"] is None
        small = s.ledger(_ledger_db(), ORG, limit=2)
        assert len(small["entries"]) == 2 and small["next"]
        older = s.ledger(_ledger_db(), ORG, before=small["next"], limit=2)
        assert [e["id"] for e in older["entries"]] == ["2", "1"]


# ═════════════════════════ routes + wiring ══════════════════════════════════

@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_supabase
    from app.dependencies import get_current_org
    from app.routers import credits
    app = FastAPI()
    app.include_router(credits.router, prefix="/api/v1")
    db = _ledger_db()
    db.tables["credit_packs"] = [dict(p) for p in PACKS]
    state = {"role": "owner"}
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: {"org_id": ORG, "id": "U1", "email": "o@x.com", "roles": {"template": state["role"]}}
    c = TestClient(app)
    c.db, c.state = db, state
    return c


class TestRoutes:
    def test_reads(self, client):
        assert client.get("/api/v1/credits/summary").json()["data"]["balance_kobo"] == 12345
        assert len(client.get("/api/v1/credits/packs").json()["data"]["packs"]) == 2
        assert client.get("/api/v1/credits/usage?days=7").json()["data"]["days"] == 7
        assert len(client.get("/api/v1/credits/ledger").json()["data"]["entries"]) == 4
        assert client.get("/api/v1/credits/orders").status_code == 200

    def test_non_managers_blocked_everywhere(self, client):
        client.state["role"] = "sales_agent"
        for path in ("summary", "usage", "ledger", "packs", "orders"):
            assert client.get(f"/api/v1/credits/{path}").status_code == 403
        assert client.post("/api/v1/credits/checkout", json={"pack_id": "p5"}).status_code == 403
        assert client.post("/api/v1/credits/verify", json={"reference": "cr_x"}).status_code == 403

    def test_checkout_pack_and_custom(self, client):
        ctx, client_mock = _paystack()
        with ctx:
            r = client.post("/api/v1/credits/checkout", json={"pack_id": "p5"})
            assert r.status_code == 200 and r.json()["data"]["checkout_url"]
            r = client.post("/api/v1/credits/checkout", json={"amount_naira": 15000})
            assert r.status_code == 200
        assert client_mock.post.call_args.kwargs["json"]["amount"] == 1_500_000
        assert client_mock.post.call_args.kwargs["json"]["callback_url"].endswith("/?credits=1")

    def test_checkout_validation(self, client):
        assert client.post("/api/v1/credits/checkout", json={}).status_code == 422
        assert client.post("/api/v1/credits/checkout", json={"pack_id": "p5", "amount_naira": 5000}).status_code == 422
        r = client.post("/api/v1/credits/checkout", json={"amount_naira": 500})
        assert r.status_code == 422 and "smallest" in r.json()["detail"]

    def test_verify_route(self, client):
        client.db.tables["credit_orders"] = [{"id": "o1", "org_id": ORG, "amount_kobo": 500000, "credit_kobo": 500000,
                                              "status": "pending", "paystack_reference": "cr_aaaa_1"}]
        ctx, _ = _paystack(verify={"status": "success", "amount": 500000})
        with ctx:
            r = client.post("/api/v1/credits/verify", json={"reference": "cr_aaaa_1"})
        assert r.json()["data"]["status"] == "paid"
        assert client.post("/api/v1/credits/verify", json={"reference": "bad"}).status_code == 422


class TestWiring:
    def test_webhook_routes_credit_topups_before_subscription_handler(self):
        import inspect
        from app.routers import webhooks
        src = inspect.getsource(webhooks.receive_paystack_webhook)
        assert "credit_topup" in src and "credit_order_service.mark_paid" in src
        assert src.index("credit_topup") < src.index("process_paystack_webhook(db=db, payload=payload)")

    def test_subscription_handler_still_used_for_other_payments(self):
        import inspect
        from app.routers import webhooks
        assert "else:\n            process_paystack_webhook" in inspect.getsource(webhooks.receive_paystack_webhook)

    def test_routes_registered(self):
        import app.main as m
        paths = {r.path for r in m.app.routes}
        assert {"/api/v1/credits/summary", "/api/v1/credits/checkout", "/api/v1/credits/verify"} <= paths
