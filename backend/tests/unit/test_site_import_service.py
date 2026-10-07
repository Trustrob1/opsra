"""
tests/unit/test_site_import_service.py
---------------------------------------
SITE-IMPORT 1a - zip intake, analysis and saving (spec sections 3, 13). Uses a small in-memory fake database
and storage; no network.
"""
from __future__ import annotations

import io
import struct
import zipfile

import pytest

from app.services import site_import_service as svc

HOSTS = ["cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
WOFF2 = b"wOF2" + b"\x00" * 40
PAGE = ("<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Shop</title>"
        "<link rel=stylesheet href='css/style.css'></head><body><h1>Hi</h1><img src='img/hero.jpg'>"
        "<a href='https://wa.me/2348000000000'>Order</a><script src='js/app.js'></script></body></html>")
CSS = "@font-face{font-family:A;src:url('../fonts/a.woff2')} body{background:url(../img/bg.png)}"
JS = "document.querySelector('h1').addEventListener('click', function(){ this.classList.toggle('on'); });"


def make_zip(files: dict, prefix: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in files.items():
            zf.writestr(prefix + name, body)
    return buf.getvalue()


GOOD = {"index.html": PAGE, "css/style.css": CSS, "js/app.js": JS, "img/hero.jpg": JPG, "img/bg.png": PNG,
        "fonts/a.woff2": WOFF2}


class TestReadUpload:
    def test_zip_roundtrip(self):
        files = svc.read_upload(make_zip(GOOD), "site.zip", 25 * svc.MB)
        assert set(files) == set(GOOD) and files["js/app.js"] == JS.encode()

    def test_single_top_folder_is_stripped(self):
        files = svc.read_upload(make_zip(GOOD, prefix="my-site/"), "site.zip", 25 * svc.MB)
        assert "index.html" in files and "my-site/index.html" not in files

    def test_single_html_file(self):
        assert svc.read_upload(PAGE.encode(), "page.html", svc.MB) == {"index.html": PAGE.encode()}

    def test_junk_files_are_skipped(self):
        z = make_zip({**GOOD, "__MACOSX/._index.html": b"x", ".DS_Store": b"x", "Thumbs.db": b"x"})
        assert set(svc.read_upload(z, "s.zip", svc.MB * 25)) == set(GOOD)

    @pytest.mark.parametrize("name", ["../evil.html", "a/../../evil.html", "/abs/evil.html", "C:/evil.html", "a\\..\\..\\evil.html"])
    def test_unsafe_names_rejected(self, name):
        with pytest.raises(svc.ImportRejected):
            svc.read_upload(make_zip({"index.html": PAGE, name: b"x"}), "s.zip", svc.MB * 25)

    @pytest.mark.parametrize("name", ["run.exe", "x.php", "deploy.sh", "inner.zip", "a.tar.gz", "setup.bat", "w.dll"])
    def test_forbidden_types_rejected(self, name):
        with pytest.raises(svc.ImportRejected, match="not allowed"):
            svc.read_upload(make_zip({"index.html": PAGE, name: b"x"}), "s.zip", svc.MB * 25)

    def test_symlink_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("index.html", PAGE)
            info = zipfile.ZipInfo("link.html")
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, "index.html")
        with pytest.raises(svc.ImportRejected, match="link"):
            svc.read_upload(buf.getvalue(), "s.zip", svc.MB * 25)

    def test_case_collision_rejected(self):
        with pytest.raises(svc.ImportRejected, match="same name"):
            svc.read_upload(make_zip({"index.html": PAGE, "img/A.png": PNG, "img/a.png": PNG}), "s.zip", svc.MB * 25)

    def test_too_many_files(self):
        z = make_zip({f"img/{i}.png": PNG for i in range(160)} | {"index.html": PAGE})
        with pytest.raises(svc.ImportRejected, match="limit"):
            svc.read_upload(z, "s.zip", svc.MB * 25)

    def test_upload_too_large(self):
        with pytest.raises(svc.ImportRejected, match="limit"):
            svc.read_upload(b"PK" + b"0" * 2000, "s.zip", 1000)

    def test_zip_bomb_rejected(self):
        z = make_zip({"index.html": PAGE, "img/big.png": PNG + b"\x00" * (30 * svc.MB)})
        with pytest.raises(svc.ImportRejected, match="zip bomb|suspiciously"):
            svc.read_upload(z, "s.zip", svc.MB * 25)

    def test_not_a_zip_and_empty(self):
        with pytest.raises(svc.ImportRejected):
            svc.read_upload(b"PK\x03\x04garbage", "s.zip", svc.MB)
        with pytest.raises(svc.ImportRejected):
            svc.read_upload(b"", "s.zip", svc.MB)
        with pytest.raises(svc.ImportRejected, match="Upload a .zip"):
            svc.read_upload(b"\x89PNG....", "a.png", svc.MB)

    def test_lying_header_cannot_exceed_declared_size(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("index.html", PAGE)
            zf.writestr("img/a.png", PNG)
        raw = bytearray(buf.getvalue())
        # shrink the declared uncompressed size of the second entry in its central directory record
        idx = raw.rfind(b"PK\x01\x02")
        raw[idx + 24: idx + 28] = struct.pack("<I", 4)
        with pytest.raises(svc.ImportRejected):
            svc.read_upload(bytes(raw), "s.zip", svc.MB)


class TestAnalyse:
    def run(self, files, accepted=None):
        bodies = {k: (v.encode() if isinstance(v, str) else v) for k, v in files.items()}
        return svc.analyse(bodies, HOSTS, accepted)

    def test_good_site(self):
        r = self.run(GOOD)["report"]
        assert r["ok"] and r["errors"] == [] and r["entry"] == "index.html"
        assert r["scripts"] == ["js/app.js"] and r["stylesheets"] == ["css/style.css"]
        assert r["counts"]["css"] == 1 and r["counts"]["js"] == 1 and r["counts"]["image"] == 2 and r["counts"]["font"] == 1
        assert r["missing_files"] == [] and r["unreferenced"] == []

    def test_css_references_resolve_relative_to_the_css_file(self):
        r = self.run({**GOOD, "img/extra.png": PNG})["report"]
        assert "img/bg.png" not in r["unreferenced"] and "fonts/a.woff2" not in r["unreferenced"]
        assert r["unreferenced"] == ["img/extra.png"]

    def test_missing_files_reported(self):
        r = self.run({k: v for k, v in GOOD.items() if k != "img/hero.jpg"})["report"]
        assert "img/hero.jpg" in r["missing_files"] and r["ok"]

    def test_unknown_external_resources_listed(self):
        page = PAGE.replace("</head>", "<link rel=stylesheet href='https://evil.example/x.css'></head>")
        r = self.run({**GOOD, "index.html": page})["report"]
        assert [u["url"] for u in r["external"]["unknown"]] == ["https://evil.example/x.css"]

    def test_scripts_with_blocked_calls_make_the_import_fail_to_pass(self):
        r = self.run({**GOOD, "js/app.js": "document.cookie='a=1'"})["report"]
        assert not r["ok"] and r["errors"][0]["rule"] == "document_cookie" and r["errors"][0]["file"] == "js/app.js"

    def test_accepted_override_downgrades_overridable_only(self):
        files = {**GOOD, "js/app.js": "eval('1'); document.cookie='a'"}
        r = self.run(files, {"js/app.js": ["eval", "document_cookie"]})["report"]
        assert [f["rule"] for f in r["errors"]] == ["document_cookie"]           # not overridable
        assert any(a["rule"] == "eval" for a in r["accepted"])
        assert any(f["rule"] == "eval" and f["severity"] == "warning" and f["accepted"] for f in r["warnings"])

    def test_accepted_works_for_inline_scripts_of_the_page(self):
        page = PAGE.replace("</body>", "<script>eval('1')</script></body>")
        r = self.run({**GOOD, "index.html": page}, {"index.html": ["eval"]})["report"]
        assert r["ok"]

    def test_unsafe_svg_blocks(self):
        r = self.run({**GOOD, "img/logo.svg": "<svg onload='x()'></svg>"})["report"]
        assert not r["ok"] and r["errors"][0]["rule"] == "svg_unsafe"

    def test_fake_image_rejected(self):
        with pytest.raises(svc.ImportRejected, match="not really"):
            self.run({**GOOD, "img/hero.jpg": b"<html>not an image</html>"})
        with pytest.raises(svc.ImportRejected, match="not really"):
            self.run({**GOOD, "fonts/a.woff2": b"PK\x03\x04"})

    def test_two_pages_rejected_and_page_must_be_at_top(self):
        with pytest.raises(svc.ImportRejected, match="Only one page"):
            self.run({**GOOD, "about.html": PAGE})
        with pytest.raises(svc.ImportRejected, match="top"):
            self.run({"site/index.html": PAGE, "site/css/style.css": CSS})
        with pytest.raises(svc.ImportRejected, match="no HTML"):
            self.run({"css/style.css": CSS})

    def test_size_limits(self):
        with pytest.raises(svc.ImportRejected, match="image limit"):
            self.run({**GOOD, "img/hero.jpg": JPG + b"\x01" * (6 * svc.MB)})
        with pytest.raises(svc.ImportRejected, match="JavaScript"):
            self.run({**GOOD, "js/a.js": "a" * (2 * svc.MB)})
        with pytest.raises(svc.ImportRejected, match="HTML"):
            self.run({**GOOD, "index.html": PAGE + "<!--" + "x" * (2 * svc.MB) + "-->"})

    def test_other_files_are_skipped_not_fatal(self):
        r = self.run({**GOOD, "video/intro.mp4": b"x", "js/app.js.map": b"{}"})["report"]
        assert r["ok"] and sorted(r["skipped"]) == ["js/app.js.map", "video/intro.mp4"]

    def test_non_utf8_page_is_read_and_warned(self):
        page = PAGE.replace("Hi", "Caf\xe9").encode("latin-1")
        r = self.run({**GOOD, "index.html": page})
        assert r["report"]["ok"] and "Café" in r["html"]
        assert any(w["rule"] == "not_utf8" for w in r["report"]["warnings"])

    def test_cleaned_html_is_returned_without_dangerous_parts(self):
        page = PAGE.replace("</head>", "<base href=//evil.example/></head>").replace("<h1>", "<iframe src=//evil.example></iframe><h1>")
        out = self.run({**GOOD, "index.html": page})["html"]
        assert "<base" not in out and "<iframe" not in out and "<h1>Hi</h1>" in out


class Result:
    def __init__(self, data=None):
        self.data = data


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op, self.payload = db, table, [], "select", None
        self._limit = None

    def select(self, *a, **k):
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, k, v):
        self.filters.append(("eq", k, v))
        return self

    def in_(self, k, vs):
        self.filters.append(("in", k, vs))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _match(self, row):
        for kind, k, v in self.filters:
            if kind == "eq" and row.get(k) != v:
                return False
            if kind == "in" and row.get(k) not in v:
                return False
        return True

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "insert":
            if self.db.fail_insert:
                raise RuntimeError("insert failed")
            row = dict(self.payload)
            row.setdefault("id", f"{self.table}-{len(rows) + 1}")
            rows.append(row)
            return Result([row])
        if self.op == "delete":
            self.db.tables[self.table] = [r for r in rows if not self._match(r)]
            return Result([])
        out = [r for r in rows if self._match(r)]
        out.sort(key=lambda r: r.get("version", 0), reverse=True) if out and "version" in out[0] else None
        return Result(out[: self._limit] if self._limit else out)


class FakeBucket:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def upload(self, path, file, file_options=None):
        if self.db.fail_upload_at is not None and len(self.db.files) >= self.db.fail_upload_at:
            raise RuntimeError("storage down")
        self.db.files[(self.name, path)] = file

    def remove(self, paths):
        for p in paths:
            self.db.files.pop((self.name, p), None)


class FakeStorage:
    def __init__(self, db):
        self.db = db

    def from_(self, name):
        return FakeBucket(self.db, name)


class FakeDb:
    def __init__(self):
        self.tables, self.files = {}, {}
        self.fail_insert, self.fail_upload_at = False, None
        self.storage = FakeStorage(self)

    def table(self, name):
        return FakeQuery(self, name)


SETTINGS = {"site_import_enabled": True, "site_import_allowed_hosts": HOSTS, "site_import_max_zip_mb": 25}
SITE = {"id": "site-1", "org_id": "org-1", "status": "preview_ready", "deleted_at": None, "current_design_id": None}


class TestImportSite:
    def go(self, db, files=None, **kw):
        return svc.import_site(db, "org-1", dict(SITE), "user:u1", make_zip(files or GOOD), "site.zip",
                               kw.pop("settings", SETTINGS), **kw)

    def test_saves_a_staged_import_design_and_files(self):
        db = FakeDb()
        out = self.go(db)
        assert out["saved"] and out["version"] == 1 and out["files"] == 6
        row = db.tables["site_designs"][0]
        assert row["kind"] == "import" and row["status"] == "ready" and row["staged"] is True and row["editable"] is False
        assert row["org_id"] == "org-1" and row["site_id"] == "site-1" and row["created_by"] == "user:u1"
        assert row["skeleton_html"].startswith("<!doctype html>") and row["skeleton_css"] == ""
        stored = {p for (b, p) in db.files if b == svc.BUCKET_FILES}
        assert len(stored) == 5 and all(p.startswith(row["files_prefix"] + "/") for p in stored)   # the page itself is not a file
        assert (svc.BUCKET_RAW, row["source_path"]) in db.files and row["source_path"].endswith(".zip")
        meta = row["import_meta"]
        assert meta["report"]["ok"] and {f["path"] for f in meta["files"]} == set(GOOD)
        assert all(len(f["sha256"]) == 64 for f in meta["files"])

    def test_does_not_touch_the_site(self):
        db = FakeDb()
        db.tables["sites"] = [dict(SITE, tier="standard")]
        self.go(db)
        assert db.tables["sites"][0]["tier"] == "standard" and db.tables["sites"][0]["current_design_id"] is None

    def test_second_import_is_version_two(self):
        db = FakeDb()
        self.go(db)
        assert self.go(db)["version"] == 2

    def test_dry_run_saves_nothing(self):
        db = FakeDb()
        out = self.go(db, dry_run=True)
        assert out["saved"] is False and out["report"]["ok"] and db.files == {} and db.tables == {}

    def test_rejected_import_saves_nothing_and_carries_the_report(self):
        db = FakeDb()
        with pytest.raises(svc.ImportRejected) as ei:
            self.go(db, {**GOOD, "js/app.js": "document.cookie='a=1'"})
        assert ei.value.report and not ei.value.report["ok"] and "js/app.js" in ei.value.errors[0]
        assert db.files == {} and db.tables.get("site_designs", []) == []

    def test_switched_off_and_cancelled_site(self):
        with pytest.raises(svc.ImportRejected, match="not switched on"):
            self.go(FakeDb(), settings={"site_import_enabled": False})
        with pytest.raises(svc.ImportRejected, match="cancelled"):
            svc.import_site(FakeDb(), "org-1", dict(SITE, status="cancelled"), "u", make_zip(GOOD), "s.zip", SETTINGS)

    def test_storage_failure_cleans_up_and_saves_no_row(self):
        db = FakeDb()
        db.fail_upload_at = 3
        with pytest.raises(svc.ImportFailed):
            self.go(db)
        assert db.files == {} and db.tables.get("site_designs", []) == []

    def test_insert_failure_cleans_up(self):
        db = FakeDb()
        db.fail_insert = True
        with pytest.raises(svc.ImportFailed):
            self.go(db)
        assert db.files == {}

    def test_single_html_upload_is_stored_as_html(self):
        db = FakeDb()
        out = svc.import_site(db, "org-1", dict(SITE), "u", b"<!doctype html><html><head><meta name=viewport content=x></head><body><p>x</p></body></html>",
                              "page.html", SETTINGS)
        assert out["saved"] and db.tables["site_designs"][0]["source_path"].endswith(".html")

    def test_old_versions_are_pruned_with_their_files(self):
        db = FakeDb()
        for _ in range(svc.KEEP_IMPORT_VERSIONS + 2):
            self.go(db)
        rows = db.tables["site_designs"]
        assert len(rows) == svc.KEEP_IMPORT_VERSIONS
        assert min(r["version"] for r in rows) == 3
        live_prefixes = {r["files_prefix"] for r in rows}
        assert all(any(p.startswith(pref) for pref in live_prefixes) for (b, p) in db.files if b == svc.BUCKET_FILES)

    def test_current_design_is_never_pruned(self):
        db = FakeDb()
        self.go(db)
        first_id = db.tables["site_designs"][0]["id"]
        for _ in range(svc.KEEP_IMPORT_VERSIONS + 1):
            svc.import_site(db, "org-1", dict(SITE, current_design_id=first_id), "u", make_zip(GOOD), "s.zip", SETTINGS)
        assert any(r["id"] == first_id for r in db.tables["site_designs"])

    def test_org_scoping_of_reads(self):
        db = FakeDb()
        self.go(db)
        db.tables["site_designs"][0]["org_id"] = "other-org"
        assert svc.latest_report(db, "org-1", "site-1") is None
        assert svc.latest_report(db, "other-org", "site-1")["version"] == 1

    def test_latest_report(self):
        db = FakeDb()
        self.go(db)
        r = svc.latest_report(db, "org-1", "site-1")
        assert r["version"] == 1 and r["report"]["ok"] and r["files"] == 6 and r["editable"] is False


class TestSettings:
    def test_defaults(self):
        s = svc.settings_for(None)
        assert s["enabled"] is False and s["max_mb"] == 25 and "cdn.jsdelivr.net" in s["allowed_hosts"]

    def test_values(self):
        s = svc.settings_for({"site_import_enabled": True, "site_import_allowed_hosts": ["a.com"], "site_import_max_zip_mb": 10})
        assert s == {"enabled": True, "allowed_hosts": ["a.com"], "max_mb": 10}
