"""
tests/unit/test_funnel_service.py
FUNNEL-1A — Event Funnel engine: pricing (hybrid), parsing, rendering,
sequence planning, inbound flow, pay link, payment hook.

Conventions: Pattern 24 (valid UUIDs), Pattern 42/63 (patch where used),
T2 (FakeDB instead of mixed side_effect/return_value chains).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import funnel_service as fs
from tests.funnel_fake_db import FakeDB

ORG_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORG = "99999999-9999-9999-9999-999999999999"
NUMBER_ID = "33333333-3333-3333-3333-333333333333"
FUNNEL_ID = "44444444-4444-4444-4444-444444444444"
LEAD_ID = "55555555-5555-5555-5555-555555555555"
OWNER_ID = "66666666-6666-6666-6666-666666666666"
PHONE = "2348031234567"

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)          # Fri 2 Oct, 11:00 WAT
EVENT = datetime(2026, 10, 10, 19, 0, tzinfo=timezone.utc)       # Sat 10 Oct, 20:00 WAT
CLOSE = datetime(2026, 10, 10, 17, 0, tzinfo=timezone.utc)       # Sat 10 Oct, 18:00 WAT


def make_funnel(**kw):
    f = {
        "id": FUNNEL_ID, "org_id": ORG_ID, "name": "Website class", "status": "active",
        "whatsapp_number_id": NUMBER_ID, "event_title": "Build a Professional Website with ChatGPT",
        "event_starts_at": EVENT.isoformat(), "registration_closes_at": CLOSE.isoformat(),
        "pricing_mode": "window", "window_hours": 24, "early_deadline_at": None,
        "early_price": 5000, "regular_price": 7500, "group_size": 3, "group_price": 12000,
        "currency": "NGN", "paid_group_link": "https://chat.whatsapp.com/PAID",
        "prep_group_link": "https://chat.whatsapp.com/PREP", "bonus_link": "https://example.com/pack.pdf",
        "ad_codes": [{"code": "B1"}, {"code": "S2"}, {"code": "ST5"}, {"code": "F7"}],
        "messages": {}, "sequence": [], "settings": {},
    }
    f.update(kw)
    return f


def make_reg(**kw):
    r = {
        "id": "77777777-7777-7777-7777-777777777777", "org_id": ORG_ID, "funnel_id": FUNNEL_ID,
        "lead_id": LEAD_ID, "phone": PHONE, "name": "Ada Obi", "email": None, "ad_code": "B1",
        "status": "new", "seats": 1, "amount_paid": 0, "ref_code": "AB1234", "pay_token": "tok_abc",
        "first_message_at": NOW.isoformat(), "last_inbound_at": NOW.isoformat(),
        "early_override_until": None, "paused_until": None, "needs_human": False, "done_steps": [],
        "referred_by_id": None,
    }
    r.update(kw)
    return r


NUMBER = {"id": NUMBER_ID, "org_id": ORG_ID, "phone_id": "PHONE_ID_1", "access_token": "tok",
          "wa_sales_mode": "event_funnel"}


def base_db(**extra):
    tables = {
        "event_funnels": [make_funnel()],
        "whatsapp_numbers": [dict(NUMBER)],
        "users": [{"id": OWNER_ID, "org_id": ORG_ID, "roles": {"template": "owner"}}],
        "leads": [], "funnel_registrations": [], "funnel_payments": [], "funnel_events": [],
        "whatsapp_messages": [], "notifications": [],
    }
    tables.update(extra)
    return FakeDB(**tables)


@pytest.fixture
def meta():
    with patch("app.services.funnel_messaging._call_meta_send", return_value={"messages": [{"id": "wamid.X"}]}) as m:
        yield m


def _types(meta_mock):
    out = []
    for c in meta_mock.call_args_list:
        p = c.args[1]
        out.append(p["type"] if p["type"] != "interactive" else "interactive:" + p["interactive"]["type"])
    return out


# ═══════════════════════════ Pricing ═══════════════════════════

class TestPricing:
    def test_FUN_U_01_window_early_within_24h(self):
        q = fs.current_price(make_funnel(), make_reg(), NOW + timedelta(hours=23, minutes=59))
        assert (q.status, q.tier, q.amount) == ("open", "early", 5000.0)
        assert q.early_ends_at == NOW + timedelta(hours=24)

    def test_FUN_U_02_window_regular_at_exactly_24h(self):
        q = fs.current_price(make_funnel(), make_reg(), NOW + timedelta(hours=24))
        assert (q.tier, q.amount) == ("regular", 7500.0)

    def test_FUN_U_03_deadline_mode(self):
        dl = datetime(2026, 10, 4, 22, 59, tzinfo=timezone.utc)
        f = make_funnel(pricing_mode="deadline", early_deadline_at=dl.isoformat())
        old_reg = make_reg(first_message_at=(dl - timedelta(days=5)).isoformat())
        assert fs.current_price(f, old_reg, dl - timedelta(seconds=1)).tier == "early"
        assert fs.current_price(f, old_reg, dl).tier == "regular"

    def test_FUN_U_04_override_regrants_early(self):
        later = NOW + timedelta(days=3)
        reg = make_reg(early_override_until=(later + timedelta(hours=5)).isoformat())
        q = fs.current_price(make_funnel(), reg, later)
        assert q.tier == "early" and q.amount == 5000.0

    def test_FUN_U_05_closed_after_registration_close_and_when_not_active(self):
        assert fs.current_price(make_funnel(), make_reg(), CLOSE).status == "closed"
        assert fs.current_price(make_funnel(status="draft"), make_reg(), NOW).status == "closed"

    def test_FUN_U_06_group_price_and_bad_seats(self):
        q = fs.current_price(make_funnel(), make_reg(), NOW, seats=3)
        assert (q.tier, q.amount, q.seats) == ("group", 12000.0, 3)
        q2 = fs.current_price(make_funnel(), make_reg(), NOW, seats=5)
        assert q2.tier == "early" and q2.seats == 1

    def test_FUN_U_07_early_end_capped_at_registration_close(self):
        reg = make_reg(first_message_at=(CLOSE - timedelta(hours=2)).isoformat())
        q = fs.current_price(make_funnel(), reg, CLOSE - timedelta(hours=1))
        assert q.early_ends_at == CLOSE


# ═══════════════════════════ Parsing & rendering ═══════════════════════════

class TestParsing:
    @pytest.mark.parametrize("text,code", [
        ("Hi, I want to join the class (B1)", "B1"),
        ("hello st5 please", "ST5"),
        ("Code: F7!", "F7"),
        ("B10 is not B1-x", "B1"),
        ("B10 only", None),
        ("nothing here", None),
    ])
    def test_FUN_U_08_ad_code(self, text, code):
        assert fs.parse_ad_code(text, make_funnel()["ad_codes"]) == code

    def test_FUN_U_09_ref_and_email(self):
        assert fs.parse_ref_codes("hi, code tr4821 sent me") == ["TR4821"]
        assert fs.parse_email("my mail is Ada.Obi@Gmail.com thanks") == "ada.obi@gmail.com"
        assert fs.parse_email("no email") is None

    def test_FUN_U_10_render_drops_empty_lines_and_never_double_expands(self):
        ctx = {"name": "{pay_link}", "pay_link": "https://x", "bonus_link": ""}
        out = fs.render("Hi {name}\n🎁 Pack: {bonus_link}\nKeep {unknown}", ctx)
        assert out == "Hi {pay_link}\nKeep {unknown}"

    def test_FUN_U_11_context_price_line_and_links(self):
        ctx = fs.build_context(make_funnel(), make_reg(), NOW)
        assert ctx["price"] == "₦5,000" and ctx["regular_price"] == "₦7,500"
        assert "₦5,000" in ctx["price_line"] and "₦7,500 after" in ctx["price_line"]
        assert ctx["pay_link"].endswith("/f/tok_abc")
        assert ctx["group_pay_link"].endswith("/f/tok_abc?seats=3")
        assert ctx["name"] == "Ada"
        ctx2 = fs.build_context(make_funnel(), make_reg(), NOW + timedelta(days=2))
        assert ctx2["price_line"] == "💰 *₦7,500*" and ctx2["deadline"] == ""

    def test_FUN_U_12_invalid_stored_step_is_skipped_not_fatal(self):
        f = make_funnel(sequence=[{"key": "BAD KEY", "anchor": "first_message", "offset_minutes": 1, "text": "x"},
                                  {"key": "ok", "anchor": "first_message", "offset_minutes": 1, "text": "x"}])
        assert [s["key"] for s in fs.funnel_sequence(f)] == ["ok"]

    def test_FUN_U_13_default_sequence_follows_mode(self):
        assert any(s["anchor"] == "window_end" for s in fs.funnel_sequence(make_funnel()))
        f = make_funnel(pricing_mode="deadline", early_deadline_at=NOW.isoformat())
        assert any(s["anchor"] == "early_deadline" for s in fs.funnel_sequence(f))


# ═══════════════════════════ Sequence planning ═══════════════════════════

class TestPlan:
    def steps(self, f=None):
        return fs.funnel_sequence(f or make_funnel())

    def test_FUN_U_14_checkin_due_at_3h_as_text(self):
        p = fs.plan_next_step(make_funnel(), make_reg(), self.steps(), NOW + timedelta(hours=3, minutes=1))
        assert (p.action, p.step["key"], p.channel) == ("send", "checkin_3h", "text")

    def test_FUN_U_15_nothing_due_before_3h(self):
        p = fs.plan_next_step(make_funnel(), make_reg(), self.steps(), NOW + timedelta(hours=2))
        assert p.action == "none"

    def test_FUN_U_16_paused_after_reply_waits(self):
        t = NOW + timedelta(hours=3, minutes=5)
        reg = make_reg(paused_until=(t + timedelta(minutes=30)).isoformat())
        assert fs.plan_next_step(make_funnel(), reg, self.steps(), t).action == "wait"

    def test_FUN_U_17_stale_step_skipped(self):
        reg = make_reg(done_steps=[])
        p = fs.plan_next_step(make_funnel(), reg, self.steps(), NOW + timedelta(hours=10))
        assert (p.action, p.reason, p.step["key"]) == ("skip", "stale", "checkin_3h")

    def test_FUN_U_18_early_reminder_skipped_once_early_price_gone(self):
        f = make_funnel()
        reg = make_reg(done_steps=["checkin_3h"], first_message_at=(NOW - timedelta(hours=24, minutes=1)).isoformat())
        p = fs.plan_next_step(f, reg, self.steps(f), NOW)
        assert p.step["key"] == "early_ends" and p.action == "skip"

    def test_FUN_U_19_window_closed_uses_template_when_24h_window_shut(self):
        first = NOW - timedelta(hours=25, minutes=5)
        reg = make_reg(first_message_at=first.isoformat(), last_inbound_at=first.isoformat(),
                       done_steps=["checkin_3h", "early_ends"])
        p = fs.plan_next_step(make_funnel(), reg, self.steps(), NOW)
        assert (p.action, p.step["key"], p.channel) == ("send", "window_closed", "template")

    def test_FUN_U_20_no_template_outside_window_skips(self):
        first = NOW - timedelta(hours=25, minutes=5)
        f = make_funnel(sequence=[{"key": "x", "anchor": "window_end", "offset_minutes": 60, "text": "hi"}])
        reg = make_reg(first_message_at=first.isoformat(), last_inbound_at=first.isoformat())
        p = fs.plan_next_step(f, reg, fs.funnel_sequence(f), NOW)
        assert (p.action, p.reason) == ("skip", "window_closed_no_template")

    def test_FUN_U_21_event_reminder_before_join_is_skipped(self):
        joined = EVENT - timedelta(hours=20)       # joined Sat morning; Thu/Fri reminders are in the past
        reg = make_reg(first_message_at=joined.isoformat(), last_inbound_at=joined.isoformat(),
                       done_steps=["checkin_3h", "early_ends", "window_closed"])
        p = fs.plan_next_step(make_funnel(), reg, self.steps(), joined + timedelta(minutes=5))
        assert p.action == "skip" and p.reason in ("before_join", "stale")

    def test_FUN_U_22_paid_lead_gets_no_unpaid_steps(self):
        reg = make_reg(status="paid")
        assert fs.plan_next_step(make_funnel(), reg, self.steps(), NOW + timedelta(hours=3, minutes=1)).action == "none"

    def test_FUN_U_23_quiet_hours_and_daily_cap_wait(self):
        t = NOW + timedelta(hours=3, minutes=1)
        assert fs.plan_next_step(make_funnel(), make_reg(), self.steps(), t, quiet=True).action == "wait"
        first = NOW - timedelta(hours=25, minutes=5)
        reg = make_reg(first_message_at=first.isoformat(), done_steps=["checkin_3h", "early_ends"])
        assert fs.plan_next_step(make_funnel(), reg, self.steps(), NOW, sent_last_24h=1).reason == "daily_cap"

    def test_FUN_U_24_window_anchor_not_applicable_in_deadline_mode(self):
        f = make_funnel(pricing_mode="deadline", early_deadline_at=(NOW + timedelta(days=2)).isoformat(),
                        sequence=[{"key": "w", "anchor": "window_end", "offset_minutes": 0, "text": "x"}])
        p = fs.plan_next_step(f, make_reg(), fs.funnel_sequence(f), NOW)
        assert (p.action, p.reason) == ("skip", "anchor_not_applicable")


# ═══════════════════════════ Inbound flow ═══════════════════════════

def _fake_create_lead(fake):
    def _create(db=None, org_id=None, user_id=None, payload=None, **kw):
        row = {"id": LEAD_ID, "org_id": org_id, "full_name": payload.full_name, "whatsapp": payload.whatsapp,
               "phone": payload.phone, "utm_ad": kw.get("utm_ad"), "deleted_at": None}
        fake.tables["leads"].append(row)
        return row
    return _create


class TestInbound:
    def _inbound(self, db, text, interactive=None, referral=None, now=NOW):
        fs.handle_inbound(db, dict(NUMBER), PHONE, "Ada Obi", "interactive" if interactive else "text",
                          text, "wamid.in." + text[:5], interactive, referral, now=now)

    def test_FUN_U_25_new_lead_gets_greeting_pay_button_and_faq(self, meta):
        db = base_db()
        with patch("app.services.lead_service.create_lead", side_effect=_fake_create_lead(db)) as cl:
            self._inbound(db, "Hi, I want to join the class (B1)", referral={"ctwa_clid": "CLID1", "headline": "Ad"})
        reg = db.rows("funnel_registrations")[0]
        assert reg["ad_code"] == "B1" and reg["ctwa_clid"] == "CLID1" and reg["lead_id"] == LEAD_ID
        assert reg["org_id"] == ORG_ID and len(reg["pay_token"]) >= 30 and len(reg["ref_code"]) == 6
        assert cl.call_args.kwargs["utm_ad"] == "B1" and cl.call_args.kwargs["org_id"] == ORG_ID
        assert _types(meta) == ["interactive:cta_url", "interactive:button"]
        cta = meta.call_args_list[0].args[1]["interactive"]
        assert cta["action"]["parameters"]["display_text"] == "Pay ₦5,000"
        assert cta["action"]["parameters"]["url"].endswith("/f/" + reg["pay_token"])
        assert meta.call_args_list[0].kwargs["token"] == "tok"          # funnel number's own token
        assert [m["direction"] for m in db.rows("whatsapp_messages")] == ["inbound", "outbound", "outbound"]

    def test_FUN_U_26_existing_lead_faq_pay_and_handoff(self, meta):
        db = base_db(funnel_registrations=[make_reg()])
        self._inbound(db, "What will I learn?", interactive={"type": "button_reply",
                      "button_reply": {"id": "faq_learn", "title": "What will I learn?"}})
        assert "ChatGPT" in meta.call_args.args[1]["text"]["body"]
        self._inbound(db, "please send the payment link")
        assert _types(meta)[-1] == "interactive:cta_url"
        self._inbound(db, "Can I pay with my aunt's card from UK?")
        reg = db.rows("funnel_registrations")[0]
        assert reg["needs_human"] is True
        assert len(db.rows("notifications")) == 1
        n_before = meta.call_count
        self._inbound(db, "hello??")                     # 2nd unknown within 6h → no second ack
        assert meta.call_count == n_before
        assert reg["paused_until"] is not None

    def test_FUN_U_27_group_offer_uses_group_link(self, meta):
        db = base_db(funnel_registrations=[make_reg()])
        self._inbound(db, "can 3 of us pay as a group?")
        url = meta.call_args.args[1]["interactive"]["action"]["parameters"]["url"]
        assert url.endswith("?seats=3")

    def test_FUN_U_28_opt_out_and_in(self, meta):
        db = base_db(funnel_registrations=[make_reg()], leads=[{"id": LEAD_ID, "org_id": ORG_ID}])
        self._inbound(db, "STOP")
        assert db.rows("funnel_registrations")[0]["status"] == "opted_out"
        assert db.rows("leads")[0]["whatsapp_opted_out"] is True
        self._inbound(db, "start")
        assert db.rows("funnel_registrations")[0]["status"] == "new"

    def test_FUN_U_29_paid_lead_email_captured(self, meta):
        db = base_db(funnel_registrations=[make_reg(status="paid", paid_at=NOW.isoformat())],
                     leads=[{"id": LEAD_ID, "org_id": ORG_ID}])
        self._inbound(db, "ada.obi@gmail.com")
        assert db.rows("funnel_registrations")[0]["email"] == "ada.obi@gmail.com"
        assert "ada.obi@gmail.com" in meta.call_args.args[1]["text"]["body"]

    def test_FUN_U_30_closed_funnel_and_no_funnel(self, meta):
        db = base_db(funnel_registrations=[make_reg()])
        self._inbound(db, "hi", now=CLOSE + timedelta(minutes=1))
        assert "closed" in meta.call_args.args[1]["text"]["body"]
        db2 = base_db(event_funnels=[make_funnel(status="closed")])
        self._inbound(db2, "hi")
        assert "isn't open" in meta.call_args.args[1]["text"]["body"]
        assert db2.rows("funnel_registrations") == []

    def test_FUN_U_31_referral_code_links_referrer(self, meta):
        referrer = make_reg(id="88888888-8888-8888-8888-888888888888", phone="2348000000000", ref_code="TR4821",
                            status="paid")
        db = base_db(funnel_registrations=[referrer])
        with patch("app.services.lead_service.create_lead", side_effect=_fake_create_lead(db)):
            self._inbound(db, "Hi, code TR4821 sent me")
        new = [r for r in db.rows("funnel_registrations") if r["phone"] == PHONE][0]
        assert new["referred_by_id"] == referrer["id"]

    def test_FUN_U_32_never_uses_another_orgs_funnel(self, meta):
        db = base_db(event_funnels=[make_funnel(org_id=OTHER_ORG)])
        self._inbound(db, "hi")
        assert db.rows("funnel_registrations") == []


# ═══════════════════════════ Pay link ═══════════════════════════

class TestPayRedirect:
    def _gen(self):
        n = {"i": 0}

        def gen(db, org_id, lead_id, amount, **kw):
            n["i"] += 1
            return {"checkout_url": f"https://checkout.paystack.com/x{n['i']}", "reference": f"ref{n['i']}",
                    "payment_link_id": None}
        return gen

    def test_FUN_U_33_redirect_creates_then_reuses_pending(self):
        db = base_db(funnel_registrations=[make_reg()])
        with patch("app.services.paystack_storefront_service.generate_payment_link", side_effect=self._gen()) as g:
            r1 = fs.get_pay_redirect(db, "tok_abc", now=NOW)
            r2 = fs.get_pay_redirect(db, "tok_abc", now=NOW + timedelta(minutes=5))
        assert r1.kind == "redirect" and r1.url == r2.url and g.call_count == 1
        assert g.call_args.kwargs["amount"] == 5000.0 and g.call_args.kwargs["org_id"] == ORG_ID
        fp = db.rows("funnel_payments")[0]
        assert (fp["amount"], fp["tier"], fp["status"]) == (5000.0, "early", "pending")

    def test_FUN_U_34_price_changes_after_window_makes_new_link(self):
        db = base_db(funnel_registrations=[make_reg()])
        with patch("app.services.paystack_storefront_service.generate_payment_link", side_effect=self._gen()) as g:
            fs.get_pay_redirect(db, "tok_abc", now=NOW)
            fs.get_pay_redirect(db, "tok_abc", now=NOW + timedelta(hours=25))
        assert [c.kwargs["amount"] for c in g.call_args_list] == [5000.0, 7500.0]

    def test_FUN_U_35_group_closed_paid_notfound(self):
        db = base_db(funnel_registrations=[make_reg()])
        with patch("app.services.paystack_storefront_service.generate_payment_link", side_effect=self._gen()) as g:
            assert fs.get_pay_redirect(db, "tok_abc", seats=3, now=NOW).kind == "redirect"
            assert g.call_args.kwargs["amount"] == 12000.0
            assert fs.get_pay_redirect(db, "tok_abc", now=CLOSE).kind == "closed"
            assert fs.get_pay_redirect(db, "nope", now=NOW).kind == "not_found"
            assert fs.get_pay_redirect(db, "bad token!", now=NOW).kind == "not_found"
        db2 = base_db(funnel_registrations=[make_reg(status="paid")])
        r = fs.get_pay_redirect(db2, "tok_abc", now=NOW)
        assert r.kind == "already_paid" and r.group_link == "https://chat.whatsapp.com/PAID"


# ═══════════════════════════ Payment hook ═══════════════════════════

class TestPaymentHook:
    def _db(self, amount=5000.0, seats=1):
        return base_db(funnel_registrations=[make_reg()], funnel_payments=[{
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "org_id": ORG_ID, "funnel_id": FUNNEL_ID,
            "registration_id": make_reg()["id"], "reference": "ref1", "amount": amount, "tier": "early",
            "seats": seats, "status": "pending", "created_at": NOW.isoformat()}])

    def _verify(self, kobo, status="success"):
        return patch("app.services.paystack_storefront_service.verify_transaction",
                     return_value={"verified": True, "status": status, "data": {"status": status, "amount": kobo}})

    def test_FUN_U_36_confirms_seat_once(self, meta):
        db = self._db()
        with self._verify(500000):
            assert fs.on_payment_confirmed(db, ORG_ID, "ref1", now=NOW) is True
            assert fs.on_payment_confirmed(db, ORG_ID, "ref1", now=NOW) is True
        reg = db.rows("funnel_registrations")[0]
        assert (reg["status"], reg["amount_paid"], reg["price_tier_paid"]) == ("paid", 5000.0, "early")
        assert meta.call_count == 1
        body = meta.call_args.args[1]["text"]["body"]
        assert "https://chat.whatsapp.com/PAID" in body and "AB1234" in body and "Gmail" in body
        assert db.rows("funnel_payments")[0]["status"] == "paid"

    def test_FUN_U_37_underpaid_is_not_seated(self, meta):
        db = self._db()
        with self._verify(100000):
            fs.on_payment_confirmed(db, ORG_ID, "ref1", now=NOW)
        assert db.rows("funnel_registrations")[0]["status"] == "new"
        assert db.rows("funnel_payments")[0]["status"] == "mismatch"
        assert meta.call_count == 0 and len(db.rows("notifications")) == 1

    def test_FUN_U_38_non_funnel_reference_and_guard(self, meta):
        db = self._db()
        assert fs.on_payment_confirmed(db, ORG_ID, "other_ref") is False
        assert fs.is_funnel_reference(db, ORG_ID, "ref1") is True
        assert fs.is_funnel_reference(db, OTHER_ORG, "ref1") is False

    def test_FUN_U_39_group_payment_sets_seats(self, meta):
        db = self._db(amount=12000.0, seats=3)
        with self._verify(1200000):
            fs.on_payment_confirmed(db, ORG_ID, "ref1", now=NOW)
        assert db.rows("funnel_registrations")[0]["seats"] == 3


# ═══════════════════════════ Step execution ═══════════════════════════

class TestExecute:
    def test_FUN_U_40_claim_prevents_double_send(self, meta):
        db = base_db(funnel_registrations=[make_reg()])
        f, reg = make_funnel(), db.rows("funnel_registrations")[0]
        steps = fs.funnel_sequence(f)
        t = NOW + timedelta(hours=3, minutes=1)
        plan = fs.plan_next_step(f, reg, steps, t)
        assert fs.execute_step(db, f, NUMBER, dict(reg), plan, t) == "sent"
        assert fs.execute_step(db, f, NUMBER, dict(reg, done_steps=[]), plan, t) == "raced"
        assert meta.call_count == 1
        assert db.rows("funnel_registrations")[0]["done_steps"] == ["checkin_3h"]

    def test_FUN_U_41_template_step_sends_rendered_params(self, meta):
        first = NOW - timedelta(hours=25, minutes=5)
        db = base_db(funnel_registrations=[make_reg(first_message_at=first.isoformat(),
                                                    last_inbound_at=first.isoformat(),
                                                    done_steps=["checkin_3h", "early_ends"])])
        f, reg = make_funnel(), db.rows("funnel_registrations")[0]
        plan = fs.plan_next_step(f, reg, fs.funnel_sequence(f), NOW)
        assert fs.execute_step(db, f, NUMBER, dict(reg), plan, NOW) == "sent"
        tpl = meta.call_args.args[1]["template"]
        assert tpl["name"] == "window_closed"
        assert tpl["components"][0]["parameters"][0]["text"].endswith("/f/tok_abc")

    def test_FUN_U_42_failed_send_marked_failed(self):
        db = base_db(funnel_registrations=[make_reg()])
        f, reg = make_funnel(), db.rows("funnel_registrations")[0]
        t = NOW + timedelta(hours=3, minutes=1)
        plan = fs.plan_next_step(f, reg, fs.funnel_sequence(f), t)
        with patch("app.services.funnel_messaging._call_meta_send", side_effect=Exception("503")):
            assert fs.execute_step(db, f, NUMBER, dict(reg), plan, t) == "failed"
        assert db.rows("funnel_events")[0]["type"] == "step_failed"
