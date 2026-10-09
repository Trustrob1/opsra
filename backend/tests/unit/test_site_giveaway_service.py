"""
tests/unit/test_site_giveaway_service.py
GIVEAWAY-1 — slot counter: create, public status, consent-gated open, claim on submit (first N win), idempotency.
"""
from __future__ import annotations

import pytest

from datetime import datetime, timedelta, timezone

from app.services import site_giveaway_service as svc
from app.services import site_partner_service
from tests.funnel_fake_db import FakeDB

ORG = "org-1"


def _setup(slots=5):
    db = FakeDB(site_builders=[], site_partners=[], site_giveaways=[], site_giveaway_entries=[], site_brief_forms=[], sites=[],
                site_orders=[], site_builder_settings=[], site_presets=[], whatsapp_numbers=[], notifications=[])
    partner = site_partner_service.create_partner(db, ORG, "Group Owner", "08030000001", "go@example.com", "Lagos Biz Hub")
    g = svc.create_giveaway(db, ORG, partner["id"], "Free Website Giveaway", slots)
    return db, partner, g


_n = {"i": 0}


def _c(phone=None):
    """a fresh member contact (a new WhatsApp number each call unless one is given)"""
    _n["i"] += 1
    return {"name": "Ada Obi", "phone": phone or f"0803{_n['i']:07d}", "email": "ada@example.com"}


def _open(db, g, phone=None):
    r = svc.open_entry(db, g["slug"], True, _c(phone))
    assert r["kind"] == "ok", r
    form = db.rows("site_brief_forms")[-1]
    return form


class TestCreate:
    def test_create_and_link(self):
        db, p, g = _setup()
        assert g["link_url"].endswith("/g/" + g["slug"]) and g["left"] == 5 and g["total_slots"] == 5

    @pytest.mark.parametrize("title,slots", [("x", 5), ("Valid title", 0), ("Valid title", 101), ("Valid title", "abc")])
    def test_validation(self, title, slots):
        db, p, _ = _setup()
        with pytest.raises(svc.GiveawayError):
            svc.create_giveaway(db, ORG, p["id"], title, slots)

    def test_unknown_or_suspended_partner(self):
        db, p, _ = _setup()
        with pytest.raises(svc.GiveawayError):
            svc.create_giveaway(db, ORG, "nope", "Valid title", 5)
        site_partner_service.set_status(db, ORG, p["id"], "suspended")
        with pytest.raises(svc.GiveawayError):
            svc.create_giveaway(db, ORG, p["id"], "Valid title", 5)


class TestPublicAndOpen:
    def test_public_status(self):
        db, p, g = _setup()
        d = svc.get_public(db, g["slug"])
        assert d["left"] == 5 and d["open"] and d["owner_name"] == "Lagos Biz Hub"
        assert "partner_id" not in d and "org_id" not in d
        assert svc.get_public(db, "nope-nope") is None

    def test_open_needs_consent(self):
        db, p, g = _setup()
        assert svc.open_entry(db, g["slug"], False, _c())["kind"] == "consent_required"
        assert db.rows("site_brief_forms") == []

    def test_open_makes_a_client_form_owned_by_the_group_owner(self):
        db, p, g = _setup()
        form = _open(db, g)
        assert form["builder_id"] == p["builder_id"] and form["audience"] == "client"
        e = db.rows("site_giveaway_entries")[0]
        assert e["status"] == "opened" and e["consent_at"] and e.get("position") is None

    def test_opening_does_not_use_a_slot(self):
        db, p, g = _setup()
        for _ in range(8):
            _open(db, g)
        assert svc.get_public(db, g["slug"])["left"] == 5

    def test_closed_giveaway(self):
        db, p, g = _setup()
        svc.set_status(db, ORG, g["id"], "closed")
        assert svc.open_entry(db, g["slug"], True, _c())["kind"] == "closed"

    def test_suspended_owner_closes_it(self):
        db, p, g = _setup()
        site_partner_service.set_status(db, ORG, p["id"], "suspended")
        assert svc.open_entry(db, g["slug"], True, _c())["kind"] == "closed"


