"""
tests/unit/test_site_renewal_service.py
-----------------------------------------
SITE-4 part A — the renewal cycle (status sync, 30/14/7 builder reminders, <=5-day client contact, lapse
alert), the renewal order + link, the builder's "Renew now", the renewal job/payment hook, staff
"Mark renewed" and "Send renewal link", and the worker task. FakeDB stands in for Supabase; every outbound
message, the Paystack link and pricing are patched at their own module.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import funnel_messaging, funnel_service, paystack_storefront_service, pricing_service
from app.services import site_ops_service as ops
from app.services import site_order_service as orders
from app.services import site_renewal_service as rs
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
NOW = datetime(2026, 9, 30, 6, 30, tzinfo=timezone.utc)          # 07:30 WAT
TODAY = date(2026, 9, 30)
QUOTE = {
    "route": "standard", "kind": "renewal", "domain": "adaeze.com.ng", "tld": ".com.ng",
    "cost": {"domain": 5913, "hosting": 36765, "ai_messages": 0, "total": 42678},
    "price": {"domain": 8000, "hosting": 42000, "service_fee": 0, "renewal_adjustment": 0, "total": 50000},
    "gateway_fee": 800, "profit": 6500,
}


def in_days(n):
    return (TODAY + timedelta(days=n)).isoformat()


def _domain(days=30, **kw):
    base = {"id": "d-1", "org_id": ORG, "site_id": "site-1", "domain": "adaeze.com.ng", "route": "standard",
            "status": "active", "renews_on": in_days(days), "hosting_renews_on": in_days(days)}
    base.update(kw)
    return base


def _db(domains=None, **extra):
    tables = dict(
        site_domains=domains if domains is not None else [_domain()],
        sites=[{"id": "site-1", "org_id": ORG, "builder_id": "b-1", "status": "live", "deleted_at": None,
                "client_business_name": "Adaeze Styles",
                "legal_owner": {"full_name": "Adaeze O", "phone": "0803 111 2222", "email": "a@x.com"}}],
        site_builders=[{"id": "b-1", "org_id": ORG, "full_name": "Chidi", "business_name": "Chidi Web",
                        "phone_number": "2348030000001", "lead_id": "lead-1"}],
        site_orders=[], site_events=[], site_hosting_jobs=[], payment_links=[], tasks=[],
        whatsapp_numbers=[{"id": "n-1", "org_id": ORG, "wa_sales_mode": "site_builder"}],
        site_chats=[], organisations=[{"id": ORG, "subscription_status": "active"}],
    )
    tables.update(extra)
    return FakeDB(**tables)


@pytest.fixture
def env(monkeypatch):
    log = {"cta": [], "tpl": [], "notify": [], "builder_msgs": [], "links": 0, "ok": True}

    def cta(db, org, number, to, text, label, url, lead_id=None):
        log["cta"].append((to, text, label, url)); return log["ok"]

    def tpl(db, org, number, to, name, params, language="en", lead_id=None):
        log["tpl"].append((to, name, params)); return log["ok"]

    def link(**kw):
        log["links"] += 1
        return {"payment_link_id": f"pl-{log['links']}", "reference": f"ref-{log['links']}",
                "checkout_url": f"https://pay.test/{log['links']}"}

    monkeypatch.setattr(funnel_messaging, "send_cta_url", cta)
    monkeypatch.setattr(funnel_messaging, "send_template", tpl)
    monkeypatch.setattr(paystack_storefront_service, "generate_payment_link", link)
    monkeypatch.setattr(pricing_service, "get_settings", lambda db, org: {})
    monkeypatch.setattr(pricing_service, "quote", lambda *a, **k: QUOTE)
    monkeypatch.setattr(funnel_service, "notify_managers",
                        lambda db, org, title, body, t, r: log["notify"].append((title, body, t)))
    monkeypatch.setattr(orders, "_message_builder", lambda db, org, order, text: log["builder_msgs"].append(text))
    return log


def _run(db, now=NOW):
    return rs.run_cycle(db, now, lambda org: True)


def _payment_link_row(db):
    # get_or_create_renewal_link reuses the link stored in payment_links
    for o in db.rows("site_orders"):
        if o.get("payment_link_id"):
            db.tables["payment_links"].append({"id": o["payment_link_id"], "org_id": ORG,
                                               "checkout_url": f"https://pay.test/{o['payment_link_id'][3:]}"})


# ── pure helpers ────────────────────────────────────────────────────────────

def test_brackets_and_status():
    assert [rs.bracket_for(d) for d in (31, 30, 15, 14, 8, 7, 0, -1)] == [None, 30, 30, 14, 14, 7, 7, None]
    assert [rs.status_for(d) for d in (45, 31, 30, 0, -1)] == ["active", "active", "expiring", "expiring", "lapsed"]


def test_expiry_is_the_earlier_date():
    row = _domain(renews_on=in_days(40), hosting_renews_on=in_days(12))
    assert rs.days_left(row, TODAY) == 12


def test_lagos_day_rolls_at_midnight_wat():
    late_utc = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)      # 00:30 WAT next day
    assert rs.lagos_today(late_utc) == date(2026, 10, 1)


# ── the daily cycle ─────────────────────────────────────────────────────────

def test_far_from_expiry_does_nothing(env):
    db = _db([_domain(days=90)])
    r = _run(db)
    assert r["checked"] == 1 and r["reminders"] == 0 and env["cta"] == [] and env["tpl"] == []
    assert db.rows("site_orders") == []


def test_status_persisted_to_domain_and_site(env):
    db = _db([_domain(days=20)])
    r = _run(db)
    assert r["status_updates"] == 1
    assert db.rows("site_domains")[0]["status"] == "expiring"
    assert db.rows("sites")[0]["status"] == "renewal_due"


def test_30_day_reminder_creates_order_and_sends_template_outside_window(env):
    db = _db([_domain(days=30)])
    r = _run(db)
    assert r["reminders"] == 1 and r["needs_attention"] == 0
    (order,) = db.rows("site_orders")
    assert order["kind"] == "renewal" and order["approval_required"] is False
    assert order["status"] == "pending_payment" and order["amount"] == 50000
    to, name, params = env["tpl"][0]
    assert name == "site_renewal_reminder" and to == "2348030000001"
    assert params[1] == "adaeze.com.ng" and params[3] == "₦50,000" and params[4].startswith("https://pay.test/")
    assert any(e["event"] == "renewal_reminder_30" for e in db.rows("site_events"))


def test_reminder_uses_pay_button_inside_the_24h_window(env):
    db = _db([_domain(days=30)], site_chats=[{"org_id": ORG, "phone_number": "2348030000001",
                                              "last_inbound_at": (NOW - timedelta(hours=2)).isoformat()}])
    _run(db)
    assert len(env["cta"]) == 1 and env["cta"][0][2] == "Renew now" and env["tpl"] == []


def test_same_reminder_not_sent_twice(env):
    db = _db([_domain(days=30)])
    _run(db); _payment_link_row(db)
    r = _run(db)
    assert r["reminders"] == 0 and len(env["tpl"]) == 1


def test_next_bracket_reuses_the_open_order_and_link(env):
    db = _db([_domain(days=30)])
    _run(db); _payment_link_row(db)
    db.tables["site_domains"][0]["renews_on"] = db.tables["site_domains"][0]["hosting_renews_on"] = in_days(14)
    r = _run(db)
    assert r["reminders"] == 1 and len(db.rows("site_orders")) == 1 and env["links"] == 1
    assert env["tpl"][0][2][4] == env["tpl"][1][2][4]


def test_new_expiry_date_after_renewal_gets_fresh_reminders(env):
    db = _db([_domain(days=30)])
    _run(db)
    # a year later the same bracket fires again because the expiry date differs
    assert rs._already_logged(db, ORG, "site-1", "renewal_reminder_30", in_days(30)) is True
    assert rs._already_logged(db, ORG, "site-1", "renewal_reminder_30", in_days(395)) is False


def test_failed_reminder_alerts_managers_with_link(env):
    env["ok"] = False
    db = _db([_domain(days=30)])
    r = _run(db)
    assert r["needs_attention"] == 1
    title, body, t = env["notify"][0]
    assert "not delivered" in title and "https://pay.test/" in body and t == "site_renewal_attention"
    ev = [e for e in db.rows("site_events") if e["event"] == "renewal_reminder_30"][0]
    assert ev["detail"]["sent"] is False


def test_client_contacted_at_five_days(env):
    db = _db([_domain(days=5)])
    r = _run(db)
    assert r["client_contacts"] == 1 and r["reminders"] == 1        # 7-day bracket reminder too
    client = [t for t in env["tpl"] if t[1] == "site_renewal_client_notice"]
    assert len(client) == 1
    to, _, params = client[0]
    assert to.endswith("8031112222") and params[1] == "adaeze.com.ng" and params[3] == "Chidi Web"
    assert all("pay.test" not in str(p) for p in params)             # the client never gets the link
    assert db.rows("tasks") == []


def test_client_contact_not_repeated(env):
    db = _db([_domain(days=5)])
    _run(db); _payment_link_row(db)
    _run(db)
    assert len([t for t in env["tpl"] if t[1] == "site_renewal_client_notice"]) == 1


def test_client_contact_falls_back_to_task_and_alert(env):
    db = _db([_domain(days=4)])
    db.tables["sites"][0]["legal_owner"] = {"full_name": "Adaeze O"}          # no phone
    r = _run(db)
    assert r["needs_attention"] >= 1
    (task,) = db.rows("tasks")
    assert task["task_type"] == "renewal_client_contact" and "no client phone" in task["description"]
    assert any(n[2] == "site_renewal_attention" and "Contact the client" in n[0] for n in env["notify"])


def test_client_not_contacted_when_renewal_already_paid(env):
    db = _db([_domain(days=3)], site_orders=[{"id": "o-1", "org_id": ORG, "site_id": "site-1", "kind": "renewal",
                                              "status": "fulfilling", "domain": "adaeze.com.ng"}])
    r = _run(db)
    assert r["client_contacts"] == 0 and r["reminders"] == 0 and env["tpl"] == []


def test_lapse_alert_once(env):
    db = _db([_domain(days=-2)])
    r = _run(db)
    assert r["lapsed"] == 1
    assert db.rows("site_domains")[0]["status"] == "lapsed" and db.rows("sites")[0]["status"] == "lapsed"
    assert env["notify"][0][2] == "site_renewal_lapsed"
    assert _run(db)["lapsed"] == 0 and len(env["notify"]) == 1


def test_transferred_and_inactive_orgs_skipped(env):
    db = _db([_domain(days=3, status="transferred")])
    assert _run(db)["checked"] == 0
    db = _db([_domain(days=3)])
    r = rs.run_cycle(db, NOW, lambda org: False)
    assert r["checked"] == 0 and env["tpl"] == []


def test_one_bad_domain_does_not_stop_the_rest(env):
    good = _domain(days=20, id="d-2", domain="ok.com.ng", site_id="site-1")
    bad = _domain(days=20, id="d-3", domain="bad.com.ng", site_id="missing-site")
    db = _db([bad, good])
    r = _run(db)
    assert r["failed"] == 1 and r["checked"] == 2
    assert db.rows("site_domains")[1]["status"] == "expiring"


def test_builder_without_lead_is_flagged_not_crashed(env):
    db = _db([_domain(days=30)])
    db.tables["site_builders"][0]["lead_id"] = None
    r = _run(db)
    assert r["failed"] == 1 and env["tpl"] == []


# ── retries (a failed send must not burn the reminder) ──────────────────────

def test_failed_reminder_is_retried_next_day_and_stops_once_delivered(env):
    env["ok"] = False
    db = _db([_domain(days=30)])
    _run(db); _payment_link_row(db)
    assert len(env["tpl"]) == 1
    env["ok"] = True                                                    # the number/template got fixed
    r = _run(db)
    assert r["reminders"] == 1 and len(env["tpl"]) == 2
    assert _run(db)["reminders"] == 0 and len(env["tpl"]) == 2          # delivered -> done


def test_gives_up_after_three_failures_and_alerts_first_and_last_only(env):
    env["ok"] = False
    db = _db([_domain(days=30)])
    for _ in range(5):
        _run(db); _payment_link_row(db)
    assert len(env["tpl"]) == rs.MAX_SEND_ATTEMPTS
    alerts = [n for n in env["notify"] if "not delivered" in n[0]]
    assert len(alerts) == 2 and "will retry" in alerts[0][1] and "giving up" in alerts[1][1]


def test_failed_client_notice_retries_but_creates_one_task(env):
    env["ok"] = False
    db = _db([_domain(days=4)])
    for _ in range(3):
        _run(db); _payment_link_row(db)
    assert len(db.rows("tasks")) == 1
    env["ok"] = True
    _run(db)                                                            # tries used up -> no fourth attempt
    assert len([t for t in env["tpl"] if t[1] == "site_renewal_client_notice"]) == rs.MAX_SEND_ATTEMPTS

# ── builder "Renew now" ─────────────────────────────────────────────────────

def test_builder_can_renew_within_60_days(env):
    db = _db([_domain(days=45)])
    out = rs.builder_renewal_checkout(db, ORG, db.rows("site_builders")[0], "site-1", NOW)
    assert out["checkout_url"].startswith("https://pay.test/") and out["amount"] == 50000
    assert out["domain"] == "adaeze.com.ng"


def test_builder_cannot_renew_a_year_early(env):
    db = _db([_domain(days=200)])
    with pytest.raises(rs.RenewalBlocked):
        rs.builder_renewal_checkout(db, ORG, db.rows("site_builders")[0], "site-1", NOW)


def test_builder_can_renew_after_lapse(env):
    db = _db([_domain(days=-10, status="lapsed")])
    assert rs.builder_renewal_checkout(db, ORG, db.rows("site_builders")[0], "site-1", NOW)["checkout_url"]


def test_builder_cannot_renew_someone_elses_site(env):
    db = _db([_domain(days=10)])
    other = dict(db.rows("site_builders")[0], id="b-2")
    with pytest.raises(rs.RenewalNotFound):
        rs.builder_renewal_checkout(db, ORG, other, "site-1", NOW)


def test_builder_blocked_while_paid_renewal_in_progress(env):
    db = _db([_domain(days=10)], site_orders=[{"id": "o-1", "org_id": ORG, "site_id": "site-1", "kind": "renewal",
                                               "status": "fulfilling", "domain": "adaeze.com.ng"}])
    with pytest.raises(rs.RenewalBlocked):
        rs.builder_renewal_checkout(db, ORG, db.rows("site_builders")[0], "site-1", NOW)


def test_builder_view_fields():
    assert rs.builder_view(None, TODAY) == {"days_to_renewal": None, "renewal_status": None}
    assert rs.builder_view(_domain(days=12), TODAY) == {"days_to_renewal": 12, "renewal_status": "expiring"}


# ── payment → renewal job ───────────────────────────────────────────────────

def _paid_setup(env, status="pending_payment"):
    db = _db([_domain(days=10, status="expiring")])
    db.tables["site_orders"].append({
        "id": "o-1", "org_id": ORG, "site_id": "site-1", "builder_id": "b-1", "lead_id": "lead-1", "kind": "renewal",
        "route": "standard", "domain": "adaeze.com.ng", "amount": 50000, "status": status,
        "approval_required": False, "payment_reference": "ref-9"})
    return db


def test_payment_starts_renewal_job_without_approval(env):
    db = _paid_setup(env)
    assert orders.on_payment_confirmed(db, ORG, "ref-9", NOW) is True
    order = db.rows("site_orders")[0]
    assert order["status"] == "fulfilling"
    (job,) = db.rows("site_hosting_jobs")
    assert [c["key"] for c in job["checklist"]] == ["renew_domain", "renew_hosting", "confirm_site"]
    paid = datetime.fromisoformat(order["sla_due_at"]) - timedelta(hours=24)
    assert paid == NOW                                                     # order keeps paid+24h (KPI maths)
    assert datetime.fromisoformat(job["sla_due_at"]) - NOW == timedelta(hours=72)
    (task,) = db.rows("tasks")
    assert task["title"] == "Renew hosting: adaeze.com.ng"
    assert env["builder_msgs"] == ["Payment received. Your renewal of adaeze.com.ng is being processed."]
    assert env["notify"][0][0].startswith("Renewal paid")


def test_payment_on_expired_order_alerts_managers_and_changes_nothing(env):
    db = _paid_setup(env, status="expired")
    assert orders.on_payment_confirmed(db, ORG, "ref-9", NOW) is True
    assert db.rows("site_orders")[0]["status"] == "expired" and db.rows("site_hosting_jobs") == []
    assert env["notify"][0][2] == "site_order_late_payment"


def test_initial_order_payment_message_unchanged(env):
    db = _paid_setup(env)
    db.tables["site_orders"][0]["kind"] = "initial"
    orders.on_payment_confirmed(db, ORG, "ref-9", NOW)
    assert env["builder_msgs"][0].startswith("Payment received. Your site is being deployed")
    assert db.rows("tasks")[0]["title"].startswith("Deploy hosting")


# ── Mark renewed ────────────────────────────────────────────────────────────

def _fulfilling(env, days=10, ticks=("renew_domain", "renew_hosting")):
    db = _paid_setup(env)
    db.tables["site_domains"][0].update(renews_on=in_days(days), hosting_renews_on=in_days(days + 3))
    orders.on_payment_confirmed(db, ORG, "ref-9", NOW)
    job = db.rows("site_hosting_jobs")[0]
    for item in job["checklist"]:
        item["done"] = item["key"] in ticks
    return db, job


def test_mark_renewed_moves_dates_a_year_from_the_later_of_today_or_current(env):
    db, job = _fulfilling(env, days=10)
    out = ops.mark_renewed(db, ORG, job["id"], "u-1", NOW)
    d = db.rows("site_domains")[0]
    assert d["renews_on"] == in_days(10 + 365) and d["hosting_renews_on"] == in_days(13 + 365)
    assert d["status"] == "active" and d["registrar_cost_renewal"] == 5913 and d["hosting_cost_renewal"] == 36765
    assert db.rows("site_orders")[0]["status"] == "live"
    assert db.rows("site_hosting_jobs")[0]["status"] == "done"
    assert db.rows("sites")[0]["status"] == "live"
    assert db.rows("tasks")[0]["status"] == "completed"
    assert out["renews_on"] == in_days(10 + 365)
    assert env["builder_msgs"][-1] == f"adaeze.com.ng is renewed until {ops._add_year(TODAY + timedelta(days=10)).day} " \
                                      f"{ops._add_year(TODAY + timedelta(days=10)).strftime('%b %Y')}."
    assert any(e["event"] == "renewal_completed" for e in db.rows("site_events"))


def test_mark_renewed_after_lapse_counts_from_today(env):
    db, job = _fulfilling(env, days=-20)
    ops.mark_renewed(db, ORG, job["id"], "u-1", NOW)
    assert db.rows("site_domains")[0]["renews_on"] == ops._add_year(TODAY).isoformat()
    assert db.rows("sites")[0]["status"] == "live"


def test_mark_renewed_needs_both_steps(env):
    db, job = _fulfilling(env, ticks=("renew_domain",))
    with pytest.raises(ops.ValidationFailed):
        ops.mark_renewed(db, ORG, job["id"], "u-1", NOW)
    assert db.rows("site_orders")[0]["status"] == "fulfilling"


def test_mark_renewed_rejects_initial_jobs(env):
    db, job = _fulfilling(env)
    db.tables["site_orders"][0]["kind"] = "initial"
    with pytest.raises(ops.Conflict):
        ops.mark_renewed(db, ORG, job["id"], "u-1", NOW)


def test_mark_renewed_expires_other_open_renewal_orders(env):
    db, job = _fulfilling(env)
    db.tables["site_orders"].append({"id": "o-2", "org_id": ORG, "site_id": "site-1", "kind": "renewal",
                                     "status": "pending_payment", "domain": "adaeze.com.ng"})
    ops.mark_renewed(db, ORG, job["id"], "u-1", NOW)
    assert [o["status"] for o in db.rows("site_orders")] == ["live", "expired"]


def test_mark_renewed_twice_conflicts(env):
    db, job = _fulfilling(env)
    ops.mark_renewed(db, ORG, job["id"], "u-1", NOW)
    with pytest.raises(ops.Conflict):
        ops.mark_renewed(db, ORG, job["id"], "u-1", NOW)


def test_jobs_list_exposes_order_kind(env):
    db, job = _fulfilling(env)
    db.tables["site_orders"][0]["kind"] = "renewal"
    (row,) = ops.list_hosting_jobs(db, ORG, now=NOW)
    assert row["order_kind"] == "renewal"


# ── staff "Send renewal link" ───────────────────────────────────────────────

def test_send_renewal_link_creates_and_messages(env):
    db = _db([_domain(days=20)])
    out = ops.send_renewal_link(db, ORG, "d-1", "u-1")
    assert out["sent"] is True and out["checkout_url"].startswith("https://pay.test/") and out["reused"] is False
    assert any(e["event"] == "renewal_link_sent" for e in db.rows("site_events"))


def test_send_renewal_link_transferred_domain_conflicts(env):
    db = _db([_domain(days=20, status="transferred")])
    with pytest.raises(ops.Conflict):
        ops.send_renewal_link(db, ORG, "d-1", "u-1")


def test_send_renewal_link_unknown_domain(env):
    with pytest.raises(ops.NotFound):
        ops.send_renewal_link(_db(), ORG, "nope", "u-1")


# ── the worker task ─────────────────────────────────────────────────────────

def test_worker_task_runs_cycle_and_logs(env, monkeypatch):
    from app.workers import site_worker as sw
    db = _db([_domain(days=20)])
    logged = []
    monkeypatch.setattr(sw, "get_supabase", lambda: db)
    monkeypatch.setattr(sw, "write_worker_log", lambda db, **kw: logged.append(kw))
    r = sw.run_renewal_cycle()
    assert r["checked"] == 1 and r["failed"] == 0
    assert logged[0]["worker_name"] == "site_worker.renewal_cycle" and logged[0]["status"] == "passed"


def test_beat_entry_registered():
    from app.workers.celery_app import celery_app
    entry = celery_app.conf.beat_schedule["site-renewal-cycle"]
    assert entry["task"] == "app.workers.site_worker.run_renewal_cycle"
