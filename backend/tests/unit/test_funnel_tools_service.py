"""
tests/unit/test_funnel_tools_service.py
FUNNEL-1B — template budget cap, ad spend + overview, preview, test tools, Gmail list,
broadcasts (create/dry-run/cap/drain/cancel) and the worker's budget gating.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest

from app.services import funnel_service as fs
from app.services import funnel_tools_service as tools
from app.services.funnel_tools_service import FunnelToolError, TemplateBudget
from app.workers import funnel_worker
from tests.unit.test_funnel_service import (
    FUNNEL_ID, NOW, NUMBER, ORG_ID, base_db, make_funnel, make_reg,
)

ORG_ROW = {"id": ORG_ID, "subscription_status": "active", "quiet_hours_start": None,
           "quiet_hours_end": None, "timezone": "Africa/Lagos"}


def reg(i: int, **kw):
    r = make_reg(id=f"7777777{i}-7777-7777-7777-777777777777", phone=f"23480000000{i:02d}",
                 pay_token=f"tok{i}", ref_code=f"AB{1000 + i}", **kw)
    return r


def capped_funnel(cost=50, cap=100, **kw):
    return make_funnel(settings={"template_cost_estimate": cost, "template_budget_cap": cap}, **kw)


@pytest.fixture
def meta():
    with patch("app.services.funnel_messaging._call_meta_send", return_value={}) as m:
        yield m


# ═══════════════════════════ Template budget ═══════════════════════════

class TestBudget:
    def test_FUN_B_01_inactive_when_either_setting_missing(self):
        db = base_db()
        b = TemplateBudget.load(db, make_funnel(settings={"template_budget_cap": 1000}))
        assert not b.active and b.allow(10_000) and b.remaining_messages is None

    def test_FUN_B_02_counts_template_and_broadcast_events_only(self):
        db = base_db(funnel_events=[
            {"funnel_id": FUNNEL_ID, "type": "template_sent", "registration_id": "a", "step_key": "x"},
            {"funnel_id": FUNNEL_ID, "type": "broadcast_sent", "registration_id": "a", "step_key": "bc_1"},
            {"funnel_id": FUNNEL_ID, "type": "step_sent", "registration_id": "a", "step_key": "y"},
        ])
        b = TemplateBudget.load(db, capped_funnel(cost=40, cap=200))
        assert b.used == 2 and b.spent == 80.0 and b.remaining_messages == 3
        assert b.allow(3) and not b.allow(4)

    def test_FUN_B_03_notify_reached_once(self):
        db = base_db()
        b = TemplateBudget.load(db, capped_funnel())
        b.notify_reached(db)
        b2 = TemplateBudget.load(db, capped_funnel())
        b2.notify_reached(db)
        assert len(db.rows("notifications")) == 1
        assert [e["type"] for e in db.rows("funnel_events")] == ["budget_cap_reached"]


# ═══════════════════════════ Ad spend + overview ═══════════════════════════

class TestSpendOverview:
    def test_FUN_B_04_put_upserts_by_day_and_code(self):
        db = base_db(funnel_ad_spend=[])
        tools.put_ad_spend(db, ORG_ID, FUNNEL_ID, [{"date": "2026-10-01", "ad_code": "B1", "amount": 5000}])
        tools.put_ad_spend(db, ORG_ID, FUNNEL_ID, [{"date": "2026-10-01", "ad_code": "B1", "amount": 6000},
                                                   {"date": "2026-10-01", "ad_code": "S2", "amount": 3000}])
        rows = db.rows("funnel_ad_spend")
        assert len(rows) == 2 and {r["ad_code"]: r["amount"] for r in rows} == {"B1": 6000.0, "S2": 3000.0}

    def test_FUN_B_05_overview_costs_and_pause_flag(self):
        db = base_db(
            funnel_registrations=[reg(1, ad_code="B1", status="paid", amount_paid=5000, paid_at=NOW.isoformat()),
                                  reg(2, ad_code="B1"), reg(3, ad_code="S2")],
            funnel_ad_spend=[{"org_id": ORG_ID, "funnel_id": FUNNEL_ID, "spend_date": "2026-10-01", "ad_code": "B1", "amount": 8000},
                             {"org_id": ORG_ID, "funnel_id": FUNNEL_ID, "spend_date": "2026-10-01", "ad_code": "S2", "amount": 12000},
                             {"org_id": ORG_ID, "funnel_id": FUNNEL_ID, "spend_date": "2026-10-02", "ad_code": "F7", "amount": 500}])
        ov = tools.get_overview(db, ORG_ID, make_funnel())
        by = {r["code"]: r for r in ov["by_ad_code"]}
        assert by["B1"]["cost_per_payment"] == 8000.0 and by["B1"]["cost_per_lead"] == 4000.0
        assert by["S2"]["pause_flag"] is True and by["B1"]["pause_flag"] is False
        assert by["F7"]["leads"] == 0 and by["F7"]["pause_flag"] is False     # spend below threshold
        assert ov["ad_spend"] == 20500.0 and ov["cost_per_payment"] == 20500.0
        assert ov["by_ad_code"][0]["code"] == "B1"                             # best cost/payment first
        assert ov["spend_by_day"] == [{"date": "2026-10-01", "spend": 20000.0}, {"date": "2026-10-02", "spend": 500.0}]

    def test_FUN_B_06_overview_includes_template_spend_when_costed(self):
        db = base_db(funnel_registrations=[reg(1, status="paid", amount_paid=5000, paid_at=NOW.isoformat())],
                     funnel_ad_spend=[],
                     funnel_events=[{"funnel_id": FUNNEL_ID, "type": "template_sent", "registration_id": "a", "step_key": "x"}])
        ov = tools.get_overview(db, ORG_ID, capped_funnel(cost=60, cap=1000))
        assert ov["template_spend_estimate"] == 60.0 and ov["cost_per_payment"] == 60.0
        assert ov["template_budget"]["remaining_amount"] == 940.0


# ═══════════════════════════ Preview ═══════════════════════════

class TestPreview:
    def test_FUN_B_07_greeting_early_with_button_and_faq(self):
        out = tools.render_preview(make_funnel(), {"message_key": "greeting", "sample": {"name": "Tolu Ade"}}, now=NOW)
        assert out["text"].startswith("Hi Tolu") and "₦5,000" in out["text"]
        assert out["button"] == "Pay ₦5,000" and out["tier"] == "early" and len(out["faq_buttons"]) == 3

    def test_FUN_B_08_after_window_regular_price(self):
        out = tools.render_preview(make_funnel(), {"message_key": "pay_link_resend",
                                                   "sample": {"hours_since_first": 30}}, now=NOW)
        assert out["button"] == "Pay ₦7,500" and out["tier"] == "regular"

    def test_FUN_B_09_unsaved_edits_and_step_template(self):
        out = tools.render_preview(make_funnel(), {"text": "Yo {name}, {price}", "messages": {"greeting": "x"},
                                                   "sample": {"name": "Ada"}}, now=NOW)
        assert out["text"] == "Yo Ada, ₦5,000"
        st = tools.render_preview(make_funnel(), {"step_key": "window_closed", "sample": {"hours_since_first": 26}}, now=NOW)
        assert st["template"] == "window_closed" and st["template_params"][0].endswith("/f/PREVIEW")
        with pytest.raises(FunnelToolError):
            tools.render_preview(make_funnel(), {"step_key": "nope"}, now=NOW)
        with pytest.raises(FunnelToolError):
            tools.render_preview(make_funnel(), {"message_key": "faq"}, now=NOW)


# ═══════════════════════════ Test tools + Gmail ═══════════════════════════

class TestTools:
    def test_FUN_B_10_reset_only_unpaid(self):
        db = base_db(funnel_registrations=[reg(1), reg(2, status="paid", amount_paid=5000)])
        tools.reset_registration(db, ORG_ID, FUNNEL_ID, db.rows("funnel_registrations")[0])
        assert [r["id"] for r in db.rows("funnel_registrations")] == [reg(2)["id"]]
        with pytest.raises(FunnelToolError) as e:
            tools.reset_registration(db, ORG_ID, FUNNEL_ID, db.rows("funnel_registrations")[0])
        assert e.value.status == 409

    def test_FUN_B_11_duplicate_as_test_compresses_timings(self):
        db = base_db()
        copy = tools.duplicate_as_test(db, ORG_ID, make_funnel(status="active"))
        assert copy["status"] == "draft" and copy["window_hours"] == 1 and copy["name"].startswith("TEST")
        steps = {s["key"]: s for s in copy["sequence"]}
        assert steps["checkin_3h"]["offset_minutes"] == 8          # 180 / 24 = 7.5 → 8
        assert steps["early_ends"]["offset_minutes"] == 50
        assert steps["class_tonight"]["enabled"] is False
        assert copy["settings"]["respect_quiet_hours"] is False
        # the copy is a valid funnel for the engine
        assert fs.current_price(dict(copy, status="active"), make_reg(), NOW + timedelta(minutes=59)).tier == "early"
        assert fs.current_price(dict(copy, status="active"), make_reg(), NOW + timedelta(minutes=61)).tier == "regular"

    def test_FUN_B_12_duplicate_deadline_funnel_becomes_window(self):
        f = make_funnel(pricing_mode="deadline", early_deadline_at=(NOW + timedelta(days=2)).isoformat())
        copy = tools.duplicate_as_test(base_db(), ORG_ID, f)
        assert copy["pricing_mode"] == "window" and copy["early_deadline_at"] is None
        assert all(s["anchor"] != "early_deadline" for s in copy["sequence"])

    def test_FUN_B_13_gmail_list(self):
        db = base_db(funnel_registrations=[
            reg(1, status="paid", email="A@gmail.com"), reg(2, status="paid", email="a@gmail.com"),
            reg(3, status="paid", email=None), reg(4, email="x@gmail.com")])
        g = tools.gmail_list(db, ORG_ID, FUNNEL_ID)
        assert g["emails"] == ["a@gmail.com"] and g["joined"] == "a@gmail.com"
        assert [m["id"] for m in g["missing"]] == [reg(3)["id"]]


# ═══════════════════════════ Broadcasts ═══════════════════════════

class TestBroadcasts:
    BODY = {"template_name": "class_tomorrow", "template_params": ["{pay_link}"], "language": "en",
            "audience": "unpaid", "ad_code": None, "dry_run": False}

    def _db(self, n_unpaid=3, **kw):
        regs = [reg(i) for i in range(1, n_unpaid + 1)] + [reg(90, status="paid"), reg(91, status="opted_out")]
        return base_db(funnel_registrations=regs, funnel_broadcasts=[], organisations=[dict(ORG_ROW)], **kw)

    def test_FUN_B_14_dry_run_counts_segment(self):
        db = self._db()
        out = tools.create_broadcast(db, ORG_ID, capped_funnel(cost=50, cap=1000), dict(self.BODY, dry_run=True), None)
        assert out["recipients"] == 3 and out["estimated_cost"] == 150.0 and out["within_budget"] is True
        assert db.rows("funnel_broadcasts") == []
        out2 = tools.create_broadcast(db, ORG_ID, make_funnel(), dict(self.BODY, dry_run=True, audience="all"), None)
        assert out2["recipients"] == 4 and out2["estimated_cost"] is None

    def test_FUN_B_15_cap_blocks_oversized_broadcast(self):
        db = self._db()
        with pytest.raises(FunnelToolError) as e:
            tools.create_broadcast(db, ORG_ID, capped_funnel(cost=50, cap=100), self.BODY, None)
        assert e.value.code == "BUDGET_CAP" and "2 more" in e.value.message

    def test_FUN_B_16_drain_sends_once_with_rendered_params(self, meta):
        db = self._db()
        b = tools.create_broadcast(db, ORG_ID, make_funnel(), self.BODY, None)
        r1 = tools.drain_broadcasts(db, make_funnel(), NOW)
        r2 = tools.drain_broadcasts(db, make_funnel(), NOW)
        assert r1["sent"] == 3 and r2["sent"] == 0 and meta.call_count == 3
        tpl = meta.call_args.args[1]["template"]
        assert tpl["name"] == "class_tomorrow" and "/f/tok" in tpl["components"][0]["parameters"][0]["text"]
        row = db.rows("funnel_broadcasts")[0]
        assert (row["status"], row["sent"], row["failed"]) == ("done", 3, 0)

    def test_FUN_B_17_drain_stops_at_cap(self, meta):
        f = capped_funnel(cost=50, cap=100)
        db = self._db()
        db.tables["funnel_broadcasts"].append({"id": "bbbbbbbb-0000-0000-0000-000000000001", "org_id": ORG_ID,
            "funnel_id": FUNNEL_ID, "template_name": "t", "template_params": [], "audience": "unpaid",
            "ad_code": None, "status": "queued", "total": 3, "sent": 0, "failed": 0, "created_at": NOW.isoformat()})
        tools.drain_broadcasts(db, f, NOW)
        row = db.rows("funnel_broadcasts")[0]
        assert meta.call_count == 2 and row["status"] == "capped" and row["sent"] == 2
        assert len(db.rows("notifications")) == 1

    def test_FUN_B_18_cancel_and_ad_code_segment(self, meta):
        db = self._db()
        db.tables["funnel_registrations"][0]["ad_code"] = "S2"
        b = tools.create_broadcast(db, ORG_ID, make_funnel(), dict(self.BODY, ad_code="S2"), None)
        assert b["total"] == 1
        tools.cancel_broadcast(db, ORG_ID, FUNNEL_ID, b["id"])
        assert tools.drain_broadcasts(db, make_funnel(), NOW)["sent"] == 0
        with pytest.raises(FunnelToolError):
            tools.cancel_broadcast(db, ORG_ID, FUNNEL_ID, b["id"])

    def test_FUN_B_19_quiet_hours_and_wrong_mode_hold(self, meta):
        db = self._db()
        tools.create_broadcast(db, ORG_ID, make_funnel(), self.BODY, None)
        with patch("app.utils.org_gates.is_quiet_hours", return_value=True):
            assert tools.drain_broadcasts(db, make_funnel(), NOW)["sent"] == 0
        db.tables["whatsapp_numbers"][0]["wa_sales_mode"] = "human"
        assert tools.drain_broadcasts(db, make_funnel(), NOW)["sent"] == 0
        assert db.rows("funnel_broadcasts")[0]["status"] == "queued"


# ═══════════════════════════ Worker budget gating ═══════════════════════════

class TestWorkerBudget:
    def test_FUN_B_20_template_steps_skipped_when_cap_used_up(self, meta):
        first = NOW - timedelta(hours=25, minutes=5)
        regs = [reg(i, first_message_at=first.isoformat(), last_inbound_at=first.isoformat(),
                    done_steps=["checkin_3h", "early_ends"]) for i in (1, 2)]
        db = base_db(funnel_registrations=regs, organisations=[dict(ORG_ROW)])
        s = funnel_worker.process_funnel(db, capped_funnel(cost=50, cap=50), NOW)
        assert s["sent"] == 1 and s["skipped"] == 1 and meta.call_count == 1
        reasons = [e["detail"].get("reason") for e in db.rows("funnel_events") if e["type"] == "step_skipped"]
        assert reasons == ["budget_cap"]
        assert [e["type"] for e in db.rows("funnel_events")].count("template_sent") == 1

    def test_FUN_B_21_text_steps_unaffected_by_cap(self, meta):
        db = base_db(funnel_registrations=[reg(1)], organisations=[dict(ORG_ROW)])
        s = funnel_worker.process_funnel(db, capped_funnel(cost=50, cap=50,), NOW + timedelta(hours=3, minutes=2))
        assert s["sent"] == 1

    def test_FUN_B_22_run_task_drains_broadcasts(self, meta):
        db = base_db(funnel_registrations=[reg(1)], organisations=[dict(ORG_ROW)], funnel_broadcasts=[],
                     worker_run_log=[])
        tools.create_broadcast(db, ORG_ID, make_funnel(), TestBroadcasts.BODY, None)
        with patch("app.workers.funnel_worker.get_supabase", return_value=db):
            out = funnel_worker.run_funnel_sequence()
        assert out["failed"] == 0 and db.rows("funnel_broadcasts")[0]["status"] == "done"