class TestClaim:
    def test_first_n_win_then_full(self):
        db, p, g = _setup(slots=3)
        forms = [_open(db, g) for _ in range(5)]
        for f in forms[:3]:
            e = svc.claim_slot(db, f)
            assert e["status"] == "winner"
        assert sorted(e["position"] for e in db.rows("site_giveaway_entries") if e["status"] == "winner") == [1, 2, 3]
        with pytest.raises(svc.GiveawayFull):
            svc.claim_slot(db, forms[3])
        d = svc.get_public(db, g["slug"])
        assert d["left"] == 0 and d["open"] is False
        assert svc.open_entry(db, g["slug"], True, _c())["kind"] == "full"

    def test_opened_order_does_not_matter_only_submit_order(self):
        db, p, g = _setup(slots=1)
        a, b = _open(db, g), _open(db, g)
        assert svc.claim_slot(db, b)["position"] == 1
        with pytest.raises(svc.GiveawayFull):
            svc.claim_slot(db, a)

    def test_claim_is_idempotent(self):
        db, p, g = _setup(slots=2)
        f = _open(db, g)
        first = svc.claim_slot(db, f)
        again = svc.claim_slot(db, f)
        assert first["id"] == again["id"] and svc.get_public(db, g["slug"])["taken"] == 1

    def test_plain_form_is_not_a_giveaway(self):
        db, p, g = _setup()
        assert svc.claim_slot(db, {"id": "some-other-form"}) is None

    def test_retries_when_a_position_was_taken_in_between(self, monkeypatch):
        db, p, g = _setup(slots=3)
        f = _open(db, g)
        real = db.table
        state = {"raced": False}

        def racing_table(name):
            q = real(name)
            if name == "site_giveaway_entries" and not state["raced"]:
                orig = q.update

                def upd(payload):
                    if payload.get("status") == "winner" and not state["raced"]:
                        state["raced"] = True
                        db.tables["site_giveaway_entries"].append(
                            {"id": "rival", "giveaway_id": g["id"], "position": payload["position"], "status": "winner"})
                    return orig(payload)
                q.update = upd
            return q
        monkeypatch.setattr(db, "table", racing_table)
        e = svc.claim_slot(db, f)
        assert e["position"] == 2

    def test_attach_site_and_entries_list(self):
        db, p, g = _setup()
        f = _open(db, g)
        e = svc.claim_slot(db, f)
        db.table("sites").insert({"id": "s1", "client_business_name": "Zed Shop", "status": "brief_complete"}).execute()
        svc.attach_site(db, e, "s1")
        rows = svc.entries(db, ORG, g["id"])
        assert rows[0]["business_name"] == "Zed Shop" and rows[0]["position"] == 1
        listed = svc.list_giveaways(db, ORG)[0]
        assert listed["taken"] == 1 and listed["left"] == 4 and listed["owner_name"] == "Lagos Biz Hub"


class TestFeeAndTerms:
    def test_defaults_and_custom(self):
        db, p, g = _setup()
        assert g["fee_ngn"] == 24500 and g["renewal_ngn"] == 25000
        g2 = svc.create_giveaway(db, ORG, p["id"], "Second giveaway", 3, 30000, 28000)
        assert g2["fee_ngn"] == 30000 and g2["renewal_ngn"] == 28000

    @pytest.mark.parametrize("fee", [500, 99_999_999, "abc"])
    def test_fee_bounds(self, fee):
        db, p, _ = _setup()
        with pytest.raises(svc.GiveawayError):
            svc.create_giveaway(db, ORG, p["id"], "Valid title", 5, fee)

    def test_public_shows_fee_renewal_and_edit_terms(self):
        db, p, g = _setup()
        db.tables["site_presets"].extend([{"org_id": ORG, "is_active": True, "max_items": 40}, {"org_id": ORG, "is_active": True, "max_items": 30}])
        d = svc.get_public(db, g["slug"])
        assert d["fee_ngn"] == 24500 and d["renewal_ngn"] == 25000
        t = d["terms"]
        assert t["free_edits"] == 5 and t["care_price_ngn"] == 5000 and t["pack_price_ngn"] == 1500 and t["pack_edits"] == 5
        assert t["edit_item_cap"] == 10 and t["max_items"] == 30


