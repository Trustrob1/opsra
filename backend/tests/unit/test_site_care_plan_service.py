"""
tests/unit/test_site_care_plan_service.py
------------------------------------------
SITE-4 part B — care plans, edit allowance (free 5 -> plan 10/month -> purchased packs), the payment hook,
the daily care cycle (active -> grace -> ended, one reminder per period) and the 90-day image clean-up.
FakeDB stands in for Supabase; Paystack, WhatsApp and manager alerts are patched at their own module.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import funnel_messaging, funnel_service, paystack_storefront_service
from app.services import site_care_plan_service as cp
from app.services import site_order_service as orders
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 1)


class FakeStorage:
    def __init__(self, fail=False):
        self.removed, self.fail = [], fail

    def from_(self, _bucket):
        return self

    def remove(self, paths):
        if self.fail:
            raise RuntimeError("boom")
        self.removed.extend(paths)


def _site(status="live", sid="site-1"):
    return {"id": sid, "org_id": ORG, "builder_id": "b-1", "status": status, "deleted_at": None,
            "client_business_name": "Adaeze Styles", "updated_at": NOW.isoformat()}


def _db(sites=None, care=None, **extra):
    tables = dict(
        sites=sites if sites is not None else [_site()],
        site_care_plans=care or [], site_orders=[], site_events=[], site_domains=[], site_assets=[], payment_links=[],
        site_builders=[{"id": "b-1", "org_id": ORG, "full_name": "Chidi", "business_name": "Chidi Web",
                        "phone_number": "2348030000001", "lead_id": "lead-1"}],
        whatsapp_numbers=[{"id": "n-1", "org_id": ORG, "wa_sales_mode": "site_builder"}], site_chats=[],
        site_builder_settings=[{"org_id": ORG, "free_revisions": 5, "pricing": {}}],
        organisations=[{"id": ORG, "subscription_status": "active"}],
    )
    tables.update(extra)
    db = FakeDB(**tables)
    db.storage = FakeStorage()
    return db


def _care(**kw):
    base = {"id": "c-1", "org_id": ORG, "site_id": "site-1", "free_edits_used": 0, "plan_status": None,
            "period_start": None, "period_end": None, "plan_edits_used": 0, "extra_edits": 0,
            "cancel_at_period_end": False, "last_edit_counted_at": None}
    base.update(kw)
    return base


def _active(days_left=20, **kw):
    end = NOW + timedelta(days=days_left)
    return _care(plan_status="active", period_start=(end - timedelta(days=30)).isoformat(), period_end=end.isoformat(), **kw)


@pytest.fixture
def env(monkeypatch):
    log = {"cta": [], "tpl": [], "notify": [], "msgs": [], "links": 0, "ok": True}
    monkeypatch.setattr(funnel_messaging, "send_cta_url",
                        lambda db, org, number, to, text, label, url, lead_id=None: log["cta"].append((to, text, label, url)) or log["ok"])
    monkeypatch.setattr(funnel_messaging, "send_template",
                        lambda db, org, number, to, name, params, language="en", lead_id=None: log["tpl"].append((name, params)) or log["ok"])

    def link(**kw):
        log["links"] += 1
        return {"payment_link_id": f"pl-{log['links']}", "reference": f"ref-{log['links']}", "checkout_url": f"https://pay.test/{log['links']}"}

    monkeypatch.setattr(paystack_storefront_service, "generate_payment_link", link)
    monkeypatch.setattr(funnel_service, "notify_managers", lambda db, org, t, b, ty, r: log["notify"].append((t, b, ty)))
    monkeypatch.setattr(orders, "_message_builder", lambda db, org, order, text: log["msgs"].append(text))
    return log


def _consume(db, at=NOW, site=None):
    return cp.consume_edit(db, ORG, site or db.rows("sites")[0], at)


# ── config ──────────────────────────────────────────────────────────────────

def test_defaults_and_overrides():
    assert cp.get_config({}) == {"price_ngn": 5000, "edits_per_month": 10, "pack_price_ngn": 1500, "pack_edits": 5,
                                 "grace_days": 5, "reminder_days": 5, "free_edits": 5}
    cfg = cp.get_config({"free_revisions": 3, "pricing": {"care_plan": {"price_ngn": 8000, "edits_per_month": "12", "grace_days": "bad"}}})
    assert cfg["price_ngn"] == 8000 and cfg["edits_per_month"] == 12 and cfg["grace_days"] == 5 and cfg["free_edits"] == 3


# ── counting edits ──────────────────────────────────────────────────────────

def test_preview_sites_edit_freely_and_create_no_row():
    db = _db([_site("preview_ready")])
    for i in range(20):
        assert _consume(db, NOW + timedelta(hours=i))["counted"] is False
    assert db.rows("site_care_plans") == []


def test_free_edits_then_block_with_offer():
    db = _db()
    for i in range(5):
        assert _consume(db, NOW + timedelta(hours=i))["source"] == "free"
    with pytest.raises(cp.EditLimitReached) as exc:
        _consume(db, NOW + timedelta(hours=10))
    assert exc.value.offer["plan_price"] == 5000 and exc.value.offer["pack_price"] == 1500 and exc.value.offer["pack_edits"] == 5
    assert db.rows("site_care_plans")[0]["free_edits_used"] == 5


def test_saves_in_one_session_count_once():
    db = _db()
    assert _consume(db, NOW)["counted"] is True
    assert _consume(db, NOW + timedelta(minutes=10)) == {"counted": False, "source": "session"}
    assert _consume(db, NOW + timedelta(minutes=40))["counted"] is True
    assert db.rows("site_care_plans")[0]["free_edits_used"] == 2


def test_open_session_may_finish_even_when_out_of_edits():
    db = _db(care=[_care(free_edits_used=5, last_edit_counted_at=(NOW - timedelta(minutes=5)).isoformat())])
    assert _consume(db)["source"] == "session"


def test_order_free_then_plan_then_pack():
    db = _db(care=[_active(free_edits_used=4, plan_edits_used=9, extra_edits=2)])
    sources = [_consume(db, NOW + timedelta(hours=i))["source"] for i in range(4)]
    assert sources == ["free", "plan", "pack", "pack"]
    with pytest.raises(cp.EditLimitReached):
        _consume(db, NOW + timedelta(hours=9))
    row = db.rows("site_care_plans")[0]
    assert (row["free_edits_used"], row["plan_edits_used"], row["extra_edits"]) == (5, 10, 0)


def test_grace_and_ended_plans_give_no_monthly_edits():
    grace = _care(plan_status="active", period_end=(NOW - timedelta(days=2)).isoformat(), free_edits_used=5)
    assert cp.effective_status(grace, cp.get_config({}), NOW) == "grace"
    with pytest.raises(cp.EditLimitReached):
        _consume(_db(care=[grace]))
    ended = _care(plan_status="active", period_end=(NOW - timedelta(days=9)).isoformat(), free_edits_used=5)
    assert cp.effective_status(ended, cp.get_config({}), NOW) == "ended"


def test_cancelled_plan_ends_at_period_end_without_grace():
    row = _care(plan_status="active", period_end=(NOW - timedelta(days=1)).isoformat(), cancel_at_period_end=True)
    assert cp.effective_status(row, cp.get_config({}), NOW) == "ended"


def test_concurrent_save_is_retried(monkeypatch):
    db = _db(care=[_care(free_edits_used=1)])
    real = db.table
    state = {"bumped": False}

    def table(name):
        q = real(name)
        if name == "site_care_plans" and not state["bumped"]:
            orig = q.update

            def upd(payload):
                if not state["bumped"] and "free_edits_used" in payload:
                    state["bumped"] = True
                    db.tables["site_care_plans"][0]["free_edits_used"] = 2       # someone else counted first
                return orig(payload)
            q.update = upd
        return q
    monkeypatch.setattr(db, "table", table)
    assert _consume(db)["counted"] is True
    assert db.rows("site_care_plans")[0]["free_edits_used"] == 3


def test_allowance_view_numbers():
    v = cp.allowance_view(_active(free_edits_used=2, plan_edits_used=3, extra_edits=5), cp.get_config({}), NOW)
    assert (v["free_edits_left"], v["plan_edits_left"], v["extra_edits"], v["edits_left"]) == (3, 7, 5, 15)
    assert v["plan_status"] == "active" and v["plan_price"] == 5000
    assert cp.allowance_view(None, cp.get_config({}), NOW)["edits_left"] == 5


# ── buying ──────────────────────────────────────────────────────────────────

def test_checkout_creates_plan_and_pack_orders_and_reuses_open_links(env):
    db = _db()
    builder = db.rows("site_builders")[0]
    plan = cp.create_checkout(db, ORG, builder, "site-1", "plan")
    assert plan["amount"] == 5000 and plan["kind"] == "care_plan" and plan["reused"] is False
    (o,) = db.rows("site_orders")
    assert o["kind"] == "care_plan" and o["approval_required"] is False and o["status"] == "pending_payment"
    db.tables["payment_links"].append({"id": o["payment_link_id"], "org_id": ORG, "checkout_url": plan["checkout_url"]})
    assert cp.create_checkout(db, ORG, builder, "site-1", "plan")["reused"] is True
    pack = cp.create_checkout(db, ORG, builder, "site-1", "pack")
    assert pack["amount"] == 1500 and pack["kind"] == "edit_pack" and len(db.rows("site_orders")) == 2
    assert db.rows("site_orders")[1]["quote"]["edits"] == 5


def test_checkout_rules(env):
    db = _db([_site("preview_ready")])
    builder = db.rows("site_builders")[0]
    with pytest.raises(cp.CarePlanBlocked):
        cp.create_checkout(db, ORG, builder, "site-1", "plan")                 # not live yet
    db = _db()
    with pytest.raises(cp.CarePlanNotFound):
        cp.create_checkout(db, ORG, dict(db.rows("site_builders")[0], id="b-2"), "site-1", "plan")   # someone else's site
    with pytest.raises(cp.CarePlanBlocked):
        cp.create_checkout(db, ORG, dict(db.rows("site_builders")[0], lead_id=None), "site-1", "plan")
    with pytest.raises(cp.CarePlanBlocked):
        cp.create_checkout(db, ORG, db.rows("site_builders")[0], "site-1", "gold")


# ── payment hook ────────────────────────────────────────────────────────────

def _pay(db, env, what="plan", ref="ref-9", status="pending_payment"):
    db.tables["site_orders"].append({
        "id": "o-1", "org_id": ORG, "site_id": "site-1", "builder_id": "b-1", "lead_id": "lead-1",
        "kind": "care_plan" if what == "plan" else "edit_pack", "route": "standard", "amount": 5000 if what == "plan" else 1500,
        "quote": {"edits": 10 if what == "plan" else 5}, "status": status, "approval_required": False, "payment_reference": ref})
    return orders.on_payment_confirmed(db, ORG, ref, NOW)


def test_paying_a_plan_activates_it_without_a_hosting_job(env):
    db = _db(care=[_care(free_edits_used=5, plan_edits_used=7)])
    assert _pay(db, env, "plan") is True
    order, row = db.rows("site_orders")[0], db.rows("site_care_plans")[0]
    assert order["status"] == "live" and "site_hosting_jobs" not in db.tables         # nothing to fulfil, no hosting job
    assert row["plan_status"] == "active" and row["plan_edits_used"] == 0
    assert datetime.fromisoformat(row["period_end"]) - datetime.fromisoformat(row["period_start"]) == timedelta(days=30)
    assert datetime.fromisoformat(order["sla_due_at"]) - NOW == timedelta(hours=24)         # KPI paid-time maths
    assert "Care plan active for Adaeze Styles" in env["msgs"][0] and "10 edits" in env["msgs"][0]
    assert env["notify"][0][0] == "Care plan paid"
    _consume(db, NOW + timedelta(hours=1))                                                    # edits work again
    assert db.rows("site_care_plans")[0]["plan_edits_used"] == 1


def test_paying_early_extends_from_the_old_end_date(env):
    db = _db(care=[_active(days_left=3, plan_edits_used=8)])
    old_end = datetime.fromisoformat(db.rows("site_care_plans")[0]["period_end"])
    _pay(db, env, "plan")
    row = db.rows("site_care_plans")[0]
    assert datetime.fromisoformat(row["period_start"]) == old_end
    assert datetime.fromisoformat(row["period_end"]) == old_end + timedelta(days=30)
    assert row["plan_edits_used"] == 0


def test_paying_after_it_ended_starts_today_and_clears_the_cancel_flag(env):
    db = _db(care=[_care(plan_status="ended", period_end=(NOW - timedelta(days=40)).isoformat(), cancel_at_period_end=True)])
    _pay(db, env, "plan")
    row = db.rows("site_care_plans")[0]
    assert datetime.fromisoformat(row["period_start"]) == NOW and row["cancel_at_period_end"] is False


def test_paying_a_pack_adds_edits_that_do_not_expire(env):
    db = _db(care=[_care(free_edits_used=5, extra_edits=2)])
    _pay(db, env, "pack")
    assert db.rows("site_care_plans")[0]["extra_edits"] == 7 and db.rows("site_care_plans")[0]["plan_status"] is None
    assert env["msgs"][0].startswith("5 extra edits added") and env["notify"][0][0] == "Extra edits paid"


def test_care_payment_is_idempotent_and_late_payment_alerts(env):
    db = _db()
    _pay(db, env, "pack")
    assert orders.on_payment_confirmed(db, ORG, "ref-9", NOW) is True
    assert db.rows("site_care_plans")[0]["extra_edits"] == 5
    db2 = _db()
    _pay(db2, env, "pack", status="expired")
    assert db2.rows("site_care_plans") == [] and env["notify"][-1][2] == "site_order_late_payment"


# ── cancel ──────────────────────────────────────────────────────────────────

def test_cancel_and_withdraw(env):
    db = _db(care=[_active()])
    builder = db.rows("site_builders")[0]
    assert cp.set_cancel(db, ORG, builder, "site-1", True, NOW)["cancel_at_period_end"] is True
    assert cp.set_cancel(db, ORG, builder, "site-1", False, NOW)["cancel_at_period_end"] is False
    with pytest.raises(cp.CarePlanBlocked):
        cp.set_cancel(_db(), ORG, builder, "site-1", True, NOW)                 # no plan


# ── staff link ──────────────────────────────────────────────────────────────

def test_staff_plan_link_uses_template_outside_the_window(env):
    db = _db()
    out = cp.send_care_link(db, ORG, "site-1", "plan", NOW)
    assert out["sent"] is True and out["kind"] == "care_plan"
    name, params = env["tpl"][0]
    assert name == "site_care_plan_reminder" and params[1] == "Adaeze Styles" and params[2] == "₦5,000" and params[3].startswith("https://pay.test/")


def test_staff_pack_link_only_sends_inside_the_window_but_always_returns_the_link(env):
    db = _db()
    out = cp.send_care_link(db, ORG, "site-1", "pack", NOW)
    assert out["sent"] is False and out["checkout_url"].startswith("https://pay.test/") and env["tpl"] == []
    db.tables["site_chats"].append({"org_id": ORG, "phone_number": "2348030000001", "last_inbound_at": (NOW - timedelta(hours=1)).isoformat()})
    assert cp.send_care_link(db, ORG, "site-1", "pack", NOW)["sent"] is True and env["cta"][0][2] == "Buy extra edits"


# ── the daily care cycle ────────────────────────────────────────────────────

def _cycle(db, now=NOW, active=lambda o: True):
    return cp.run_cycle(db, now, active)


def test_no_reminder_until_five_days_before_the_end(env):
    db = _db(care=[_active(days_left=12)])
    r = _cycle(db)
    assert r["checked"] == 1 and r["reminders"] == 0 and env["tpl"] == [] and db.rows("site_orders") == []


def test_reminder_once_per_period_with_a_payment_link(env):
    db = _db(care=[_active(days_left=4)])
    r = _cycle(db)
    assert r["reminders"] == 1 and env["tpl"][0][0] == "site_care_plan_reminder"
    (o,) = db.rows("site_orders")
    assert o["kind"] == "care_plan" and o["amount"] == 5000
    db.tables["payment_links"].append({"id": o["payment_link_id"], "org_id": ORG, "checkout_url": "https://pay.test/1"})
    assert _cycle(db)["reminders"] == 0 and len(env["tpl"]) == 1


def test_failed_reminder_retries_then_gives_up(env):
    env["ok"] = False
    db = _db(care=[_active(days_left=4)])
    for _ in range(5):
        _cycle(db)
        for o in db.rows("site_orders"):
            if o.get("payment_link_id") and not [l for l in db.rows("payment_links") if l["id"] == o["payment_link_id"]]:
                db.tables["payment_links"].append({"id": o["payment_link_id"], "org_id": ORG, "checkout_url": "https://pay.test/x"})
    assert len(env["tpl"]) == 3
    alerts = [n for n in env["notify"] if "not delivered" in n[0]]
    assert len(alerts) == 2 and "https://pay.test/" in alerts[0][1]


def test_cancelled_plans_get_no_reminder(env):
    db = _db(care=[_active(days_left=2, cancel_at_period_end=True)])
    assert _cycle(db)["reminders"] == 0 and env["tpl"] == []


def test_plan_moves_to_grace_then_ended(env):
    db = _db(care=[_active(days_left=-2)])
    r = _cycle(db)
    assert db.rows("site_care_plans")[0]["plan_status"] == "grace" and r["status_updates"] == 1 and r["ended"] == 0
    later = NOW + timedelta(days=6)
    r = _cycle(db, later)
    assert db.rows("site_care_plans")[0]["plan_status"] == "ended" and r["ended"] == 1
    assert any(n[2] == "site_care_plan_ended" for n in env["notify"])
    assert _cycle(db, later)["checked"] == 0                                    # ended plans leave the sweep


def test_inactive_org_is_skipped_and_one_bad_plan_does_not_stop_the_rest(env):
    db = _db(care=[_active(days_left=4)])
    assert _cycle(db, active=lambda o: False)["checked"] == 0
    broken = _active(days_left=4, id="c-9", site_id="ghost")
    db = _db(care=[broken, _active(days_left=-2, id="c-2", site_id="site-2")], sites=[_site(), _site(sid="site-2")])
    r = _cycle(db)
    assert r["failed"] == 1 and db.rows("site_care_plans")[1]["plan_status"] == "grace"


# ── 90-day clean-up ─────────────────────────────────────────────────────────

def _assets(db, site_id="site-1", n=2):
    for i in range(n):
        db.tables["site_assets"].append({"id": f"a-{site_id}-{i}", "site_id": site_id, "storage_path": f"{site_id}/img{i}.jpg"})


def _domain(days, site_id="site-1", **kw):
    d = {"id": f"d-{site_id}", "org_id": ORG, "site_id": site_id, "domain": "x.com.ng", "status": "lapsed",
         "renews_on": (TODAY + timedelta(days=days)).isoformat(), "hosting_renews_on": (TODAY + timedelta(days=days)).isoformat()}
    d.update(kw)
    return d


def _clean(db, now=NOW):
    return cp.run_cleanup(db, now, lambda o: True)


def test_images_deleted_90_days_after_the_domain_lapsed(env):
    db = _db(site_domains=[_domain(-90)])
    _assets(db)
    r = _clean(db)
    assert r["cleaned_sites"] == 1 and r["files_removed"] == 2
    assert db.storage.removed == ["site-1/img0.jpg", "site-1/img1.jpg"] and db.rows("site_assets") == []
    assert db.rows("sites")[0]["client_business_name"] == "Adaeze Styles"                 # the site record stays
    assert [e["event"] for e in db.rows("site_events")] == ["assets_cleaned"]
    assert _clean(db)["cleaned_sites"] == 0


def test_nothing_deleted_before_90_days_or_for_current_domains(env):
    db = _db(site_domains=[_domain(-60)])
    _assets(db)
    assert _clean(db)["cleaned_sites"] == 0 and len(db.rows("site_assets")) == 2
    db = _db(site_domains=[_domain(30, status="active")])
    _assets(db)
    assert _clean(db)["checked"] == 0


def test_a_site_with_any_current_domain_is_kept(env):
    db = _db(site_domains=[_domain(-200), _domain(40, status="active", id="d-2")])
    _assets(db)
    assert _clean(db)["checked"] == 0


def test_manager_warned_once_seven_days_before(env):
    db = _db(site_domains=[_domain(-84)])                     # due in 6 days
    _assets(db)
    assert _clean(db)["warned"] == 1 and env["notify"][0][2] == "site_cleanup_warning" and len(db.rows("site_assets")) == 2
    assert _clean(db)["warned"] == 0 and len(env["notify"]) == 1


def test_cancelled_sites_are_cleaned_90_days_after_cancellation(env):
    old = (NOW - timedelta(days=91)).isoformat()
    db = _db([dict(_site("cancelled"), updated_at=old)])
    _assets(db)
    assert _clean(db)["cleaned_sites"] == 1
    db = _db([_site("cancelled")])
    _assets(db)
    assert _clean(db)["cleaned_sites"] == 0


def test_storage_failure_keeps_the_rows_for_tomorrow(env):
    db = _db(site_domains=[_domain(-100)])
    db.storage = FakeStorage(fail=True)
    _assets(db)
    r = _clean(db)
    assert r["failed"] == 1 and r["cleaned_sites"] == 0 and len(db.rows("site_assets")) == 2
    db.storage = FakeStorage()
    assert _clean(db)["cleaned_sites"] == 1


# ── workers + beat ──────────────────────────────────────────────────────────

def test_worker_tasks_and_beat_entries(env, monkeypatch):
    from app.workers import site_worker as sw
    from app.workers.celery_app import celery_app
    db = _db(care=[_active(days_left=-2)], site_domains=[_domain(-100)])
    _assets(db)
    logged = []
    monkeypatch.setattr(sw, "get_supabase", lambda: db)
    monkeypatch.setattr(sw, "write_worker_log", lambda db, **kw: logged.append(kw))
    assert sw.run_care_cycle()["status_updates"] == 1
    assert sw.run_asset_cleanup()["cleaned_sites"] == 1
    assert [l["worker_name"] for l in logged] == ["site_worker.care_cycle", "site_worker.asset_cleanup"]
    sched = celery_app.conf.beat_schedule
    assert sched["site-care-cycle"]["task"].endswith("run_care_cycle") and sched["site-asset-cleanup"]["task"].endswith("run_asset_cleanup")
