"""
tests/unit/test_site_order_service.py
----------------------------------------
SITE-3 part 2 — site_order_service. Every DB call is mocked (MagicMock) —
no real Supabase calls. Cross-service calls (pricing_service.quote,
paystack_storefront_service.generate_payment_link, lead_service.move_stage,
funnel_service.notify_managers, whatsapp_service.send_agent_text_message)
are monkeypatched at their OWN module (Pattern 63 — site_order_service
imports each of these lazily inside its functions via
`from app.services import X`, which binds the same singleton module object
Python already has in sys.modules, so patching that module's attribute
directly works regardless of where/when the lazy import happens).

T2/Pattern 59: where a mocked table needs two different results across two
`.execute()` calls in the same function (on_payment_confirmed's initial
SELECT then its claim UPDATE), the chain's `execute.side_effect` is a list —
never mixed with `execute.return_value` on the same mock.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services import site_order_service as svc
from app.services import funnel_service as funnel_svc
from app.services import lead_service as lead_svc
from app.services import paystack_storefront_service as pay_svc
from app.services import pricing_service as pricing_svc
from app.services import whatsapp_service as wa_svc

ORG_ID = "org-1"
BUILDER_ID = "builder-1"
SITE_ID = "site-1"
LEAD_ID = "lead-1"

_BUILDER = {"id": BUILDER_ID, "org_id": ORG_ID, "lead_id": LEAD_ID, "phone_number": "+2348030000000"}
_SITE_ROW = {"id": SITE_ID, "org_id": ORG_ID, "builder_id": BUILDER_ID, "deleted_at": None}

_QUOTE = {
    "route": "standard", "kind": "initial", "domain": "adaezastyles.com.ng", "tld": ".com.ng",
    "cost": {"domain": 5913, "hosting": 36765, "ai_messages": 400, "total": 43078},
    "price": {"domain": 11000, "hosting": 50000, "service_fee": 18500, "renewal_adjustment": 0, "total": 79500},
    "gateway_fee": 1293, "profit": 35130, "suggested_client_price": 150000, "live_within_hours": 24,
}


def _chain(data=None) -> MagicMock:
    result = MagicMock()
    result.data = data if data is not None else []
    m = MagicMock()
    for method in ("select", "insert", "update", "delete", "eq", "neq", "is_", "order",
                   "range", "limit", "maybe_single", "filter", "in_", "not_"):
        getattr(m, method).return_value = m
    m.execute.return_value = result
    return m


def _db_mock(**kwargs) -> MagicMock:
    db = MagicMock()
    db.table.side_effect = lambda name: kwargs.get(name, _chain())
    return db


class _Payload:
    """Stand-in for models.sites.CheckoutRequest — only the attributes
    create_checkout actually reads, since the real model's own validators
    are exercised at the integration layer, not here."""
    def __init__(self, domain="adaezastyles.com.ng", backup_domain="adaezastyles.ng", route="standard"):
        self.site_id = SITE_ID
        self.route = route
        self.domain = domain
        self.backup_domain = backup_domain
        self.accepted_terms = True
        self.legal_owner = _LegalOwner()


class _LegalOwner:
    def model_dump(self, mode="json"):
        return {"full_name": "Chioma Adaeze", "email": "chioma@example.com",
                "phone": "+2348030000000", "address": "14 Adeola Odeku St, Lagos"}


# ---------------------------------------------------------------------------
# create_checkout
# ---------------------------------------------------------------------------

class TestCreateCheckout:
    def test_happy_path_creates_order_and_returns_link(self, monkeypatch):
        db = _db_mock(
            sites=_chain([_SITE_ROW]),
            site_orders=_chain([]),  # is_first_order check -> no prior orders
            site_builder_settings=_chain([{"approval_required": True}]),
        )
        monkeypatch.setattr(pricing_svc, "get_settings", lambda db, org_id: {"approval_required": True})
        monkeypatch.setattr(pricing_svc, "quote", lambda *a, **k: _QUOTE)
        monkeypatch.setattr(pay_svc, "generate_payment_link", lambda **k: {
            "checkout_url": "https://paystack.test/pay/abc", "reference": "opsra_ref_1", "payment_link_id": "pl-1",
        })
        moved = {}
        monkeypatch.setattr(lead_svc, "move_stage", lambda **k: moved.update(k) or {})

        result = svc.create_checkout(db, ORG_ID, _BUILDER, _Payload())

        assert result["checkout_url"] == "https://paystack.test/pay/abc"
        assert result["reference"] == "opsra_ref_1"
        assert result["amount"] == 79500
        db.table("site_orders").insert.assert_called()
        # spec §11.7 — first order moves the lead to proposal_sent
        assert moved["new_stage"] == "proposal_sent"
        assert moved["lead_id"] == LEAD_ID

    def test_fixed_amount_replaces_the_quote_and_skips_discount_and_balance(self, monkeypatch):
        """GIVEAWAY-1: a giveaway winner pays the giveaway's fee; the quote is kept so staff see real cost and loss."""
        db = _db_mock(sites=_chain([_SITE_ROW]), site_orders=_chain([]))
        monkeypatch.setattr(pricing_svc, "get_settings", lambda db, org_id: {"approval_required": False})
        monkeypatch.setattr(pricing_svc, "quote", lambda *a, **k: _QUOTE)
        paid_for = {}
        monkeypatch.setattr(pay_svc, "generate_payment_link", lambda **k: paid_for.update(k) or {
            "checkout_url": "https://paystack.test/pay/g", "reference": "ref_g", "payment_link_id": "pl-g"})
        monkeypatch.setattr(lead_svc, "move_stage", lambda **k: {})
        from app.services import site_discount_service, site_premium_billing_service
        monkeypatch.setattr(site_discount_service, "validate", lambda *a, **k: pytest.fail("discount must not apply"))
        monkeypatch.setattr(site_premium_billing_service, "go_live_balance", lambda *a, **k: pytest.fail("balance must not apply"))
        payload = _Payload()
        payload.discount_code = "FREE100"

        result = svc.create_checkout(db, ORG_ID, _BUILDER, payload, fixed_amount=24500)

        assert result["amount"] == 24500 and paid_for["amount"] == 24500
        row = db.table("site_orders").insert.call_args[0][0]
        assert row["amount"] == 24500 and row["quote"]["fixed_amount"] == 24500
        assert row["expected_profit"] == 24500 - _QUOTE["cost"]["total"]          # a loss is shown as a negative number
        assert row["cost_snapshot"] == _QUOTE["cost"]

    def test_site_not_found_raises(self, monkeypatch):
        db = _db_mock(sites=_chain([]))
        with pytest.raises(svc.SiteNotFound):
            svc.create_checkout(db, ORG_ID, _BUILDER, _Payload())

    def test_builder_with_no_lead_raises_checkout_blocked(self, monkeypatch):
        db = _db_mock(sites=_chain([_SITE_ROW]))
        builder_no_lead = dict(_BUILDER, lead_id=None)
        with pytest.raises(svc.CheckoutBlocked):
            svc.create_checkout(db, ORG_ID, builder_no_lead, _Payload())

    def test_paystack_link_error_becomes_checkout_blocked(self, monkeypatch):
        db = _db_mock(sites=_chain([_SITE_ROW]), site_orders=_chain([]))
        monkeypatch.setattr(pricing_svc, "get_settings", lambda db, org_id: {"approval_required": True})
        monkeypatch.setattr(pricing_svc, "quote", lambda *a, **k: _QUOTE)

        def _raise(**k):
            raise pay_svc.PaystackLinkError("Paystack storefront is not connected for this organisation.")

        monkeypatch.setattr(pay_svc, "generate_payment_link", _raise)
        with pytest.raises(svc.CheckoutBlocked):
            svc.create_checkout(db, ORG_ID, _BUILDER, _Payload())

    def test_pricing_error_propagates_uncaught(self, monkeypatch):
        db = _db_mock(sites=_chain([_SITE_ROW]))
        monkeypatch.setattr(pricing_svc, "get_settings", lambda db, org_id: {"approval_required": True})

        def _raise(*a, **k):
            raise pricing_svc.UnsupportedDomain("'.xyz' isn't supported on the standard route.")

        monkeypatch.setattr(pricing_svc, "quote", _raise)
        with pytest.raises(pricing_svc.UnsupportedDomain):
            svc.create_checkout(db, ORG_ID, _BUILDER, _Payload())

    def test_second_order_does_not_move_lead_stage(self, monkeypatch):
        db = _db_mock(
            sites=_chain([_SITE_ROW]),
            site_orders=_chain([{"id": "existing-order"}]),  # a prior order already exists
        )
        monkeypatch.setattr(pricing_svc, "get_settings", lambda db, org_id: {"approval_required": False})
        monkeypatch.setattr(pricing_svc, "quote", lambda *a, **k: _QUOTE)
        monkeypatch.setattr(pay_svc, "generate_payment_link", lambda **k: {
            "checkout_url": "https://paystack.test/pay/xyz", "reference": "opsra_ref_2", "payment_link_id": "pl-2",
        })
        called = {"n": 0}
        monkeypatch.setattr(lead_svc, "move_stage", lambda **k: called.__setitem__("n", called["n"] + 1))

        svc.create_checkout(db, ORG_ID, _BUILDER, _Payload())
        assert called["n"] == 0

    def test_lead_stage_move_failure_does_not_break_checkout(self, monkeypatch):
        """S14 — move_stage is wrapped; an invalid-transition 400 (or anything
        else) from the CRM lead's current stage must never fail the checkout
        the builder is actively completing."""
        db = _db_mock(sites=_chain([_SITE_ROW]), site_orders=_chain([]))
        monkeypatch.setattr(pricing_svc, "get_settings", lambda db, org_id: {"approval_required": True})
        monkeypatch.setattr(pricing_svc, "quote", lambda *a, **k: _QUOTE)
        monkeypatch.setattr(pay_svc, "generate_payment_link", lambda **k: {
            "checkout_url": "https://paystack.test/pay/abc", "reference": "opsra_ref_3", "payment_link_id": "pl-3",
        })

        def _raise(**k):
            raise RuntimeError("lead not in a stage that allows this transition")

        monkeypatch.setattr(lead_svc, "move_stage", _raise)
        result = svc.create_checkout(db, ORG_ID, _BUILDER, _Payload())
        assert result["reference"] == "opsra_ref_3"