class TestContact:
    def test_name_email_whatsapp_required(self):
        db, p, g = _setup()
        for bad in ({"name": "", "phone": "08031234567", "email": "a@b.com"},
                    {"name": "Ada", "phone": "08031234567", "email": "nope"},
                    {"name": "Ada", "phone": "abc", "email": "a@b.com"}, None):
            r = svc.open_entry(db, g["slug"], True, bad)
            assert r["kind"] == "invalid" and r["message"]
        assert db.rows("site_brief_forms") == []

    def test_contact_saved_on_the_entry_with_one_phone_spelling(self):
        db, p, g = _setup()
        _open(db, g, "+234 803 123 4567")
        assert db.rows("site_giveaway_entries")[0]["contact_phone"] == "2348031234567"

    def test_one_slot_per_whatsapp_number(self):
        db, p, g = _setup()
        a, b = _open(db, g, "08031234567"), _open(db, g, "+2348031234567")
        assert svc.claim_slot(db, a)["status"] == "winner"
        with pytest.raises(svc.GiveawayDuplicate):
            svc.claim_slot(db, b)
        assert svc.open_entry(db, g["slug"], True, _c("08031234567"))["kind"] == "duplicate"
        assert svc.get_public(db, g["slug"])["taken"] == 1


class TestVoid:
    def test_void_frees_slot_and_number_and_kills_the_link(self):
        db, p, g = _setup(slots=1)
        f = _open(db, g, "08031234567")
        e = svc.claim_slot(db, f)
        raw = e["_winner_token"]
        db.table("sites").insert({"id": "s1", "org_id": ORG, "client_business_name": "Zed", "status": "brief_complete", "slug": "zed"}).execute()
        svc.attach_site(db, e, "s1")
        svc.void_slot(db, ORG, g["id"], 1)
        assert svc.get_public(db, g["slug"])["left"] == 1
        with pytest.raises(svc.WinnerError):
            svc.winner_view(db, raw)
        assert db.rows("sites")[0].get("deleted_at")
        f2 = _open(db, g, "08031234567")                 # the same number may enter again
        assert svc.claim_slot(db, f2)["position"] == 1

    def test_cannot_void_after_payment(self):
        db, p, g = _setup()
        e = svc.claim_slot(db, _open(db, g))
        db.table("sites").insert({"id": "s1", "client_business_name": "Zed", "status": "paid"}).execute()
        svc.attach_site(db, e, "s1")
        db.table("site_orders").insert({"id": "o1", "site_id": "s1", "kind": "initial", "status": "fulfilling"}).execute()
        with pytest.raises(svc.GiveawayError):
            svc.void_slot(db, ORG, g["id"], 1)
        with pytest.raises(svc.GiveawayError):
            svc.void_slot(db, ORG, g["id"], 4)


def _winner(db, g, status="preview_ready"):
    e = svc.claim_slot(db, _open(db, g))
    db.table("sites").insert({"id": "s1", "org_id": ORG, "client_business_name": "Zed Shop", "status": status, "slug": "zed-shop",
                              "rendered_html": "<html></html>"}).execute()
    svc.attach_site(db, e, "s1")
    return e["_winner_token"]


class TestWinnerPage:
    def test_token_is_issued_once_and_only_its_hash_is_stored(self):
        db, p, g = _setup()
        e = svc.claim_slot(db, _open(db, g))
        raw = e["_winner_token"]
        stored = db.rows("site_giveaway_entries")[0]["winner_token_hash"]
        assert stored and raw not in str(db.rows("site_giveaway_entries"))
        with pytest.raises(svc.WinnerError) as x:
            svc.winner_view(db, "wrong-token")
        assert x.value.status_code == 404

    def test_stages(self):
        db, p, g = _setup()
        tok = _winner(db, g, "generating")
        assert svc.winner_view(db, tok)["stage"] == "building" and svc.winner_view(db, tok)["can_pay"] is False
        db.table("sites").update({"status": "preview_ready"}).eq("id", "s1").execute()
        v = svc.winner_view(db, tok)
        assert v["stage"] == "preview" and v["can_pay"] and v["preview_url"].endswith("/s/zed-shop")
        assert v["fee_ngn"] == 24500 and v["terms"]["edit_item_cap"] == 10
        assert "winner_token_hash" not in v and "org_id" not in str(v.keys())
        db.table("site_orders").insert({"id": "o1", "site_id": "s1", "kind": "initial", "status": "fulfilling"}).execute()
        assert svc.winner_view(db, tok)["stage"] == "going_live"
        db.table("sites").update({"status": "live", "live_url": "https://zed.ng"}).eq("id", "s1").execute()
        v = svc.winner_view(db, tok)
        assert v["stage"] == "live" and v["live_url"] == "https://zed.ng"

    def test_on_won_sends_email_and_alerts_staff(self, monkeypatch):
        db, p, g = _setup()
        sent, alerts = [], []
        from app.services import site_partner_apply_service as apply_svc, funnel_service
        monkeypatch.setattr(apply_svc, "_send_email", lambda to, subj, text: sent.append((to, text)) or True)
        monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: alerts.append(a))
        e = svc.claim_slot(db, _open(db, g))
        url = svc.on_won(db, e, "Zed Shop")
        assert url and "/w/" in url and sent and url in sent[0][1] and sent[0][0] == "ada@example.com"
        assert alerts and "Zed Shop" in alerts[0][2]
        assert svc.on_won(db, None) is None and svc.on_won(db, {**e, "_winner_token": None}) is None


