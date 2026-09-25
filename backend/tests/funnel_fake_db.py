"""
tests/funnel_fake_db.py
------------------------
FUNNEL-1A — tiny in-memory stand-in for the Supabase client, used by the
funnel tests so whole flows (inbound → registration → pay link → webhook)
can be exercised without long MagicMock chains (T2).

Supports: table().select/eq/neq/in_/gte/lte/lt/gt/is_/limit/order/range/
maybe_single/single/insert/update/delete/execute, plus unique constraints
(including the partial funnel_events (registration_id, step_key) index).
Embedded selects like "id, roles(template)" return the stored row as-is.
"""
from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace
from typing import Any, Optional

UNIQUE = {
    "funnel_registrations": [("funnel_id", "phone"), ("funnel_id", "ref_code"), ("pay_token",)],
    "funnel_payments": [("reference",)],
    "funnel_events": [("registration_id", "step_key")],   # partial: step_key not null
    "payment_links": [("reference",)],
}


class UniqueViolation(Exception):
    pass


def _cmp_val(v):
    return "" if v is None else str(v)


class Query:
    def __init__(self, db: "FakeDB", name: str):
        self.db, self.name = db, name
        self.filters: list = []
        self.op = "select"
        self.payload: Any = None
        self._limit: Optional[int] = None
        self._range: Optional[tuple] = None
        self._single = False
        self._order: Optional[tuple] = None

    # builders
    def select(self, *_a, **_k): self.op = "select"; return self
    def eq(self, c, v): self.filters.append(lambda r: r.get(c) == v); return self
    def neq(self, c, v): self.filters.append(lambda r: r.get(c) != v); return self
    def in_(self, c, vs): vs = list(vs); self.filters.append(lambda r: r.get(c) in vs); return self
    def gte(self, c, v): self.filters.append(lambda r: r.get(c) is not None and _cmp_val(r.get(c)) >= _cmp_val(v)); return self
    def lte(self, c, v): self.filters.append(lambda r: r.get(c) is not None and _cmp_val(r.get(c)) <= _cmp_val(v)); return self
    def gt(self, c, v): self.filters.append(lambda r: r.get(c) is not None and _cmp_val(r.get(c)) > _cmp_val(v)); return self
    def lt(self, c, v): self.filters.append(lambda r: r.get(c) is not None and _cmp_val(r.get(c)) < _cmp_val(v)); return self

    def is_(self, c, v):
        if v in ("null", None):
            self.filters.append(lambda r: r.get(c) is None)
        else:
            self.filters.append(lambda r: r.get(c) is not None)
        return self

    def limit(self, n): self._limit = n; return self
    def range(self, a, b): self._range = (a, b); return self
    def order(self, col, desc=False): self._order = (col, desc); return self
    def maybe_single(self): self._single = True; return self
    def single(self): self._single = True; return self
    def insert(self, payload): self.op = "insert"; self.payload = payload; return self
    def update(self, payload): self.op = "update"; self.payload = payload; return self
    def upsert(self, payload, **_k): self.op = "insert"; self.payload = payload; return self
    def delete(self): self.op = "delete"; return self

    def _match(self):
        return [r for r in self.db.tables.setdefault(self.name, []) if all(f(r) for f in self.filters)]

    def execute(self):
        self.db.calls.append((self.name, self.op))
        if self.op == "insert":
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for row in rows:
                row = copy.deepcopy(row)
                row.setdefault("id", str(uuid.uuid4()))
                self.db._check_unique(self.name, row)
                self.db.tables.setdefault(self.name, []).append(row)
                out.append(copy.deepcopy(row))
            return SimpleNamespace(data=out)
        if self.op == "update":
            matched = self._match()
            for r in matched:
                candidate = dict(r)
                candidate.update(copy.deepcopy(self.payload))
                self.db._check_unique(self.name, candidate, exclude=r)
                r.update(copy.deepcopy(self.payload))
            return SimpleNamespace(data=[copy.deepcopy(r) for r in matched])
        if self.op == "delete":
            matched = self._match()
            self.db.tables[self.name] = [r for r in self.db.tables.get(self.name, []) if r not in matched]
            return SimpleNamespace(data=matched)
        rows = [copy.deepcopy(r) for r in self._match()]
        if self._order:
            col, desc = self._order
            rows.sort(key=lambda r: _cmp_val(r.get(col)), reverse=desc)
        if self._range:
            a, b = self._range
            rows = rows[a:b + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._single:
            return SimpleNamespace(data=rows[0] if rows else None)
        return SimpleNamespace(data=rows)


class FakeDB:
    def __init__(self, **tables):
        self.tables: dict[str, list] = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.calls: list = []

    def table(self, name: str) -> Query:
        return Query(self, name)

    def rows(self, name: str) -> list:
        return self.tables.get(name, [])

    def _check_unique(self, name: str, row: dict, exclude: Optional[dict] = None):
        for cols in UNIQUE.get(name, []):
            if name == "funnel_events" and row.get("step_key") is None:
                continue
            key = tuple(row.get(c) for c in cols)
            for other in self.tables.get(name, []):
                if other is exclude:
                    continue
                if tuple(other.get(c) for c in cols) == key:
                    raise UniqueViolation(f"duplicate key {name}{cols}={key}")