# ---------------------------------------------------------------------------
# is_site_order_reference (D6)
# ---------------------------------------------------------------------------

class TestIsSiteOrderReference:
    def test_true_when_row_exists(self):
        db = _db_mock(site_orders=_chain([{"id": "order-1"}]))
        assert svc.is_site_order_reference(db, ORG_ID, "opsra_ref_1") is True

    def test_false_when_no_row(self):
        db = _db_mock(site_orders=_chain([]))
        assert svc.is_site_order_reference(db, ORG_ID, "unknown_ref") is False

    def test_false_on_db_error(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("connection reset")
        assert svc.is_site_order_reference(db, ORG_ID, "opsra_ref_1") is False


# ---------------------------------------------------------------------------
# on_payment_confirmed
# ---------------------------------------------------------------------------

class TestOnPaymentConfirmed:
    def _order_row(self, **overrides):
        row = {
            "id": "order-1", "org_id": ORG_ID, "builder_id": BUILDER_ID, "lead_id": LEAD_ID,
            "site_id": SITE_ID, "domain": "adaezastyles.com.ng", "amount": 79500,
            "status": "pending_payment", "approval_required": True, "route": "standard",
        }
        row.update(overrides)
        return row

    def test_unknown_reference_returns_false(self, monkeypatch):
        db = _db_mock(site_orders=_chain([]))
        assert svc.on_payment_confirmed(db, ORG_ID, "no-such-ref") is False

    def test_already_processed_is_idempotent(self, monkeypatch):
        order = self._order_row(status="fulfilling")
        db = _db_mock(site_orders=_chain([order]))
        assert svc.on_payment_confirmed(db, ORG_ID, "opsra_ref_1") is True
        # No claim attempted past the initial lookup — status untouched.
        db.table("site_orders").update.assert_not_called()

    def test_approval_required_moves_to_awaiting_approval_no_job(self, monkeypatch):
        order = self._order_row(approval_required=True)
        site_orders_chain = _chain()
        select_result = MagicMock(data=[order])
        claim_result = MagicMock(data=[{**order, "status": "awaiting_approval"}])
        site_orders_chain.execute.side_effect = [select_result, claim_result]
        db = _db_mock(site_orders=site_orders_chain)

        monkeypatch.setattr(svc, "_message_builder", lambda *a, **k: None)
        monkeypatch.setattr(funnel_svc, "notify_managers", lambda *a, **k: None)
        job_calls = []
        monkeypatch.setattr(svc, "create_hosting_job", lambda *a, **k: job_calls.append(1))

        assert svc.on_payment_confirmed(db, ORG_ID, "opsra_ref_1") is True
        assert job_calls == []  # no job while awaiting approval

    def test_no_approval_required_moves_to_fulfilling_and_creates_job(self, monkeypatch):
        order = self._order_row(approval_required=False)
        site_orders_chain = _chain()
        select_result = MagicMock(data=[order])
        claim_result = MagicMock(data=[{**order, "status": "fulfilling"}])
        site_orders_chain.execute.side_effect = [select_result, claim_result]
        db = _db_mock(site_orders=site_orders_chain)

        monkeypatch.setattr(svc, "_message_builder", lambda *a, **k: None)
        monkeypatch.setattr(funnel_svc, "notify_managers", lambda *a, **k: None)
        job_calls = []
        monkeypatch.setattr(svc, "create_hosting_job", lambda db, org_id, o: job_calls.append(o["id"]))

        assert svc.on_payment_confirmed(db, ORG_ID, "opsra_ref_1") is True
        assert job_calls == ["order-1"]

    def test_double_delivery_second_claim_is_a_noop(self, monkeypatch):
        """Two webhook deliveries for the same charge: the second one's claim
        UPDATE (eq("status","pending_payment")) affects zero rows because the
        first delivery already moved it — it must return True without
        creating a second hosting job or sending a second message."""
        order = self._order_row(approval_required=False)
        site_orders_chain = _chain()
        select_result = MagicMock(data=[order])
        claim_result = MagicMock(data=[])  # another delivery already claimed it
        site_orders_chain.execute.side_effect = [select_result, claim_result]
        db = _db_mock(site_orders=site_orders_chain)

        messaged = []
        monkeypatch.setattr(svc, "_message_builder", lambda *a, **k: messaged.append(1))
        job_calls = []
        monkeypatch.setattr(svc, "create_hosting_job", lambda *a, **k: job_calls.append(1))

        assert svc.on_payment_confirmed(db, ORG_ID, "opsra_ref_1") is True
        assert messaged == []
        assert job_calls == []

    def test_message_or_notify_failure_never_raises(self, monkeypatch):
        """S14 — everything inside on_payment_confirmed is individually
        try/excepted; a broken WhatsApp send must never stop the order's
        status transition from having already been committed."""
        order = self._order_row(approval_required=True)
        site_orders_chain = _chain()
        select_result = MagicMock(data=[order])
        claim_result = MagicMock(data=[{**order, "status": "awaiting_approval"}])
        site_orders_chain.execute.side_effect = [select_result, claim_result]
        db = _db_mock(site_orders=site_orders_chain)

        def _raise(*a, **k):
            raise RuntimeError("WhatsApp API down")

        monkeypatch.setattr(svc, "_message_builder", _raise)
        monkeypatch.setattr(funnel_svc, "notify_managers", lambda *a, **k: None)
        assert svc.on_payment_confirmed(db, ORG_ID, "opsra_ref_1") is True

    def test_unexpected_error_still_returns_true_never_raises(self, monkeypatch):
        db = MagicMock()
        db.table.side_effect = RuntimeError("connection reset")
        assert svc.on_payment_confirmed(db, ORG_ID, "opsra_ref_1") is True


# ---------------------------------------------------------------------------
# _message_builder
# ---------------------------------------------------------------------------

class TestMessageBuilder:
    def test_sends_when_phone_present(self, monkeypatch):
        db = _db_mock(site_builders=_chain([{"phone_number": "+2348030000000"}]))
        sent = {}
        monkeypatch.setattr(wa_svc, "send_agent_text_message", lambda **k: sent.update(k))
        svc._message_builder(db, ORG_ID, {"builder_id": BUILDER_ID, "lead_id": LEAD_ID}, "hello")
        assert sent["phone_number"] == "+2348030000000"
        assert sent["message"] == "hello"

    def test_noop_when_no_phone(self, monkeypatch):
        db = _db_mock(site_builders=_chain([]))
        called = []
        monkeypatch.setattr(wa_svc, "send_agent_text_message", lambda **k: called.append(1))
        svc._message_builder(db, ORG_ID, {"builder_id": BUILDER_ID, "lead_id": LEAD_ID}, "hello")
        assert called == []


# ---------------------------------------------------------------------------
# create_hosting_job
# ---------------------------------------------------------------------------

class TestCreateHostingJob:
    def _order(self):
        return {"id": "order-1", "org_id": ORG_ID, "site_id": SITE_ID, "domain": "adaezastyles.com.ng",
                "sla_due_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()}

    def test_creates_job_with_six_step_checklist(self, monkeypatch):
        db = _db_mock(
            site_hosting_jobs=_chain([]),  # no existing job for this order
            site_orders=_chain([]),
            tasks=_chain([]),
        )
        monkeypatch.setattr(funnel_svc, "notify_managers", lambda *a, **k: None)

        job = svc.create_hosting_job(db, ORG_ID, self._order())
        assert len(job["checklist"]) == 5
        assert job["checklist"][0]["key"] == "recheck_domain"
        assert job["status"] == "queued"
        db.table("tasks").insert.assert_called()

    def test_idempotent_returns_existing_job(self, monkeypatch):
        existing = {"id": "job-1", "order_id": "order-1", "status": "queued"}
        db = _db_mock(site_hosting_jobs=_chain([existing]))
        job = svc.create_hosting_job(db, ORG_ID, self._order())
        assert job == existing
        db.table("site_hosting_jobs").insert.assert_not_called()
