"""WA-AUTO-2: the contact export for the simple inbox."""
from __future__ import annotations

import csv
import io

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.services import contact_export_service as cx
from tests.unit.test_account_plans_1 import FakeDB

ORG = "00000000-0000-0000-0000-00000000aa01"
OTHER = "00000000-0000-0000-0000-00000000aa02"


def _db(**extra):
    return FakeDB(
        leads=[
            {"org_id": ORG, "full_name": "Ada", "whatsapp": "2348000000001", "source": "whatsapp_inbound", "created_at": "2026-10-01T10:00:00", "deleted_at": None},
            {"org_id": ORG, "full_name": "=HYPERLINK(\"http://x\")", "whatsapp": "2348000000002", "source": "-cmd", "created_at": "2026-10-02T10:00:00", "deleted_at": None},
            {"org_id": ORG, "full_name": "No number", "whatsapp": None, "source": "x", "created_at": "2026-10-03T10:00:00", "deleted_at": None},
            {"org_id": OTHER, "full_name": "Someone else", "whatsapp": "2348999999999", "source": "x", "created_at": "2026-10-04T10:00:00", "deleted_at": None},
            {"org_id": ORG, "full_name": "Deleted", "whatsapp": "2348000000003", "source": "x", "created_at": "2026-10-05T10:00:00", "deleted_at": "2026-10-06"},
        ],
        customers=[{"org_id": ORG, "full_name": "Bola", "whatsapp": "2348000000004", "created_at": "2026-09-01T10:00:00", "deleted_at": None}],
        audit_logs=[], **extra)


def _parse(text):
    return list(csv.reader(io.StringIO(text)))


def test_csv_has_only_this_orgs_live_contacts_with_a_number():
    text, n = cx.build_csv(_db(), ORG)
    rows = _parse(text)
    assert rows[0] == cx.HEADER
    numbers = {r[1] for r in rows[1:]}
    assert numbers == {"2348000000001", "2348000000002", "2348000000004"} and n == 3
    assert ("Bola", "2348000000004", "customer") == tuple(rows[-1][:3]) or any(r[0] == "Bola" and r[2] == "customer" for r in rows)


def test_spreadsheet_formulas_are_defused():
    rows = _parse(cx.build_csv(_db(), ORG)[0])
    bad = [r for r in rows if r[1] == "2348000000002"][0]
    assert bad[0].startswith("'=") and bad[3] == "'-cmd"


def test_an_unreadable_table_is_skipped_not_fatal():
    class Boom(FakeDB):
        def table(self, name):
            if name == "customers":
                raise RuntimeError("down")
            return super().table(name)
    db = Boom(leads=_db().tables["leads"], audit_logs=[])
    text, n = cx.build_csv(db, ORG)
    assert n == 2


def test_audit_row_is_written():
    db = _db()
    cx.write_audit(db, ORG, "user-1", 3)
    row = db.tables["audit_logs"][0]
    assert row["action"] == "contacts_exported" and row["new_value"] == {"count": 3} and row["org_id"] == ORG


def _client(db, template):
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: {"org_id": ORG, "id": "user-1", "roles": {"template": template}}
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    yield
    from app.main import app
    app.dependency_overrides.clear()


def test_owner_gets_the_csv_and_it_is_audited():
    db = _db()
    r = _client(db, "owner").get("/api/v1/contacts/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    assert "2348000000001" in r.text
    assert len(db.tables["audit_logs"]) == 1


@pytest.mark.parametrize("template", ["sales_agent", "ops_manager", "admin", ""])
def test_everyone_else_is_refused_and_nothing_is_logged(template):
    db = _db()
    r = _client(db, template).get("/api/v1/contacts/export")
    assert r.status_code == 403 and "2348000000001" not in r.text
    assert db.tables["audit_logs"] == []


def test_export_is_not_handed_over_when_the_audit_cannot_be_written():
    class NoAudit(FakeDB):
        def table(self, name):
            if name == "audit_logs":
                raise RuntimeError("down")
            return super().table(name)
    db = NoAudit(leads=_db().tables["leads"], customers=[])
    r = _client(db, "owner").get("/api/v1/contacts/export")
    assert r.status_code == 500 and "2348000000001" not in r.text
