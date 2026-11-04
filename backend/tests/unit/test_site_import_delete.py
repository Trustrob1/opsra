"""
tests/unit/test_site_import_delete.py
--------------------------------------
DELETE-IMPORT-1 - delete one saved import: its row and stored files go, the design in use never does. No network, no database.
"""
from __future__ import annotations

import pytest

from app.services import site_import_service as svc

ORG, SITE = "org-1", "site-1"


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op = db, table, [], "select"

    def select(self, *_a, **_k): return self
    def delete(self): self.op = "delete"; return self
    def eq(self, k, v): self.filters.append((k, v)); return self
    def limit(self, *_a): return self

    def _rows(self):
        return [r for r in self.db.rows[self.table] if all(r.get(k) == v for k, v in self.filters)]

    def execute(self):
        if self.op == "delete":
            if self.db.fail_delete:
                raise RuntimeError("foreign key violation")
            gone = self._rows()
            self.db.rows[self.table] = [r for r in self.db.rows[self.table] if r not in gone]
            return type("R", (), {"data": gone})()
        return type("R", (), {"data": self._rows()})()


class _Bucket:
    def __init__(self, db, name): self.db, self.name = db, name
    def remove(self, keys): self.db.removed.append((self.name, list(keys)))


class _Storage:
    def __init__(self, db): self.db = db
    def from_(self, name): return _Bucket(self.db, name)


class FakeDb:
    def __init__(self, rows, fail_delete=False):
        self.rows, self.removed, self.fail_delete = {"site_designs": rows}, [], fail_delete
        self.storage = _Storage(self)

    def table(self, name): return _Q(self, name)


def design(did, version, **over):
    row = {"id": did, "site_id": SITE, "org_id": ORG, "version": version, "kind": "import", "source_path": f"raw/{did}.zip",
           "files_prefix": f"{ORG}/{SITE}/tok/v{version}",
           "import_meta": {"files": [{"path": "index.html", "stored": False},
                                      {"path": "css/a.css", "stored": True, "storage_path": f"{ORG}/{SITE}/tok/v{version}/css/a.css"},
                                      {"path": "about/index.html", "stored": True, "page": True,
                                       "storage_path": f"{ORG}/{SITE}/tok/v{version}/about/index.html"}]}}
    row.update(over)
    return row


SITE_ROW = {"id": SITE, "org_id": ORG, "current_design_id": "d3", "tier": "imported"}


def test_deletes_the_row_stored_files_and_raw_upload():
    db = FakeDb([design("d1", 1), design("d3", 3)])
    out = svc.delete_import(db, ORG, SITE_ROW, "d1")
    assert out == {"deleted": True, "design_id": "d1", "version": 1, "files": 2}
    assert [r["id"] for r in db.rows["site_designs"]] == ["d3"]
    assert ("site-import-files", [f"{ORG}/{SITE}/tok/v1/css/a.css", f"{ORG}/{SITE}/tok/v1/about/index.html"]) in db.removed
    assert ("site-imports", ["raw/d1.zip"]) in db.removed


def test_the_design_in_use_is_never_deleted():
    db = FakeDb([design("d3", 3)])
    with pytest.raises(svc.ImportBlocked) as e:
        svc.delete_import(db, ORG, SITE_ROW, "d3")
    assert e.value.status_code == 409 and "using" in str(e.value)
    assert len(db.rows["site_designs"]) == 1 and db.removed == []


@pytest.mark.parametrize("bad", [
    design("d9", 9, site_id="other-site"),            # another site's import
    design("d9", 9, org_id="other-org"),              # another account's import
    design("d9", 9, files_prefix=None),               # a Premium pasted skeleton: no uploaded files
    design("d9", 9, kind="premium"),                  # not an import at all
])
def test_other_rows_are_not_found_and_left_alone(bad):
    db = FakeDb([bad, design("d3", 3)])
    with pytest.raises(svc.ImportNotFound):
        svc.delete_import(db, ORG, SITE_ROW, "d9")
    assert len(db.rows["site_designs"]) == 2 and db.removed == []


def test_unknown_id_is_not_found():
    with pytest.raises(svc.ImportNotFound):
        svc.delete_import(FakeDb([design("d3", 3)]), ORG, SITE_ROW, "nope")


def test_if_the_database_refuses_the_delete_the_files_are_kept():
    db = FakeDb([design("d1", 1), design("d3", 3)], fail_delete=True)
    with pytest.raises(svc.ImportFailed) as e:
        svc.delete_import(db, ORG, SITE_ROW, "d1")
    assert "still used" in str(e.value)
    assert len(db.rows["site_designs"]) == 2 and db.removed == []