class TestWinnerCheckout:
    BODY = {"domain": "zedshop.ng", "backup_domain": "zedshop.com.ng", "accepted_terms": True,
            "legal_owner": {"full_name": "Ada Obi", "email": "ada@example.com", "phone": "08031234567", "address": "1 Allen Ave, Ikeja"}}

    def _patch(self, monkeypatch):
        from app.services import site_order_service, site_access_service
        calls = []
        monkeypatch.setattr(site_access_service, "ensure_lead", lambda db, org, b: "lead-1")
        monkeypatch.setattr(site_order_service, "create_checkout",
                            lambda db, org, b, payload, fixed_amount=None: calls.append((payload, fixed_amount)) or
                            {"checkout_url": "https://pay.test/x", "reference": "r1", "order_id": "o9", "amount": fixed_amount})
        return calls

    def test_pays_the_giveaway_fee_never_a_browser_amount(self, monkeypatch):
        db, p, g = _setup()
        db.table("site_giveaways").update({"fee_ngn": 31000}).eq("id", g["id"]).execute()
        tok = _winner(db, g)
        calls = self._patch(monkeypatch)
        out = svc.winner_checkout(db, tok, {**self.BODY, "amount": 1, "fixed_amount": 1})
        assert out["checkout_url"] == "https://pay.test/x" and out["amount"] == 31000
        payload, fixed = calls[0]
        assert fixed == 31000 and payload.site_id == "s1" and payload.route == "standard"

    def test_blocked_until_preview_and_after_payment(self, monkeypatch):
        db, p, g = _setup()
        tok = _winner(db, g, "generating")
        self._patch(monkeypatch)
        with pytest.raises(svc.WinnerError) as x:
            svc.winner_checkout(db, tok, self.BODY)
        assert x.value.code == "NOT_READY"
        db.table("sites").update({"status": "preview_ready"}).eq("id", "s1").execute()
        db.table("site_orders").insert({"id": "o1", "site_id": "s1", "kind": "initial", "status": "awaiting_approval"}).execute()
        with pytest.raises(svc.WinnerError) as x:
            svc.winner_checkout(db, tok, self.BODY)
        assert x.value.code == "ALREADY_PAID"

    def test_bad_details_and_terms(self, monkeypatch):
        db, p, g = _setup()
        tok = _winner(db, g)
        calls = self._patch(monkeypatch)
        for bad in ({**self.BODY, "accepted_terms": False}, {**self.BODY, "backup_domain": "zedshop.ng"},
                    {**self.BODY, "legal_owner": {**self.BODY["legal_owner"], "email": "nope"}}, {}):
            with pytest.raises(svc.WinnerError) as x:
                svc.winner_checkout(db, tok, bad)
            assert x.value.status_code == 422
        assert calls == []

    def test_domain_check_uses_a_giveaway_rate_key(self, monkeypatch):
        db, p, g = _setup()
        tok = _winner(db, g)
        from app.services import domain_check_service
        seen = []
        monkeypatch.setattr(domain_check_service, "check_domain", lambda db_, org, key, dom: seen.append((org, key, dom)) or {"domain": dom, "available": True})
        assert svc.winner_domain_check(db, tok, "zedshop.ng")["available"] is True
        assert seen[0][1].startswith("giveaway:")


NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


