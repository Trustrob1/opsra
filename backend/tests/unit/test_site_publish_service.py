"""
tests/unit/test_site_publish_service.py
----------------------------------------
SITE-PUBLISH — uploads a site to R2 under its domain. Uses a fake S3 client; no network.
"""
from __future__ import annotations

import pytest

from app.services import site_ops_service, site_publish_service as sp

DOMAIN = "adaezastyles.com.ng"


class FakeS3:
    def __init__(self, existing=None, fail_on=None, page_size=1000):
        self.objects = dict(existing or {})
        self.puts = []                 # keys in upload order
        self.deleted = []
        self.fail_on = fail_on
        self.page_size = page_size

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl):
        if self.fail_on and Key.endswith(self.fail_on):
            raise RuntimeError("boom")
        self.puts.append(Key)
        self.objects[Key] = {"body": Body, "type": ContentType, "cache": CacheControl, "bucket": Bucket}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start:start + self.page_size]
        more = start + self.page_size < len(keys)
        out = {"Contents": [{"Key": k} for k in page], "IsTruncated": more}
        if more:
            out["NextContinuationToken"] = str(start + self.page_size)
        return out

    def delete_objects(self, Bucket, Delete, **_):
        for o in Delete["Objects"]:
            self.deleted.append(o["Key"])
            self.objects.pop(o["Key"], None)


FILES = [
    ("index.html", "<html>hi</html>"),
    ("robots.txt", "User-agent: *"),
    ("sitemap.xml", "<urlset/>"),
    ("images/hero.jpg", b"JPG"),
    ("images/logo.png", b"PNG"),
]


@pytest.fixture
def export(monkeypatch):
    def _set(files=FILES, domain=DOMAIN):
        monkeypatch.setattr(site_ops_service, "collect_export_files", lambda db, org, site: (list(files), {}, domain))
    _set()
    return _set


# ── domain handling ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    ("shop.com.ng", "shop.com.ng"),
    ("WWW.Shop.com.ng", "shop.com.ng"),
    ("https://www.shop.com.ng/", "shop.com.ng"),
    ("http://shop.com.ng/path?x=1", "shop.com.ng"),
    ("shop.com.ng.", "shop.com.ng"),
])
def test_normalise_domain(raw, want):
    assert sp.normalise_domain(raw) == want


@pytest.mark.parametrize("raw", [None, "", "   ", "localhost", "a b.com", "../x.com", "shop..com", "bad_domain.com"])
def test_normalise_domain_rejects(raw):
    with pytest.raises(sp.NoDomain):
        sp.normalise_domain(raw)


# ── publish ─────────────────────────────────────────────────────────────────

def test_uploads_every_file_under_the_domain_folder(export):
    s3 = FakeS3()
    out = sp.publish_site(None, "org", "site", client=s3, bucket="opsra-sites")
    assert set(s3.objects) == {f"{DOMAIN}/{p}" for p, _ in FILES}
    assert out["domain"] == DOMAIN and out["files"] == 5 and out["removed"] == 0
    assert out["urls"] == [f"https://{DOMAIN}/", f"https://www.{DOMAIN}/"]
    assert all(o["bucket"] == "opsra-sites" for o in s3.objects.values())


def test_www_domain_uses_the_same_folder(export):
    export(domain="www.Adaezastyles.com.ng")
    s3 = FakeS3()
    assert sp.publish_site(None, "org", "site", client=s3, bucket="b")["prefix"] == f"{DOMAIN}/"


def test_content_types_and_cache_headers(export):
    s3 = FakeS3()
    sp.publish_site(None, "org", "site", client=s3, bucket="b")
    o = s3.objects
    assert o[f"{DOMAIN}/index.html"]["type"] == "text/html; charset=utf-8"
    assert o[f"{DOMAIN}/index.html"]["cache"] == "public, max-age=60"
    assert o[f"{DOMAIN}/sitemap.xml"]["type"] == "application/xml; charset=utf-8"
    assert o[f"{DOMAIN}/robots.txt"]["type"] == "text/plain; charset=utf-8"
    assert o[f"{DOMAIN}/images/hero.jpg"]["type"] == "image/jpeg"
    assert o[f"{DOMAIN}/images/logo.png"]["type"] == "image/png"
    assert o[f"{DOMAIN}/images/hero.jpg"]["cache"] == "public, max-age=3600"


