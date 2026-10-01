"""
tests/unit/test_site_zone_service.py
--------------------------------------
SITE-ZONES — a client domain's DNS on Cloudflare + Worker custom domains. A fake Cloudflare stands in; no network.
"""
from __future__ import annotations

import pytest

from app.services import site_zone_service as z

ACCT = "acct1"
NS = ["amy.ns.cloudflare.com", "bob.ns.cloudflare.com"]


class FakeCF:
    def __init__(self, zones=None, activate_on_check=False, fail_attach=False):
        self.zones = {r["name"]: dict(r) for r in (zones or [])}
        self.attached = {}
        self.calls = []
        self.activate_on_check = activate_on_check
        self.fail_attach = fail_attach
        self._n = 0

    def request(self, method, path, json=None, params=None):
        self.calls.append((method, path, json, params))
        if path == "/zones" and method == "GET":
            return {"success": True, "result": [r for r in self.zones.values() if r["name"] == (params or {}).get("name")]}
        if path == "/zones" and method == "POST":
            self._n += 1
            row = {"id": f"z{self._n}", "name": json["name"], "status": "pending", "name_servers": NS}
            self.zones[json["name"]] = row
            return {"success": True, "result": row}
        if path.endswith("/activation_check"):
            if self.activate_on_check:
                zid = path.split("/")[2]
                for r in self.zones.values():
                    if r["id"] == zid:
                        r["status"] = "active"
            return {"success": True, "result": {}}
        if path.startswith("/zones/") and method == "GET":
            zid = path.split("/")[2]
            return {"success": True, "result": next(dict(r) for r in self.zones.values() if r["id"] == zid)}
        if path == f"/accounts/{ACCT}/workers/domains" and method == "GET":
            h = (params or {}).get("hostname")
            return {"success": True, "result": [{"hostname": h, "service": s} for hh, s in self.attached.items() if hh == h]}
        if path == f"/accounts/{ACCT}/workers/domains" and method == "PUT":
            if self.fail_attach:
                raise z.HostnameError("x")
            self.attached[json["hostname"]] = json["service"]
            return {"success": True, "result": {}}
        raise AssertionError((method, path))


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    class _S:
        SITES_WORKER_NAME = "opsra-sites"
        CLOUDFLARE_API_TOKEN = "tok"
        CLOUDFLARE_ACCOUNT_ID = ACCT
    monkeypatch.setattr(z, "_settings", lambda: _S())
    from app.services import site_cloudflare_service as cf
    monkeypatch.setattr(cf, "_settings", lambda: _S())


def _connect(c, domain="shop.com", live=True, create=True):
    return z.connect_domain(domain, create=create, client=c, account=ACCT, probe=lambda h: live)


def test_creates_zone_and_returns_nameservers_without_attaching_while_pending():
    c = FakeCF()
    out = _connect(c)
    posts = [x for x in c.calls if x[0] == "POST" and x[1] == "/zones"]
    assert len(posts) == 1 and posts[0][2] == {"account": {"id": ACCT}, "name": "shop.com", "type": "full"}
    assert out["mode"] == "cloudflare_zone" and out["zone_status"] == "pending" and out["nameservers"] == NS
    assert [h["status"] for h in out["hostnames"]] == ["waiting_nameservers", "waiting_nameservers"]
    assert out["all_active"] is False and out["dns"] == []
    assert not any(x[0] == "PUT" and "workers/domains" in x[1] for x in c.calls)


def test_nudges_cloudflare_to_recheck_nameservers():
    c = FakeCF()
    _connect(c)
    assert any(x[0] == "PUT" and x[1].endswith("/activation_check") for x in c.calls)


def test_attaches_domain_and_www_once_the_zone_is_active():
    c = FakeCF(activate_on_check=True)
    out = _connect(c)
    assert out["zone_status"] == "active"
    assert c.attached == {"shop.com": "opsra-sites", "www.shop.com": "opsra-sites"}
    puts = [x for x in c.calls if x[0] == "PUT" and x[1] == f"/accounts/{ACCT}/workers/domains"]
    assert all(p[2]["zone_id"] == "z1" and p[2]["environment"] == "production" for p in puts)
    assert out["all_active"] is True


def test_attached_but_not_answering_yet_is_not_live():
    c = FakeCF(activate_on_check=True)
    out = _connect(c, live=False)
    assert out["all_active"] is False
    assert [h["status"] for h in out["hostnames"]] == ["pending", "pending"]


def test_is_idempotent_for_zone_and_attachments():
    c = FakeCF(activate_on_check=True)
    _connect(c)
    n_posts = len([x for x in c.calls if x[0] == "POST"])
    n_puts = len([x for x in c.calls if x[0] == "PUT" and "workers/domains" in x[1]])
    _connect(c)
    assert len([x for x in c.calls if x[0] == "POST"]) == n_posts
    assert len([x for x in c.calls if x[0] == "PUT" and "workers/domains" in x[1]]) == n_puts


def test_existing_active_zone_is_reused_not_recreated():
    c = FakeCF(zones=[{"id": "zz", "name": "shop.com", "status": "active", "name_servers": NS}])
    out = _connect(c)
    assert not any(x[0] == "POST" for x in c.calls)
    assert out["zone_id"] == "zz" and out["all_active"] is True


