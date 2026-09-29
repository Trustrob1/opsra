"""
tests/unit/test_site_ops_service.py
--------------------------------------
SITE-3 part 3 — site_ops_service (the staff Orders / Hosting queue / Domains actions).

Uses tests.funnel_fake_db.FakeDB (an in-memory Supabase stand-in) so whole
flows — approve → hosting job → mark live → domain register — run against real
state instead of long MagicMock chains (T2). Cross-service side effects
(WhatsApp to the builder, manager push, CRM lead conversion, registry lookups)
are monkeypatched at their OWN module (Pattern 63 — site_ops_service imports
them lazily inside its functions).
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.services import domain_check_service as dcs
from app.services import funnel_service, lead_service, pricing_service
from app.services import site_ops_service as ops
from app.services import site_order_service
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
OTHER_ORG = "org-2"
USER = "user-1"

QUOTE = {
    "route": "standard", "kind": "initial", "domain": "adaezastyles.com.ng", "tld": ".com.ng",
    "cost": {"domain": 5913, "hosting": 36765, "ai_messages": 400, "total": 43078},
    "price": {"domain": 11000, "hosting": 50000, "service_fee": 18500, "renewal_adjustment": 0, "total": 79500},
    "gateway_fee": 1293, "profit": 35130, "suggested_client_price": 150000, "live_within_hours": 24,
}
SETTINGS = {
    "org_id": ORG, "enabled": True, "approval_required": True, "approval_orders_remaining": 30,
    "approval_window_start": "08:00", "approval_window_end": "23:00", "approval_timezone": "Africa/Lagos",
    "express_enabled": False,
    "pricing": {"routes": {"standard": {"domains": {".com.ng": {}, ".ng": {}, ".com": {}}}}},
}

# 10:00 WAT (inside the approval window) and 02:00 WAT (outside), as UTC
INSIDE = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)
OUTSIDE = datetime(2026, 9, 29, 1, 0, tzinfo=timezone.utc)


def wat(hour, minute):
    """A UTC datetime for the given WAT wall-clock time (WAT = UTC+1, no DST)."""
    return datetime(2026, 9, 29, hour, minute, tzinfo=timezone(timedelta(hours=1))).astimezone(timezone.utc)


def _order(**kw):
    base = {
        "id": "ord-1", "org_id": ORG, "site_id": "site-1", "builder_id": "b-1", "lead_id": "lead-1",
        "kind": "initial", "route": "standard", "domain": "adaezastyles.com.ng", "backup_domain": "adaezastyles.ng",
        "quote": QUOTE, "amount": 79500, "expected_profit": 35130, "payment_reference": "ref-1",
        "status": "awaiting_approval", "approval_required": True, "approved_at": None, "hosting_job_id": None,
        "sla_due_at": (INSIDE + timedelta(hours=24)).isoformat(), "created_at": INSIDE.isoformat(), "refund_amount": None,
    }
    base.update(kw)
    return base


def _job(**kw):
    base = {
        "id": "job-1", "org_id": ORG, "order_id": "ord-1", "site_id": "site-1", "status": "queued", "assigned_to": None,
        "checklist": [dict(k) for k in site_order_service._HOSTING_CHECKLIST], "domain_used": None,
        "sla_due_at": (INSIDE + timedelta(hours=24)).isoformat(),
    }
    base.update(kw)
    return base


def _db(**tables):
    tables.setdefault("site_builder_settings", [dict(SETTINGS)])
    tables.setdefault("site_builders", [{"id": "b-1", "org_id": ORG, "lead_id": "lead-1", "approved_orders_count": 0,
                                         "full_name": "Chioma", "business_name": "Adaeze Styles", "phone_number": "+2348030000000"}])
    tables.setdefault("sites", [{"id": "site-1", "org_id": ORG, "builder_id": "b-1", "client_business_name": "Adaeze Styles",
                                 "slug": "adaeze-styles-abc123", "status": "hosting_checkout", "live_url": None}])
    return FakeDB(**tables)


@pytest.fixture
def spy(monkeypatch):
    """Records builder messages, manager notifications and CRM conversions."""
    s = {"messages": [], "notified": [], "converted": []}
    monkeypatch.setattr(site_order_service, "_message_builder", lambda db, org_id, order, text: s["messages"].append(text))
    monkeypatch.setattr(funnel_service, "notify_managers",
                        lambda db, org_id, title, body, t, lead: s["notified"].append((title, t)))
    monkeypatch.setattr(lead_service, "convert_lead",
                        lambda db, org_id, lead_id, user_id: s["converted"].append((lead_id, user_id)) or {})
    return s


def _avail(monkeypatch, mapping):
    """mapping: domain -> True/False/None; anything else is unavailable."""
    monkeypatch.setattr(dcs, "check_availability_fresh",
                        lambda db, org_id, domain: (domain.lower(), mapping.get(domain.lower(), False)))


# ---------------------------------------------------------------------------
# Approval window — spec §19 (22:59, 23:01, 07:59, 08:00 WAT)
# ---------------------------------------------------------------------------

class TestApprovalWindow:
    @pytest.mark.parametrize("h,m,expected", [
        (22, 59, True), (23, 0, False), (23, 1, False), (7, 59, False), (8, 0, True), (12, 30, True), (0, 0, False),
    ])
    def test_default_window(self, h, m, expected):
        assert ops.in_approval_window(SETTINGS, wat(h, m)) is expected

    def test_window_wrapping_midnight(self):
        s = {**SETTINGS, "approval_window_start": "22:00", "approval_window_end": "06:00"}
        assert ops.in_approval_window(s, wat(23, 0)) is True
        assert ops.in_approval_window(s, wat(3, 0)) is True
        assert ops.in_approval_window(s, wat(12, 0)) is False

    def test_time_with_seconds_and_missing_values(self):
        s = {**SETTINGS, "approval_window_start": "08:00:00", "approval_window_end": None}
        assert ops.in_approval_window(s, wat(9, 0)) is True
        assert ops.in_approval_window(s, wat(23, 30)) is False  # falls back to 23:00

    def test_approval_info_shape(self):
        info = ops.approval_info(SETTINGS, INSIDE)
        assert info == {"required": True, "orders_remaining": 30, "window_start": "08:00", "window_end": "23:00",
                        "timezone": "Africa/Lagos", "in_window": True}


# ---------------------------------------------------------------------------
# Refund maths — L16
# ---------------------------------------------------------------------------

def test_refund_excludes_service_fee():
    assert ops.refund_amount_for(_order()) == 61000.0


def test_refund_never_negative_and_tolerates_missing_quote():
    assert ops.refund_amount_for(_order(quote=None, amount=5000)) == 5000.0
    assert ops.refund_amount_for(_order(amount=100)) == 0.0


# ---------------------------------------------------------------------------
# approve_order
# ---------------------------------------------------------------------------

class TestApprove:
    def test_happy_path_creates_job_and_registers_first_order(self, spy):
        db = _db(site_orders=[_order()])
        res = ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)

        row = db.rows("site_orders")[0]
        assert row["status"] == "fulfilling" and row["approved_by"] == USER and row["approved_at"]
        jobs = db.rows("site_hosting_jobs")
        assert len(jobs) == 1 and jobs[0]["order_id"] == "ord-1" and len(jobs[0]["checklist"]) == 6
        assert row["hosting_job_id"] == jobs[0]["id"]
        assert res["hosting_job"]["id"] == jobs[0]["id"]
        assert any(t["task_type"] == "hosting_job" for t in db.rows("tasks"))
        # first order → lead converted, count bumped, quota used
        assert spy["converted"] == [("lead-1", USER)]
        assert db.rows("site_builders")[0]["approved_orders_count"] == 1
        assert db.rows("site_builder_settings")[0]["approval_orders_remaining"] == 29
        assert [e["event"] for e in db.rows("site_events")] == ["order_approved"]

    def test_second_order_does_not_convert_lead_again(self, spy):
        db = _db(site_orders=[_order()],
                 site_builders=[{"id": "b-1", "org_id": ORG, "lead_id": "lead-1", "approved_orders_count": 3}])
        ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)
        assert spy["converted"] == []
        assert db.rows("site_builders")[0]["approved_orders_count"] == 4

    def test_sla_is_carried_from_payment_not_reset_by_approval(self, spy):
        paid_sla = (INSIDE + timedelta(hours=5)).isoformat()
        db = _db(site_orders=[_order(sla_due_at=paid_sla)])
        ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE + timedelta(hours=4))
        assert db.rows("site_hosting_jobs")[0]["sla_due_at"] == paid_sla

    def test_outside_window_is_refused_and_nothing_changes(self, spy):
        db = _db(site_orders=[_order()])
        with pytest.raises(ops.OutsideApprovalWindow) as exc:
            ops.approve_order(db, ORG, "ord-1", USER, now=OUTSIDE)
        assert "08:00" in str(exc.value) and "23:00" in str(exc.value)
        assert db.rows("site_orders")[0]["status"] == "awaiting_approval"
        assert db.rows("site_hosting_jobs") == []

    @pytest.mark.parametrize("status", ["pending_payment", "fulfilling", "live", "refund_pending", "rejected"])
    def test_wrong_status_conflicts(self, spy, status):
        db = _db(site_orders=[_order(status=status)])
        with pytest.raises(ops.Conflict):
            ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)

    def test_other_orgs_order_is_not_found(self, spy):
        db = _db(site_orders=[_order(org_id=OTHER_ORG)])
        with pytest.raises(ops.NotFound):
            ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)

    def test_approving_twice_only_creates_one_job(self, spy):
        db = _db(site_orders=[_order()])
        ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)
        with pytest.raises(ops.Conflict):
            ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)
        assert len(db.rows("site_hosting_jobs")) == 1
        assert spy["converted"] == [("lead-1", USER)]

    def test_job_failure_rolls_the_approval_back(self, spy, monkeypatch):
        db = _db(site_orders=[_order()])
        monkeypatch.setattr(site_order_service, "create_hosting_job", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
        with pytest.raises(ops.SiteOpsError):
            ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)
        row = db.rows("site_orders")[0]
        assert row["status"] == "awaiting_approval" and row["approved_by"] is None
        assert spy["converted"] == []

    def test_quota_reaching_zero_notifies_but_does_not_switch_approvals_off(self, spy):
        s = {**SETTINGS, "approval_orders_remaining": 1}
        db = _db(site_orders=[_order()], site_builder_settings=[s])
        ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)
        cfg = db.rows("site_builder_settings")[0]
        assert cfg["approval_orders_remaining"] == 0 and cfg["approval_required"] is True
        assert ("Approval quota reached", "site_approval_quota") in spy["notified"]

    def test_express_route_is_approved_without_a_hosting_job(self, spy):
        db = _db(site_orders=[_order(route="express")])
        res = ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)
        assert db.rows("site_orders")[0]["status"] == "fulfilling"
        assert db.rows("site_hosting_jobs") == [] and res["express_pending"] is True

    def test_conversion_failure_never_breaks_the_approval(self, spy, monkeypatch):
        db = _db(site_orders=[_order()])
        monkeypatch.setattr(lead_service, "convert_lead", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stage")))
        ops.approve_order(db, ORG, "ord-1", USER, now=INSIDE)
        assert db.rows("site_orders")[0]["status"] == "fulfilling"


# ---------------------------------------------------------------------------
# reject_order / record_refund
# ---------------------------------------------------------------------------

class TestRejectAndRefund:
    def test_reject_sets_refund_pending_with_refund_amount_and_task(self, spy):
        db = _db(site_orders=[_order()])
        out = ops.reject_order(db, ORG, "ord-1", USER, "Client is a scammer")
        row = db.rows("site_orders")[0]
        assert row["status"] == "refund_pending" and row["refund_amount"] == 61000.0
        assert row["rejected_reason"] == "Client is a scammer" and out["status"] == "refund_pending"
        task = db.rows("tasks")[0]
        assert task["task_type"] == "refund" and task["source_record_id"] == "ord-1" and "61,000" in task["title"]
        assert "61,000" in spy["messages"][0] and "Client is a scammer" not in spy["messages"][0]
        assert db.rows("site_events")[0]["event"] == "order_rejected"

    def test_reject_closes_any_open_hosting_job(self, spy):
        db = _db(site_orders=[_order(status="needs_builder_choice", hosting_job_id="job-1")],
                 site_hosting_jobs=[_job(status="blocked")],
                 tasks=[{"id": "t1", "org_id": ORG, "source_record_id": "job-1", "status": "pending"}])
        ops.reject_order(db, ORG, "ord-1", USER, "Builder asked for a refund")
        assert db.rows("site_hosting_jobs")[0]["status"] == "done"
        assert db.rows("tasks")[0]["status"] == "completed"
        assert db.rows("site_events")[0]["event"] == "refund_requested"

    def test_reason_is_required(self, spy):
        db = _db(site_orders=[_order()])
        with pytest.raises(ops.ValidationFailed):
            ops.reject_order(db, ORG, "ord-1", USER, "  ")
        assert db.rows("site_orders")[0]["status"] == "awaiting_approval"

    @pytest.mark.parametrize("status", ["fulfilling", "live", "pending_payment", "refunded"])
    def test_cannot_reject_from_other_statuses(self, spy, status):
        db = _db(site_orders=[_order(status=status)])
        with pytest.raises(ops.Conflict):
            ops.reject_order(db, ORG, "ord-1", USER, "Not needed")

    def test_record_refund_defaults_to_computed_amount(self, spy):
        db = _db(site_orders=[_order(status="refund_pending", refund_amount=61000.0)],
                 tasks=[{"id": "t1", "org_id": ORG, "source_record_id": "ord-1", "status": "pending"}])
        out = ops.record_refund(db, ORG, "ord-1", USER)
        row = db.rows("site_orders")[0]
        assert row["status"] == "refunded" and row["refund_amount"] == 61000.0 and row["refunded_at"]
        assert out["status"] == "refunded"
        assert db.rows("tasks")[0]["status"] == "completed"
        assert "61,000" in spy["messages"][0]

    def test_record_refund_custom_amount_and_bounds(self, spy):
        db = _db(site_orders=[_order(status="refund_pending", refund_amount=61000.0)])
        with pytest.raises(ops.ValidationFailed):
            ops.record_refund(db, ORG, "ord-1", USER, amount=80000)   # more than paid
        with pytest.raises(ops.ValidationFailed):
            ops.record_refund(db, ORG, "ord-1", USER, amount=0)
        ops.record_refund(db, ORG, "ord-1", USER, amount=50000)
        assert db.rows("site_orders")[0]["refund_amount"] == 50000.0

    def test_record_refund_only_from_refund_pending_and_only_once(self, spy):
        db = _db(site_orders=[_order(status="live")])
        with pytest.raises(ops.Conflict):
            ops.record_refund(db, ORG, "ord-1", USER)
        db = _db(site_orders=[_order(status="refund_pending", refund_amount=61000.0)])
        ops.record_refund(db, ORG, "ord-1", USER)
        with pytest.raises(ops.Conflict):
            ops.record_refund(db, ORG, "ord-1", USER)


# ---------------------------------------------------------------------------
# Hosting queue — list, SLA colours, patch
# ---------------------------------------------------------------------------

class TestHostingQueue:
    def test_sla_colours(self):
        now = INSIDE
        assert ops._sla_state(_job(sla_due_at=(now + timedelta(hours=20)).isoformat()), now) == "green"
        assert ops._sla_state(_job(sla_due_at=(now + timedelta(hours=12)).isoformat()), now) == "amber"
        assert ops._sla_state(_job(sla_due_at=(now + timedelta(hours=1)).isoformat()), now) == "amber"
        assert ops._sla_state(_job(sla_due_at=(now - timedelta(minutes=1)).isoformat()), now) == "red"
        assert ops._sla_state(_job(status="done"), now) == "done"
        assert ops._sla_state(_job(sla_due_at=None), now) == "none"

    def test_list_enriches_and_hides_done(self):
        db = _db(site_orders=[_order(status="fulfilling", hosting_job_id="job-1")],
                 site_hosting_jobs=[_job(assigned_to=USER), _job(id="job-2", status="done")],
                 users=[{"id": USER, "org_id": ORG, "full_name": "Trust", "is_active": True}])
        rows = ops.list_hosting_jobs(db, ORG, now=INSIDE)
        assert [r["id"] for r in rows] == ["job-1"]
        r = rows[0]
        assert r["domain"] == "adaezastyles.com.ng" and r["client_business_name"] == "Adaeze Styles"
        assert r["assigned_name"] == "Trust" and r["sla_state"] == "green" and r["seconds_to_sla"] == 24 * 3600
        assert len(ops.list_hosting_jobs(db, ORG, include_done=True, now=INSIDE)) == 2

    def test_mine_filter(self):
        db = _db(site_orders=[_order(status="fulfilling")],
                 site_hosting_jobs=[_job(assigned_to=USER), _job(id="job-2", assigned_to="someone-else"), _job(id="job-3")])
        assert [r["id"] for r in ops.list_hosting_jobs(db, ORG, assigned_to=USER, now=INSIDE)] == ["job-1"]

    def test_assign_sets_task_and_moves_queued_to_in_progress(self, spy):
        db = _db(site_orders=[_order(status="fulfilling")], site_hosting_jobs=[_job()],
                 users=[{"id": USER, "org_id": ORG, "full_name": "Trust", "is_active": True}],
                 tasks=[{"id": "t1", "org_id": ORG, "source_record_id": "job-1", "status": "pending", "assigned_to": None}])
        out = ops.patch_hosting_job(db, ORG, "job-1", USER, {"assigned_to": USER})
        assert out["assigned_to"] == USER and out["status"] == "in_progress" and out["assigned_name"] == "Trust"
        assert db.rows("tasks")[0]["assigned_to"] == USER

    def test_cannot_assign_to_inactive_or_foreign_user(self, spy):
        db = _db(site_orders=[_order(status="fulfilling")], site_hosting_jobs=[_job()],
                 users=[{"id": "u-off", "org_id": ORG, "is_active": False}, {"id": "u-other", "org_id": OTHER_ORG, "is_active": True}])
        for uid in ("u-off", "u-other", "nobody"):
            with pytest.raises(ops.ValidationFailed):
                ops.patch_hosting_job(db, ORG, "job-1", USER, {"assigned_to": uid})
        assert db.rows("site_hosting_jobs")[0]["assigned_to"] is None

    def test_unassign(self, spy):
        db = _db(site_orders=[_order(status="fulfilling")], site_hosting_jobs=[_job(assigned_to=USER, status="in_progress")])
        out = ops.patch_hosting_job(db, ORG, "job-1", USER, {"assigned_to": None})
        assert out["assigned_to"] is None and out["status"] == "in_progress"

    def test_tick_and_untick_a_step(self, spy):
        db = _db(site_orders=[_order(status="fulfilling")], site_hosting_jobs=[_job()])
        out = ops.patch_hosting_job(db, ORG, "job-1", USER, {"step": "register_domain", "step_done": True})
        step = next(s for s in out["checklist"] if s["key"] == "register_domain")
        assert step["done"] is True and step["done_at"] and out["status"] == "in_progress"
        out = ops.patch_hosting_job(db, ORG, "job-1", USER, {"step": "register_domain", "step_done": False})
        assert next(s for s in out["checklist"] if s["key"] == "register_domain")["done"] is False

    def test_unknown_step_and_invalid_status_rejected(self, spy):
        db = _db(site_orders=[_order(status="fulfilling")], site_hosting_jobs=[_job()])
        with pytest.raises(ops.ValidationFailed):
            ops.patch_hosting_job(db, ORG, "job-1", USER, {"step": "make_coffee"})
        with pytest.raises(ops.ValidationFailed):
            ops.patch_hosting_job(db, ORG, "job-1", USER, {"status": "done"})   # only mark-live finishes a job

    def test_notes_and_blocked(self, spy):
        db = _db(site_orders=[_order(status="fulfilling")], site_hosting_jobs=[_job()])
        out = ops.patch_hosting_job(db, ORG, "job-1", USER, {"status": "blocked", "notes": "Waiting on QServers"})
        assert out["status"] == "blocked" and out["notes"] == "Waiting on QServers"

    def test_done_job_cannot_be_edited(self, spy):
        db = _db(site_orders=[_order(status="live")], site_hosting_jobs=[_job(status="done")])
        with pytest.raises(ops.Conflict):
            ops.patch_hosting_job(db, ORG, "job-1", USER, {"notes": "x"})

    def test_other_orgs_job_is_not_found(self, spy):
        db = _db(site_hosting_jobs=[_job(org_id=OTHER_ORG)])
        with pytest.raises(ops.NotFound):
            ops.patch_hosting_job(db, ORG, "job-1", USER, {"notes": "x"})


# ---------------------------------------------------------------------------
# Domain re-check / backup / resolve
# ---------------------------------------------------------------------------

class TestDomainActions:
    def _setup(self, **job_kw):
        return _db(site_orders=[_order(status="fulfilling", hosting_job_id="job-1")], site_hosting_jobs=[_job(**job_kw)])

    def test_recheck_available_ticks_step_and_records_domain(self, spy, monkeypatch):
        _avail(monkeypatch, {"adaezastyles.com.ng": True})
        db = self._setup()
        out = ops.recheck_domain(db, ORG, "job-1", USER)
        job = db.rows("site_hosting_jobs")[0]
        assert out["available"] is True and job["domain_used"] == "adaezastyles.com.ng" and job["domain_rechecked_at"]
        assert next(s for s in job["checklist"] if s["key"] == "recheck_domain")["done"] is True

    def test_recheck_taken_does_not_tick_and_suggests_backup(self, spy, monkeypatch):
        _avail(monkeypatch, {})
        db = self._setup()
        out = ops.recheck_domain(db, ORG, "job-1", USER)
        job = db.rows("site_hosting_jobs")[0]
        assert out["available"] is False and "backup" in out["message"].lower()
        assert next(s for s in job["checklist"] if s["key"] == "recheck_domain")["done"] is False
        assert job["domain_rechecked_at"]

    def test_recheck_unknown_changes_nothing(self, spy, monkeypatch):
        _avail(monkeypatch, {"adaezastyles.com.ng": None})
        db = self._setup()
        out = ops.recheck_domain(db, ORG, "job-1", USER)
        assert out["available"] is None and db.rows("site_hosting_jobs")[0].get("domain_rechecked_at") is None

    def test_recheck_after_registration_is_refused(self, spy, monkeypatch):
        _avail(monkeypatch, {})
        cl = [dict(k) for k in site_order_service._HOSTING_CHECKLIST]
        cl[1]["done"] = True   # register_domain
        db = self._setup(checklist=cl)
        with pytest.raises(ops.Conflict):
            ops.recheck_domain(db, ORG, "job-1", USER)

    def test_use_backup_when_available(self, spy, monkeypatch):
        _avail(monkeypatch, {"adaezastyles.ng": True})
        db = self._setup()
        out = ops.use_backup_domain(db, ORG, "job-1", USER)
        assert out["available"] is True and db.rows("site_hosting_jobs")[0]["domain_used"] == "adaezastyles.ng"
        assert db.rows("site_orders")[0]["status"] == "fulfilling"
        assert db.rows("site_orders")[0]["domain"] == "adaezastyles.com.ng"   # the order keeps what was bought

    def test_both_domains_lost_moves_order_to_needs_builder_choice(self, spy, monkeypatch):
        _avail(monkeypatch, {})
        db = self._setup()
        out = ops.use_backup_domain(db, ORG, "job-1", USER)
        assert out["available"] is False and out["order_status"] == "needs_builder_choice"
        assert db.rows("site_orders")[0]["status"] == "needs_builder_choice"
        job = db.rows("site_hosting_jobs")[0]
        assert job["status"] == "blocked" and "taken" in job["notes"]
        assert "61,000" in spy["messages"][0] and ("Order needs a new domain", "site_order_needs_choice") in spy["notified"]
        assert db.rows("site_events")[0]["event"] == "order_needs_builder_choice"

    def test_use_backup_unknown_is_a_retryable_conflict(self, spy, monkeypatch):
        _avail(monkeypatch, {"adaezastyles.ng": None})
        db = self._setup()
        with pytest.raises(ops.Conflict):
            ops.use_backup_domain(db, ORG, "job-1", USER)
        assert db.rows("site_orders")[0]["status"] == "fulfilling"   # not moved on a lookup hiccup

    def test_use_backup_guards(self, spy, monkeypatch):
        _avail(monkeypatch, {"adaezastyles.ng": True})
        with pytest.raises(ops.Conflict):
            ops.use_backup_domain(self._setup(domain_used="adaezastyles.ng"), ORG, "job-1", USER)
        db = _db(site_orders=[_order(status="fulfilling", backup_domain=None)], site_hosting_jobs=[_job()])
        with pytest.raises(ops.ValidationFailed):
            ops.use_backup_domain(db, ORG, "job-1", USER)
        cl = [dict(k) for k in site_order_service._HOSTING_CHECKLIST]
        cl[1]["done"] = True
        with pytest.raises(ops.Conflict):
            ops.use_backup_domain(self._setup(checklist=cl), ORG, "job-1", USER)

    def _stuck(self):
        return _db(site_orders=[_order(status="needs_builder_choice", hosting_job_id="job-1")],
                   site_hosting_jobs=[_job(status="blocked")])

    def test_resolve_domain_choice_resumes_the_job(self, spy, monkeypatch):
        _avail(monkeypatch, {"adaezaboutique.com.ng": True})
        db = self._stuck()
        ops.resolve_domain_choice(db, ORG, "ord-1", USER, "AdaezaBoutique.com.ng")
        o, j = db.rows("site_orders")[0], db.rows("site_hosting_jobs")[0]
        assert o["status"] == "fulfilling" and o["domain"] == "adaezaboutique.com.ng"
        assert j["status"] == "queued" and j["domain_used"] == "adaezaboutique.com.ng"

    def test_resolve_rejects_different_ending_taken_or_unknown(self, spy, monkeypatch):
        _avail(monkeypatch, {"adaezaboutique.com": True, "adaezaboutique.com.ng": False, "another.com.ng": None})
        for bad in ("adaezaboutique.com", "adaezaboutique.com.ng", "another.com.ng"):
            db = self._stuck()
            with pytest.raises(ops.ValidationFailed):
                ops.resolve_domain_choice(db, ORG, "ord-1", USER, bad)
            assert db.rows("site_orders")[0]["status"] == "needs_builder_choice"

    def test_resolve_only_from_needs_builder_choice(self, spy, monkeypatch):
        _avail(monkeypatch, {"x.com.ng": True})
        db = _db(site_orders=[_order(status="fulfilling")])
        with pytest.raises(ops.Conflict):
            ops.resolve_domain_choice(db, ORG, "ord-1", USER, "x.com.ng")


# ---------------------------------------------------------------------------
# mark_live
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, code):
        self.status_code = code


class TestMarkLive:
    def _setup(self, order_kw=None, job_kw=None):
        return _db(site_orders=[_order(status="fulfilling", hosting_job_id="job-1", **(order_kw or {}))],
                   site_hosting_jobs=[_job(status="in_progress", **(job_kw or {}))],
                   tasks=[{"id": "t1", "org_id": ORG, "source_record_id": "job-1", "status": "pending"}])

    @pytest.fixture(autouse=True)
    def _quote(self, monkeypatch):
        monkeypatch.setattr(pricing_service, "quote", lambda db, org, domain, route, kind="initial", settings=None: {
            "cost": {"domain": 5913.0, "hosting": 36765.0, "ai_messages": 0, "total": 42678.0}})

    def test_happy_path(self, spy):
        db = self._setup()
        out = ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.com.ng/", http_get=lambda u: _Resp(200), now=INSIDE)

        assert db.rows("site_orders")[0]["status"] == "live"
        job = db.rows("site_hosting_jobs")[0]
        assert job["status"] == "done" and job["completed_at"] and job["domain_used"] == "adaezastyles.com.ng"
        assert next(s for s in job["checklist"] if s["key"] == "paste_url")["done"] is True
        site = db.rows("sites")[0]
        assert site["status"] == "live" and site["live_url"] == "https://adaezastyles.com.ng/" and site["published_at"]
        dom = db.rows("site_domains")[0]
        assert dom["domain"] == "adaezastyles.com.ng" and dom["registrar"] == "qservers" and dom["status"] == "active"
        assert dom["renews_on"] == "2027-09-29" and dom["hosting_renews_on"] == "2027-09-29"
        assert dom["registrar_cost_renewal"] == 5913.0 and dom["hosting_cost_renewal"] == 36765.0
        assert db.rows("tasks")[0]["status"] == "completed"
        assert spy["messages"] == ["Your client's website is live: https://adaezastyles.com.ng/"]
        assert out["order_status"] == "live"
        assert [e["event"] for e in db.rows("site_events")] == ["site_published"]

    def test_approvals_off_path_registers_first_order_on_going_live(self, spy):
        db = self._setup()   # approved_at is None ⇒ never went through approve_order
        ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.com.ng", http_get=lambda u: _Resp(200), now=INSIDE)
        assert spy["converted"] == [("lead-1", USER)]
        assert db.rows("site_builders")[0]["approved_orders_count"] == 1

    def test_approved_order_is_not_counted_twice(self, spy):
        db = self._setup(order_kw={"approved_at": INSIDE.isoformat()})
        ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.com.ng", http_get=lambda u: _Resp(200), now=INSIDE)
        assert spy["converted"] == [] and db.rows("site_builders")[0]["approved_orders_count"] == 0

    def test_www_and_backup_domain_in_use(self, spy):
        db = self._setup(job_kw={"domain_used": "adaezastyles.ng"})
        ops.mark_live(db, ORG, "job-1", USER, "https://www.adaezastyles.ng", http_get=lambda u: _Resp(200), now=INSIDE)
        assert db.rows("site_domains")[0]["domain"] == "adaezastyles.ng"

    @pytest.mark.parametrize("url", ["http://adaezastyles.com.ng", "adaezastyles.com.ng", "ftp://adaezastyles.com.ng",
                                     "https://evil.example.com", "https://adaezastyles.com.ng.evil.com"])
    def test_url_must_be_https_and_on_the_chosen_domain(self, spy, url):
        db = self._setup()
        fetched = []
        with pytest.raises(ops.ValidationFailed):
            ops.mark_live(db, ORG, "job-1", USER, url, http_get=lambda u: fetched.append(u) or _Resp(200), now=INSIDE)
        assert fetched == []   # never fetches a URL it wouldn't accept (no server-side request to arbitrary hosts)
        assert db.rows("site_orders")[0]["status"] == "fulfilling"

    def test_backup_url_rejected_while_main_domain_is_in_use(self, spy):
        db = self._setup()
        with pytest.raises(ops.ValidationFailed):
            ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.ng", http_get=lambda u: _Resp(200), now=INSIDE)

    @pytest.mark.parametrize("code", [301, 403, 404, 500, 503])
    def test_non_200_is_refused(self, spy, code):
        db = self._setup()
        with pytest.raises(ops.ValidationFailed) as exc:
            ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.com.ng", http_get=lambda u: _Resp(code), now=INSIDE)
        assert str(code) in str(exc.value)
        assert db.rows("site_orders")[0]["status"] == "fulfilling" and db.rows("site_domains") == []

    def test_unreachable_url_is_refused(self, spy):
        db = self._setup()
        def boom(u):
            raise ConnectionError("dns")
        with pytest.raises(ops.ValidationFailed):
            ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.com.ng", http_get=boom, now=INSIDE)
        assert spy["messages"] == []

    def test_cannot_mark_live_twice(self, spy):
        db = self._setup()
        ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.com.ng", http_get=lambda u: _Resp(200), now=INSIDE)
        with pytest.raises(ops.Conflict):
            ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.com.ng", http_get=lambda u: _Resp(200), now=INSIDE)
        assert len(db.rows("site_domains")) == 1 and len(spy["messages"]) == 1

    def test_blocked_order_cannot_go_live(self, spy):
        db = _db(site_orders=[_order(status="needs_builder_choice", hosting_job_id="job-1")], site_hosting_jobs=[_job(status="blocked")])
        with pytest.raises(ops.Conflict):
            ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.com.ng", http_get=lambda u: _Resp(200), now=INSIDE)

    def test_quote_failure_still_publishes_and_records_the_domain(self, spy, monkeypatch):
        monkeypatch.setattr(pricing_service, "quote", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pricing off")))
        db = self._setup()
        ops.mark_live(db, ORG, "job-1", USER, "https://adaezastyles.com.ng", http_get=lambda u: _Resp(200), now=INSIDE)
        dom = db.rows("site_domains")[0]
        assert db.rows("site_orders")[0]["status"] == "live" and dom["registrar_cost_renewal"] is None

    def test_leap_day_renewal(self):
        assert ops._add_year(datetime(2028, 2, 29).date()).isoformat() == "2029-02-28"


# ---------------------------------------------------------------------------
# Domains & renewals list
# ---------------------------------------------------------------------------

class TestDomains:
    def _dom(self, id, domain, days, **kw):
        renews = (INSIDE.date() + timedelta(days=days)).isoformat()
        base = {"id": id, "org_id": ORG, "site_id": "site-1", "domain": domain, "registrar": "qservers", "route": "standard",
                "renews_on": renews, "hosting_renews_on": renews, "registrar_cost_renewal": 6000, "hosting_cost_renewal": 37000,
                "registrar_cost_currency": "NGN", "status": "active"}
        base.update(kw)
        return base

    def test_effective_status_days_and_cost(self):
        db = _db(site_domains=[self._dom("d1", "a.com", 200), self._dom("d2", "b.com", 20), self._dom("d3", "c.com", -3),
                               self._dom("d4", "d.com", 5, status="transferred")])
        rows = {r["domain"]: r for r in ops.list_domains(db, ORG, now=INSIDE)}
        assert rows["a.com"]["effective_status"] == "active" and rows["a.com"]["days_to_renewal"] == 200
        assert rows["b.com"]["effective_status"] == "expiring"
        assert rows["c.com"]["effective_status"] == "lapsed" and rows["c.com"]["days_to_renewal"] == -3
        assert rows["d.com"]["effective_status"] == "transferred"
        assert rows["a.com"]["cost_at_renewal"] == 43000.0
        assert rows["a.com"]["client_business_name"] == "Adaeze Styles" and rows["a.com"]["builder_name"] == "Chioma"

    def test_sorted_soonest_first_and_missing_dates_last(self):
        db = _db(site_domains=[self._dom("d1", "a.com", 200), self._dom("d2", "b.com", 20),
                               self._dom("d3", "c.com", 0, renews_on=None, hosting_renews_on=None)])
        assert [r["domain"] for r in ops.list_domains(db, ORG, now=INSIDE)] == ["b.com", "a.com", "c.com"]

    @pytest.mark.parametrize("window,expected", [(30, {"b.com", "c.com", "e.com"}), (14, {"c.com", "e.com"}), (7, {"c.com"})])
    def test_expiring_filters(self, window, expected):
        db = _db(site_domains=[self._dom("d1", "a.com", 200), self._dom("d2", "b.com", 20), self._dom("d3", "c.com", -3),
                               self._dom("d4", "d.com", 5, status="transferred"), self._dom("d5", "e.com", 10)])
        got = {r["domain"] for r in ops.list_domains(db, ORG, expiring_within=window, now=INSIDE)}
        assert got == expected   # overdue counts; transferred domains never do

    def test_earliest_of_domain_and_hosting_renewal_wins(self):
        d = self._dom("d1", "a.com", 200, hosting_renews_on=(INSIDE.date() + timedelta(days=9)).isoformat())
        rows = ops.list_domains(_db(site_domains=[d]), ORG, now=INSIDE)
        assert rows[0]["days_to_renewal"] == 9 and rows[0]["effective_status"] == "expiring"

    def test_status_and_search_filters_and_org_isolation(self):
        db = _db(site_domains=[self._dom("d1", "a.com", 200), self._dom("d2", "b.com", 20),
                               self._dom("d9", "z.com", 1, org_id=OTHER_ORG)])
        assert [r["domain"] for r in ops.list_domains(db, ORG, status="expiring", now=INSIDE)] == ["b.com"]
        assert [r["domain"] for r in ops.list_domains(db, ORG, search="adaeze", now=INSIDE)] == ["b.com", "a.com"]
        assert "z.com" not in [r["domain"] for r in ops.list_domains(db, ORG, now=INSIDE)]

    def test_no_cost_data_gives_none(self):
        d = self._dom("d1", "a.com", 200, registrar_cost_renewal=None, hosting_cost_renewal=None)
        assert ops.list_domains(_db(site_domains=[d]), ORG, now=INSIDE)[0]["cost_at_renewal"] is None


# ---------------------------------------------------------------------------
# Orders list + overview KPIs
# ---------------------------------------------------------------------------

class TestOrdersListAndKpis:
    def test_list_enriches_filters_and_reports_approval_window(self):
        db = _db(site_orders=[_order(), _order(id="ord-2", status="live", domain="other.com", payment_reference="ref-2"),
                              _order(id="ord-3", org_id=OTHER_ORG)])
        res = ops.list_orders(db, ORG, now=INSIDE)
        assert res["total"] == 2 and res["approval"]["in_window"] is True and res["approval"]["required"] is True
        first = next(r for r in res["items"] if r["id"] == "ord-1")
        assert first["client_business_name"] == "Adaeze Styles" and first["builder_name"] == "Chioma"
        assert first["service_fee"] == 18500 and first["refund_due"] == 61000.0
        assert next(r for r in res["items"] if r["id"] == "ord-2")["refund_due"] is None
        assert [r["id"] for r in ops.list_orders(db, ORG, status="live", now=INSIDE)["items"]] == ["ord-2"]
        assert [r["id"] for r in ops.list_orders(db, ORG, search="OTHER.com", now=INSIDE)["items"]] == ["ord-2"]
        assert ops.list_orders(db, ORG, now=OUTSIDE)["approval"]["in_window"] is False

    def test_pagination(self):
        db = _db(site_orders=[_order(id=f"o{i}", created_at=(INSIDE + timedelta(minutes=i)).isoformat()) for i in range(5)])
        res = ops.list_orders(db, ORG, page=2, page_size=2, now=INSIDE)
        assert res["total"] == 5 and [r["id"] for r in res["items"]] == ["o2", "o1"]

    def test_kpis(self):
        paid_now = (INSIDE + timedelta(hours=24)).isoformat()                  # paid ~ now → this month
        paid_old = (INSIDE - timedelta(days=60) + timedelta(hours=24)).isoformat()   # paid two months ago
        db = _db(
            site_orders=[
                _order(id="a", status="live", amount=100000, expected_profit=40000, sla_due_at=paid_now),
                _order(id="b", status="awaiting_approval", amount=50000, expected_profit=20000, sla_due_at=paid_now),
                _order(id="c", status="live", amount=70000, expected_profit=30000, sla_due_at=paid_old),
                _order(id="d", status="refunded", amount=80000, refund_amount=60000, expected_profit=25000, sla_due_at=paid_now),
                _order(id="e", status="refund_pending", amount=90000, expected_profit=25000, sla_due_at=paid_now),
                _order(id="f", status="pending_payment", amount=60000, sla_due_at=None),
                _order(id="g", status="live", kind="renewal", amount=10000, expected_profit=5000, sla_due_at=paid_now),
            ],
            site_domains=[{"id": "d1", "org_id": ORG, "renews_on": (INSIDE.date() + timedelta(days=10)).isoformat(),
                           "hosting_renews_on": None, "status": "active"},
                          {"id": "d2", "org_id": ORG, "renews_on": (INSIDE.date() + timedelta(days=300)).isoformat(),
                           "hosting_renews_on": None, "status": "active"}],
            site_hosting_jobs=[_job(id="j1", sla_due_at=(INSIDE - timedelta(hours=1)).isoformat()),
                               _job(id="j2"), _job(id="j3", status="done", sla_due_at=(INSIDE - timedelta(days=2)).isoformat())],
        )
        k = ops.order_kpis(db, ORG, sites_total=10, now=INSIDE)
        # paid = everything except pending_payment
        assert k["orders_paid"] == 6 and k["orders_awaiting_approval"] == 1 and k["orders_refund_pending"] == 1
        # revenue: 100k + 50k + 70k + 20k (refunded keeps the service fee) + 0 (refund_pending) + 10k
        assert k["all_time"]["revenue"] == 250000.0
        assert k["all_time"]["expected_profit"] == 40000 + 20000 + 30000 + 5000
        assert k["this_month"]["revenue"] == 100000 + 50000 + 20000 + 10000
        assert k["conversion_rate"] == 50.0          # 5 paid initial orders (a–e; g is a renewal) / 10 sites
        assert k["renewals_due_30d"] == 1
        assert k["hosting_jobs_open"] == 2 and k["hosting_jobs_overdue"] == 1

    def test_kpis_with_no_data(self):
        k = ops.order_kpis(_db(), ORG, sites_total=0, now=INSIDE)
        assert k["orders_paid"] == 0 and k["conversion_rate"] is None and k["all_time"]["revenue"] == 0


# ---------------------------------------------------------------------------
# Export zip — spec §8.6
# ---------------------------------------------------------------------------

class _Storage:
    def __init__(self, files):
        self.files = files
        self.bucket = None

    def from_(self, bucket):
        self.bucket = bucket
        return self

    def download(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


class TestExport:
    def _site_db(self):
        from app.routers import sites as sites_router
        content = sites_router._SAMPLE_CONTENT
        db = _db(
            sites=[{"id": "site-1", "org_id": ORG, "builder_id": "b-1", "preset_id": "p1", "slug": "adaeze-styles-abc123",
                    "client_business_name": "Adaeze Styles", "status": "live", "deleted_at": None,
                    "content": content, "recipe": {"theme": "atelier", "palette": "berry", "order": ["hero", "items", "order"], "hidden": []}}],
            site_presets=[{"id": "p1", "org_id": ORG, "key": "boutique"}],
            site_assets=[{"id": "as1", "site_id": "site-1", "slot": "hero", "storage_path": "site-1/hero-x.jpg", "mime_type": "image/jpeg"},
                         {"id": "as2", "site_id": "site-1", "slot": "Item 3!", "storage_path": "site-1/i3.png", "mime_type": "image/png"},
                         {"id": "as3", "site_id": "site-1", "slot": "gone", "storage_path": "site-1/missing.jpg", "mime_type": "image/jpeg"}],
            site_orders=[_order(status="live")],
        )
        db.storage = _Storage({"site-1/hero-x.jpg": b"JPEGBYTES", "site-1/i3.png": b"PNGBYTES"})
        return db

    def test_zip_contents(self):
        db = self._site_db()
        data, filename = ops.build_export_zip(db, ORG, "site-1")
        assert filename == "adaeze-styles-abc123-export.zip" and db.storage.bucket == "site-assets"
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist())
        assert names == {"index.html", "robots.txt", "sitemap.xml", "images/hero.jpg", "images/item-3-.png"}   # missing asset skipped
        assert zf.read("images/hero.jpg") == b"JPEGBYTES"
        html = zf.read("index.html").decode()
        assert "Preview — not yet live" not in html          # no preview bar in an export (§8.6)
        assert "Sample Business" in html
        assert "https://adaezastyles.com.ng/" in zf.read("sitemap.xml").decode()
        assert "Sitemap: https://adaezastyles.com.ng/sitemap.xml" in zf.read("robots.txt").decode()

    def test_zip_without_any_order_skips_sitemap(self):
        db = self._site_db()
        db.tables["site_orders"] = []
        data, _ = ops.build_export_zip(db, ORG, "site-1")
        zf = zipfile.ZipFile(io.BytesIO(data))
        assert "sitemap.xml" not in zf.namelist() and "Sitemap:" not in zf.read("robots.txt").decode()

    def test_other_orgs_or_deleted_site_is_not_found(self):
        db = self._site_db()
        with pytest.raises(ops.NotFound):
            ops.build_export_zip(db, OTHER_ORG, "site-1")
        db.tables["sites"][0]["deleted_at"] = "2026-09-01T00:00:00+00:00"
        with pytest.raises(ops.NotFound):
            ops.build_export_zip(db, ORG, "site-1")


# ---------------------------------------------------------------------------
# site_worker regression — finished jobs must not keep paging
# ---------------------------------------------------------------------------

def test_sla_worker_excludes_only_statuses_the_table_allows():
    from app.workers import site_worker
    allowed = {"queued", "in_progress", "blocked", "done"}   # site_hosting_jobs_status_check
    assert set(site_worker._OPEN_JOB_STATUSES_EXCLUDE) == {"done"}
    assert set(site_worker._OPEN_JOB_STATUSES_EXCLUDE) <= allowed


def test_domain_check_fresh_bypasses_cache_and_rate_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(dcs, "_lookup_availability", lambda d, t: calls.append(d) or True)
    db = _db()
    for _ in range(30):   # well past the 20/hour builder limit; and no cache
        name, avail = dcs.check_availability_fresh(db, ORG, "Adaezastyles.COM.ng")
    assert name == "adaezastyles.com.ng" and avail is True and len(calls) == 30
    with pytest.raises(dcs.InvalidDomain):
        dcs.check_availability_fresh(db, ORG, "adaezastyles.xyz")
