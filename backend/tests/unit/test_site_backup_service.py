"""
tests/unit/test_site_backup_service.py
---------------------------------------
SITE-BACKUP — nightly R2 -> separate backup bucket copy. Uses an in-memory fake S3 (two instances: R2 and the
backup bucket) and a tiny in-memory fake of the Supabase client. No network.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.services import site_backup_service as bk

D1 = "adaezastyles.com.ng"
D2 = "brightpath.ng"
NOW = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)


# ── fakes ───────────────────────────────────────────────────────────────────

class FakeS3:
    def __init__(self, objects=None, page_size=1000, fail_get=None, fail_put=None, drop_on_put=None):
        self.objects = {}
        for k, v in (objects or {}).items():
            self.put_object(Bucket="b", Key=k, Body=v if isinstance(v, bytes) else v.encode())
        self.page_size = page_size
        self.fail_get, self.fail_put, self.drop_on_put = fail_get, fail_put, drop_on_put
        self.deleted = []

    def put_object(self, Bucket, Key, Body, **kw):
        if getattr(self, "fail_put", None) and self.fail_put in Key:
            raise RuntimeError("put boom")
        if getattr(self, "drop_on_put", None) and self.drop_on_put in Key:
            return  # silently loses the file -> verification must catch it
        self.objects[Key] = {"body": Body, "etag": hashlib.md5(Body).hexdigest(), **kw}

    def get_object(self, Bucket, Key):
        if self.fail_get and self.fail_get in Key:
            raise RuntimeError("get boom")
        o = self.objects[Key]
        import io
        return {"Body": io.BytesIO(o["body"]), "ContentType": o.get("ContentType", "application/octet-stream")}

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, MaxKeys=1000, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        if Delimiter:
            prefixes = sorted({Prefix + k[len(Prefix):].split(Delimiter)[0] + Delimiter
                               for k in keys if Delimiter in k[len(Prefix):]})
            return {"CommonPrefixes": [{"Prefix": p} for p in prefixes], "IsTruncated": False}
        start = int(ContinuationToken or 0)
        size = min(self.page_size, MaxKeys)
        page = keys[start:start + size]
        more = start + size < len(keys)
        out = {"Contents": [{"Key": k, "Size": len(self.objects[k]["body"]), "ETag": f'"{self.objects[k]["etag"]}"'} for k in page],
               "IsTruncated": more}
        if more:
            out["NextContinuationToken"] = str(start + size)
        return out

    def delete_objects(self, Bucket, Delete, **_):
        for o in Delete["Objects"]:
            self.deleted.append(o["Key"])
            self.objects.pop(o["Key"], None)


class _Res:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.op, self.payload = db, name, "select", None
        self.filters, self._order, self._limit = [], None, None

    def select(self, *_a, **_k): return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def update(self, row): self.op, self.payload = "update", row; return self
    def eq(self, c, v): self.filters.append(lambda r: r.get(c) == v); return self
    def in_(self, c, vs): self.filters.append(lambda r: r.get(c) in vs); return self
    def gte(self, c, v): self.filters.append(lambda r: str(r.get(c) or "") >= str(v)); return self
    def order(self, c, desc=False): self._order = (c, desc); return self
    def limit(self, n): self._limit = n; return self

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            row = dict(self.payload)
            row.setdefault("id", f"{self.name}-{len(rows) + 1}")
            row.setdefault("created_at", f"{len(rows):08d}")  # insertion order stands in for time
            rows.append(row)
            return _Res([dict(row)])
        match = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "update":
            for r in match:
                r.update(self.payload)
            return _Res([dict(r) for r in match])
        if self._order:
            c, desc = self._order
            match.sort(key=lambda r: str(r.get(c) or ""), reverse=desc)
        if self._limit:
            match = match[: self._limit]
        return _Res([dict(r) for r in match])


class FakeDB:
    def __init__(self): self.tables = {}
    def table(self, name): return _Q(self, name)


def r2_with(*domains):
    objs = {}
    for d in domains:
        objs[f"{d}/index.html"] = f"<html>{d}</html>"
        objs[f"{d}/robots.txt"] = "User-agent: *"
        objs[f"{d}/images/hero.jpg"] = b"JPG" + d.encode()
    return FakeS3(objs)


def run(db, r2, b2, now=NOW, **kw):
    return bk.run_backup(db, src=r2, dst=b2, src_bucket="opsra-sites", dst_bucket="backups", now=now, **kw)


# ── manifest / listing ──────────────────────────────────────────────────────

def test_manifest_hash_ignores_order_and_etag_quotes():
    a = [("index.html", '"abc"', 5), ("images/a.jpg", "def", 9)]
    b = [("images/a.jpg", "def", 9), ("index.html", "abc", 5)]
    assert bk.manifest_hash(a) == bk.manifest_hash(b)
    assert bk.manifest_hash(a) != bk.manifest_hash([("index.html", "abc", 6), ("images/a.jpg", "def", 9)])


def test_list_source_sites_groups_by_domain_and_skips_strays():
    s3 = r2_with(D1, D2)
    s3.put_object(Bucket="b", Key="stray.txt", Body=b"x")          # no folder
    s3.put_object(Bucket="b", Key="not_a_domain/index.html", Body=b"x")
    s3.put_object(Bucket="b", Key=f"{D1}/folder/", Body=b"")        # folder marker
    s3.page_size = 2                                                 # force paging
    sites = bk.list_source_sites(s3, "opsra-sites")
    assert set(sites) == {D1, D2}
    assert {p for p, _e, _s in sites[D1]} == {"index.html", "robots.txt", "images/hero.jpg"}


# ── a normal run ────────────────────────────────────────────────────────────

def test_first_run_copies_every_site_and_records_it():
    db, r2, b2 = FakeDB(), r2_with(D1, D2), FakeS3()
    out = run(db, r2, b2)
    assert out["status"] == "ok" and out["domains_total"] == 2 and out["domains_backed_up"] == 2
    assert out["files_copied"] == 6 and out["domains_failed"] == 0
    assert set(b2.objects) == {f"snapshots/{d}/2026-10-02/{p}" for d in (D1, D2)
                               for p in ("index.html", "robots.txt", "images/hero.jpg")}
    run_row = db.tables["site_backup_runs"][0]
    assert run_row["status"] == "ok" and run_row["finished_at"] and run_row["domains_backed_up"] == 2
    items = db.tables["site_backup_items"]
    assert {i["domain"] for i in items} == {D1, D2} and all(i["verified"] and i["status"] == "backed_up" for i in items)


def test_content_type_and_source_etag_are_kept():
    r2 = FakeS3()
    r2.put_object(Bucket="b", Key=f"{D1}/index.html", Body=b"<html/>", ContentType="text/html; charset=utf-8")
    b2 = FakeS3()
    run(FakeDB(), r2, b2)
    o = b2.objects[f"snapshots/{D1}/2026-10-02/index.html"]
    assert o["ContentType"] == "text/html; charset=utf-8"
    assert o["Metadata"]["src-etag"] == hashlib.md5(b"<html/>").hexdigest()


def test_nothing_is_ever_written_or_deleted_in_r2():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    before = dict(r2.objects)
    run(db, r2, b2)
    assert r2.objects == before and r2.deleted == []


def test_unchanged_site_is_not_copied_again():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    run(db, r2, b2)
    puts_before = dict(b2.objects)
    out = run(db, r2, b2, now=NOW + timedelta(days=1))
    assert out["domains_unchanged"] == 1 and out["domains_backed_up"] == 0 and out["files_copied"] == 0
    assert b2.objects == puts_before                      # no 2026-10-03 snapshot made
    item = db.tables["site_backup_items"][-1]
    assert item["status"] == "unchanged" and str(item["snapshot_date"]) == "2026-10-02"


def test_changed_site_gets_a_new_snapshot_and_old_one_stays():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    run(db, r2, b2)
    r2.put_object(Bucket="b", Key=f"{D1}/index.html", Body=b"<html>edited</html>")
    out = run(db, r2, b2, now=NOW + timedelta(days=1))
    assert out["domains_backed_up"] == 1
    assert bk.list_snapshot_dates(b2, "backups", D1) == ["2026-10-03", "2026-10-02"]
    assert b2.objects[f"snapshots/{D1}/2026-10-02/index.html"]["body"] == f"<html>{D1}</html>".encode()
    assert b2.objects[f"snapshots/{D1}/2026-10-03/index.html"]["body"] == b"<html>edited</html>"


def test_unchanged_but_snapshot_missing_in_backup_is_recopied():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    run(db, r2, b2)
    for k in [k for k in b2.objects if k.startswith(f"snapshots/{D1}/")]:
        del b2.objects[k]                                  # someone emptied the backup bucket
    out = run(db, r2, b2, now=NOW + timedelta(days=1))
    assert out["domains_backed_up"] == 1 and out["domains_unchanged"] == 0
    assert any(k.startswith(f"snapshots/{D1}/2026-10-03/") for k in b2.objects)


def test_rerun_same_day_after_change_leaves_no_leftovers():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    run(db, r2, b2)
    del r2.objects[f"{D1}/robots.txt"]
    run(db, r2, b2, now=NOW + timedelta(hours=5))          # same date, one file fewer
    keys = {k for k in b2.objects if k.startswith(f"snapshots/{D1}/2026-10-02/")}
    assert keys == {f"snapshots/{D1}/2026-10-02/index.html", f"snapshots/{D1}/2026-10-02/images/hero.jpg"}


# ── failures ────────────────────────────────────────────────────────────────

def test_one_failing_site_does_not_stop_the_others():
    db, r2, b2 = FakeDB(), r2_with(D1, D2), FakeS3()
    r2.fail_get = D1
    out = run(db, r2, b2)
    assert out["status"] == "partial" and out["domains_failed"] == 1 and out["domains_backed_up"] == 1
    assert out["failures"][0]["domain"] == D1 and D1 in out["error"]
    assert any(k.startswith(f"snapshots/{D2}/") for k in b2.objects)
    failed = [i for i in db.tables["site_backup_items"] if i["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["verified"] is False
    assert db.tables["site_backup_runs"][0]["status"] == "partial"


def test_failed_site_is_retried_next_night():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    r2.fail_get = D1
    assert run(db, r2, b2)["status"] == "failed"
    r2.fail_get = None
    out = run(db, r2, b2, now=NOW + timedelta(days=1))
    assert out["status"] == "ok" and out["domains_backed_up"] == 1


def test_copy_that_does_not_match_the_source_is_a_failure():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3(drop_on_put="robots.txt")
    out = run(db, r2, b2)
    assert out["status"] == "failed" and "verification failed" in out["error"]


@pytest.mark.parametrize("endpoint,configured,want", [
    ("https://46cd988efbb236bf3dcf5802a6db8a03.r2.cloudflarestorage.com", "", "auto"),
    ("https://abc123.eu.r2.cloudflarestorage.com", "", "auto"),
    ("https://46cd988efbb236bf3dcf5802a6db8a03.r2.cloudflarestorage.com", "auto", "auto"),
    ("https://s3.us-west-004.backblazeb2.com", "", "us-west-004"),
    ("https://s3.eu-central-003.backblazeb2.com", "", "eu-central-003"),
    ("https://s3.example.com", "", "us-east-1"),
    ("https://s3.us-west-004.backblazeb2.com", "us-west-002", "us-west-002"),
])
def test_backup_region(endpoint, configured, want):
    assert bk.backup_region(endpoint, configured) == want


def test_not_configured_is_recorded_as_a_failed_run(monkeypatch):
    class S:
        BACKUP_S3_ENDPOINT = ""; BACKUP_S3_ACCESS_KEY_ID = ""; BACKUP_S3_SECRET_ACCESS_KEY = ""
        BACKUP_S3_BUCKET = ""; BACKUP_S3_REGION = ""; BACKUP_KEEP_SNAPSHOTS = 14
    monkeypatch.setattr(bk, "_settings", lambda: S())
    db = FakeDB()
    out = bk.run_backup(db, src=r2_with(D1), src_bucket="opsra-sites", now=NOW)
    assert out["status"] == "failed" and "aren't set up" in out["error"]
    assert db.tables["site_backup_runs"][0]["status"] == "failed"


def test_a_run_already_in_progress_blocks_a_second_one():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    db.table("site_backup_runs").insert({"status": "running", "started_at": (NOW - timedelta(minutes=30)).isoformat()}).execute()
    out = run(db, r2, b2)
    assert out["status"] == "skipped" and b2.objects == {}


def test_a_stale_running_row_does_not_block_forever():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    db.table("site_backup_runs").insert({"status": "running", "started_at": (NOW - timedelta(hours=5)).isoformat()}).execute()
    assert run(db, r2, b2)["status"] == "ok"


def test_listing_failure_fails_the_run_without_touching_the_backup():
    class Broken(FakeS3):
        def list_objects_v2(self, **kw): raise RuntimeError("r2 down")
    db, b2 = FakeDB(), FakeS3({"snapshots/x.com/2026-09-01/index.html": "old"})
    out = run(db, Broken(), b2)
    assert out["status"] == "failed" and "could not list" in out["error"]
    assert "snapshots/x.com/2026-09-01/index.html" in b2.objects and b2.deleted == []


# ── retention ───────────────────────────────────────────────────────────────

def test_only_the_newest_snapshots_are_kept():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    for day in range(1, 6):                                  # five snapshots, each with a new edit
        r2.put_object(Bucket="b", Key=f"{D1}/index.html", Body=f"v{day}".encode())
        run(db, r2, b2, now=NOW + timedelta(days=day), keep=3)
    assert bk.list_snapshot_dates(b2, "backups", D1) == ["2026-10-07", "2026-10-06", "2026-10-05"]


def test_domain_gone_from_r2_keeps_snapshots_for_90_days():
    db, r2, b2 = FakeDB(), r2_with(D1, D2), FakeS3()
    run(db, r2, b2)
    for k in [k for k in r2.objects if k.startswith(D2 + "/")]:
        del r2.objects[k]                                    # D2 lapsed / unpublished
    run(db, r2, b2, now=NOW + timedelta(days=30))
    assert bk.list_snapshot_dates(b2, "backups", D2) == ["2026-10-02"]
    out = run(db, r2, b2, now=NOW + timedelta(days=95))
    assert bk.list_snapshot_dates(b2, "backups", D2) == [] and out["snapshots_pruned"] == 1
    assert bk.list_snapshot_dates(b2, "backups", D1)         # live site untouched


def test_empty_r2_listing_never_prunes_anything():
    db, b2 = FakeDB(), FakeS3({f"snapshots/{D1}/2025-01-01/index.html": "ancient"})
    out = run(db, FakeS3(), b2, now=NOW)
    assert out["status"] == "ok" and out["domains_total"] == 0
    assert f"snapshots/{D1}/2025-01-01/index.html" in b2.objects


def test_delete_prefix_refuses_paths_outside_snapshots():
    with pytest.raises(bk.BackupError):
        bk._delete_prefix(FakeS3(), "b", f"{D1}/")
    with pytest.raises(bk.BackupError):
        bk._delete_prefix(FakeS3(), "b", "snapshots/")


# ── watchdog ────────────────────────────────────────────────────────────────

def test_watchdog_messages():
    db = FakeDB()
    assert "ever run" in bk.backup_problem(db, NOW)
    db.table("site_backup_runs").insert({"status": "ok", "started_at": (NOW - timedelta(hours=5)).isoformat()}).execute()
    assert bk.backup_problem(db, NOW) is None
    assert "26 hours" in bk.backup_problem(db, NOW + timedelta(hours=30))
    db.table("site_backup_runs").insert({"status": "failed", "error": "bucket missing",
                                         "started_at": (NOW - timedelta(hours=1)).isoformat()}).execute()
    assert "bucket missing" in bk.backup_problem(db, NOW)
    db.table("site_backup_runs").insert({"status": "partial", "error": "1 site(s) failed",
                                         "started_at": NOW.isoformat()}).execute()
    assert "most sites" in bk.backup_problem(db, NOW)


# ── restore ─────────────────────────────────────────────────────────────────

def test_restore_puts_the_newest_snapshot_back_in_r2_images_first():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    run(db, r2, b2)
    r2.put_object(Bucket="b", Key=f"{D1}/index.html", Body=b"<html>broken</html>")
    r2.put_object(Bucket="b", Key=f"{D1}/old-leftover.txt", Body=b"x")
    order = []
    real_put = r2.put_object
    r2.put_object = lambda **kw: (order.append(kw["Key"]), real_put(**kw))[1]
    out = bk.restore_site_from_backup(D1, src=b2, src_bucket="backups", dst=r2, dst_bucket="opsra-sites")
    assert out["snapshot_date"] == "2026-10-02" and out["files"] == 3 and out["removed"] == 1
    assert r2.objects[f"{D1}/index.html"]["body"] == f"<html>{D1}</html>".encode()
    assert f"{D1}/old-leftover.txt" not in r2.objects
    assert order[-1] == f"{D1}/index.html"
    assert r2.objects[f"{D1}/index.html"]["ContentType"] == "text/html; charset=utf-8"


def test_restore_a_chosen_date_and_unknown_cases():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    run(db, r2, b2)
    r2.put_object(Bucket="b", Key=f"{D1}/index.html", Body=b"v2")
    run(db, r2, b2, now=NOW + timedelta(days=1))
    out = bk.restore_site_from_backup(D1, "2026-10-02", src=b2, src_bucket="backups", dst=r2, dst_bucket="opsra-sites")
    assert out["snapshot_date"] == "2026-10-02"
    with pytest.raises(bk.BackupError, match="No backup of"):
        bk.restore_site_from_backup(D1, "2020-01-01", src=b2, src_bucket="backups", dst=r2, dst_bucket="opsra-sites")
    with pytest.raises(bk.BackupError, match="No backup exists"):
        bk.restore_site_from_backup("never-backed-up.com", src=b2, src_bucket="backups", dst=r2, dst_bucket="opsra-sites")


def test_failed_restore_removes_nothing_from_r2():
    db, r2, b2 = FakeDB(), r2_with(D1), FakeS3()
    run(db, r2, b2)
    r2.put_object(Bucket="b", Key=f"{D1}/keep-me.txt", Body=b"x")
    r2.fail_put = "robots.txt"
    with pytest.raises(bk.BackupError, match="failed part-way"):
        bk.restore_site_from_backup(D1, src=b2, src_bucket="backups", dst=r2, dst_bucket="opsra-sites")
    assert f"{D1}/keep-me.txt" in r2.objects and r2.deleted == []


# ── standby host (SITE-STANDBY) ─────────────────────────────────────────────

def _backed_up(*domains):
    r2, b2, db = r2_with(*domains), FakeS3(), FakeDB()
    run(db, r2, b2)
    return b2


def test_prepare_copies_newest_snapshot_to_live_and_verifies():
    b2 = _backed_up(D1)
    out = bk.prepare_backup_host(D1, client=b2, bucket="backups")
    assert out["ok"] and out["results"][0]["files"] == 3
    assert b2.objects[f"live/{D1}/index.html"]["body"] == f"<html>{D1}</html>".encode()
    assert b2.objects[f"live/{D1}/index.html"]["ContentType"].startswith("text/html")
    assert f"snapshots/{D1}/2026-10-02/index.html" in b2.objects          # snapshot untouched


def test_prepare_all_domains_and_removes_stale_live_files():
    b2 = _backed_up(D1, D2)
    b2.put_object(Bucket="b", Key=f"live/{D1}/old.html", Body=b"old")
    out = bk.prepare_backup_host(client=b2, bucket="backups")
    assert {r["domain"] for r in out["results"]} == {D1, D2}
    assert f"live/{D1}/old.html" not in b2.objects
    assert not any(k.startswith("live/") and "/old" in k for k in b2.objects)


def test_prepare_one_bad_site_does_not_stop_the_others():
    b2 = _backed_up(D1, D2)
    b2.fail_get = f"snapshots/{D1}/"
    out = bk.prepare_backup_host(client=b2, bucket="backups")
    assert not out["ok"] and [f["domain"] for f in out["failed"]] == [D1]
    assert [r["domain"] for r in out["results"]] == [D2]


def test_prepare_unknown_domain_date_and_empty_bucket():
    b2 = _backed_up(D1)
    assert bk.prepare_backup_host("nope.com", client=b2, bucket="backups")["failed"][0]["error"].startswith("No backup exists")
    assert "No backup of" in bk.prepare_backup_host(D1, "2020-01-01", client=b2, bucket="backups")["failed"][0]["error"]
    with pytest.raises(bk.BackupError):
        bk.prepare_backup_host(client=FakeS3(), bucket="backups")


def test_prepare_detects_a_dropped_file():
    b2 = _backed_up(D1)
    b2.drop_on_put = f"live/{D1}/robots.txt"
    out = bk.prepare_backup_host(D1, client=b2, bucket="backups")
    assert not out["ok"] and "verification failed" in out["failed"][0]["error"]