def test_text_is_encoded_and_bytes_pass_through(export):
    s3 = FakeS3()
    export([("index.html", "café ₦"), ("images/a.jpg", b"\xff\xd8")])
    sp.publish_site(None, "org", "site", client=s3, bucket="b")
    assert s3.objects[f"{DOMAIN}/index.html"]["body"] == "café ₦".encode("utf-8")
    assert s3.objects[f"{DOMAIN}/images/a.jpg"]["body"] == b"\xff\xd8"


def test_index_html_is_uploaded_last(export):
    s3 = FakeS3()
    sp.publish_site(None, "org", "site", client=s3, bucket="b")
    assert s3.puts[-1] == f"{DOMAIN}/index.html"


def test_stale_files_in_the_folder_are_removed_and_other_sites_untouched(export):
    s3 = FakeS3(existing={
        f"{DOMAIN}/images/old.jpg": {}, f"{DOMAIN}/old-page.html": {},
        "other.com.ng/index.html": {}, f"{DOMAIN}x.ng/index.html": {},
    })
    out = sp.publish_site(None, "org", "site", client=s3, bucket="b")
    assert sorted(s3.deleted) == [f"{DOMAIN}/images/old.jpg", f"{DOMAIN}/old-page.html"]
    assert out["removed"] == 2
    assert "other.com.ng/index.html" in s3.objects and f"{DOMAIN}x.ng/index.html" in s3.objects


def test_stale_cleanup_handles_paged_listings(export):
    stale = {f"{DOMAIN}/images/old{i}.jpg": {} for i in range(25)}
    s3 = FakeS3(existing=stale, page_size=10)
    out = sp.publish_site(None, "org", "site", client=s3, bucket="b")
    assert out["removed"] == 25 and not any("old" in k for k in s3.objects)


def test_republishing_is_safe_to_repeat(export):
    s3 = FakeS3()
    sp.publish_site(None, "org", "site", client=s3, bucket="b")
    out = sp.publish_site(None, "org", "site", client=s3, bucket="b")
    assert out["removed"] == 0 and len(s3.objects) == 5


def test_failed_upload_leaves_the_old_version_untouched(export):
    old = {f"{DOMAIN}/index.html": {"body": b"OLD"}, f"{DOMAIN}/images/old.jpg": {}}
    s3 = FakeS3(existing=old, fail_on="sitemap.xml")
    with pytest.raises(sp.PublishError) as e:
        sp.publish_site(None, "org", "site", client=s3, bucket="b")
    assert s3.deleted == []                                            # nothing cleaned up
    assert s3.objects[f"{DOMAIN}/index.html"]["body"] == b"OLD"        # index.html not replaced
    assert f"{DOMAIN}/images/old.jpg" in s3.objects
    assert "boom" not in str(e.value)                                  # internals not leaked
    assert e.value.status_code == 502


def test_no_domain_raises_before_any_upload(export):
    export(domain=None)
    s3 = FakeS3()
    with pytest.raises(sp.NoDomain) as e:
        sp.publish_site(None, "org", "site", client=s3, bucket="b")
    assert e.value.status_code == 422 and s3.puts == []


# ── configuration ───────────────────────────────────────────────────────────

class _S:
    def __init__(self, **kw):
        self.R2_ACCOUNT_ID = kw.get("acc", "acc123")
        self.R2_ACCESS_KEY_ID = kw.get("key", "k")
        self.R2_SECRET_ACCESS_KEY = kw.get("secret", "s")
        self.R2_BUCKET = kw.get("bucket", "opsra-sites")


