import pytest
from fastapi import HTTPException

from app.services import webchat_embed_service as em
from app.services import webchat_service as wc


def test_clean_host():
    assert em.clean_host("https://www.Example.com/shop?x=1") == "www.example.com"
    assert em.clean_host("example.com") == "example.com"
    assert em.clean_host("localhost:3000") == "localhost"
    assert em.clean_host("not a site") == ""
    assert em.clean_host("javascript:alert(1)") == ""
    assert em.clean_host("") == ""


def test_sanitise_domains_dedupes_caps_and_accepts_text():
    assert em.sanitise_domains(["https://a.com", "A.com", "", "b.ng/x"]) == ["a.com", "b.ng"]
    assert em.sanitise_domains("a.com, b.com\nc.com") == ["a.com", "b.com", "c.com"]
    assert len(em.sanitise_domains([f"s{i}.com" for i in range(50)])) == em.MAX_DOMAINS
    assert em.sanitise_domains(None) == []


def test_origin_allowed():
    assert em.origin_allowed([], "https://anything.com")            # no list: any website
    assert em.origin_allowed([], None)
    lst = ["royalrest.com"]
    assert em.origin_allowed(lst, "https://royalrest.com")
    assert em.origin_allowed(lst, "https://www.royalrest.com")
    assert em.origin_allowed(lst, "https://shop.royalrest.com:8443")
    assert not em.origin_allowed(lst, "https://evilroyalrest.com")  # not a sub-domain
    assert not em.origin_allowed(lst, "https://royalrest.com.evil.io")
    assert not em.origin_allowed(lst, None)                           # unknown site: refused when a list is set
    assert not em.origin_allowed(lst, "unknown")
    assert not em.origin_allowed(lst, "http://localhost:5173")
    assert em.origin_allowed(["localhost"], "http://localhost:5173")


def test_config_keeps_list_and_side():
    c = wc.sanitise_config({"allowed_domains": ["https://Royalrest.com/", "bad site"], "widget_side": "left"})
    assert c["allowed_domains"] == ["royalrest.com"] and c["widget_side"] == "left"
    assert wc.sanitise_config({"widget_side": "top"})["widget_side"] == "right"
    assert wc.DEFAULT_CONFIG["allowed_domains"] == []


def test_guard_and_widget_endpoint(monkeypatch):
    from app.routers import public_webchat as r
    found = {"org_id": "o", "config": {"allowed_domains": ["royalrest.com"], "business_name": "RR", "brand_color": "#028090", "widget_side": "left"}}
    r._embed_guard(found, None)                                   # not embedded: never blocked
    r._embed_guard(found, "https://royalrest.com")
    with pytest.raises(HTTPException) as e:
        r._embed_guard(found, "https://other.com")
    assert e.value.status_code == 403 and e.value.detail["code"] == "EMBED_NOT_ALLOWED"

    monkeypatch.setattr(wc, "resolve_key", lambda db, k: found if k == "wc_ok123456" else None)
    class Req:
        def __init__(self, o): self.headers = {"origin": o} if o else {}
    import json
    res = r.widget_info("wc_ok123456", Req("https://www.royalrest.com"), None)
    body = json.loads(res.body)["data"]
    assert body["allowed"] and body["side"] == "left" and res.headers["access-control-allow-origin"] == "*"
    assert not json.loads(r.widget_info("wc_ok123456", Req("https://other.com"), None).body)["data"]["allowed"]
    assert json.loads(r.widget_info("wc_missing00", Req("https://royalrest.com"), None).body)["data"] == {"allowed": False}


# ── WEBCHAT-EMBED-2 ──────────────────────────────────────────────────────────

def test_install_email_has_code_and_note():
    tag = em.script_tag("https://opsra.com.ng/", "wc_abcdefgh")
    assert tag == '<script src="https://opsra.com.ng/widget.js" data-key="wc_abcdefgh" async></script>'
    subj, body = em.install_email("Royal Rest", "Please do it today", tag, "https://opsra.com.ng/c/wc_abcdefgh")
    assert "Royal Rest" in subj and tag in body and "Please do it today" in body and "</body>" in body
    assert "A note from" not in em.install_email("Royal Rest", "  ", tag, "x")[1]


class _Up:
    def __init__(self, db): self.db = db
    def upsert(self, row, on_conflict=None): self.db.writes.append((row, on_conflict)); return self
    def execute(self): return None


class _SeenDB:
    def __init__(self): self.writes = []
    def table(self, n): assert n == "webchat_widget_seen"; return _Up(self)


def test_record_seen_throttles_and_skips_own_host():
    em._SEEN_WRITTEN.clear()
    db = _SeenDB()
    em.record_seen(db, "o1", "https://www.royalrest.com")
    em.record_seen(db, "o1", "https://www.royalrest.com")           # same host again: no second write
    em.record_seen(db, "o1", "https://opsra.com.ng", own_hosts=("opsra.com.ng",))
    em.record_seen(db, "o1", None)
    em.record_seen(db, "o1", "https://other.ng")
    assert [w[0]["host"] for w in db.writes] == ["www.royalrest.com", "other.ng"]
    assert db.writes[0][1] == "org_id,host"


def test_record_seen_never_raises():
    class Boom:
        def table(self, n): raise RuntimeError("db down")
    em._SEEN_WRITTEN.clear()
    em.record_seen(Boom(), "o1", "https://x.com")


def test_routes_exist():
    from app.routers import webchat as r
    paths = {x.path for x in r.router.routes}
    assert "/webchat/embed-email" in paths and "/webchat/embed-seen" in paths