def _ready(db, g, status="preview_ready"):
    tok = _winner(db, g, status)
    return tok, db.rows("site_giveaway_entries")[0]


class TestPayByDeadline:
    def test_default_and_custom_days_and_bounds(self):
        db, p, g = _setup()
        assert g["pay_by_days"] == 3 and svc.get_public(db, g["slug"])["pay_by_days"] == 3
        assert svc.create_giveaway(db, ORG, p["id"], "Another one", 5, None, None, 7)["pay_by_days"] == 7
        for bad in (0, 31, "x"):
            with pytest.raises(svc.GiveawayError):
                svc.create_giveaway(db, ORG, p["id"], "Another one", 5, None, None, bad)

    def test_clock_starts_when_the_winner_first_sees_the_preview(self):
        db, p, g = _setup()
        tok, _ = _ready(db, g)
        assert db.rows("site_giveaway_entries")[0].get("preview_ready_at") is None
        v = svc.winner_view(db, tok)
        assert v["stage"] == "preview" and v["pay_by"] and v["pay_by_days"] == 3
        started = db.rows("site_giveaway_entries")[0]["preview_ready_at"]
        svc.winner_view(db, tok)
        assert db.rows("site_giveaway_entries")[0]["preview_ready_at"] == started      # not restarted

    def test_sweep_starts_the_clock_but_does_nothing_before_the_reminder(self):
        db, p, g = _setup()
        _ready(db, g)
        r = svc.run_deadlines(db, NOW)
        assert r["reminded"] == 0 and r["released"] == 0
        assert db.rows("site_giveaway_entries")[0]["preview_ready_at"]

    def test_reminder_once_then_the_slot_lapses_at_the_pay_by_time(self, monkeypatch):
        db, p, g = _setup()
        tok, _ = _ready(db, g)
        sent, alerts = [], []
        monkeypatch.setattr(svc, "_send_to_contact", lambda db_, e, subj, text: sent.append((subj, text)) or True)
        from app.services import funnel_service
        monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: alerts.append(a))
        svc.run_deadlines(db, NOW)                                              # clock starts at NOW
        r = svc.run_deadlines(db, NOW + timedelta(days=2, hours=2))             # 22h left
        assert r["reminded"] == 1 and "waiting" in sent[0][0] and "65,000" in sent[0][1]
        assert svc.run_deadlines(db, NOW + timedelta(days=2, hours=5))["reminded"] == 0     # only once
        r = svc.run_deadlines(db, NOW + timedelta(days=3, minutes=1))
        assert r["lapsed"] == 1 and r["released"] == 0 and "slot has ended" in sent[-1][0] and alerts
        e = db.rows("site_giveaway_entries")[0]
        assert e["status"] == "lapsed" and e.get("position") is None and e.get("lapsed_at")
        assert not db.rows("sites")[0].get("deleted_at")                        # the site is kept
        assert svc.get_public(db, g["slug"])["left"] == 5                       # the slot is open again
        v = svc.winner_view(db, tok, NOW + timedelta(days=3, minutes=2))        # the link still works, at the normal rate
        assert v["stage"] == "preview" and v["can_pay"] is True
        assert v["price_mode"] == "full" and v["fee_ngn"] == 65000 and v["slot_released"] is True

    def test_normal_rate_is_charged_after_the_pay_by_time(self, monkeypatch):
        db, p, g = _setup()
        tok, _ = _ready(db, g)
        svc.winner_view(db, tok, NOW)
        before = svc.winner_view(db, tok, NOW + timedelta(days=1))
        assert before["price_mode"] == "giveaway" and before["fee_ngn"] == before["giveaway_fee_ngn"]
        late = svc.winner_view(db, tok, NOW + timedelta(days=3, hours=1))      # past the deadline, before the sweep runs
        assert late["price_mode"] == "full" and late["fee_ngn"] == 65000

    def test_takedown_reminder_then_takedown_after_the_extra_days(self, monkeypatch):
        db, p, g = _setup()
        tok, _ = _ready(db, g)
        sent = []
        monkeypatch.setattr(svc, "_send_to_contact", lambda db_, e, subj, text: sent.append(subj) or True)
        from app.services import funnel_service
        monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: None)
        svc.run_deadlines(db, NOW)
        svc.run_deadlines(db, NOW + timedelta(days=3, minutes=1))               # lapsed
        r = svc.run_deadlines(db, NOW + timedelta(days=6, hours=2))             # 22h to takedown
        assert r["reminded"] == 1 and "taken down soon" in sent[-1]
        assert svc.run_deadlines(db, NOW + timedelta(days=6, hours=5))["reminded"] == 0
        r = svc.run_deadlines(db, NOW + timedelta(days=7, minutes=1))
        assert r["released"] == 1 and "taken down" in sent[-1]
        e = db.rows("site_giveaway_entries")[0]
        assert e["status"] == "voided" and e["void_reason"] == "expired"
        assert db.rows("sites")[0].get("deleted_at")
        v = svc.winner_view(db, tok, NOW + timedelta(days=7, minutes=2))
        assert v["stage"] == "expired" and v["can_pay"] is False
        with pytest.raises(svc.WinnerError) as x:
            svc.winner_checkout(db, tok, TestWinnerCheckout.BODY)
        assert x.value.status_code == 410

    def test_lapsed_number_still_cannot_take_another_slot(self, monkeypatch):
        db, p, g = _setup(slots=2)
        monkeypatch.setattr(svc, "_send_to_contact", lambda *a, **k: True)
        from app.services import funnel_service
        monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: None)
        e = svc.claim_slot(db, _open(db, g, "08031234567"))
        db.table("sites").insert({"id": "s1", "org_id": ORG, "client_business_name": "Zed", "status": "preview_ready"}).execute()
        svc.attach_site(db, e, "s1")
        svc.run_deadlines(db, NOW)
        svc.run_deadlines(db, NOW + timedelta(days=4))
        assert svc.get_public(db, g["slug"])["left"] == 2
        assert db.rows("site_giveaway_entries")[0]["status"] == "lapsed"
        with pytest.raises(Exception):
            svc.claim_slot(db, _open(db, g, "08031234567"))

    def test_paid_winner_is_never_touched(self, monkeypatch):
        db, p, g = _setup()
        _ready(db, g)
        db.table("site_orders").insert({"id": "o1", "site_id": "s1", "kind": "initial", "status": "fulfilling"}).execute()
        monkeypatch.setattr(svc, "_send_to_contact", lambda *a, **k: pytest.fail("must not message"))
        svc.run_deadlines(db, NOW)
        r = svc.run_deadlines(db, NOW + timedelta(days=30))
        assert r["released"] == 0 and r["lapsed"] == 0
        assert db.rows("site_giveaway_entries")[0]["status"] == "winner"

    def test_a_payment_link_opened_in_the_last_day_gives_more_time(self, monkeypatch):
        db, p, g = _setup()
        _ready(db, g)
        monkeypatch.setattr(svc, "_send_to_contact", lambda *a, **k: True)
        from app.services import funnel_service
        monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: None)
        svc.run_deadlines(db, NOW)
        late = NOW + timedelta(days=3, hours=1)
        db.table("site_orders").insert({"id": "o1", "site_id": "s1", "kind": "initial", "status": "pending_payment",
                                        "created_at": (late - timedelta(hours=2)).isoformat()}).execute()
        assert svc.run_deadlines(db, late)["lapsed"] == 0
        assert svc.run_deadlines(db, late + timedelta(hours=30))["lapsed"] == 1
        assert db.rows("site_orders")[0]["status"] == "expired"

    def test_custom_normal_rate_and_days_with_bounds(self):
        db, p, g = _setup()
        assert g["full_price_ngn"] == 65000 and g["full_price_days"] == 4
        r = svc.create_giveaway(db, ORG, p["id"], "Another one", 5, None, None, None, None, None, 50000, 6)
        assert r["full_price_ngn"] == 50000 and r["full_price_days"] == 6
        for bad_ngn, bad_days in ((500, 4), (65000, 0), (65000, 31)):
            with pytest.raises(svc.GiveawayError):
                svc.create_giveaway(db, ORG, p["id"], "Another one", 5, None, None, None, None, None, bad_ngn, bad_days)

    def test_site_not_ready_is_ignored(self):
        db, p, g = _setup()
        _ready(db, g, "generating")
        assert svc.run_deadlines(db, NOW + timedelta(days=30))["released"] == 0

    def test_staff_view_shows_the_pay_by_time(self):
        db, p, g = _setup()
        tok, _ = _ready(db, g)
        svc.winner_view(db, tok)
        rows = svc.entries(db, ORG, g["id"])
        assert rows[0]["pay_by"] and rows[0]["paid"] is False and rows[0]["takedown_at"] is None


