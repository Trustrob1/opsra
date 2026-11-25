"""INV-2: routes the screens need - money summary, product and contact pickers, invoice logo upload."""
from __future__ import annotations

import io
from datetime import date, timedelta
from types import SimpleNamespace

from tests.unit.test_invoices_1 import (  # noqa: F401  (_plan_allows is an autouse fixture)
    InvDB, InvQuery, LEAD, LEAD_OTHER, ORG, OTHER, PROD, PROD_OTHER, USER, _client, _db, _draft, _plan_allows,
)
from app.services import invoice_service as inv


class Q2(InvQuery):
    def ilike(self, col, pattern):
        needle = pattern.strip("%").lower()
        self.filters.append(lambda r: needle in str(r.get(col) or "").lower())
        return self


class FakeBucket:
    def __init__(self, store):
        self.store = store

    def upload(self, path, file, file_options=None):
        self.store[path] = file

    def get_public_url(self, path):
        return f"https://x.supabase.co/storage/v1/object/public/catalog/{path}?"


class DB2(InvDB):
    def __init__(self, **tables):
        super().__init__(**tables)
        self.files: dict = {}
        self.storage = SimpleNamespace(from_=lambda bucket: FakeBucket(self.files))

    def table(self, name):
        return Q2(self, name)


def _db2():
    db = DB2(**_db().tables)
    for r in db.rows("leads"):
        r.setdefault("last_activity_at", "2026-11-01T00:00:00+00:00")
    db.rows("products").append({"id": "99999999-9999-9999-9999-999999999999", "org_id": ORG, "title": "Old pillow",
                                "price": 5, "is_active": False})
    return db


def _png(w=1200, h=300):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (13, 148, 136)).save(buf, format="PNG")
    return buf.getvalue()


# ───────────────────────────── summary ─────────────────────────────

def test_summary_counts_owed_overdue_quotes_and_drafts():
    db = _db2()
    _draft(db)                                                    # a draft
    owed = inv.issue(db, ORG, USER, _draft(db)["id"])             # 30,000 owed, not due yet
    late = inv.issue(db, ORG, USER, _draft(db)["id"])
    for r in db.rows("invoices"):
        if r["id"] == late["id"]:
            r["due_date"] = (date.today() - timedelta(days=3)).isoformat()
            r["status"] = "part_paid"
            r["amount_paid"] = 10000
    inv.issue(db, ORG, USER, _draft(db, doc_type="quote")["id"])  # an open quote
    s = inv.summary(db, ORG)
    assert s["drafts"] == 1
    assert s["outstanding_count"] == 2 and s["outstanding_amount"] == 50000.0
    assert s["overdue_count"] == 1 and s["overdue_amount"] == 20000.0
    assert s["open_quotes"] == 1 and s["open_quotes_amount"] == 30000.0
    assert owed["number"] == "INV-0001"


def test_summary_route_only_counts_this_org():
    db = _db2()
    inv.issue(db, ORG, USER, _draft(db)["id"])
    for r in db.rows("invoices"):
        r["org_id"] = OTHER
    r = _client(db).get("/api/v1/invoices/summary")
    assert r.status_code == 200 and r.json()["data"]["outstanding_count"] == 0


# ───────────────────────────── pickers ─────────────────────────────

def test_product_picker_is_org_scoped_and_skips_hidden():
    db = _db2()
    rows = _client(db).get("/api/v1/invoices/products").json()["data"]
    ids = [r["id"] for r in rows]
    assert PROD in ids and PROD_OTHER not in ids and len(ids) == 1
    rows = _client(db).get("/api/v1/invoices/products", params={"q": "ortho"}).json()["data"]
    assert [r["id"] for r in rows] == [PROD]
    assert _client(db).get("/api/v1/invoices/products", params={"q": "zzz"}).json()["data"] == []


def test_contact_picker_is_org_scoped_and_searches_phone():
    db = _db2()
    c = _client(db)
    assert [r["id"] for r in c.get("/api/v1/invoices/contacts", params={"q": "ada"}).json()["data"]] == [LEAD]
    assert [r["id"] for r in c.get("/api/v1/invoices/contacts", params={"q": "23480111"}).json()["data"]] == [LEAD]
    assert LEAD_OTHER not in [r["id"] for r in c.get("/api/v1/invoices/contacts", params={"q": "yours"}).json()["data"]]


def test_needle_strips_filter_syntax():
    out = inv._needle("ada),org_id.eq.x%")
    assert not set(out) & set(",()%*:\"'\\")
    assert inv._needle("  ") == "" and inv._needle(None) == ""
    assert len(inv._needle("a" * 500)) <= 60


def test_picker_routes_are_not_shadowed_by_doc_id():
    db = _db2()
    c = _client(db)
    for path in ("summary", "products", "contacts"):
        assert c.get(f"/api/v1/invoices/{path}").status_code == 200, path


# ───────────────────────────── logo ─────────────────────────────

def test_logo_upload_is_resized_stored_under_org_and_saved():
    db = _db2()
    c = _client(db)
    r = c.post("/api/v1/invoices/settings/logo", files={"file": ("logo.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    url = r.json()["data"]["logo_url"]
    assert url.startswith("https://x.supabase.co/storage/v1/object/public/catalog/" + ORG + "/invoice-logo/")
    assert not url.endswith("?")
    (path, data), = db.files.items()
    assert path.startswith(f"{ORG}/invoice-logo/") and data[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    assert max(Image.open(io.BytesIO(data)).size) <= 600
    r = c.delete("/api/v1/invoices/settings/logo")
    assert r.status_code == 200 and r.json()["data"]["logo_url"] is None


def test_logo_rejects_non_images_and_big_files():
    db = _db2()
    c = _client(db)
    r = c.post("/api/v1/invoices/settings/logo", files={"file": ("x.png", b"<svg onload=alert(1)>", "image/png")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (inv.LOGO_MAX_BYTES + 1)
    assert c.post("/api/v1/invoices/settings/logo", files={"file": ("x.png", big, "image/png")}).status_code == 422
    assert db.files == {}


def test_logo_upload_needs_admin():
    db = _db2()
    r = _client(db, admin=False).post("/api/v1/invoices/settings/logo", files={"file": ("l.png", _png(), "image/png")})
    assert r.status_code == 403 and db.files == {}
