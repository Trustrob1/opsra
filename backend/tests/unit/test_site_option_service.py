"""
tests/unit/test_site_option_service.py
SITE-OPTIONS OPT-1 - option sets: create/attach/detach rules, the free-sites exemption, the pick (change, payment
lock, double pick), the builder notice, the public view and the daily sweep. FakeDB stands in for Supabase and the
message senders are recorded instead of sent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import site_access_service as access
from app.services import site_capture_service as cap
from app.services import site_option_service as opt
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
B1, B2 = "builder-1", "builder-2"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _site(sid, builder=B1, status="preview_ready", **kw):
    r = {"id": sid, "org_id": ORG, "builder_id": builder, "deleted_at": None, "status": status, "slug": f"slug-{sid}",
         "client_business_name": f"Biz {sid}", "tier": "standard", "preview_expires_at": _iso(NOW + timedelta(days=2)),
         "content": {"hero": {"headline": f"Headline {sid}"}}, "option_set_id": None, "option_offered": False}
    r.update(kw)
    return r


def _db(sites=None, pricing=None, builders=None):
    return FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": pricing or {}}],
        site_builders=builders if builders is not None else [
            {"id": B1, "org_id": ORG, "business_name": "Pixel Co", "full_name": "Ada", "phone_number": "2348030000001",
             "email": "ada@example.com", "max_active_sites": None, "access_paid_until": None},
            {"id": B2, "org_id": ORG, "business_name": "Other", "full_name": "Bayo", "phone_number": "2348030000002"}],
        sites=sites if sites is not None else [_site("s1"), _site("s2"), _site("s3")],
        site_option_sets=[], site_option_items=[], site_orders=[], site_events=[])


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    log = {"wa": [], "email": []}
    monkeypatch.setattr(cap, "_send_whatsapp", lambda db, org, phone, text, **kw: log["wa"].append((phone, text, kw)) or True)
    monkeypatch.setattr(cap, "_send_email", lambda to, subject, text: log["email"].append((to, subject, text)) or True)
    monkeypatch.setattr(opt, "_now", lambda: NOW)
    return log


def _set(db, site_ids=("s1", "s2"), builder=B1):
    return opt.create_set(db, ORG, builder, "Mrs Obi", "user:u1", list(site_ids))


def _row(db, table, id_):
    return next(r for r in db.rows(table) if r["id"] == id_)


# -- creating and attaching ----------------------------------------------------------

def test_a_set_gets_a_private_link_and_labelled_designs():
    db = _db()
    s = _set(db)
    assert s["link"].endswith("/o/" + db.rows("site_option_sets")[0]["token"]) and len(db.rows("site_option_sets")[0]["token"]) >= 30
    assert [i["label"] for i in s["items"]] == ["Design A", "Design B"] and s["status"] == "open"
    assert [r["option_offered"] for r in db.rows("sites")[:2]] == [True, True] and db.rows("sites")[2]["option_offered"] is False


def test_the_link_keeps_working_as_long_as_the_set_lives():
    db = _db()
    s = _set(db)
    expires = db.rows("site_option_sets")[0]["expires_at"]
    assert _row(db, "sites", "s1")["preview_expires_at"] == expires          # was 2 days, now at least the set's life


def test_at_most_five_designs_per_set():
    db = _db(sites=[_site(f"s{i}") for i in range(7)])
    s = _set(db, [f"s{i}" for i in range(5)])
    with pytest.raises(opt.OptionLimit):
        opt.attach_site(db, ORG, s["id"], "s5", None, "u")
    assert len(db.rows("site_option_items")) == 5


def test_a_builder_cannot_open_more_than_ten_sets_at_once():
    db = _db()
    for _ in range(10):
        opt.create_set(db, ORG, B1, None, "u")
    with pytest.raises(opt.OptionLimit):
        opt.create_set(db, ORG, B1, None, "u")
    assert opt.create_set(db, ORG, B2, None, "u")["status"] == "open"          # another builder is unaffected


def test_the_limits_come_from_settings():
    db = _db(pricing={"options": {"max_items": 2, "max_open_sets": 1}})
    s = _set(db, ["s1", "s2"])
    with pytest.raises(opt.OptionLimit):
        opt.attach_site(db, ORG, s["id"], "s3", None, "u")
    with pytest.raises(opt.OptionLimit):
        opt.create_set(db, ORG, B1, None, "u")


@pytest.mark.parametrize("site,why", [
    (_site("x", builder=B2), "different builder"), (_site("x", status="live"), "live"), (_site("x", status="cancelled"), "cancelled"),
    (_site("x", option_set_id="other"), "already in a set"), (_site("x", deleted_at="2026-10-01T00:00:00Z"), "deleted")])
def test_sites_that_do_not_qualify_are_refused(site, why):
    db = _db(sites=[site])
    s = opt.create_set(db, ORG, B1, None, "u")
    with pytest.raises(opt.OptionError):
        opt.attach_site(db, ORG, s["id"], "x", None, "u")
    assert db.rows("site_option_items") == [], why


def test_a_site_with_a_payment_cannot_be_offered():
    db = _db()
    db.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "fulfilling"})
    s = opt.create_set(db, ORG, B1, None, "u")
    with pytest.raises(opt.OptionError):
        opt.attach_site(db, ORG, s["id"], "s1", None, "u")


def test_other_orgs_and_other_builders_cannot_see_or_change_a_set():
    db = _db()
    s = _set(db)
    with pytest.raises(opt.OptionNotFound):
        opt.get_set(db, ORG, s["id"], builder_id=B2)
    with pytest.raises(opt.OptionNotFound):
        opt.get_set(db, "org-2", s["id"])
    with pytest.raises(opt.OptionNotFound):
        opt.attach_site(db, ORG, s["id"], "s3", None, "u", builder_id=B2)


# -- the free-sites limit -------------------------------------------------------------

def test_offered_designs_do_not_use_free_site_slots():
    db = _db(sites=[_site(f"s{i}") for i in range(5)])
    _set(db, ["s0", "s1", "s2", "s3"])
    assert access.count_sites(db, ORG, B1) == 1                                   # only s4 counts


def test_the_chosen_design_counts_once_picked():
    db = _db(sites=[_site(f"s{i}") for i in range(3)])
    s = _set(db, ["s0", "s1", "s2"])
    assert access.count_sites(db, ORG, B1) == 0
    opt.choose_for_client(db, ORG, s["id"], s["items"][1]["id"], "u")
    assert access.count_sites(db, ORG, B1) == 1


def test_taking_a_design_out_brings_the_free_limit_back():
    db = _db(sites=[_site(f"s{i}") for i in range(5)] + [_site(f"n{i}") for i in range(3)])
    s = _set(db, ["s0", "s1"])                                                  # 3 other counted sites = at the 3 free sites
    with pytest.raises(opt.OptionLimit):
        opt.detach_site(db, ORG, s["id"], "s0", "u")
    assert _row(db, "sites", "s0")["option_offered"] is True


def test_taking_a_design_out_works_when_there_is_room():
    db = _db()
    s = _set(db)
    out = opt.detach_site(db, ORG, s["id"], "s1", "u")
    assert [i["site_id"] for i in out["items"]] == ["s2"]
    assert _row(db, "sites", "s1")["option_offered"] is False and _row(db, "sites", "s1")["option_set_id"] is None
    assert _row(db, "sites", "s2")["option_offered"] is True


def test_the_picked_design_cannot_be_taken_out():
    db = _db()
    s = _set(db)
    opt.choose_for_client(db, ORG, s["id"], s["items"][0]["id"], "u")
    with pytest.raises(opt.OptionConflict):
        opt.detach_site(db, ORG, s["id"], "s1", "u")


# -- the pick -------------------------------------------------------------------------

def test_picking_marks_the_design_and_keeps_it_for_14_days_on_the_others(sent):
    db = _db()
    s = _set(db)
    r = opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], s["items"][1]["id"], NOW)
    row = db.rows("site_option_sets")[0]
    assert r["label"] == "Design B" and r["changed"] is False and row["status"] == "chosen"
    assert row["chosen_site_id"] == "s2" and row["release_after"] == _iso(NOW + timedelta(days=14))
    assert _row(db, "sites", "s2")["option_offered"] is False and _row(db, "sites", "s1")["option_offered"] is True
    assert [i["status"] for i in db.rows("site_option_items")] == ["offered", "chosen"]
    assert [e["event"] for e in db.rows("site_events")][-1] == "option_chosen"


def test_the_builder_is_told_with_a_payment_link_button(sent):
    db = _db()
    s = _set(db)
    opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], s["items"][0]["id"], NOW)
    phone, text, kw = sent["wa"][0]
    assert phone == "2348030000001" and "Mrs Obi" in text and "Design A" in text
    assert kw["cta"][0] == "Create payment link" and kw["cta"][1].endswith("/builders") and kw["template_env"] == opt.PICK_TEMPLATE_ENV
    assert sent["email"][0][0] == "ada@example.com"


def test_a_builder_notice_failure_never_blocks_the_pick(monkeypatch):
    db = _db()
    s = _set(db)

    def boom(*a, **k):
        raise RuntimeError("whatsapp down")
    monkeypatch.setattr(cap, "_send_whatsapp", boom)
    assert opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], s["items"][0]["id"], NOW)["label"] == "Design A"


def test_choosing_on_the_clients_behalf_does_not_message_the_builder(sent):
    db = _db()
    s = _set(db)
    opt.choose_for_client(db, ORG, s["id"], s["items"][0]["id"], "builder:b1", B1)
    assert sent["wa"] == [] and sent["email"] == []


def test_the_pick_can_change_and_the_old_payment_link_is_switched_off():
    db = _db()
    s = _set(db)
    tok = db.rows("site_option_sets")[0]["token"]
    opt.choose_by_token(db, tok, s["items"][0]["id"], NOW)
    db.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "pending_payment"})
    r = opt.choose_by_token(db, tok, s["items"][1]["id"], NOW + timedelta(days=1))
    assert r["changed"] is True and db.rows("site_option_sets")[0]["chosen_site_id"] == "s2"
    assert _row(db, "site_orders", "o1")["status"] == "expired"
    assert _row(db, "sites", "s1")["option_offered"] is True and _row(db, "sites", "s2")["option_offered"] is False
    assert [i["status"] for i in db.rows("site_option_items")] == ["offered", "chosen"]


def test_picking_the_same_design_twice_does_nothing_new(sent):
    db = _db()
    s = _set(db)
    tok = db.rows("site_option_sets")[0]["token"]
    opt.choose_by_token(db, tok, s["items"][0]["id"], NOW)
    again = opt.choose_by_token(db, tok, s["items"][0]["id"], NOW)
    assert again["already"] is True and len(sent["wa"]) == 1 and len([e for e in db.rows("site_events") if e["event"] == "option_chosen"]) == 1


def test_once_paid_the_pick_cannot_change():
    db = _db()
    s = _set(db)
    tok = db.rows("site_option_sets")[0]["token"]
    opt.choose_by_token(db, tok, s["items"][0]["id"], NOW)
    db.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "fulfilling"})
    with pytest.raises(opt.OptionConflict):
        opt.choose_by_token(db, tok, s["items"][1]["id"], NOW)
    assert db.rows("site_option_sets")[0]["chosen_site_id"] == "s1"


def test_two_devices_cannot_both_win_the_same_change():
    db = _db()
    s = _set(db)
    tok = db.rows("site_option_sets")[0]["token"]
    stale = dict(db.rows("site_option_sets")[0])                  # what a second request read before the first one finished
    opt.choose_by_token(db, tok, s["items"][0]["id"], NOW)
    with pytest.raises(opt.OptionConflict):
        opt._choose(db, stale, s["items"][1]["id"], "client", NOW, notify=False)
    assert db.rows("site_option_sets")[0]["chosen_site_id"] == "s1"


@pytest.mark.parametrize("status", ["closed", "expired"])
def test_a_closed_set_takes_no_pick(status):
    db = _db()
    s = _set(db)
    db.rows("site_option_sets")[0]["status"] = status
    with pytest.raises(opt.OptionConflict):
        opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], s["items"][0]["id"], NOW)


def test_a_link_past_its_expiry_takes_no_pick():
    db = _db()
    s = _set(db)
    with pytest.raises(opt.OptionConflict):
        opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], s["items"][0]["id"], NOW + timedelta(days=40))


def test_unknown_links_and_designs_are_refused():
    db = _db()
    s = _set(db)
    with pytest.raises(opt.OptionNotFound):
        opt.choose_by_token(db, "nope", s["items"][0]["id"], NOW)
    with pytest.raises(opt.OptionNotFound):
        opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], "not-an-item", NOW)


def test_a_cancelled_design_cannot_be_picked():
    db = _db()
    s = _set(db)
    _row(db, "sites", "s1")["status"] = "cancelled"
    with pytest.raises(opt.OptionConflict):
        opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], s["items"][0]["id"], NOW)


# -- what the client sees ----------------------------------------------------------------

def test_the_public_view_has_no_internal_ids_and_marks_the_pick():
    db = _db()
    s = _set(db)
    tok = db.rows("site_option_sets")[0]["token"]
    v = opt.public_view(db, tok)
    assert v["builder_name"] == "Pixel Co" and v["can_choose"] is True and len(v["items"]) == 2
    assert all("site_id" not in i for i in v["items"]) and v["items"][0]["preview_url"].endswith("/s/slug-s1")
    opt.choose_by_token(db, tok, s["items"][0]["id"], NOW)
    assert [i["chosen"] for i in opt.public_view(db, tok)["items"]] == [True, False]


def test_unknown_token_has_no_view():
    assert opt.public_view(_db(), "nope") is None and opt.public_view(_db(), "") is None


def test_a_paid_choice_shows_as_paid_and_closed_for_changes():
    db = _db()
    s = _set(db)
    tok = db.rows("site_option_sets")[0]["token"]
    opt.choose_by_token(db, tok, s["items"][0]["id"], NOW)
    db.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "live"})
    v = opt.public_view(db, tok)
    assert v["paid"] is True and v["can_choose"] is False


# -- forms ----------------------------------------------------------------------------------

def test_a_form_for_a_set_is_exempt_only_while_there_is_room():
    db = _db(sites=[_site(f"s{i}") for i in range(6)])
    s = _set(db, ["s0", "s1", "s2", "s3"])
    assert opt.usable_for_new_site(db, ORG, s["id"], B1)["id"] == s["id"]
    opt.attach_site(db, ORG, s["id"], "s4", None, "u")
    assert opt.usable_for_new_site(db, ORG, s["id"], B1) is None                  # full: the normal free-sites rule applies
    assert opt.usable_for_new_site(db, ORG, s["id"], B2) is None                  # someone else's set
    assert opt.usable_for_new_site(db, ORG, None, B1) is None and opt.usable_for_new_site(db, ORG, "missing", B1) is None


# -- the sweep ----------------------------------------------------------------------------------

def _age(db, **fields):
    db.rows("site_option_sets")[0].update(fields)


def test_a_set_nobody_picked_expires_and_its_sites_go_back_to_normal():
    db = _db()
    _set(db)
    _age(db, expires_at=_iso(NOW - timedelta(hours=1)))
    assert opt.run_sweep(db, NOW)["expired"] == 1
    assert db.rows("site_option_sets")[0]["status"] == "expired"
    assert all(r["option_offered"] is False and r["option_set_id"] is None for r in db.rows("sites"))
    assert opt.run_sweep(db, NOW)["expired"] == 0                                    # idempotent


def test_a_paid_pick_closes_the_set_and_keeps_the_others_14_days_then_cleans_them_up():
    db = _db()
    s = _set(db)
    opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], s["items"][0]["id"], NOW)
    db.rows("site_orders").append({"id": "o1", "org_id": ORG, "site_id": "s1", "kind": "initial", "status": "fulfilling"})
    assert opt.run_sweep(db, NOW + timedelta(days=1))["closed"] == 1
    row = db.rows("site_option_sets")[0]
    assert row["status"] == "closed" and row["release_after"] == _iso(NOW + timedelta(days=15))
    assert [i["status"] for i in db.rows("site_option_items")] == ["chosen", "released"]
    assert _row(db, "sites", "s2")["status"] == "preview_ready"                       # still kept
    assert opt.run_sweep(db, NOW + timedelta(days=16))["cleaned"] == 1
    assert _row(db, "sites", "s2")["status"] == "cancelled" and _row(db, "sites", "s1")["status"] == "preview_ready"
    assert opt.run_sweep(db, NOW + timedelta(days=17))["cleaned"] == 0


def test_an_unpaid_pick_is_locked_in_after_14_days_and_the_others_are_cleaned_up():
    db = _db()
    s = _set(db)
    opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], s["items"][0]["id"], NOW)
    assert opt.run_sweep(db, NOW + timedelta(days=13))["closed"] == 0                  # still changeable
    out = opt.run_sweep(db, NOW + timedelta(days=15))
    assert out["closed"] == 1 and out["cleaned"] == 1 and out["failed"] == 0
    assert _row(db, "sites", "s2")["status"] == "cancelled" and _row(db, "sites", "s1")["status"] == "preview_ready"


def test_cleanup_never_touches_a_paid_or_live_site():
    db = _db()
    s = _set(db)
    opt.choose_by_token(db, db.rows("site_option_sets")[0]["token"], s["items"][0]["id"], NOW)
    db.rows("site_orders").append({"id": "o2", "org_id": ORG, "site_id": "s2", "kind": "initial", "status": "fulfilling"})
    opt.run_sweep(db, NOW + timedelta(days=15))
    assert _row(db, "sites", "s2")["status"] == "preview_ready"


def test_a_manual_close_returns_the_sites_and_blocks_picks():
    db = _db()
    s = _set(db)
    out = opt.close_set(db, ORG, s["id"], "u")
    assert out["status"] == "closed" and all(r["option_offered"] is False for r in db.rows("sites"))
    with pytest.raises(opt.OptionConflict):
        opt.close_set(db, ORG, s["id"], "u")


def test_a_set_with_a_pick_cannot_be_closed_by_hand():
    db = _db()
    s = _set(db)
    opt.choose_for_client(db, ORG, s["id"], s["items"][0]["id"], "u")
    with pytest.raises(opt.OptionConflict):
        opt.close_set(db, ORG, s["id"], "u")
