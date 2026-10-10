"""
tests/unit/test_site_entitlement_service.py
---------------------------------------------
SITE-ADDONS A0-1 - tiers, add-ons, has_feature(), monthly caps, staff grant / pause / resume / cancel,
and the Settings numbers. FakeDB stands in for Supabase.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.services import site_entitlement_service as ent
from app.services import site_feature_registry as reg
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
OTHER_ORG = "org-2"
SITE = "site-1"
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def _db(settings_pricing=None, rows=None, sites=None):
    return FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": settings_pricing or {}}],
        sites=sites if sites is not None else [
            {"id": SITE, "org_id": ORG, "deleted_at": None},
            {"id": "site-2", "org_id": ORG, "deleted_at": None},
            {"id": "site-x", "org_id": OTHER_ORG, "deleted_at": None},
        ],
        site_addons=rows or [], site_usage_counters=[], site_events=[],
    )


def _row(kind="tier", key="capture", status="active", source="paid", paid_until=None, picks=None, site=SITE,
         org=ORG, **kw):
    r = {"id": f"r-{kind}-{key}-{site}", "org_id": org, "site_id": site, "kind": kind, "key": key, "status": status,
         "source": source, "billing_mode": "link", "paid_until": paid_until.isoformat() if paid_until else None,
         "grace_until": None, "config": {"picks": picks or []}}
    r.update(kw)
    return r


# -- config ---------------------------------------------------------------------

def test_defaults_are_the_approved_contents_with_every_price_at_zero():
    cfg = ent.get_config({})
    assert list(cfg["tiers"]) == ["capture", "convert", "grow"]
    assert all(t["monthly_ngn"] == 0 and t["setup_fee_ngn"] == 0 and not t["sellable"] for t in cfg["tiers"].values())
    cap, con, gro = (set(cfg["tiers"][k]["features"]) for k in ("capture", "convert", "grow"))
    assert cap < con < gro                                              # each tier includes the one below it
    assert {"form_instant_reply", "speed_alerts", "wa_menu", "my_leads_page"} <= cap
    assert {"ai_assistant", "qualification", "followups", "payment_links", "fb_ig_leads", "own_wa_number"} <= con
    assert "selling_catalog" not in con and "selling_booking" not in con      # Convert picks ONE
    assert cfg["tiers"]["convert"]["pick_one"] == [["selling_catalog", "selling_booking"]]
    assert {"selling_catalog", "selling_booking", "bulk_messaging", "weekly_report", "multi_rep_inbox"} <= gro
    assert cfg["billing"] == {"period_days": 30, "grace_days": 7, "reminder_days": [5, 1]}
    assert cfg["addons"]["extra_rep"]["caps"] == {"reps": 1}


def test_settings_override_prices_features_and_caps_and_bad_values_fall_back():
    cfg = ent.get_config({"pricing": {
        "tiers": {"capture": {"monthly_ngn": 15000, "setup_fee_ngn": 5000, "label": "Starter",
                              "features": ["wa_menu", "not_a_feature", "wa_menu"], "caps": {"ai_messages": 200, "bogus": 3}},
                  "convert": {"monthly_ngn": -5, "caps": {"ai_messages": "x"}}},
        "tier_billing": {"grace_days": 3, "reminder_days": [7, 2, "x"], "period_days": 0}}})
    cap = cfg["tiers"]["capture"]
    assert cap["monthly_ngn"] == 15000 and cap["sellable"] and cap["label"] == "Starter"
    assert cap["features"] == ["wa_menu"] and cap["caps"] == {"ai_messages": 200}
    assert cfg["tiers"]["convert"]["monthly_ngn"] == 0 and cfg["tiers"]["convert"]["caps"] == {}
    assert cfg["billing"]["grace_days"] == 3 and cfg["billing"]["reminder_days"] == [7, 2]
    assert cfg["billing"]["period_days"] == 30


@pytest.mark.parametrize("pricing", [
    {"tiers": {"capture": {"monthly_ngn": -1}}}, {"tiers": {"capture": {"monthly_ngn": 12.5}}},
    {"tiers": {"capture": {"monthly_ngn": True}}}, {"tiers": {"capture": {"monthly_ngn": "5000"}}},
    {"tiers": {"platinum": {"monthly_ngn": 1}}}, {"tiers": []}, {"tiers": {"capture": []}},
    {"tiers": {"capture": {"features": ["made_up"]}}}, {"tiers": {"capture": {"features": "wa_menu"}}},
    {"tiers": {"capture": {"caps": {"nope": 1}}}}, {"tiers": {"capture": {"caps": {"ai_messages": -1}}}},
    {"tiers": {"capture": {"label": ""}}}, {"addons": {"flying_car": {"monthly_ngn": 1}}},
    {"tier_billing": {"grace_days": 61}}, {"tier_billing": {"period_days": 0}}, {"tier_billing": {"reminder_days": "5"}},
])
def test_validate_pricing_refuses_nonsense(pricing):
    with pytest.raises(ent.EntitlementError):
        ent.validate_pricing(pricing)


def test_validate_pricing_accepts_good_blocks_and_makes_whole_numbers():
    p = {"vat_pct": 7.5, "tiers": {"capture": {"monthly_ngn": 15000.0, "caps": {"ai_messages": 100.0}}},
         "addons": {"extra_rep": {"monthly_ngn": 5000}}, "tier_billing": {"grace_days": 7.0, "reminder_days": [5.0, 1]}}
    ent.validate_pricing(p)
    assert p["tiers"]["capture"]["monthly_ngn"] == 15000 and isinstance(p["tiers"]["capture"]["monthly_ngn"], int)
    assert p["tier_billing"]["reminder_days"] == [5, 1]
    ent.validate_pricing({"vat_pct": 7.5})          # no tier blocks at all is fine
    ent.validate_pricing(None)


# -- status from dates ----------------------------------------------------------

@pytest.mark.parametrize("row,expect", [
    ({"status": "pending", "source": "paid", "paid_until": None}, "pending"),
    ({"status": "paused", "source": "paid", "paid_until": NOW + 5 * DAY}, "paused"),
    ({"status": "cancelled", "source": "staff", "paid_until": None}, "cancelled"),
    ({"status": "active", "source": "staff", "paid_until": None}, "active"),            # staff, no end date
    ({"status": "active", "source": "paid", "paid_until": None}, "pending"),            # nothing was ever paid
    ({"status": "active", "source": "paid", "paid_until": NOW + DAY}, "active"),
    ({"status": "active", "source": "paid", "paid_until": NOW - DAY}, "grace"),         # inside 7 days
    ({"status": "active", "source": "paid", "paid_until": NOW - 7 * DAY + timedelta(minutes=1)}, "grace"),
    ({"status": "active", "source": "paid", "paid_until": NOW - 8 * DAY}, "paused"),    # worker has not run yet
    ({"status": "grace", "source": "paid", "paid_until": NOW - 20 * DAY}, "paused"),
])
def test_effective_status(row, expect):
    cfg = ent.get_config({})
    r = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}
    assert ent.effective_status(r, cfg, NOW) == expect


# -- has_feature ----------------------------------------------------------------

def test_no_rows_means_everything_is_off():
    db = _db()
    assert not ent.has_feature(db, ORG, SITE, "form_instant_reply", NOW)


def test_capture_switches_on_capture_features_only():
    db = _db(rows=[_row("tier", "capture", source="staff")])
    assert ent.has_feature(db, ORG, SITE, "form_instant_reply", NOW)
    assert ent.has_feature(db, ORG, SITE, "speed_alerts", NOW)
    assert not ent.has_feature(db, ORG, SITE, "ai_assistant", NOW)
    assert not ent.has_feature(db, ORG, SITE, "bulk_messaging", NOW)


def test_unknown_feature_key_and_blank_ids_are_off():
    db = _db(rows=[_row("tier", "grow", source="staff")])
    assert not ent.has_feature(db, ORG, SITE, "made_up", NOW)
    assert not ent.has_feature(db, ORG, "", "wa_menu", NOW)
    assert not ent.has_feature(db, "", SITE, "wa_menu", NOW)


def test_features_do_not_leak_to_other_sites_or_orgs():
    db = _db(rows=[_row("tier", "grow", source="staff")])
    assert not ent.has_feature(db, ORG, "site-2", "wa_menu", NOW)
    assert not ent.has_feature(db, OTHER_ORG, SITE, "wa_menu", NOW)


def test_paid_tier_follows_the_dates_and_stored_status():
    in_week = _row("tier", "convert", paid_until=NOW + 7 * DAY)
    assert ent.has_feature(_db(rows=[in_week]), ORG, SITE, "qualification", NOW)
    lapsed = _row("tier", "convert", paid_until=NOW - 2 * DAY)
    assert ent.has_feature(_db(rows=[lapsed]), ORG, SITE, "qualification", NOW)             # grace
    long_gone = _row("tier", "convert", paid_until=NOW - 9 * DAY)
    assert not ent.has_feature(_db(rows=[long_gone]), ORG, SITE, "qualification", NOW)      # even if the worker is late
    for st in ("pending", "paused", "cancelled"):
        assert not ent.has_feature(_db(rows=[_row("tier", "convert", status=st, paid_until=NOW + 9 * DAY)]),
                                   ORG, SITE, "qualification", NOW)


def test_grace_length_comes_from_settings():
    row = _row("tier", "capture", paid_until=NOW - 2 * DAY)
    db = _db({"tier_billing": {"grace_days": 1}}, rows=[row])
    assert not ent.has_feature(db, ORG, SITE, "wa_menu", NOW)
    db = _db({"tier_billing": {"grace_days": 3}}, rows=[row])
    assert ent.has_feature(db, ORG, SITE, "wa_menu", NOW)


def test_convert_picks_one_selling_tool_and_grow_has_both():
    cat = _db(rows=[_row("tier", "convert", source="staff", picks=["selling_catalog"])])
    assert ent.has_feature(cat, ORG, SITE, "selling_catalog", NOW)
    assert not ent.has_feature(cat, ORG, SITE, "selling_booking", NOW)
    none = _db(rows=[_row("tier", "convert", source="staff")])
    assert not ent.has_feature(none, ORG, SITE, "selling_catalog", NOW)
    grow = _db(rows=[_row("tier", "grow", source="staff")])
    assert ent.has_feature(grow, ORG, SITE, "selling_catalog", NOW) and ent.has_feature(grow, ORG, SITE, "selling_booking", NOW)


def test_addon_adds_its_feature_and_cap_and_ends_with_its_own_status():
    rows = [_row("tier", "grow", source="staff"), _row("addon", "extra_rep", source="staff"),
            _row("addon", "support_tickets", status="paused")]
    db = _db({"tiers": {"grow": {"caps": {"reps": 3}}}}, rows=rows)
    e = ent.get_entitlements(db, ORG, SITE, NOW)
    assert e["caps"]["reps"] == 4                                     # 3 from the tier + 1 from the add-on
    assert "extra_rep" in e["features"] and "support_tickets" not in e["features"]
    assert e["tier"]["key"] == "grow" and e["tier"]["status"] == "active"
    assert {a["key"]: a["status"] for a in e["addons"]} == {"extra_rep": "active", "support_tickets": "paused"}


def test_has_feature_fails_closed_on_a_database_error():
    class Broken:
        def table(self, *_a):
            raise RuntimeError("db down")
    assert ent.has_feature(Broken(), ORG, SITE, "wa_menu", NOW) is False
    assert ent.consume(Broken(), ORG, SITE, "ai_assistant", 1, NOW) is False


# -- monthly caps ---------------------------------------------------------------

def _ai_db(cap=3):
    return _db({"tiers": {"convert": {"caps": {"ai_messages": cap} if cap is not None else {}}}},
               rows=[_row("tier", "convert", source="staff")])


def test_consume_counts_up_to_the_cap_then_hands_over():
    db = _ai_db(3)
    assert [ent.consume(db, ORG, SITE, "ai_assistant", 1, NOW) for _ in range(5)] == [True, True, True, False, False]
    assert db.rows("site_usage_counters")[0]["used"] == 3
    assert ent.get_entitlements(db, ORG, SITE, NOW)["usage"]["ai_messages"] == {"used": 3, "cap": 3}


def test_consume_with_no_cap_set_or_zero_cap_allows_nothing():
    assert not ent.consume(_ai_db(None), ORG, SITE, "ai_assistant", 1, NOW)
    assert not ent.consume(_ai_db(0), ORG, SITE, "ai_assistant", 1, NOW)


def test_consume_refuses_when_the_feature_is_off_or_n_is_bad():
    db = _db({"tiers": {"capture": {"caps": {"ai_messages": 50}}}}, rows=[_row("tier", "capture", source="staff")])
    assert not ent.consume(db, ORG, SITE, "ai_assistant", 1, NOW)          # Capture has no AI assistant
    db = _ai_db(5)
    assert not ent.consume(db, ORG, SITE, "ai_assistant", -1, NOW)
    assert ent.consume(db, ORG, SITE, "ai_assistant", 0, NOW)
    assert not ent.consume(db, ORG, SITE, "ai_assistant", 6, NOW)          # more than the whole cap in one go
    assert not db.rows("site_usage_counters") or db.rows("site_usage_counters")[0]["used"] == 0


def test_an_uncapped_feature_is_allowed_whenever_it_is_on():
    db = _db(rows=[_row("tier", "capture", source="staff")])
    assert ent.consume(db, ORG, SITE, "wa_menu", 1, NOW)
    assert not db.rows("site_usage_counters")


def test_counters_reset_each_lagos_month():
    db = _ai_db(1)
    assert ent.consume(db, ORG, SITE, "ai_assistant", 1, NOW)
    assert not ent.consume(db, ORG, SITE, "ai_assistant", 1, NOW)
    nxt = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
    assert ent.consume(db, ORG, SITE, "ai_assistant", 1, nxt)
    assert ent.period_start(datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)).isoformat() == "2026-11-01"   # 00:30 Lagos


def test_a_parallel_request_cannot_push_usage_over_the_cap():
    class RacyDB(FakeDB):
        """Another request bumps the counter between our read and our update, once."""
        raced = False

        def table(self, name):
            q = super().table(name)
            if name == "site_usage_counters":
                real = q.update

                def update(payload):
                    if not RacyDB.raced:
                        RacyDB.raced = True
                        self.tables["site_usage_counters"][0]["used"] += 1
                    return real(payload)
                q.update = update
            return q

    base = _ai_db(2)
    db = RacyDB(**{k: copy.deepcopy(v) for k, v in base.tables.items()})
    ent.consume(db, ORG, SITE, "ai_assistant", 1, NOW)                      # first call creates the counter row
    RacyDB.raced = False
    allowed = ent.consume(db, ORG, SITE, "ai_assistant", 1, NOW)           # raced by one other request
    used = db.rows("site_usage_counters")[0]["used"]
    assert used <= 2
    assert allowed is False                                                 # the racer took the last unit


# -- staff actions --------------------------------------------------------------

def test_grant_creates_a_tier_and_logs_it():
    db = _db()
    e = ent.grant(db, ORG, SITE, "user:u1", "tier", "capture", now=NOW)
    assert e["tier"]["key"] == "capture" and e["tier"]["status"] == "active" and e["tier"]["source"] == "staff"
    assert "form_instant_reply" in e["features"]
    assert [x["event"] for x in db.rows("site_events")] == ["site_addon_granted"]
    assert db.rows("site_addons")[0]["org_id"] == ORG


def test_granting_another_tier_replaces_the_current_one_not_adds():
    db = _db()
    ent.grant(db, ORG, SITE, "user:u1", "tier", "capture", now=NOW)
    e = ent.grant(db, ORG, SITE, "user:u1", "tier", "grow", until=NOW + 30 * DAY, now=NOW)
    tiers = [r for r in db.rows("site_addons") if r["kind"] == "tier" and r["status"] != "cancelled"]
    assert len(tiers) == 1 and tiers[0]["key"] == "grow"
    assert e["tier"]["key"] == "grow" and "weekly_report" in e["features"]
    assert db.rows("site_events")[-1]["event"] == "site_addon_changed"


def test_granting_the_same_addon_twice_keeps_one_row():
    db = _db()
    ent.grant(db, ORG, SITE, "user:u1", "addon", "extra_rep", now=NOW)
    ent.grant(db, ORG, SITE, "user:u1", "addon", "extra_rep", until=NOW + 10 * DAY, now=NOW)
    assert len([r for r in db.rows("site_addons") if r["key"] == "extra_rep"]) == 1


@pytest.mark.parametrize("kw", [
    {"kind": "plan", "key": "capture"}, {"kind": "tier", "key": "platinum"}, {"kind": "addon", "key": "capture"},
    {"kind": "tier", "key": "capture", "billing_mode": "cash"},
    {"kind": "tier", "key": "capture", "until": NOW - DAY},
    {"kind": "tier", "key": "convert", "picks": ["selling_catalog", "selling_booking"]},     # only one of the pair
    {"kind": "tier", "key": "convert", "picks": ["wa_menu"]},                                # not a choice for this tier
])
def test_grant_refuses_bad_requests_and_changes_nothing(kw):
    db = _db()
    with pytest.raises(ent.EntitlementError):
        ent.grant(db, ORG, SITE, "user:u1", now=NOW, **kw)
    assert db.rows("site_addons") == []


def test_grant_checks_the_site_belongs_to_this_org():
    db = _db()
    with pytest.raises(ent.EntitlementNotFound):
        ent.grant(db, ORG, "site-x", "user:u1", "tier", "capture", now=NOW)
    with pytest.raises(ent.EntitlementNotFound):
        ent.grant(db, ORG, "nope", "user:u1", "tier", "capture", now=NOW)
    assert db.rows("site_addons") == []


def test_grant_records_the_payer_and_billing_mode():
    db = _db()
    ent.grant(db, ORG, SITE, "user:u1", "tier", "convert", picks=["selling_booking"], billing_mode="auto",
              payer={"name": "Ada", "phone": "2348030000001", "email": "ada@example.com"}, now=NOW)
    r = db.rows("site_addons")[0]
    assert (r["billing_mode"], r["payer_name"], r["payer_email"]) == ("auto", "Ada", "ada@example.com")
    assert r["config"] == {"picks": ["selling_booking"]}


def test_pause_resume_cancel_switch_features_and_are_conditional():
    db = _db()
    ent.grant(db, ORG, SITE, "user:u1", "tier", "capture", now=NOW)
    rid = db.rows("site_addons")[0]["id"]
    ent.set_status(db, ORG, SITE, rid, "pause", "user:u1", now=NOW)
    assert not ent.has_feature(db, ORG, SITE, "wa_menu", NOW)
    with pytest.raises(ent.EntitlementError):
        ent.set_status(db, ORG, SITE, rid, "pause", "user:u1", now=NOW)          # already paused: nothing changes twice
    ent.set_status(db, ORG, SITE, rid, "resume", "user:u1", until=NOW + 20 * DAY, now=NOW)
    assert ent.has_feature(db, ORG, SITE, "wa_menu", NOW)
    with pytest.raises(ent.EntitlementError):
        ent.set_status(db, ORG, SITE, rid, "resume", "user:u1", now=NOW)         # only a paused row can resume
    ent.set_status(db, ORG, SITE, rid, "cancel", "user:u1", now=NOW)
    assert not ent.has_feature(db, ORG, SITE, "wa_menu", NOW)
    with pytest.raises(ent.EntitlementError):
        ent.set_status(db, ORG, SITE, rid, "cancel", "user:u1", now=NOW)
    assert [x["event"] for x in db.rows("site_events")] == [
        "site_addon_granted", "site_addon_pause", "site_addon_resume", "site_addon_cancel"]


def test_set_status_scopes_by_org_and_site_and_rejects_unknown_actions():
    db = _db()
    ent.grant(db, ORG, SITE, "user:u1", "tier", "capture", now=NOW)
    rid = db.rows("site_addons")[0]["id"]
    with pytest.raises(ent.EntitlementNotFound):
        ent.set_status(db, OTHER_ORG, SITE, rid, "pause", "user:u1", now=NOW)
    with pytest.raises(ent.EntitlementNotFound):
        ent.set_status(db, ORG, "site-2", rid, "pause", "user:u1", now=NOW)
    with pytest.raises(ent.EntitlementError):
        ent.set_status(db, ORG, SITE, rid, "delete", "user:u1", now=NOW)
    assert db.rows("site_addons")[0]["status"] == "active"


def test_a_cancelled_tier_can_be_replaced_by_a_new_one():
    db = _db()
    ent.grant(db, ORG, SITE, "user:u1", "tier", "capture", now=NOW)
    ent.set_status(db, ORG, SITE, db.rows("site_addons")[0]["id"], "cancel", "user:u1", now=NOW)
    ent.grant(db, ORG, SITE, "user:u1", "tier", "convert", now=NOW)
    live = [r for r in db.rows("site_addons") if r["status"] != "cancelled"]
    assert len(live) == 1 and live[0]["key"] == "convert" and len(db.rows("site_addons")) == 2


def test_registry_is_consistent():
    assert set(reg.TIER_KEYS) == {"capture", "convert", "grow"}
    for tier, feats in reg.DEFAULT_TIER_FEATURES.items():
        assert all(f in reg.FEATURES for f in feats), tier
    for k in reg.ADDON_KEYS:
        assert reg.FEATURES[k]["group"] == "addon"
    assert all(v["cap"] is None or v["cap"] in reg.CAPS for v in reg.FEATURES.values())