class TestWinnerMessages:
    def test_giveaway_site_messages_go_to_the_winner_not_the_owner(self, monkeypatch):
        db, p, g = _setup()
        _winner(db, g)
        sent = []
        monkeypatch.setattr(svc, "_send_to_contact", lambda db_, e, subj, text: sent.append((e["contact_email"], text)) or True)
        from app.services import site_order_service, whatsapp_service
        monkeypatch.setattr(whatsapp_service, "send_agent_text_message", lambda **k: pytest.fail("owner must not be messaged"))
        order = {"id": "o1", "site_id": "s1", "builder_id": p["builder_id"], "lead_id": "l1"}
        site_order_service._message_builder(db, ORG, order, "Your client's website is live: https://zed.ng")
        assert sent == [("ada@example.com", "Your website is live: https://zed.ng")]

    def test_a_normal_site_still_messages_its_builder(self, monkeypatch):
        db, p, g = _setup()
        db.table("site_builders").update({"phone_number": "+2348030000001"}).eq("id", p["builder_id"]).execute()
        from app.services import site_order_service, whatsapp_service
        calls = []
        monkeypatch.setattr(whatsapp_service, "send_agent_text_message", lambda **k: calls.append(k))
        site_order_service._message_builder(db, ORG, {"id": "o2", "site_id": "plain-site", "builder_id": p["builder_id"], "lead_id": "l"}, "hi")
        assert len(calls) == 1 and calls[0]["message"] == "hi"

    def test_order_without_a_site_is_not_a_giveaway_message(self):
        db, p, g = _setup()
        assert svc.message_winner(db, ORG, {"id": "o", "site_id": None}, "x") is False


