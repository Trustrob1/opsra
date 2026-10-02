"""
tests/unit/test_site_cloudflare_service.py
-------------------------------------------
SITE-HOSTNAMES — custom hostnames via the Cloudflare API. A fake client stands in for Cloudflare; no network.
"""
from __future__ import annotations

import pytest

from app.services import site_cloudflare_service as cf

ZONE = "zone123"


@pytest.fixture(autouse=True)
def _worker_settings(monkeypatch):
    class _W:
        SITES_WORKER_NAME = "opsra-sites"
    monkeypatch.setattr(cf, "_settings", lambda: _W())
TARGET = "sites.coreaicloudtech.com.ng"


class FakeCF:
    def __init__(self, existing=None, fail=False):
        self.rows = {r["hostname"]: dict(r) for r in (existing or [])}
        self.routes = {}
        self.calls = []
        self.fail = fail
        self._n = 0

    def request(self, method, path, json=None, params=None):
        self.calls.append((method, path, json, params))
        if self.fail:
            raise cf.HostnameError("x")
        if "/workers/routes" in path:
            if method == "GET":
                return {"success": True, "result": [dict(r) for r in self.routes.values()]}
            if method == "POST":
                self._n += 1
                self.routes[f"r{self._n}"] = {"id": f"r{self._n}", **json}
                return {"success": True, "result": {}}
            rid = path.rsplit("/", 1)[-1]
            if method == "PUT":
                self.routes[rid].update(json)
                return {"success": True, "result": {}}
            if method == "DELETE":
                self.routes.pop(rid, None)
                return {"success": True, "result": {}}
        if method == "GET":
            h = (params or {}).get("hostname")
            return {"success": True, "result": [r for r in self.rows.values() if r["hostname"] == h]}
        if method == "POST":
            self._n += 1
            row = {"id": f"id{self._n}", "hostname": json["hostname"], "status": "pending",
                   "ssl": {"status": "initializing"}, "verification_errors": ["custom hostname does not CNAME to this zone."]}
            self.rows[json["hostname"]] = row
            return {"success": True, "result": row}
        if method == "DELETE":
            hid = path.rsplit("/", 1)[-1]
            self.rows = {k: v for k, v in self.rows.items() if v["id"] != hid}
            return {"success": True, "result": {"id": hid}}
        raise AssertionError(method)


def _reg(c, domain="shop.com.ng"):
    return cf.register_domain(domain, client=c, zone=ZONE, target=TARGET)


def test_registers_domain_and_www_with_http_validation():
    c = FakeCF()
    out = _reg(c)
    posts = [x for x in c.calls if x[0] == "POST" and x[1].endswith("custom_hostnames")]
    assert [p[2]["hostname"] for p in posts] == ["shop.com.ng", "www.shop.com.ng"]
    assert all(p[2]["ssl"]["method"] == "http" and p[2]["ssl"]["type"] == "dv" for p in posts)
    assert all(p[1] == f"/zones/{ZONE}/custom_hostnames" for p in posts)
    assert out["domain"] == "shop.com.ng" and out["target"] == TARGET and out["all_active"] is False
    assert [h["hostname"] for h in out["hostnames"]] == ["shop.com.ng", "www.shop.com.ng"]


def test_register_is_idempotent():
    c = FakeCF()
    _reg(c)
    n = len([x for x in c.calls if x[0] == "POST" and x[1].endswith("custom_hostnames")])
    _reg(c)
    assert len([x for x in c.calls if x[0] == "POST" and x[1].endswith("custom_hostnames")]) == n == 2


def test_www_and_url_input_normalise_to_the_same_hostnames():
    c = FakeCF()
    out = _reg(c, "https://WWW.Shop.com.ng/")
    assert out["domain"] == "shop.com.ng"
    assert set(c.rows) == {"shop.com.ng", "www.shop.com.ng"}


def test_all_active_only_when_status_and_ssl_are_both_active():
    active = {"status": "active", "ssl": {"status": "active"}, "verification_errors": []}
    c = FakeCF(existing=[{"id": "1", "hostname": "shop.com.ng", **active},
                         {"id": "2", "hostname": "www.shop.com.ng", "status": "active", "ssl": {"status": "pending_validation"}}])
    out = _reg(c)
    assert out["hostnames"][0]["active"] is True and out["hostnames"][1]["active"] is False
    assert out["all_active"] is False
    c.rows["www.shop.com.ng"]["ssl"]["status"] = "active"
    assert cf.status_domain("shop.com.ng", client=c, zone=ZONE, target=TARGET)["all_active"] is True


