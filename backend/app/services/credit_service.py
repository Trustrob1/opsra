"""
app/services/credit_service.py
------------------------------
CREDITS-1 — prepaid credit wallet: metering, fee rules, budget level.

Money is integer kobo. The wallet, lots and ledger live in Postgres; the
atomic work (row lock, oldest-expiry-first lot use, idempotency on `ref`)
is done by the credit_credit / credit_debit / credit_expire SQL functions.

Nothing here changes behaviour for an org until
credit_wallets.metering_enabled is switched on for that org.

S14: every public function here swallows its own errors and returns a safe
value. A billing problem must never break a customer conversation.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

FEE_MODES = ("flat_kobo", "percent_of_meta_cost", "percent_of_ai_cost")
EVENT_TYPES = (
    "wa_service", "wa_utility", "wa_marketing", "wa_auth", "ai_turn", "email", "any",
)

# AI budget levels, cheapest-to-serve last.
LEVEL_NORMAL = "normal"
LEVEL_CHEAPER = "cheaper_model"
LEVEL_MENU = "menu_only"
CHEAPER_AT = 0.80   # share of the monthly AI budget at which we step down
MENU_AT = 1.00


def _rows(res) -> list:
    data = getattr(res, "data", None)
    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) and data else []


def _month_start() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


# ── Reads ───────────────────────────────────────────────────────────────────

def get_wallet(db, org_id: str) -> Optional[dict]:
    try:
        rows = _rows(db.table("credit_wallets").select("*").eq("org_id", org_id).limit(1).execute())
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("credit_service.get_wallet failed: %s", exc)
        return None


def metering_on(wallet: Optional[dict]) -> bool:
    return bool(isinstance(wallet, dict) and wallet.get("metering_enabled") is True)


def get_rates(db) -> Optional[dict]:
    """Newest credit_rates row already in effect."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        rows = _rows(
            db.table("credit_rates").select("*")
            .lte("effective_from", now).order("effective_from", desc=True).limit(1).execute()
        )
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("credit_service.get_rates failed: %s", exc)
        return None


def get_meta_usd(db, category: str, country: str = "NG") -> Optional[float]:
    """US$ per message for a Meta category, newest card already in effect."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        rows = _rows(
            db.table("meta_rate_cards").select("usd_per_message")
            .eq("country", country).eq("category", category)
            .lte("effective_from", now).order("effective_from", desc=True).limit(1).execute()
        )
        return float(rows[0]["usd_per_message"]) if rows else None
    except Exception as exc:
        logger.warning("credit_service.get_meta_usd failed: %s", exc)
        return None


# ── Pure money maths ────────────────────────────────────────────────────────

def usd_to_kobo(usd: float, rates: dict, markup_pct: float) -> int:
    """Customer charge in kobo: usd × FX × 100 × (1 + markup), rounded up."""
    fx = float(rates.get("fx_ngn_per_usd") or 0)
    raw = float(usd) * fx * 100.0 * (1.0 + float(markup_pct) / 100.0)
    if raw <= 0:
        return 0
    step = max(int(rates.get("rounding_kobo") or 1), 1)
    kobo = int(math.ceil(raw / step) * step)
    return max(kobo, int(rates.get("min_charge_kobo") or 0))


def _fee_amount(rule: dict, meta_cost_kobo: int, ai_cost_kobo: int) -> int:
    mode = rule.get("mode")
    value = float(rule.get("value") or 0)
    if mode == "flat_kobo":
        raw = value
    elif mode == "percent_of_meta_cost":
        raw = meta_cost_kobo * value / 100.0
    elif mode == "percent_of_ai_cost":
        raw = ai_cost_kobo * value / 100.0
    else:
        return 0
    amt = int(math.ceil(raw))
    amt = max(amt, int(rule.get("min_kobo") or 0))
    if rule.get("max_kobo") is not None:
        amt = min(amt, int(rule["max_kobo"]))
    return max(amt, 0)


def find_fee_rule(db, org_id: str, event_type: str) -> Optional[dict]:
    """
    Enabled rule in effect for this event. An org-specific rule beats the
    default; a rule for the exact event beats an 'any' rule. None = no fee.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        rows = _rows(
            db.table("automation_fee_rules").select("*")
            .eq("enabled", True).lte("effective_from", now)
            .in_("event_type", [event_type, "any"]).execute()
        )
        live = [
            r for r in rows
            if (not r.get("effective_to") or r["effective_to"] > now)
            and (r.get("scope") == "default" or r.get("org_id") == org_id)
        ]
        if not live:
            return None
        live.sort(key=lambda r: (r.get("scope") == "org", r.get("event_type") == event_type), reverse=True)
        return live[0]
    except Exception as exc:
        logger.warning("credit_service.find_fee_rule failed: %s", exc)
        return None