def test_create_false_never_creates_a_zone():
    c = FakeCF()
    out = _connect(c, create=False)
    assert not any(x[0] == "POST" for x in c.calls)
    assert out["zone_status"] == "none" and out["zone_id"] is None and out["all_active"] is False


def test_www_prefix_and_case_are_normalised():
    c = FakeCF()
    out = z.connect_domain("WWW.Shop.COM", client=c, account=ACCT, probe=lambda h: True)
    assert out["domain"] == "shop.com" and "shop.com" in c.zones


def test_attach_failure_surfaces_a_hostname_error():
    c = FakeCF(zones=[{"id": "zz", "name": "shop.com", "status": "active", "name_servers": NS}], fail_attach=True)
    with pytest.raises(z.HostnameError):
        _connect(c)


def test_not_configured_without_account_id(monkeypatch):
    class _S:
        CLOUDFLARE_API_TOKEN = "tok"
        CLOUDFLARE_ACCOUNT_ID = ""
        SITES_WORKER_NAME = "opsra-sites"
    monkeypatch.setattr(z, "_settings", lambda: _S())
    assert z.is_configured() is False
    with pytest.raises(z.HostnamesNotConfigured):
        z.connect_domain("shop.com")
    assert z.existing_zone("shop.com") is None


# ---- mode resolution + remembered state (fake DB) ---------------------------------------------

class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload = db, name, {}, "select", None

    def select(self, *_a): return self
    def eq(self, k, v): self.filters[k] = ("eq", v); return self
    def in_(self, k, v): self.filters[k] = ("in", list(v)); return self
    def limit(self, *_a): return self
    def update(self, payload): self.op, self.payload = "update", payload; return self

    def _match(self, row):
        for k, (kind, v) in self.filters.items():
            if kind == "eq" and row.get(k) != v:
                return False
            if kind == "in" and row.get(k) not in v:
                return False
        return True

    def execute(self):
        rows = [r for r in self.db.rows[self.name] if self._match(r)]
        if self.op == "update":
            for r in rows:
                r.update(self.payload)
        return type("R", (), {"data": [dict(r) for r in rows]})()


class FakeDB:
    def __init__(self, rows):
        self.rows = {"site_domains": rows}

    def table(self, name): return _Q(self, name)


def _db(**row):
    base = {"id": "d1", "org_id": "o1", "domain": "shop.com", "dns_mode": "client_cname"}
    base.update(row)
    return FakeDB([base])


def test_requested_mode_wins():
    assert z.resolve_mode(_db(), "o1", "shop.com", "cloudflare_zone") == "cloudflare_zone"
    assert z.resolve_mode(_db(dns_mode="cloudflare_zone"), "o1", "shop.com", "client_cname") == "client_cname"


def test_remembered_zone_mode_is_used():
    assert z.resolve_mode(_db(dns_mode="cloudflare_zone"), "o1", "shop.com") == "cloudflare_zone"


def test_existing_zone_in_cloudflare_means_zone_mode(monkeypatch):
    monkeypatch.setattr(z, "existing_zone", lambda d, **k: {"id": "z1"})
    assert z.resolve_mode(FakeDB([]), "o1", "shop.com") == "cloudflare_zone"


def test_default_is_client_cname(monkeypatch):
    monkeypatch.setattr(z, "existing_zone", lambda d, **k: None)
    assert z.resolve_mode(_db(), "o1", "shop.com") == "client_cname"
    assert z.resolve_mode(FakeDB([]), "o1", "www.shop.com") == "client_cname"


def test_row_matched_by_www_form_and_other_orgs_ignored(monkeypatch):
    monkeypatch.setattr(z, "existing_zone", lambda d, **k: None)
    assert z.resolve_mode(_db(domain="www.shop.com", dns_mode="cloudflare_zone"), "o1", "shop.com") == "cloudflare_zone"
    assert z.resolve_mode(_db(dns_mode="cloudflare_zone"), "OTHER", "shop.com") == "client_cname"


def test_save_state_updates_the_row():
    db = _db()
    z.save_state(db, "o1", "shop.com", {"zone_id": "z1", "zone_status": "pending", "nameservers": NS})
    row = db.rows["site_domains"][0]
    assert row["dns_mode"] == "cloudflare_zone" and row["cf_zone_id"] == "z1"
    assert row["cf_zone_status"] == "pending" and row["cf_nameservers"] == NS


def test_save_state_without_a_row_or_on_error_never_raises():
    z.save_state(FakeDB([]), "o1", "shop.com", {"zone_id": "z1"})

    class Boom:
        def table(self, *_a): raise RuntimeError("db down")
    z.save_state(Boom(), "o1", "shop.com", {"zone_id": "z1"})


def test_lookup_failure_falls_back_instead_of_breaking_publish(monkeypatch):
    class Boom:
        def table(self, *_a): raise RuntimeError("db down")
    monkeypatch.setattr(z, "existing_zone", lambda d, **k: None)
    assert z.resolve_mode(Boom(), "o1", "shop.com") == "client_cname"