def test_status_does_not_create_and_reports_unregistered():
    c = FakeCF()
    out = cf.status_domain("shop.com.ng", client=c, zone=ZONE, target=TARGET)
    assert not [x for x in c.calls if x[0] == "POST"]
    assert {h["status"] for h in out["hostnames"]} == {"not_registered"} and out["all_active"] is False


def test_hostname_match_is_exact_not_a_substring():
    c = FakeCF(existing=[{"id": "9", "hostname": "notshop.com.ng", "status": "active", "ssl": {"status": "active"}}])
    c.request = lambda m, p, json=None, params=None, _o=c.request: (  # Cloudflare's filter can return near matches
        {"success": True, "result": list(c.rows.values())} if m == "GET" else _o(m, p, json, params))
    out = _reg(c)
    assert not any(h["active"] for h in out["hostnames"])


def test_errors_are_shown_but_capped():
    row = {"id": "1", "hostname": "shop.com.ng", "status": "pending", "ssl": {},
           "verification_errors": ["a", "b", "c", "d", "e"]}
    c = FakeCF(existing=[row])
    assert cf.status_domain("shop.com.ng", client=c, zone=ZONE, target=TARGET)["hostnames"][0]["errors"] == ["a", "b", "c"]


def test_dns_instructions():
    ins = cf.dns_instructions("www.Shop.com.ng", TARGET)
    assert ins[0]["host"] == "www.shop.com.ng" and ins[0]["type"] == "CNAME" and ins[0]["value"] == TARGET
    assert ins[1]["host"] == "shop.com.ng" and "forward" in ins[1]["note"]


def test_remove_deletes_both_hostnames_only():
    c = FakeCF()
    _reg(c)
    _reg(c, "other.ng")
    out = cf.remove_domain("shop.com.ng", client=c, zone=ZONE)
    assert out == {"domain": "shop.com.ng", "removed": 2}
    assert set(c.rows) == {"other.ng", "www.other.ng"}


def test_bad_domain_raises_before_calling_cloudflare():
    from app.services.site_publish_service import NoDomain
    c = FakeCF()
    with pytest.raises(NoDomain):
        _reg(c, "not a domain")
    assert c.calls == []


def test_cloudflare_failure_propagates_as_hostname_error():
    with pytest.raises(cf.HostnameError):
        _reg(FakeCF(fail=True))


class _S:
    def __init__(self, token="t", zone="z", target="t.example.ng"):
        self.CLOUDFLARE_API_TOKEN, self.CLOUDFLARE_ZONE_ID, self.SITES_CNAME_TARGET = token, zone, target


@pytest.mark.parametrize("kw", [{"token": ""}, {"zone": ""}])
def test_not_configured(monkeypatch, kw):
    monkeypatch.setattr(cf, "_settings", lambda: _S(**kw))
    with pytest.raises(cf.HostnamesNotConfigured) as e:
        cf.make_client()
    assert e.value.status_code == 503


def test_make_client_returns_zone_and_default_target(monkeypatch):
    monkeypatch.setattr(cf, "_settings", lambda: _S(target=""))
    client, zone, target = cf.make_client()
    assert isinstance(client, cf.CloudflareClient) and zone == "z" and target == "sites.coreaicloudtech.com.ng"


def test_real_client_turns_http_and_api_failures_into_friendly_errors(monkeypatch):
    import httpx

    class R:
        def __init__(self, code, body): self.status_code, self._b = code, body
        def json(self): return self._b

    secret = "SECRET-TOKEN"
    c = cf.CloudflareClient(secret)
    monkeypatch.setattr(httpx, "request", lambda *a, **k: R(403, {"success": False, "errors": [{"message": "nope"}]}))
    with pytest.raises(cf.HostnameError) as e:
        c.request("GET", "/x")
    assert secret not in str(e.value) and "nope" not in str(e.value)

    def boom(*a, **k): raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "request", boom)
    with pytest.raises(cf.HostnameError):
        c.request("GET", "/x")

    seen = {}
    def ok(method, url, **k):
        seen.update(url=url, auth=k["headers"]["Authorization"])
        return R(200, {"success": True, "result": []})
    monkeypatch.setattr(httpx, "request", ok)
    assert c.request("GET", "/zones/z/custom_hostnames")["success"] is True
    assert seen["url"].endswith("/client/v4/zones/z/custom_hostnames") and seen["auth"] == f"Bearer {secret}"