_WA_CATEGORY = {"wa_service": "service", "wa_utility": "utility",
                "wa_marketing": "marketing", "wa_auth": "authentication"}


def _units_this_month(db, org_id: str, event_type: str) -> int:
    """
    Events of this type so far this month, including the one being metered.
    WhatsApp events are counted from whatsapp_messages (Meta may bill the
    client directly, so there may be no ledger row); AI from the ledger.
    """
    try:
        if event_type in _WA_CATEGORY:
            res = (
                db.table("whatsapp_messages").select("id", count="exact")
                .eq("org_id", org_id).eq("meta_category", _WA_CATEGORY[event_type])
                .gte("created_at", _month_start()).execute()
            )
        else:
            res = (
                db.table("credit_ledger").select("id", count="exact")
                .eq("org_id", org_id).eq("unit", event_type)
                .in_("kind", ["ai", "meta"]).gte("created_at", _month_start()).execute()
            )
        return int(getattr(res, "count", 0) or 0)
    except Exception:
        return 0


def compute_fee_kobo(db, org_id: str, event_type: str, meta_cost_kobo: int, ai_cost_kobo: int) -> tuple[int, Optional[str]]:
    """(fee_kobo, rule_id). Zero when no rule, or still inside the free units."""
    rule = find_fee_rule(db, org_id, event_type)
    if not rule:
        return 0, None
    free = int(rule.get("free_units_per_month") or 0)
    if free and _units_this_month(db, org_id, event_type) <= free:
        return 0, rule.get("id")
    return _fee_amount(rule, meta_cost_kobo, ai_cost_kobo), rule.get("id")


# ── Atomic ledger calls ─────────────────────────────────────────────────────

def _debit(db, org_id: str, amount: int, kind: str, ref: str, unit: str, meta: dict) -> Optional[dict]:
    try:
        res = db.rpc("credit_debit", {
            "p_org": org_id, "p_amount": int(amount), "p_kind": kind,
            "p_ref": ref, "p_unit": unit, "p_meta": meta,
        }).execute()
        rows = _rows(res)
        return rows[0] if rows else None
    except Exception as exc:
        logger.error("credit_service: credit_debit failed org=%s ref=%s: %s", org_id, ref, exc)
        return None


def add_credit(db, org_id: str, amount_kobo: int, kind: str, ref: str, meta: Optional[dict] = None,
               expires_at: Optional[str] = None) -> Optional[dict]:
    """Top-up / refund / positive adjustment. Idempotent on `ref`. Returns the RPC row or None."""
    try:
        res = db.rpc("credit_credit", {
            "p_org": org_id, "p_amount": int(amount_kobo), "p_kind": kind, "p_ref": ref,
            "p_unit": None, "p_meta": meta or {}, "p_expires_at": expires_at,
        }).execute()
        rows = _rows(res)
        return rows[0] if rows else None
    except Exception as exc:
        logger.error("credit_service: credit_credit failed org=%s ref=%s: %s", org_id, ref, exc)
        return None


# ── Metering ────────────────────────────────────────────────────────────────