class TestWinnerCatalog:
    def test_buying_items_needs_a_paid_site_and_uses_the_pack_checkout(self, monkeypatch):
        db, p, g = _setup()
        tok = _winner(db, g)
        from app.services import site_access_service, site_catalog_service
        monkeypatch.setattr(site_access_service, "ensure_lead", lambda *a: "lead-1")
        monkeypatch.setattr(site_catalog_service, "create_checkout",
                            lambda db_, org, b, site_id: {"checkout_url": "https://pay.test/c", "amount": 5000, "items": 30, "reused": False})
        with pytest.raises(svc.WinnerError) as x:
            svc.winner_catalog_checkout(db, tok)
        assert x.value.code == "NOT_READY"
        db.table("site_orders").insert({"id": "o1", "site_id": "s1", "kind": "initial", "status": "fulfilling"}).execute()
        assert svc.winner_catalog_checkout(db, tok)["items"] == 30
        v = svc.winner_view(db, tok)
        assert v["can_buy_items"] is True and v["terms"]["catalog_pack_items"] == 30 and v["terms"]["catalog_pack_price_ngn"] == 5000


class TestLostLink:
    def _sent(self, monkeypatch):
        sent = []
        monkeypatch.setattr(svc, "_send_to_contact", lambda db_, e, subj, text: sent.append((e["contact_email"], text)) or True)
        return sent

    def test_staff_resend_gives_a_new_working_link_and_kills_the_old_one(self, monkeypatch):
        db, p, g = _setup()
        old = _winner(db, g)
        sent = self._sent(monkeypatch)
        r = svc.resend_link(db, ORG, g["id"], 1)
        assert r["emailed"] is True and r["email"] == "ada@example.com"
        new = sent[0][1].split("/w/")[1].split()[0]
        assert svc.winner_view(db, new)["business_name"] == "Zed Shop"
        with pytest.raises(svc.WinnerError) as x:
            svc.winner_view(db, old)
        assert x.value.status_code == 404
        with pytest.raises(svc.GiveawayError):
            svc.resend_link(db, ORG, g["id"], 4)

    def test_winner_asks_with_their_number_in_any_spelling(self, monkeypatch):
        db, p, g = _setup()
        e = svc.claim_slot(db, _open(db, g, "08031234567"))
        old = e["_winner_token"]
        db.table("sites").insert({"id": "s1", "org_id": ORG, "client_business_name": "Zed", "status": "brief_complete"}).execute()
        svc.attach_site(db, e, "s1")
        sent = self._sent(monkeypatch)
        assert svc.request_link(db, g["slug"], "+234 803 123 4567", NOW) is True
        assert len(sent) == 1 and sent[0][0] == "ada@example.com"       # goes to the email they entered with, never elsewhere
        with pytest.raises(svc.WinnerError):
            svc.winner_view(db, old)

    def test_same_answer_for_a_stranger_and_nothing_is_sent(self, monkeypatch):
        db, p, g = _setup()
        _winner(db, g)
        sent = self._sent(monkeypatch)
        assert svc.request_link(db, g["slug"], "08099999999", NOW) is True
        assert svc.request_link(db, g["slug"], "not a number", NOW) is True
        assert svc.request_link(db, "no-such-giveaway", "08031234567", NOW) is False
        assert sent == []

    def test_cooldown_stops_repeated_requests(self, monkeypatch):
        db, p, g = _setup()
        e = svc.claim_slot(db, _open(db, g, "08031234567"))
        sent = self._sent(monkeypatch)
        svc.request_link(db, g["slug"], "08031234567", NOW)
        svc.request_link(db, g["slug"], "08031234567", NOW + timedelta(minutes=2))
        assert len(sent) == 1
        svc.request_link(db, g["slug"], "08031234567", NOW + timedelta(minutes=11))
        assert len(sent) == 2

    def test_a_released_winner_gets_nothing(self, monkeypatch):
        db, p, g = _setup()
        svc.claim_slot(db, _open(db, g, "08031234567"))
        svc.void_slot(db, ORG, g["id"], 1)
        sent = self._sent(monkeypatch)
        assert svc.request_link(db, g["slug"], "08031234567", NOW) is True
        assert sent == []


