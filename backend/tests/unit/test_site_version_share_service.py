"""
tests/unit/test_site_version_share_service.py
SITE-OPTIONS OPT-3 - sharing several saved versions of one Premium site behind one link: creating, the rules
(Premium only, one open link per site, max versions, nothing paid), the pick (becomes the live design, can change until
paid, rolls back if the design can't be applied), the builder notice, the public view and the hourly sweep.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import site_capture_service as cap
from app.services import site_option_service as opt
from app.services import site_premium_service
from app.services import site_version_share_service as ver
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
B1, B2 = "builder-1", "builder-2"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _design(i, site="s1", **kw):
    r = {"id": f"d{i}", "org_id": ORG, "site_id": site, "version": i, "kind": "generate", "status": "ready", "staged": False,
         "created_at": _iso(NOW - timedelta(days=10 - i)), "checks": {}}
    r.update(kw)
    return r


def _site(sid="s1", builder=B1, **kw):
    r = {"id": sid, "org_id": ORG, "builder_id": builder, "deleted_at": None, "status": "preview_ready", "tier": "premium",
         "slug": f"slug-{sid}", "client_business_name": f"Biz {sid}", "current_design_id": "d1",
         "preview_expires_at": _iso(NOW + timedelta(days=2))}
    r.update(kw)
    return r


def _db(n_designs=4, **site_kw):
    return FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": {}}],
        site_builders=[{"id": B1, "org_id": ORG, "business_name": "Pixel Co", "full_name": "Ada", "phone_number": "2348030000001",
                        "email": "ada@example.com"}, {"id": B2, "org_id": ORG, "business_name": "Other", "full_name": "Bayo"}],
        sites=[_site(**site_kw), _site("s2", tier="standard")],
        site_designs=[_design(i) for i in range(1, n_designs + 1)],
        site_version_shares=[], site_version_items=[], site_orders=[], site_events=[], site_assets=[])


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    log = {"wa": [], "email": []}
    monkeypatch.setattr(cap, "_send_whatsapp", lambda db, org, phone, text, **kw: log["wa"].append((phone, text, kw)) or True)
    monkeypatch.setattr(cap, "_send_email", lambda to, subject, text: log["email"].append((to, subject, text)) or True)
    monkeypatch.setattr(opt, "_now", lambda: NOW)
    monkeypatch.setattr(ver, "_now", lambda: NOW)
    return log


def _share(db, ids=("d2", "d3")):
    return ver.create_share(db, ORG, "s1", "Mrs Obi", list(ids), "user:u1")


def _site_row(db, sid="s1"):
    return next(r for r in db.rows("sites") if r["id"] == sid)


# -- listing what can be shared ------------------------------------------------------------

def test_premium_sites_say_which_site_they_are_and_how_many_versions_they_have():
    db = _db()
    rows = ver.premium_sites(db, ORG, B1)
    assert [s["site_id"] for s in rows] == ["s1"]                      # the Standard site is not offered
    r = rows[0]
    assert r["business_name"] == "Biz s1" and r["versions"] == 4 and r["builder_name"] == "Pixel Co"
    assert r["preview_url"].endswith("/s/slug-s1") and r["status"] == "preview_ready"
    assert ver.premium_sites(_db(n_designs=1), ORG, B1)[0]["versions"] == 1      # still listed, the screen disables it
    assert ver.premium_sites(db, ORG, B2) == []


def test_without_a_builder_every_builders_premium_sites_are_listed():
    db = _db()
    db.rows("sites").append(_site("s9", builder=B2))
    db.rows("site_designs").extend([_design(1, "s9") | {"id": "n1"}, _design(2, "s9") | {"id": "n2"}])
    rows = ver.premium_sites(db, ORG)
    assert sorted(r["site_id"] for r in rows) == ["s1", "s9"]
    assert {r["site_id"]: r["builder_name"] for r in rows} == {"s1": "Pixel Co", "s9": "Other"}


def test_versions_are_listed_newest_first_and_held_back_ones_are_left_out():
    db = _db()
    db.rows("site_designs").append(_design(9, staged=True))
    assert [v["version"] for v in ver.site_versions(db, ORG, "s1")] == [4, 3, 2, 1]
    assert ver.site_versions(db, ORG, "s2") == []          # a Standard site has none
    with pytest.raises(opt.OptionNotFound):
        ver.site_versions(db, ORG, "s1", builder_id=B2)


# -- creating -------------------------------------------------------------------------------

def test_a_link_gets_a_private_url_and_labelled_versions():
    db = _db()
    s = _share(db)
    tok = db.rows("site_version_shares")[0]["token"]
    assert s["link"].endswith("/v/" + tok) and len(tok) >= 30 and s["status"] == "open"
    assert [(i["label"], i["version"]) for i in s["items"]] == [("Version 2", 2), ("Version 3", 3)]
    assert s["items"][0]["preview_url"].endswith(f"/v/{tok}/view/{s['items'][0]['id']}")
    assert s["business_name"] == "Biz s1" and s["client_name"] == "Mrs Obi"


def test_the_preview_stays_alive_for_as_long_as_the_link():
    db = _db(preview_expires_at=_iso(NOW + timedelta(hours=3)))
    s = _share(db)
    assert opt._parse(_site_row(db)["preview_expires_at"]) >= opt._parse(s["expires_at"])


def test_rules_for_creating():
    db = _db()
    with pytest.raises(opt.OptionError):                   # Standard site
        ver.create_share(db, ORG, "s2", None, ["d1"], "u")
    with pytest.raises(opt.OptionError):                   # a version that is not this site's / not ready
        ver.create_share(db, ORG, "s1", None, ["nope"], "u")
    with pytest.raises(opt.OptionError):                   # none picked
        ver.create_share(db, ORG, "s1", None, [], "u")
    with pytest.raises(opt.OptionNotFound):                # someone else's site
        ver.create_share(db, ORG, "s1", None, ["d1"], "u", builder_id=B2)
    _share(db)
    with pytest.raises(opt.OptionConflict):                # one open link per site
        ver.create_share(db, ORG, "s1", None, ["d1"], "u")


def test_at_most_five_versions_and_a_paid_site_is_refused():
    db = _db(n_designs=7)
    with pytest.raises(opt.OptionLimit):
        ver.create_share(db, ORG, "s1", None, [f"d{i}" for i in range(1, 7)], "u")
    db2 = _db()
    db2.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "paid"})
    with pytest.raises(opt.OptionConflict):
        _share(db2)


def test_open_links_per_builder_are_limited():
    db = _db()
    db.rows("site_builder_settings")[0]["pricing"] = {"options": {"max_open_sets": 1}}
    db.rows("sites").append(_site("s3"))
    db.rows("site_designs").extend([_design(1, "s3"), _design(2, "s3") | {"id": "x2"}])
    _share(db)
    with pytest.raises(opt.OptionLimit):
        ver.create_share(db, ORG, "s3", None, ["d1"], "u")


# -- adding / removing / closing -----------------------------------------------------------

def test_add_remove_and_close():
    db = _db()
    s = _share(db)
    s = ver.add_version(db, ORG, s["id"], "d4", "Bold one", "u")
    assert [i["label"] for i in s["items"]] == ["Version 2", "Version 3", "Bold one"]
    with pytest.raises(opt.OptionConflict):
        ver.add_version(db, ORG, s["id"], "d4", None, "u")          # already in
    s = ver.remove_version(db, ORG, s["id"], s["items"][2]["id"], "u")
    assert len(s["items"]) == 2
    s = ver.close_share(db, ORG, s["id"], "u")
    assert s["status"] == "closed"
    with pytest.raises(opt.OptionConflict):
        ver.add_version(db, ORG, s["id"], "d4", None, "u")
    with pytest.raises(opt.OptionConflict):
        ver.close_share(db, ORG, s["id"], "u")


def test_the_last_version_and_the_picked_one_cannot_be_removed():
    db = _db()
    s = _share(db, ("d2", "d3"))
    ver.choose_for_client(db, ORG, s["id"], s["items"][0]["id"], "u")
    with pytest.raises(opt.OptionConflict):
        ver.remove_version(db, ORG, s["id"], s["items"][0]["id"], "u")
    s = ver.remove_version(db, ORG, s["id"], s["items"][1]["id"], "u")
    with pytest.raises(opt.OptionConflict):
        ver.remove_version(db, ORG, s["id"], s["items"][0]["id"], "u")


# -- the pick -------------------------------------------------------------------------------

def test_a_client_pick_makes_that_version_the_live_design_and_tells_the_builder(sent):
    db = _db()
    s = _share(db)
    tok = db.rows("site_version_shares")[0]["token"]
    r = ver.choose_by_token(db, tok, s["items"][1]["id"])
    assert r["label"] == "Version 3" and r["already"] is False
    assert _site_row(db)["current_design_id"] == "d3"
    sh = db.rows("site_version_shares")[0]
    assert sh["status"] == "chosen" and sh["chosen_design_id"] == "d3"
    assert sent["wa"] and "Version 3" in sent["wa"][0][1] and sent["wa"][0][2]["cta"][0] == "Create payment link"
    assert sent["email"] and any(e["event"] == "version_chosen" for e in db.rows("site_events"))


def test_the_pick_can_change_until_paid_and_a_repeat_is_a_no_op(sent):
    db = _db()
    s = _share(db)
    tok = db.rows("site_version_shares")[0]["token"]
    ver.choose_by_token(db, tok, s["items"][0]["id"])
    again = ver.choose_by_token(db, tok, s["items"][0]["id"])
    assert again["already"] is True and len(sent["wa"]) == 1
    r = ver.choose_by_token(db, tok, s["items"][1]["id"])
    assert r["changed"] is True and _site_row(db)["current_design_id"] == "d3"
    db.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "paid"})
    with pytest.raises(opt.OptionConflict):
        ver.choose_by_token(db, tok, s["items"][0]["id"])
    assert _site_row(db)["current_design_id"] == "d3"


def test_a_pick_that_cannot_be_applied_leaves_everything_as_it_was(monkeypatch):
    db = _db()
    s = _share(db)
    tok = db.rows("site_version_shares")[0]["token"]

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(site_premium_service, "use_design", boom)
    with pytest.raises(opt.OptionConflict):
        ver.choose_by_token(db, tok, s["items"][0]["id"])
    sh = db.rows("site_version_shares")[0]
    assert sh["status"] == "open" and sh["chosen_design_id"] is None and _site_row(db)["current_design_id"] == "d1"


def test_closed_expired_and_unknown_picks_are_refused():
    db = _db()
    s = _share(db)
    tok = db.rows("site_version_shares")[0]["token"]
    with pytest.raises(opt.OptionNotFound):
        ver.choose_by_token(db, tok, "nope")
    with pytest.raises(opt.OptionNotFound):
        ver.choose_by_token(db, "x" * 40, s["items"][0]["id"])
    with pytest.raises(opt.OptionConflict):
        ver.choose_by_token(db, tok, s["items"][0]["id"], now=NOW + timedelta(days=60))
    ver.close_share(db, ORG, s["id"], "u")
    with pytest.raises(opt.OptionConflict):
        ver.choose_by_token(db, tok, s["items"][0]["id"])


def test_a_builder_can_record_the_pick_without_a_notice(sent):
    db = _db()
    s = _share(db)
    ver.choose_for_client(db, ORG, s["id"], s["items"][0]["id"], "builder:b1", builder_id=B1)
    assert _site_row(db)["current_design_id"] == "d2" and sent["wa"] == []
    with pytest.raises(opt.OptionNotFound):
        ver.choose_for_client(db, ORG, s["id"], s["items"][0]["id"], "builder:b2", builder_id=B2)


# -- the client's view ---------------------------------------------------------------------

def test_public_view_and_rendering(monkeypatch):
    db = _db()
    s = _share(db)
    tok = db.rows("site_version_shares")[0]["token"]
    v = ver.public_view(db, tok)
    assert v["can_choose"] and v["builder_name"] == "Pixel Co" and [i["label"] for i in v["items"]] == ["Version 2", "Version 3"]
    assert ver.public_view(db, "x" * 40) is None
    seen = {}
    monkeypatch.setattr(site_premium_service, "preview_design",
                        lambda db_, org, site, design_id, assets: seen.update(d=design_id) or "<html>page</html>")
    assert ver.render_version(db, tok, s["items"][1]["id"]) == "<html>page</html>" and seen["d"] == "d3"
    with pytest.raises(opt.OptionNotFound):
        ver.render_version(db, tok, "nope")
    ver.close_share(db, ORG, s["id"], "u")
    with pytest.raises(opt.OptionNotFound):
        ver.render_version(db, tok, s["items"][0]["id"])


def test_paid_site_shows_as_paid_and_cannot_be_chosen_from():
    db = _db()
    s = _share(db)
    tok = db.rows("site_version_shares")[0]["token"]
    ver.choose_by_token(db, tok, s["items"][0]["id"])
    db.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "paid"})
    v = ver.public_view(db, tok)
    assert v["paid"] is True and v["can_choose"] is False


# -- sweep ----------------------------------------------------------------------------------

def test_sweep_expires_unpicked_links_and_closes_paid_ones():
    db = _db()
    s = _share(db)
    db.rows("site_version_shares")[0]["expires_at"] = _iso(NOW - timedelta(hours=1))
    assert ver.run_sweep(db, NOW) == {"expired": 1, "closed": 0, "failed": 0}
    assert db.rows("site_version_shares")[0]["status"] == "expired"
    db2 = _db()
    s2 = _share(db2)
    ver.choose_for_client(db2, ORG, s2["id"], s2["items"][0]["id"], "u")
    assert ver.run_sweep(db2, NOW)["closed"] == 0
    db2.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "paid"})
    assert ver.run_sweep(db2, NOW)["closed"] == 1 and db2.rows("site_version_shares")[0]["status"] == "closed"
