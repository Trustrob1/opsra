"""
tests/unit/test_site_discount_service.py
-----------------------------------------
SITE-DISCOUNT — discount code rules. Uses a tiny in-memory fake of the Supabase
query builder, so no DB is needed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import site_discount_service as sd

ORG = "org-1"
B1, B2 = "builder-1", "builder-2"


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.filters, self.op, self.payload, self._desc = [], "select", None, False

    def select(self, *_a, **_k): self.op = "select"; return self
    def eq(self, k, v): self.filters.append((k, v)); return self
    def order(self, k, desc=False): self._desc = desc; return self
    def limit(self, *_a): return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def update(self, row): self.op, self.payload = "update", row; return self
    def delete(self): self.op = "delete"; return self

    def _match(self, r): return all(r.get(k) == v for k, v in self.filters)

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            row = {"id": f"{self.name}-{len(rows) + 1}", "created_at": "2026-01-01T00:00:00+00:00", **self.payload}
            if self.name == "site_discount_redemptions" and row.get("order_id") and any(
                    r.get("order_id") == row["order_id"] for r in rows):
                raise RuntimeError("duplicate order_id")
            rows.append(row)
            return _Res([row])
        if self.op == "update":
            out = []
            for r in rows:
                if self._match(r):
                    r.update(self.payload)
                    out.append(r)
            return _Res(out)
        if self.op == "delete":
            self.db.tables[self.name] = [r for r in rows if not self._match(r)]
            return _Res([])
        return _Res([dict(r) for r in rows if self._match(r)])


class FakeDB:
    def __init__(self): self.tables = {}
    def table(self, name): return _Q(self, name)


def _code(db, **over):
    payload = {"code": "welcome10", "kind": "percent", "value": 10, **over}
    return sd.create_code(db, ORG, payload)


# ── maths ───────────────────────────────────────────────────────────────────

def test_percent_and_fixed():
    assert sd.compute_discount("percent", 10, 50000) == 5000
    assert sd.compute_discount("fixed", 2000, 50000) == 2000


def test_discount_never_leaves_less_than_minimum():
    assert sd.compute_discount("percent", 100, 50000) == 50000 - sd.MIN_PAYABLE_NGN
    assert sd.compute_discount("fixed", 999999, 50000) == 50000 - sd.MIN_PAYABLE_NGN
    assert sd.compute_discount("fixed", 500, 50) == 0  # order already below the minimum


# ── validate ────────────────────────────────────────────────────────────────

def test_valid_code_is_case_and_space_insensitive():
    db = FakeDB(); _code(db)
    d = sd.validate(db, ORG, B1, " Welcome 10 ", 60000)
    assert d["discount"] == 6000 and d["amount_due"] == 54000 and d["code"] == "WELCOME10"


def test_unknown_and_inactive_codes_share_one_message():
    db = FakeDB(); c = _code(db)
    with pytest.raises(sd.DiscountError) as a:
        sd.validate(db, ORG, B1, "nope", 60000)
    sd.update_code(db, ORG, c["id"], {"active": False})
    with pytest.raises(sd.DiscountError) as b:
        sd.validate(db, ORG, B1, "welcome10", 60000)
    assert str(a.value) == str(b.value)


def test_other_orgs_code_is_not_visible():
    db = FakeDB(); _code(db)
    with pytest.raises(sd.DiscountError):
        sd.validate(db, "org-2", B1, "welcome10", 60000)


def test_expired_code():
    db = FakeDB()
    _code(db, expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    with pytest.raises(sd.DiscountError, match="expired"):
        sd.validate(db, ORG, B1, "welcome10", 60000)


def test_future_expiry_is_fine():
    db = FakeDB()
    _code(db, expires_at=(datetime.now(timezone.utc) + timedelta(days=5)).isoformat())
    assert sd.validate(db, ORG, B1, "welcome10", 60000)["discount"] == 6000


def test_max_uses_counts_paid_redemptions_only():
    db = FakeDB(); c = _code(db, max_uses=1)
    sd.validate(db, ORG, B1, "welcome10", 60000)            # an unpaid checkout does not use it up
    order = {"id": "o1", "builder_id": B1, "quote": {"discount": {"code_id": c["id"], "discount": 6000}}}
    sd.record_redemption(db, ORG, order)
    with pytest.raises(sd.DiscountError, match="used up"):
        sd.validate(db, ORG, B2, "welcome10", 60000)


def test_one_per_builder():
    db = FakeDB(); c = _code(db, one_per_builder=True)
    sd.record_redemption(db, ORG, {"id": "o1", "builder_id": B1, "quote": {"discount": {"code_id": c["id"], "discount": 1}}})
    with pytest.raises(sd.DiscountError, match="already used"):
        sd.validate(db, ORG, B1, "welcome10", 60000)
    assert sd.validate(db, ORG, B2, "welcome10", 60000)


def test_record_redemption_is_idempotent_and_never_raises():
    db = FakeDB(); c = _code(db)
    order = {"id": "o1", "builder_id": B1, "quote": {"discount": {"code_id": c["id"], "discount": 600}}}
    sd.record_redemption(db, ORG, order)
    sd.record_redemption(db, ORG, order)                     # duplicate webhook
    sd.record_redemption(db, ORG, {"id": "o2", "quote": {}})  # no discount on the order
    assert len(db.tables["site_discount_redemptions"]) == 1


# ── apply_to_quotes ─────────────────────────────────────────────────────────

def _quotes():
    return {"standard": {"price": {"total": 50000}}, "express": None}


def test_apply_to_quotes_adds_discount_and_amount_due():
    db = FakeDB(); _code(db, kind="fixed", value=2000)
    q = sd.apply_to_quotes(db, ORG, B1, "WELCOME10", _quotes())
    assert q["standard"]["discount"]["discount"] == 2000 and q["standard"]["amount_due"] == 48000
    assert "discount_error" not in q


def test_apply_to_quotes_bad_code_reports_error_and_keeps_prices():
    db = FakeDB()
    q = sd.apply_to_quotes(db, ORG, B1, "NOPE", _quotes())
    assert q["discount_error"] and "discount" not in q["standard"]
    assert q["standard"]["price"]["total"] == 50000


def test_apply_to_quotes_without_code_changes_nothing():
    db = FakeDB()
    assert sd.apply_to_quotes(db, ORG, B1, "  ", _quotes()) == _quotes()


# ── staff management ────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload", [
    {"code": "ab", "kind": "percent", "value": 10},
    {"code": "has space!", "kind": "percent", "value": 10},
    {"code": "GOOD", "kind": "weird", "value": 10},
    {"code": "GOOD", "kind": "percent", "value": 150},
    {"code": "GOOD", "kind": "fixed", "value": 0},
    {"code": "GOOD", "kind": "fixed", "value": "abc"},
    {"code": "GOOD", "kind": "fixed", "value": 5, "max_uses": 0},
    {"code": "GOOD", "kind": "fixed", "value": 5, "expires_at": "not a date"},
])
def test_create_rejects_bad_input(payload):
    with pytest.raises(sd.DiscountError):
        sd.create_code(FakeDB(), ORG, payload)


def test_duplicate_code_name_rejected():
    db = FakeDB(); _code(db)
    with pytest.raises(sd.DiscountError, match="already have"):
        _code(db, code="WELCOME10")


def test_update_value_respects_percent_cap():
    db = FakeDB(); c = _code(db)
    with pytest.raises(sd.DiscountError):
        sd.update_code(db, ORG, c["id"], {"value": 120})


def test_list_shows_uses_and_total_given():
    db = FakeDB(); c = _code(db)
    sd.record_redemption(db, ORG, {"id": "o1", "builder_id": B1, "quote": {"discount": {"code_id": c["id"], "discount": 600}}})
    row = sd.list_codes(db, ORG)[0]
    assert row["uses"] == 1 and row["discount_given_ngn"] == 600


def test_delete_unused_removes_but_used_is_switched_off():
    db = FakeDB(); a = _code(db, code="UNUSED"); b = _code(db, code="USEDONE")
    sd.record_redemption(db, ORG, {"id": "o1", "builder_id": B1, "quote": {"discount": {"code_id": b["id"], "discount": 1}}})
    sd.delete_code(db, ORG, a["id"]); sd.delete_code(db, ORG, b["id"])
    left = {r["code"]: r for r in db.tables["site_discount_codes"]}
    assert "UNUSED" not in left and left["USEDONE"]["active"] is False