# ── Worker routes ───────────────────────────────────────────────────────────

def test_register_creates_one_worker_route_covering_bare_and_www():
    c = FakeCF()
    out = _reg(c)
    assert [r["pattern"] for r in c.routes.values()] == ["*shop.com.ng/*"]
    assert list(c.routes.values())[0]["script"] == "opsra-sites"
    assert out["route_ok"] is True


def test_route_is_not_duplicated_on_repeat_and_is_repaired_when_it_points_elsewhere():
    c = FakeCF()
    _reg(c)
    _reg(c)
    assert len(c.routes) == 1
    next(iter(c.routes.values()))["script"] = "something-else"
    assert cf.status_domain("shop.com.ng", client=c, zone=ZONE, target=TARGET)["route_ok"] is False
    _reg(c)
    assert next(iter(c.routes.values()))["script"] == "opsra-sites" and len(c.routes) == 1


def test_status_reports_missing_route_and_blocks_all_active():
    active = {"status": "active", "ssl": {"status": "active"}}
    c = FakeCF(existing=[{"id": "1", "hostname": "shop.com.ng", **active}, {"id": "2", "hostname": "www.shop.com.ng", **active}])
    out = cf.status_domain("shop.com.ng", client=c, zone=ZONE, target=TARGET)
    assert out["route_ok"] is False and out["all_active"] is False
    assert not [x for x in c.calls if x[0] in ("POST", "PUT", "DELETE")]


def test_remove_also_deletes_only_that_domains_route():
    c = FakeCF()
    _reg(c)
    _reg(c, "other.ng")
    cf.remove_domain("shop.com.ng", client=c, zone=ZONE)
    assert [r["pattern"] for r in c.routes.values()] == ["*other.ng/*"]


def test_route_pattern():
    assert cf.route_pattern("https://www.Shop.com.ng/") == "*shop.com.ng/*"


# ── standby account (SITE-FAILOVER) ─────────────────────────────────────────

STANDBY_TARGET = "sites.opsraedge.com.ng"


def test_register_standby_uses_standby_zone_target_and_worker():
    c = FakeCF()
    out = cf.register_standby("shop.com.ng", client=c, zone="standbyzone", target=STANDBY_TARGET, script="opsra-sites-standby")
    assert out["target"] == STANDBY_TARGET
    assert [h["hostname"] for h in out["hostnames"]] == ["shop.com.ng", "www.shop.com.ng"]
    assert all("/zones/standbyzone/" in call[1] for call in c.calls)
    assert list(c.routes.values())[0]["script"] == "opsra-sites-standby"
    assert out["all_active"] is False        # pending until DNS is switched: normal for a standby


def test_register_standby_is_idempotent():
    c = FakeCF()
    for _ in range(2):
        cf.register_standby("shop.com.ng", client=c, zone="z", target=STANDBY_TARGET, script="opsra-sites-standby")
    assert len(c.rows) == 2 and len(c.routes) == 1


def test_standby_not_configured_raises(monkeypatch):
    class _S:
        STANDBY_CLOUDFLARE_API_TOKEN = "t"
        STANDBY_CLOUDFLARE_ZONE_ID = ""
        STANDBY_SITES_CNAME_TARGET = "x"
    monkeypatch.setattr(cf, "_settings", lambda: _S())
    with pytest.raises(cf.HostnamesNotConfigured):
        cf.register_standby("shop.com.ng")


def test_make_standby_client_reads_settings(monkeypatch):
    class _S:
        STANDBY_CLOUDFLARE_API_TOKEN = "t"
        STANDBY_CLOUDFLARE_ZONE_ID = "zz"
        STANDBY_SITES_CNAME_TARGET = STANDBY_TARGET
        STANDBY_SITES_WORKER_NAME = ""
    monkeypatch.setattr(cf, "_settings", lambda: _S())
    _client, zone, target, worker = cf.make_standby_client()
    assert (zone, target, worker) == ("zz", STANDBY_TARGET, "opsra-sites-standby")


def test_remove_standby_deletes_route_and_hostnames():
    c = FakeCF()
    cf.register_standby("shop.com.ng", client=c, zone="z", target=STANDBY_TARGET, script="opsra-sites-standby")
    assert cf.remove_standby("shop.com.ng", client=c, zone="z")["removed"] == 2
    assert not c.rows and not c.routes
