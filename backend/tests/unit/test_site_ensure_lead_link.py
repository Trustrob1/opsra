"""
tests/unit/test_site_ensure_lead_link.py
-----------------------------------------
A builder added by hand has no CRM lead, and creating one is refused when the same email or number is already a lead
(the builder's own WhatsApp lead, say). The checkout then said "no linked CRM lead yet". ensure_lead now links the
existing lead, and checkout / care plan / renewal / Premium billing call it instead of giving up.
"""
from __future__ import annotations

from app.services import site_access_service as acc


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.f, self.upd = db, table, [], None

    def select(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def update(self, row): self.upd = row; return self
    def eq(self, c, v): self.f.append((c, lambda x, v=v: x == v)); return self
    def ilike(self, c, v): self.f.append((c, lambda x, v=v: (x or "").lower() == v.lower())); return self

    def execute(self):
        rows = [r for r in self.db.rows[self.table] if all(fn(r.get(c)) for c, fn in self.f)]
        if self.upd is not None:
            for r in rows:
                r.update(self.upd)
        class R: pass
        out = R(); out.data = rows
        return out


class _Db:
    def __init__(self, leads, builders):
        self.rows = {"leads": leads, "site_builders": builders}

    def table(self, name): return _Q(self, name)


LEAD = {"id": "lead-1", "org_id": "o1", "email": "Trust@Example.com", "phone": "2348109374720", "whatsapp": "2348109374720"}


def _builder(**k):
    return {"id": "b1", "org_id": "o1", "full_name": "Test Name", "email": "trust@example.com",
            "phone_number": "2348109374751", "lead_id": None, **k}


def test_links_the_lead_with_the_same_email():
    b = _builder()
    db = _Db([dict(LEAD)], [b])
    assert acc.ensure_lead(db, "o1", b) == "lead-1"
    assert b["lead_id"] == "lead-1" and db.rows["site_builders"][0]["lead_id"] == "lead-1"


def test_links_the_lead_with_the_same_number_with_or_without_plus():
    b = _builder(email="other@example.com", phone_number="+2348109374720")
    assert acc.ensure_lead(_Db([dict(LEAD)], [b]), "o1", b) == "lead-1"


def test_another_business_lead_is_never_linked():
    b = _builder()
    lead = {**LEAD, "org_id": "other-org"}
    db = _Db([lead], [b])
    assert acc._existing_lead_id(db, "o1", b) is None


def test_builder_that_already_has_a_lead_is_left_alone():
    b = _builder(lead_id="keep")
    assert acc.ensure_lead(_Db([dict(LEAD)], [b]), "o1", b) == "keep"


def test_lookup_failure_returns_none_instead_of_raising():
    class Boom:
        def table(self, _n): raise RuntimeError("db down")
    assert acc._existing_lead_id(Boom(), "o1", _builder()) is None


def test_checkout_no_longer_stops_when_a_lead_can_be_linked(monkeypatch):
    """create_checkout used to raise at once for a builder with no lead_id; it now asks ensure_lead first."""
    import pytest
    from types import SimpleNamespace
    from app.services import site_order_service as orders
    called = {}
    monkeypatch.setattr(acc, "ensure_lead", lambda db, org, b: called.setdefault("n", 1) and "lead-1")

    class Db:
        def table(self, _n): return _Q2()

    class _Q2:
        def __getattr__(self, _name): return lambda *a, **k: self
        def execute(self):
            return SimpleNamespace(data=[{"id": "s1", "option_offered": False}])

    class Stop(Exception):
        pass

    from app.services import pricing_service
    monkeypatch.setattr(pricing_service, "get_settings", lambda *a, **k: (_ for _ in ()).throw(Stop()))
    payload = SimpleNamespace(site_id="s1")
    with pytest.raises(Stop):          # got past the lead check and reached pricing
        orders.create_checkout(Db(), "o1", {"id": "b1", "lead_id": None}, payload)
    assert called.get("n") == 1