@pytest.mark.parametrize("missing", ["acc", "key", "secret", "bucket"])
def test_not_configured_when_any_r2_setting_is_missing(monkeypatch, missing):
    monkeypatch.setattr(sp, "_settings", lambda: _S(**{missing: ""}))
    with pytest.raises(sp.NotConfigured) as e:
        sp.make_client()
    assert e.value.status_code == 503


def test_not_configured_is_raised_by_publish(monkeypatch, export):
    monkeypatch.setattr(sp, "_settings", lambda: _S(key=""))
    with pytest.raises(sp.NotConfigured):
        sp.publish_site(None, "org", "site")


def test_client_points_at_r2(monkeypatch):
    monkeypatch.setattr(sp, "_settings", lambda: _S())
    c = sp.make_client()
    assert c.meta.endpoint_url == "https://acc123.r2.cloudflarestorage.com"
    assert c.meta.region_name == "auto"


# ── unpublish ───────────────────────────────────────────────────────────────

def test_unpublish_removes_only_that_domain():
    s3 = FakeS3(existing={f"{DOMAIN}/index.html": {}, f"{DOMAIN}/images/a.jpg": {}, "other.ng/index.html": {}})
    out = sp.unpublish_domain("https://www." + DOMAIN, client=s3, bucket="b")
    assert out == {"domain": DOMAIN, "removed": 2} and list(s3.objects) == ["other.ng/index.html"]


def test_delete_keys_refuses_keys_outside_the_prefix():
    s3 = FakeS3(existing={"a.com/x": {}, "b.com/x": {}})
    n = sp._delete_keys(s3, "b", ["a.com/x", "b.com/x", "a.com/"], "a.com/")
    assert n == 1 and "b.com/x" in s3.objects and "a.com/x" not in s3.objects


def test_unpublish_with_bad_domain_raises():
    with pytest.raises(sp.NoDomain):
        sp.unpublish_domain("", client=FakeS3(), bucket="b")


# ── site_domain (used by the hostname status endpoint) ──────────────────────

class _Q:
    def __init__(self, rows): self.rows, self.f = rows, []
    def select(self, *_a): return self
    def eq(self, k, v): self.f.append(lambda r: r.get(k) == v); return self
    def neq(self, k, v): self.f.append(lambda r: r.get(k) != v); return self
    def is_(self, k, _v): self.f.append(lambda r: r.get(k) is None); return self
    def order(self, k, desc=False): self.rows = sorted(self.rows, key=lambda r: r.get(k) or "", reverse=desc); return self
    def limit(self, *_a): return self
    def execute(self):
        class R: pass
        r = R(); r.data = [x for x in self.rows if all(f(x) for f in self.f)]; return r


class _DB:
    def __init__(self, sites, orders): self.t = {"sites": sites, "site_orders": orders}
    def table(self, n): return _Q(list(self.t[n]))


def test_site_domain_uses_latest_live_order():
    db = _DB([{"id": "s1", "org_id": "o", "deleted_at": None}], [
        {"site_id": "s1", "org_id": "o", "domain": "old.ng", "status": "live", "created_at": "2026-01-01"},
        {"site_id": "s1", "org_id": "o", "domain": "WWW.New.ng", "status": "live", "created_at": "2026-02-01"},
        {"site_id": "s1", "org_id": "o", "domain": "expired.ng", "status": "expired", "created_at": "2026-03-01"},
    ])
    assert sp.site_domain(db, "o", "s1") == "new.ng"


def test_site_domain_errors():
    db = _DB([{"id": "s1", "org_id": "o", "deleted_at": None}], [])
    with pytest.raises(sp.NoDomain):
        sp.site_domain(db, "o", "s1")
    with pytest.raises(site_ops_service.NotFound):
        sp.site_domain(db, "o", "missing")
    with pytest.raises(site_ops_service.NotFound):
        sp.site_domain(db, "other-org", "s1")