class TestCampaignAndClosing:
    """GIVEAWAY-4 — campaign name (flier headline) and optional closing time."""

    def _future(self, **kw):
        return (datetime.now(timezone.utc) + timedelta(**(kw or {"days": 2}))).isoformat()

    def _set_end(self, db, g, when):
        db.table("site_giveaways").update({"ends_at": when.isoformat()}).eq("id", g["id"]).execute()

    def test_campaign_name_is_stored_trimmed_and_public(self):
        db, p, _ = _setup()
        g = svc.create_giveaway(db, ORG, p["id"], "Valid title", 3, campaign_name="  Launch   Week  ")
        assert g["campaign_name"] == "Launch Week"
        assert svc.get_public(db, g["slug"])["campaign_name"] == "Launch Week"

    def test_campaign_name_optional_and_length_checked(self):
        db, p, _ = _setup()
        assert svc.create_giveaway(db, ORG, p["id"], "Valid title", 3, campaign_name="   ")["campaign_name"] is None
        for bad in ("ab", "x" * 61):
            with pytest.raises(svc.GiveawayError):
                svc.create_giveaway(db, ORG, p["id"], "Valid title", 3, campaign_name=bad)

    def test_ends_at_must_be_a_future_date(self):
        db, p, _ = _setup()
        g = svc.create_giveaway(db, ORG, p["id"], "Valid title", 3, ends_at=self._future())
        assert g["ends_at"]
        with pytest.raises(svc.GiveawayError):
            svc.create_giveaway(db, ORG, p["id"], "Valid title", 3, ends_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
        with pytest.raises(svc.GiveawayError):
            svc.create_giveaway(db, ORG, p["id"], "Valid title", 3, ends_at="not a date")

    def test_ended_giveaway_stops_new_forms_but_gives_grace_to_open_ones(self):
        db, p, _ = _setup()
        g = svc.create_giveaway(db, ORG, p["id"], "Valid title", 3, ends_at=self._future())
        form = _open(db, g)
        late_form = _open(db, g)
        now = datetime.now(timezone.utc)
        self._set_end(db, g, now - timedelta(hours=1))
        pub = svc.get_public(db, g["slug"])
        assert pub["ended"] is True and pub["open"] is False
        assert svc.open_entry(db, g["slug"], True, _c())["kind"] == "closed"
        assert svc.claim_slot(db, form)["status"] == "winner"          # inside the 6 h grace
        self._set_end(db, g, now - timedelta(hours=7))
        with pytest.raises(svc.GiveawayFull):
            svc.claim_slot(db, late_form)
