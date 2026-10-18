"""
tests/unit/test_credits_1.py
----------------------------
CREDITS-1: cost table, wallet metering, automation-fee rules, AI budget gate,
Meta pricing capture, superadmin routes, nightly reconcile.

The SQL functions (credit_debit / credit_credit / credit_expire) are covered
by the SQL checks in the build session, not here (they need Postgres).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ORG = "00000000-0000-0000-0000-0000000000aa"


# ── A tiny in-memory stand-in for the Supabase client ───────────────────────

class _Q:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.filters, self.op, self.payload, self._limit = [], "select", None, None
        self._count = False

    def select(self, *_a, count=None, **_k):
        self._count = bool(count)
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, row):
        self.op, self.payload = "update", row
        return self

    def upsert(self, row, **_k):
        self.op, self.payload = "upsert", row
        return self

    def _f(self, kind, col, val):
        self.filters.append((kind, col, val))
        return self

    def eq(self, c, v): return self._f("eq", c, v)
    def lte(self, c, v): return self._f("lte", c, v)
    def gte(self, c, v): return self._f("gte", c, v)
    def in_(self, c, v): return self._f("in", c, v)
    def order(self, *_a, **_k): return self
    def limit(self, n):
        self._limit = n
        return self

    def _match(self, row):
        for kind, c, v in self.filters:
            x = row.get(c)
            if kind == "eq" and x != v: return False
            if kind == "in" and x not in v: return False
            if kind == "lte" and not (x is not None and str(x) <= str(v)): return False
            if kind == "gte" and not (x is not None and str(x) >= str(v)): return False
        return True

    def execute(self):
        self.db.calls.append((self.name, self.op, self.payload, list(self.filters)))
        if self.name in self.db.fail_tables and self.op in self.db.fail_tables[self.name]:
            raise RuntimeError(f"forced failure on {self.name}.{self.op}")
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            rows.append(dict(self.payload))
            return SimpleNamespace(data=[dict(self.payload)], count=None)
        if self.op == "update":
            hit = [r for r in rows if self._match(r)]
            for r in hit:
                r.update(self.payload)
            return SimpleNamespace(data=[dict(r) for r in hit], count=None)
        if self.op == "upsert":
            return SimpleNamespace(data=[], count=None)
        hit = [dict(r) for r in rows if self._match(r)]
        if self._limit:
            hit = hit[: self._limit]
        return SimpleNamespace(data=hit, count=len(hit) if self._count else None)


class FakeDB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.calls, self.rpcs, self.fail_tables = [], [], {}
        self.rpc_result = {"applied": True, "charged_kobo": 0, "shortfall_kobo": 0, "balance_kobo": 0}

    def table(self, name): return _Q(self, name)

    def rpc(self, fn, args):
        self.rpcs.append((fn, args))
        out = dict(self.rpc_result)
        if fn == "credit_debit":
            out["charged_kobo"] = args["p_amount"]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[out]))


RATES = {"fx_ngn_per_usd": 1340, "ai_markup_pct": 50, "meta_markup_pct": 0,
         "min_charge_kobo": 0, "rounding_kobo": 1, "effective_from": "2026-01-01T00:00:00+00:00"}
PAST = "2026-01-01T00:00:00+00:00"


def _metered_db(**extra):
    wallet = {"org_id": ORG, "balance_kobo": 100_000, "metering_enabled": True,
              "meta_billing": "client_direct", "ai_monthly_budget_kobo": None}
    wallet.update(extra.pop("wallet", {}))
    return FakeDB(credit_wallets=[wallet], credit_rates=[dict(RATES)], **extra)


# ═══════════════════════════ ai_cost ════════════════════════════════════════

class TestAiCost:
    def test_rates_by_model(self):
        from app.services.ai_cost import get_rate
        assert get_rate("claude-sonnet-5")[:2] == (2.0, 10.0)
        assert get_rate("claude-sonnet-5-5")[:2] == (2.0, 10.0)
        assert get_rate("claude-sonnet-4-6")[:2] == (3.0, 15.0)
        assert get_rate("claude-sonnet-4-20250514")[:2] == (3.0, 15.0)
        assert get_rate("claude-haiku-4-5-20251001")[:2] == (1.0, 5.0)
        assert get_rate("claude-haiku-5-5")[:2] == (0.10, 0.50)
        assert get_rate("claude-opus-5-5")[:2] == (4.0, 20.0)

    def test_unknown_model_uses_safe_over_estimate(self):
        from app.services.ai_cost import get_rate
        inp, out, matched = get_rate("mystery-model")
        assert (inp, out, matched) == (3.0, 15.0, False)
        assert get_rate(None)[2] is False

    def test_cache_tokens_priced(self):
        from app.services.ai_cost import cost_usd
        # Sonnet 5: 1M cache read = 0.1 × $2 = $0.20 ; 1M cache write = 1.25 × $2 = $2.50
        assert cost_usd("claude-sonnet-5", 0, 0, cache_read_tokens=1_000_000) == pytest.approx(0.20)
        assert cost_usd("claude-sonnet-5", 0, 0, cache_creation_tokens=1_000_000) == pytest.approx(2.50)
        assert cost_usd("claude-sonnet-5", 1_000_000, 1_000_000) == pytest.approx(12.0)

    def test_bad_numbers_do_not_raise(self):
        from app.services.ai_cost import cost_usd
        assert cost_usd("claude-sonnet-5", None, -5) == 0.0


# ═══════════════════════════ money maths and fee rules ══════════════════════

class TestMoneyMaths:
    def test_usd_to_kobo_rounds_up_with_markup(self):
        from app.services.credit_service import usd_to_kobo
        # 0.0114 × 1340 × 100 × 1.5 = 2291.4 → 2292
        assert usd_to_kobo(0.0114, RATES, 50) == 2292
        assert usd_to_kobo(0.0114, RATES, 0) == 1528  # 1527.6 rounded up

    def test_min_charge_and_rounding_step(self):
        from app.services.credit_service import usd_to_kobo
        r = dict(RATES, rounding_kobo=100, min_charge_kobo=500)
        assert usd_to_kobo(0.0001, r, 0) == 500
        assert usd_to_kobo(0.0114, r, 0) == 1600
        assert usd_to_kobo(0, r, 50) == 0

    def test_fee_modes_min_max(self):
        from app.services.credit_service import _fee_amount
        assert _fee_amount({"mode": "flat_kobo", "value": 300}, 0, 0) == 300
        assert _fee_amount({"mode": "percent_of_meta_cost", "value": 20}, 1400, 0) == 280
        assert _fee_amount({"mode": "percent_of_ai_cost", "value": 10}, 0, 2000) == 200
        assert _fee_amount({"mode": "percent_of_meta_cost", "value": 1, "min_kobo": 50}, 1400, 0) == 50
        assert _fee_amount({"mode": "flat_kobo", "value": 900, "max_kobo": 500}, 0, 0) == 500
        assert _fee_amount({"mode": "nonsense", "value": 5}, 1, 1) == 0


def _rule(**kw):
    base = {"id": "r1", "scope": "default", "org_id": None, "event_type": "wa_service",
            "mode": "flat_kobo", "value": 100, "min_kobo": 0, "max_kobo": None,
            "free_units_per_month": 0, "effective_from": PAST, "effective_to": None, "enabled": True}
    base.update(kw)
    return base


class TestFeeRuleSelection:
    def test_no_rules_means_no_fee(self):
        from app.services.credit_service import compute_fee_kobo
        assert compute_fee_kobo(FakeDB(automation_fee_rules=[]), ORG, "wa_service", 1000, 0) == (0, None)

    def test_disabled_rule_ignored(self):
        from app.services.credit_service import find_fee_rule
        db = FakeDB(automation_fee_rules=[_rule(enabled=False)])
        assert find_fee_rule(db, ORG, "wa_service") is None

    def test_future_and_expired_rules_ignored(self):
        from app.services.credit_service import find_fee_rule
        future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        db = FakeDB(automation_fee_rules=[_rule(effective_from=future)])
        assert find_fee_rule(db, ORG, "wa_service") is None
        db = FakeDB(automation_fee_rules=[_rule(effective_to="2026-02-01T00:00:00+00:00")])
        assert find_fee_rule(db, ORG, "wa_service") is None

    def test_org_rule_beats_default_and_exact_beats_any(self):
        from app.services.credit_service import find_fee_rule
        db = FakeDB(automation_fee_rules=[
            _rule(id="default-exact", value=100),
            _rule(id="default-any", event_type="any", value=50),
            _rule(id="org-any", scope="org", org_id=ORG, event_type="any", value=10),
        ])
        assert find_fee_rule(db, ORG, "wa_service")["id"] == "org-any"
        db.tables["automation_fee_rules"] = db.tables["automation_fee_rules"][:2]
        assert find_fee_rule(db, ORG, "wa_service")["id"] == "default-exact"

    def test_other_orgs_rule_not_used(self):
        from app.services.credit_service import find_fee_rule
        db = FakeDB(automation_fee_rules=[_rule(scope="org", org_id="someone-else")])
        assert find_fee_rule(db, ORG, "wa_service") is None

    def test_free_units_cover_first_n_messages(self):
        from app.services.credit_service import compute_fee_kobo
        month = datetime.now(timezone.utc).replace(day=1).isoformat()
        msgs = [{"org_id": ORG, "meta_category": "service", "created_at": month} for _ in range(3)]
        db = FakeDB(automation_fee_rules=[_rule(free_units_per_month=3)], whatsapp_messages=msgs)
        assert compute_fee_kobo(db, ORG, "wa_service", 0, 0)[0] == 0      # 3rd message still free
        db.tables["whatsapp_messages"].append(msgs[0])
        assert compute_fee_kobo(db, ORG, "wa_service", 0, 0)[0] == 100    # 4th is charged


# ═══════════════════════════ metering ═══════════════════════════════════════

class TestMeterAi:
    def test_unmetered_org_is_untouched(self):
        from app.services.credit_service import meter_ai_call
        db = FakeDB(credit_wallets=[{"org_id": ORG, "metering_enabled": False, "balance_kobo": 5}],
                    credit_rates=[dict(RATES)])
        assert meter_ai_call(db, ORG, function_name="f", model="m", cost_usd=0.01) is None
        assert db.rpcs == []

    def test_no_wallet_row_is_untouched(self):
        from app.services.credit_service import meter_ai_call
        db = FakeDB(credit_wallets=[], credit_rates=[dict(RATES)])
        assert meter_ai_call(db, ORG, function_name="f", model="m", cost_usd=0.01) is None

    def test_metered_org_is_debited_cost_plus_markup(self):
        from app.services.credit_service import meter_ai_call
        db = _metered_db(automation_fee_rules=[])
        charged = meter_ai_call(db, ORG, function_name="ai_agent_turn", model="claude-sonnet-5",
                                cost_usd=0.0114, ref="ai:1")
        assert charged == 2292
        fn, args = db.rpcs[0]
        assert fn == "credit_debit" and args["p_kind"] == "ai" and args["p_amount"] == 2292
        assert args["p_ref"] == "ai:1" and args["p_org"] == ORG

    def test_ai_fee_rule_adds_separate_fee_line(self):
        from app.services.credit_service import meter_ai_call
        db = _metered_db(automation_fee_rules=[_rule(event_type="ai_turn", mode="flat_kobo", value=500)])
        charged = meter_ai_call(db, ORG, function_name="x", model="claude-sonnet-5", cost_usd=0.0114, ref="ai:2")
        assert [a["p_kind"] for _, a in db.rpcs] == ["ai", "fee"]
        assert db.rpcs[1][1]["p_ref"] == "ai:2:fee" and charged == 2292 + 500

    def test_rpc_failure_never_raises(self):
        from app.services.credit_service import meter_ai_call
        db = _metered_db(automation_fee_rules=[])
        db.rpc = MagicMock(side_effect=RuntimeError("db down"))
        assert meter_ai_call(db, ORG, function_name="x", model="m", cost_usd=0.01, ref="r") == 0


class TestMeterMeta:
    def test_client_direct_charges_no_meta_cost_and_no_fee_by_default(self):
        from app.services.credit_service import meter_meta_message
        db = _metered_db(meta_rate_cards=[{"country": "NG", "category": "service", "usd_per_message": 0.0101,
                                           "effective_from": PAST}], automation_fee_rules=[])
        assert meter_meta_message(db, ORG, category="service", billable=True, meta_message_id="wamid.1") == 0
        assert db.rpcs == []

    def test_client_direct_with_percent_fee(self):
        from app.services.credit_service import meter_meta_message
        db = _metered_db(
            meta_rate_cards=[{"country": "NG", "category": "service", "usd_per_message": 0.0101, "effective_from": PAST}],
            automation_fee_rules=[_rule(mode="percent_of_meta_cost", value=50)])
        charged = meter_meta_message(db, ORG, category="service", billable=True, meta_message_id="wamid.2")
        # Meta cost 0.0101×1340×100 = 1353.4 → 1354 ; 50% → 677
        assert charged == 677
        assert [a["p_kind"] for _, a in db.rpcs] == ["fee"] and db.rpcs[0][1]["p_ref"] == "fee:wamid.2"

    def test_credit_line_org_is_debited_for_meta(self):
        from app.services.credit_service import meter_meta_message
        db = _metered_db(
            wallet={"meta_billing": "opsra_credit_line"},
            meta_rate_cards=[{"country": "NG", "category": "utility", "usd_per_message": 0.0101, "effective_from": PAST}],
            automation_fee_rules=[])
        charged = meter_meta_message(db, ORG, category="utility", billable=True, meta_message_id="wamid.3")
        assert charged == 1354
        assert db.rpcs[0][1]["p_kind"] == "meta" and db.rpcs[0][1]["p_ref"] == "meta:wamid.3"

    def test_non_billable_message_costs_nothing(self):
        from app.services.credit_service import meter_meta_message
        db = _metered_db(wallet={"meta_billing": "opsra_credit_line"}, automation_fee_rules=[])
        assert meter_meta_message(db, ORG, category="service", billable=False, meta_message_id="w4") == 0
        assert db.rpcs == []

    def test_unknown_category_ignored(self):
        from app.services.credit_service import meter_meta_message
        db = _metered_db(automation_fee_rules=[])
        assert meter_meta_message(db, ORG, category="referral_conversion", billable=False, meta_message_id="w5") is None


class TestAiLevel:
    def _spend(self, kobo):
        month = datetime.now(timezone.utc).replace(day=1).isoformat()
        return [{"org_id": ORG, "kind": "ai", "amount_kobo": -kobo, "created_at": month}]

    def test_unmetered_is_always_normal(self):
        from app.services.credit_service import get_ai_level
        db = FakeDB(credit_wallets=[{"org_id": ORG, "metering_enabled": False, "balance_kobo": 0}])
        assert get_ai_level(db, ORG) == "normal"
        assert get_ai_level(db, None) == "normal"

    def test_empty_wallet_is_menu_only(self):
        from app.services.credit_service import get_ai_level
        assert get_ai_level(_metered_db(wallet={"balance_kobo": 0}), ORG) == "menu_only"

    def test_budget_steps(self):
        from app.services.credit_service import get_ai_level
        kw = dict(wallet={"ai_monthly_budget_kobo": 10_000})
        assert get_ai_level(_metered_db(credit_ledger=self._spend(7_900), **kw), ORG) == "normal"
        assert get_ai_level(_metered_db(credit_ledger=self._spend(8_000), **kw), ORG) == "cheaper_model"
        assert get_ai_level(_metered_db(credit_ledger=self._spend(10_000), **kw), ORG) == "menu_only"

    def test_no_budget_set_stays_normal(self):
        from app.services.credit_service import get_ai_level
        assert get_ai_level(_metered_db(credit_ledger=self._spend(999_999)), ORG) == "normal"


# ═══════════════════════════ ai_service hooks ═══════════════════════════════

class TestLogClaudeUsage:
    def test_cost_includes_cache_and_cache_columns_stored(self):
        from app.services.ai_service import _log_claude_usage
        db = FakeDB()
        _log_claude_usage(db, org_id=None, function_name="f", model="claude-sonnet-5",
                          input_tokens=1_000_000, output_tokens=0,
                          cache_read_tokens=1_000_000, cache_creation_tokens=0)
        row = db.tables["claude_usage_log"][0]
        assert row["estimated_cost_usd"] == pytest.approx(2.20)   # $2 + $0.20 cache read
        assert row["cache_read_tokens"] == 1_000_000

    def test_insert_retries_without_cache_columns_if_not_migrated(self):
        from app.services.ai_service import _log_claude_usage
        db = FakeDB()
        calls = {"n": 0}
        real_table = db.table

        def table(name):
            q = real_table(name)
            orig = q.execute

            def execute():
                if q.op == "insert" and "cache_read_tokens" in (q.payload or {}):
                    calls["n"] += 1
                    raise RuntimeError("column does not exist")
                return orig()
            q.execute = execute
            return q
        db.table = table
        _log_claude_usage(db, org_id=None, function_name="f", model="claude-haiku-4-5",
                          input_tokens=10, output_tokens=5)
        assert calls["n"] == 1
        assert len(db.tables["claude_usage_log"]) == 1
        assert "cache_read_tokens" not in db.tables["claude_usage_log"][0]

    def test_metered_org_is_charged_through_log(self):
        from app.services.ai_service import _log_claude_usage
        db = _metered_db(automation_fee_rules=[])
        _log_claude_usage(db, org_id=ORG, function_name="ai_agent_turn", model="claude-sonnet-5",
                          input_tokens=1000, output_tokens=341)
        assert db.rpcs and db.rpcs[0][0] == "credit_debit"

    def test_unmetered_org_not_charged(self):
        from app.services.ai_service import _log_claude_usage
        db = FakeDB(credit_wallets=[], credit_rates=[dict(RATES)])
        _log_claude_usage(db, org_id=ORG, function_name="x", model="claude-sonnet-5",
                          input_tokens=1000, output_tokens=10)
        assert db.rpcs == []

    def test_old_positional_call_shape_still_works(self):
        """site_import_editable / site_premium_generate call without cache args."""
        from app.services.ai_service import _log_claude_usage
        db = FakeDB()
        _log_claude_usage(db, org_id=None, function_name="f", model="claude-sonnet-5",
                          input_tokens=1, output_tokens=1)
        assert len(db.tables["claude_usage_log"]) == 1


class TestCallClaudeGate:
    def _resp(self):
        r = MagicMock()
        r.content = [SimpleNamespace(type="text", text="hi")]
        r.usage = SimpleNamespace(input_tokens=10, output_tokens=5,
                                  cache_read_input_tokens=4, cache_creation_input_tokens=0)
        return r

    def test_agent_turn_blocked_when_budget_exhausted(self):
        from app.services.ai_service import call_claude
        db = _metered_db(wallet={"balance_kobo": 0})
        with patch("app.services.ai_service.check_and_increment_token_usage", return_value=True), \
             patch("app.services.ai_service._get_client") as client:
            assert call_claude("p", org_id=ORG, db=db, function_name="ai_agent_turn") == ""
        client.assert_not_called()

    def test_agent_turn_steps_down_to_haiku(self):
        from app.services.ai_service import call_claude, HAIKU, SONNET
        month = datetime.now(timezone.utc).replace(day=1).isoformat()
        db = _metered_db(wallet={"ai_monthly_budget_kobo": 10_000},
                         credit_ledger=[{"org_id": ORG, "kind": "ai", "amount_kobo": -9_000, "created_at": month}],
                         automation_fee_rules=[])
        with patch("app.services.ai_service.check_and_increment_token_usage", return_value=True), \
             patch("app.services.ai_service._get_client") as client:
            client.return_value.messages.create.return_value = self._resp()
            out = call_claude("p", model=SONNET, org_id=ORG, db=db, function_name="ai_agent_turn")
        assert out == "hi"
        assert client.return_value.messages.create.call_args.kwargs["model"] == HAIKU
        logged = db.tables["claude_usage_log"][0]
        assert logged["cache_read_tokens"] == 4 and logged["model"] == HAIKU

    def test_other_functions_are_never_gated(self):
        from app.services.ai_service import call_claude
        db = _metered_db(wallet={"balance_kobo": 0})
        with patch("app.services.ai_service.check_and_increment_token_usage", return_value=True), \
             patch("app.services.ai_service._get_client") as client:
            client.return_value.messages.create.return_value = self._resp()
            assert call_claude("p", org_id=ORG, db=db, function_name="aria_chat") == "hi"


# ═══════════════════════════ webhook pricing capture ════════════════════════

class TestMetaPricingCapture:
    def _db(self, **msg):
        row = {"org_id": ORG, "meta_message_id": "wamid.X", "meta_category": None}
        row.update(msg)
        return _metered_db(whatsapp_messages=[row], meta_rate_cards=[], automation_fee_rules=[])

    def test_category_and_billable_stored(self):
        from app.routers.webhooks import _handle_status_update
        db = self._db()
        _handle_status_update(db, {"id": "wamid.X", "status": "sent",
                                   "pricing": {"billable": True, "pricing_model": "PMP", "category": "Service"}})
        m = db.tables["whatsapp_messages"][0]
        assert m["status"] == "sent" and m["meta_category"] == "service" and m["meta_billable"] is True

    def test_free_message_stored_as_not_billable(self):
        from app.routers.webhooks import _handle_status_update
        db = self._db()
        _handle_status_update(db, {"id": "wamid.X", "status": "sent",
                                   "pricing": {"billable": False, "category": "service"}})
        assert db.tables["whatsapp_messages"][0]["meta_billable"] is False

    def test_second_status_does_not_remeter(self):
        from app.routers.webhooks import _handle_status_update
        db = self._db(meta_category="service")
        before = len(db.calls)
        with patch("app.services.credit_service.meter_meta_message") as meter:
            _handle_status_update(db, {"id": "wamid.X", "status": "delivered",
                                       "pricing": {"billable": True, "category": "service"}})
        meter.assert_not_called()
        assert db.tables["whatsapp_messages"][0]["status"] == "delivered"
        assert len(db.calls) > before

    def test_no_pricing_object_changes_nothing_extra(self):
        from app.routers.webhooks import _handle_status_update
        db = self._db()
        _handle_status_update(db, {"id": "wamid.X", "status": "read"})
        assert db.tables["whatsapp_messages"][0]["meta_category"] is None

    def test_unknown_category_ignored(self):
        from app.routers.webhooks import _handle_status_update
        db = self._db()
        _handle_status_update(db, {"id": "wamid.X", "status": "sent", "pricing": {"billable": True, "category": "weird"}})
        assert db.tables["whatsapp_messages"][0]["meta_category"] is None

    def test_pricing_failure_never_loses_the_status(self):
        from app.routers.webhooks import _handle_status_update
        db = self._db()
        real = db.table

        def table(name):
            q = real(name)
            if name == "whatsapp_messages":
                orig = q.execute

                def execute():
                    if q.op == "update" and "meta_category" in (q.payload or {}):
                        raise RuntimeError("column does not exist")
                    return orig()
                q.execute = execute
            return q
        db.table = table
        _handle_status_update(db, {"id": "wamid.X", "status": "delivered",
                                   "pricing": {"billable": True, "category": "service"}})
        assert db.tables["whatsapp_messages"][0]["status"] == "delivered"

    def test_metering_called_once_for_new_pricing(self):
        from app.routers.webhooks import _handle_status_update
        db = self._db()
        with patch("app.services.credit_service.meter_meta_message") as meter:
            _handle_status_update(db, {"id": "wamid.X", "status": "sent",
                                       "pricing": {"billable": True, "category": "utility"}})
        meter.assert_called_once()
        assert meter.call_args.kwargs["category"] == "utility"
        assert meter.call_args.kwargs["meta_message_id"] == "wamid.X"


# ═══════════════════════════ reconcile worker ═══════════════════════════════

class TestReconcile:
    def test_clean_wallet_has_no_problems(self):
        from app.workers.credit_worker import reconcile_wallets
        db = FakeDB(credit_wallets=[{"org_id": ORG, "balance_kobo": 700}],
                    credit_ledger=[{"org_id": ORG, "amount_kobo": 1000}, {"org_id": ORG, "amount_kobo": -300}],
                    credit_lots=[{"org_id": ORG, "remaining_kobo": 700}])
        assert reconcile_wallets(db) == []

    def test_mismatch_reported(self):
        from app.workers.credit_worker import reconcile_wallets
        db = FakeDB(credit_wallets=[{"org_id": ORG, "balance_kobo": 700}],
                    credit_ledger=[{"org_id": ORG, "amount_kobo": 1000}],
                    credit_lots=[{"org_id": ORG, "remaining_kobo": 700}])
        out = reconcile_wallets(db)
        assert out == [{"org_id": ORG, "balance": 700, "ledger_sum": 1000, "lots_sum": 700}]

    def test_dry_run_passes_flag_to_sql(self):
        from app.workers.credit_worker import run_credit_housekeeping
        db = FakeDB(credit_wallets=[])
        db.rpc_result = 3
        db.rpc = lambda fn, args: SimpleNamespace(execute=lambda: SimpleNamespace(data=3))
        out = run_credit_housekeeping(db, dry_run=True)
        assert out == {"dry_run": True, "lots_expired": 3, "mismatches": []}


# ═══════════════════════════ superadmin routes ══════════════════════════════

@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_supabase
    from app.routers import superadmin_credits
    from app.routers.superadmin_health import require_superadmin

    app = FastAPI()
    app.include_router(superadmin_credits.router, prefix="/api/v1")
    db = _metered_db(automation_fee_rules=[], meta_rate_cards=[])
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[require_superadmin] = lambda: None
    c = TestClient(app)
    c.db = db
    return c


class TestSuperadminRoutes:
    def test_requires_superadmin(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers import superadmin_credits
        app = FastAPI()
        app.include_router(superadmin_credits.router, prefix="/api/v1")
        r = TestClient(app).get("/api/v1/superadmin/credits/rates")
        assert r.status_code == 403

    def test_new_fee_rule_always_starts_disabled(self, client):
        r = client.post("/api/v1/superadmin/credits/fee-rules",
                        json={"event_type": "wa_service", "mode": "flat_kobo", "value": 200, "enabled": True})
        assert r.status_code == 200
        assert client.db.tables["automation_fee_rules"][0]["enabled"] is False

    def test_org_scope_needs_org_id(self, client):
        r = client.post("/api/v1/superadmin/credits/fee-rules",
                        json={"scope": "org", "event_type": "any", "mode": "flat_kobo", "value": 1})
        assert r.status_code == 422
        r = client.post("/api/v1/superadmin/credits/fee-rules",
                        json={"scope": "default", "org_id": ORG, "event_type": "any", "mode": "flat_kobo", "value": 1})
        assert r.status_code == 422

    def test_bad_mode_and_negative_value_rejected(self, client):
        assert client.post("/api/v1/superadmin/credits/fee-rules",
                           json={"event_type": "any", "mode": "free_money", "value": 1}).status_code == 422
        assert client.post("/api/v1/superadmin/credits/fee-rules",
                           json={"event_type": "any", "mode": "flat_kobo", "value": -1}).status_code == 422

    def test_preview_does_not_write(self, client):
        r = client.post("/api/v1/superadmin/credits/fee-rules/preview",
                        json={"event_type": "wa_service", "mode": "percent_of_meta_cost", "value": 25,
                              "sample_meta_cost_kobo": 1354})
        assert r.json()["data"]["fee_kobo"] == 339  # ceil(338.5)
        assert "automation_fee_rules" not in client.db.tables or client.db.tables["automation_fee_rules"] == []

    def test_adjust_requires_note_and_nonzero(self, client):
        assert client.post("/api/v1/superadmin/credits/orgs/%s/adjust" % ORG,
                           json={"amount_kobo": 0, "note": "none", "ref": "adj-1"}).status_code == 422
        assert client.post("/api/v1/superadmin/credits/orgs/%s/adjust" % ORG,
                           json={"amount_kobo": 500, "note": "", "ref": "adj-1"}).status_code == 422

    def test_positive_and_negative_adjust_use_right_sql(self, client):
        client.db.rpc_result = {"applied": True, "balance_kobo": 1}
        client.post("/api/v1/superadmin/credits/orgs/%s/adjust" % ORG,
                    json={"amount_kobo": 500, "note": "goodwill", "ref": "adj-1"})
        client.post("/api/v1/superadmin/credits/orgs/%s/adjust" % ORG,
                    json={"amount_kobo": -200, "note": "correction", "ref": "adj-2"})
        assert [f for f, _ in client.db.rpcs] == ["credit_credit", "credit_debit"]
        assert client.db.rpcs[1][1]["p_amount"] == 200

    def test_rate_history_is_appended_not_overwritten(self, client):
        client.post("/api/v1/superadmin/credits/rates", json={"fx_ngn_per_usd": 1500})
        assert len(client.db.tables["credit_rates"]) == 2

    def test_wallet_patch_validates_meta_billing(self, client):
        assert client.patch("/api/v1/superadmin/credits/orgs/%s/wallet" % ORG,
                            json={"meta_billing": "free"}).status_code == 422
        assert client.patch("/api/v1/superadmin/credits/orgs/%s/wallet" % ORG, json={}).status_code == 422