def meter_ai_call(db, org_id: Optional[str], *, function_name: str, model: str,
                  cost_usd: float, ref: Optional[str] = None) -> Optional[int]:
    """
    Charge one Claude call to the org's wallet (AI cost + markup, plus any
    'ai_turn' automation fee). Returns kobo charged, or None when the org is
    not metered or anything failed.
    """
    try:
        if not org_id or not cost_usd or cost_usd <= 0:
            return None
        wallet = get_wallet(db, org_id)
        if not metering_on(wallet):
            return None
        rates = get_rates(db)
        if not rates:
            return None
        base = usd_to_kobo(cost_usd, rates, 0)
        charge = usd_to_kobo(cost_usd, rates, rates.get("ai_markup_pct") or 0)
        if charge <= 0:
            return None
        key = ref or f"ai:{org_id}:{datetime.now(timezone.utc).timestamp()}:{function_name}"
        out = _debit(db, org_id, charge, "ai", key, "ai_turn",
                     {"function": function_name, "model": model, "cost_usd": cost_usd, "base_kobo": base})
        charged = int(out["charged_kobo"]) if out else 0
        fee, rule_id = compute_fee_kobo(db, org_id, "ai_turn", 0, base)
        if fee > 0:
            _debit(db, org_id, fee, "fee", f"{key}:fee", "fee:ai_turn", {"rule_id": rule_id})
            charged += fee
        return charged
    except Exception as exc:
        logger.warning("credit_service.meter_ai_call failed: %s", exc)
        return None


def meter_meta_message(db, org_id: Optional[str], *, category: str, billable: bool,
                       meta_message_id: str) -> Optional[int]:
    """
    Meter one outbound WhatsApp message from Meta's status-webhook pricing.

    client_direct (default): Meta bills the client's own account, so Opsra
    debits nothing for Meta itself; only the optional automation fee applies.
    opsra_credit_line: Opsra pays Meta, so the Meta cost + meta_markup_pct is
    debited as well.
    """
    try:
        if not org_id or not meta_message_id:
            return None
        wallet = get_wallet(db, org_id)
        if not metering_on(wallet):
            return None
        rates = get_rates(db)
        if not rates:
            return None
        event = {"service": "wa_service", "utility": "wa_utility",
                 "marketing": "wa_marketing", "authentication": "wa_auth"}.get(category)
        if not event:
            return None
        usd = get_meta_usd(db, category) if billable else 0.0
        meta_kobo = usd_to_kobo(usd or 0.0, rates, 0)
        charged = 0
        if billable and wallet.get("meta_billing") == "opsra_credit_line" and usd:
            amt = usd_to_kobo(usd, rates, rates.get("meta_markup_pct") or 0)
            out = _debit(db, org_id, amt, "meta", f"meta:{meta_message_id}", event,
                         {"category": category, "usd": usd})
            charged += int(out["charged_kobo"]) if out else 0
        fee, rule_id = compute_fee_kobo(db, org_id, event, meta_kobo, 0)
        if fee > 0:
            out = _debit(db, org_id, fee, "fee", f"fee:{meta_message_id}", f"fee:{event}", {"rule_id": rule_id})
            charged += int(out["charged_kobo"]) if out else 0
        return charged
    except Exception as exc:
        logger.warning("credit_service.meter_meta_message failed: %s", exc)
        return None


# ── Budget level / gate ─────────────────────────────────────────────────────

def month_ai_spend_kobo(db, org_id: str) -> int:
    try:
        rows = _rows(
            db.table("credit_ledger").select("amount_kobo")
            .eq("org_id", org_id).eq("kind", "ai").gte("created_at", _month_start()).execute()
        )
        return -sum(int(r.get("amount_kobo") or 0) for r in rows)
    except Exception:
        return 0


def get_ai_level(db, org_id: Optional[str]) -> str:
    """
    normal → cheaper_model (80% of the monthly AI budget) → menu_only (100%,
    or an empty wallet). Orgs that are not metered always get 'normal'.
    """
    try:
        if not org_id:
            return LEVEL_NORMAL
        wallet = get_wallet(db, org_id)
        if not metering_on(wallet):
            return LEVEL_NORMAL
        if int(wallet.get("balance_kobo") or 0) <= 0:
            return LEVEL_MENU
        budget = wallet.get("ai_monthly_budget_kobo")
        if not budget:
            return LEVEL_NORMAL
        used = month_ai_spend_kobo(db, org_id)
        if used >= budget * MENU_AT:
            return LEVEL_MENU
        if used >= budget * CHEAPER_AT:
            return LEVEL_CHEAPER
        return LEVEL_NORMAL
    except Exception as exc:
        logger.warning("credit_service.get_ai_level failed: %s", exc)
        return LEVEL_NORMAL
