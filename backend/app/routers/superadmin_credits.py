"""
app/routers/superadmin_credits.py
---------------------------------
CREDITS-1 — superadmin controls for the credits system. Bearer superadmin JWT.

  GET   /superadmin/credits/orgs/{org_id}          wallet + latest ledger rows
  PATCH /superadmin/credits/orgs/{org_id}/wallet   metering on/off, Meta billing mode, budget
  POST  /superadmin/credits/orgs/{org_id}/adjust   add or remove credit (needs a note)
  GET   /superadmin/credits/rates                  rate history
  POST  /superadmin/credits/rates                  new rate row (FX, markups) — history is kept
  GET   /superadmin/credits/fee-rules              all automation-fee rules
  POST  /superadmin/credits/fee-rules              create a rule (created DISABLED)
  PATCH /superadmin/credits/fee-rules/{id}         edit / enable / disable
  POST  /superadmin/credits/fee-rules/preview      what a rule would charge, before enabling
  GET   /superadmin/credits/meta-rates             Meta rate cards
  POST  /superadmin/credits/meta-rates             new Meta rate card row
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.models.common import ok
from app.routers.superadmin_health import require_superadmin
from app.services import credit_service

logger = logging.getLogger(__name__)
router = APIRouter()

_EVENTS = Literal["wa_service", "wa_utility", "wa_marketing", "wa_auth", "ai_turn", "email", "any"]
_MODES = Literal["flat_kobo", "percent_of_meta_cost", "percent_of_ai_cost"]


class WalletPatch(BaseModel):
    metering_enabled: Optional[bool] = None
    meta_billing: Optional[Literal["client_direct", "opsra_credit_line"]] = None
    ai_monthly_budget_kobo: Optional[int] = Field(default=None, ge=0)
    low_balance_kobo: Optional[int] = Field(default=None, ge=0)


class AdjustBody(BaseModel):
    amount_kobo: int
    note: str = Field(min_length=5, max_length=300)   # the reason, always recorded in the ledger
    ref: str = Field(min_length=3, max_length=120)  # idempotency key chosen by the caller
    kind: Literal["adjust", "refund"] = "adjust"       # CREDITS-3: refunds are tagged so reports can show them


class RateBody(BaseModel):
    fx_ngn_per_usd: float = Field(gt=0)
    ai_markup_pct: float = Field(ge=0, default=50)
    meta_markup_pct: float = Field(ge=0, default=0)
    min_charge_kobo: int = Field(ge=0, default=0)
    rounding_kobo: int = Field(ge=1, default=1)
    note: Optional[str] = None


class FeeRuleBody(BaseModel):
    scope: Literal["default", "org"] = "default"
    org_id: Optional[str] = None
    event_type: _EVENTS
    mode: _MODES
    value: float = Field(ge=0)
    min_kobo: int = Field(ge=0, default=0)
    max_kobo: Optional[int] = Field(default=None, ge=0)
    free_units_per_month: int = Field(ge=0, default=0)
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    note: Optional[str] = None


class FeeRulePatch(BaseModel):
    value: Optional[float] = Field(default=None, ge=0)
    min_kobo: Optional[int] = Field(default=None, ge=0)
    max_kobo: Optional[int] = Field(default=None, ge=0)
    free_units_per_month: Optional[int] = Field(default=None, ge=0)
    effective_to: Optional[str] = None
    enabled: Optional[bool] = None
    note: Optional[str] = None


class PreviewBody(FeeRuleBody):
    sample_meta_cost_kobo: int = Field(ge=0, default=0)
    sample_ai_cost_kobo: int = Field(ge=0, default=0)


class MetaRateBody(BaseModel):
    country: str = Field(default="NG", min_length=2, max_length=2)
    category: Literal["service", "utility", "marketing", "authentication"]
    usd_per_message: float = Field(ge=0)
    effective_from: str
    source: Optional[str] = None


def _check_scope(body: FeeRuleBody) -> None:
    if (body.scope == "org") != bool(body.org_id):
        raise HTTPException(status_code=422, detail="org_id is required for scope 'org' and not allowed for 'default'")
    if body.max_kobo is not None and body.max_kobo < body.min_kobo:
        raise HTTPException(status_code=422, detail="max_kobo must be at least min_kobo")


@router.get("/superadmin/credits/orgs/{org_id}")
def get_org_credits(org_id: str, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    wallet = credit_service.get_wallet(db, org_id)
    ledger = (db.table("credit_ledger").select("*").eq("org_id", org_id)
              .order("created_at", desc=True).limit(50).execute().data or [])
    return ok({"wallet": wallet, "ledger": ledger,
               "ai_level": credit_service.get_ai_level(db, org_id)})


@router.patch("/superadmin/credits/orgs/{org_id}/wallet")
def patch_wallet(org_id: str, body: WalletPatch, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to change")
    db.table("credit_wallets").upsert({"org_id": org_id}, on_conflict="org_id", ignore_duplicates=True).execute()
    db.table("credit_wallets").update(changes).eq("org_id", org_id).execute()
    return ok(credit_service.get_wallet(db, org_id))


@router.post("/superadmin/credits/orgs/{org_id}/adjust")
def adjust(org_id: str, body: AdjustBody, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    if body.amount_kobo == 0:
        raise HTTPException(status_code=422, detail="amount_kobo must not be zero")
    meta = {"note": body.note, "by": "superadmin"}
    if body.amount_kobo > 0:
        out = credit_service.add_credit(db, org_id, body.amount_kobo, body.kind, body.ref, meta)
    else:
        out = credit_service._debit(db, org_id, -body.amount_kobo, body.kind, body.ref, body.kind, meta)
    if out is None:
        raise HTTPException(status_code=500, detail="Adjustment failed")
    return ok(out)


@router.get("/superadmin/credits/rates")
def list_rates(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    return ok(db.table("credit_rates").select("*").order("effective_from", desc=True).limit(50).execute().data or [])


@router.post("/superadmin/credits/rates")
def add_rate(body: RateBody, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    row = db.table("credit_rates").insert(body.model_dump()).execute().data
    return ok(row[0] if row else None)


@router.get("/superadmin/credits/fee-rules")
def list_fee_rules(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    return ok(db.table("automation_fee_rules").select("*").order("created_at", desc=True).execute().data or [])


@router.post("/superadmin/credits/fee-rules")
def create_fee_rule(body: FeeRuleBody, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    _check_scope(body)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    data["enabled"] = False  # always starts off; preview first, then enable
    row = db.table("automation_fee_rules").insert(data).execute().data
    return ok(row[0] if row else None)


@router.patch("/superadmin/credits/fee-rules/{rule_id}")
def patch_fee_rule(rule_id: str, body: FeeRulePatch, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to change")
    row = db.table("automation_fee_rules").update(changes).eq("id", rule_id).execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return ok(row[0])


@router.post("/superadmin/credits/fee-rules/preview")
def preview_fee_rule(body: PreviewBody, _: None = Depends(require_superadmin)):
    _check_scope(body)
    fee = credit_service._fee_amount(body.model_dump(), body.sample_meta_cost_kobo, body.sample_ai_cost_kobo)
    return ok({"fee_kobo": fee, "fee_naira": fee / 100})


@router.get("/superadmin/credits/meta-rates")
def list_meta_rates(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    return ok(db.table("meta_rate_cards").select("*").order("effective_from", desc=True).limit(100).execute().data or [])


@router.post("/superadmin/credits/meta-rates")
def add_meta_rate(body: MetaRateBody, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    row = db.table("meta_rate_cards").insert(body.model_dump()).execute().data
    return ok(row[0] if row else None)


# ── CREDITS-3: overview, margin report, reconcile ───────────────────────────

_PAGE = 1000


def _all(make_query, cap: int = 50000) -> list:
    """Page through a PostgREST query (default 1000-row cap). make_query() returns a fresh query each call."""
    rows: list = []
    while len(rows) < cap:
        batch = make_query().range(len(rows), len(rows) + _PAGE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < _PAGE:
            break
    return rows


def _since(days: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@router.get("/superadmin/credits/orgs")
def list_orgs(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    """Every business with a wallet or a name: balance, metering switch, this month's AI spend, total top-ups."""
    orgs = _all(lambda: db.table("organisations").select("id, name").order("name"))
    wallets = {w["org_id"]: w for w in _all(lambda: db.table("credit_wallets").select("*"))}
    tops: dict = {}
    for r in _all(lambda: db.table("credit_ledger").select("org_id, amount_kobo").eq("kind", "topup")):
        tops[r["org_id"]] = tops.get(r["org_id"], 0) + int(r["amount_kobo"])
    out = []
    for o in orgs:
        w = wallets.get(o["id"]) or {}
        out.append({
            "org_id": o["id"], "name": o.get("name"), "has_wallet": bool(w),
            "balance_kobo": int(w.get("balance_kobo") or 0), "metering_enabled": bool(w.get("metering_enabled")),
            "meta_billing": w.get("meta_billing") or "client_direct",
            "ai_monthly_budget_kobo": w.get("ai_monthly_budget_kobo"),
            "month_ai_spend_kobo": credit_service.month_ai_spend_kobo(db, o["id"]) if w else 0,
            "topups_total_kobo": tops.get(o["id"], 0),
        })
    out.sort(key=lambda r: (not r["metering_enabled"], -r["topups_total_kobo"], r["name"] or ""))
    return ok({"orgs": out})


@router.get("/superadmin/credits/margin")
def margin_report(days: int = 30, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    """
    What was charged versus what it cost, from the ledger. AI cost = the base_kobo stored with each debit
    (provider cost at the FX rate used that day). Meta cost counts only for opsra_credit_line debits.
    Paystack fees are NOT included. 'recognised' = AI + fees + Meta charged + expired credit.
    """
    days = max(1, min(int(days or 30), 365))
    since = _since(days)
    rows = _all(lambda: db.table("credit_ledger").select("org_id, kind, amount_kobo, meta, created_at")
                .gte("created_at", since).order("created_at"))
    rates = credit_service.get_rates(db) or {}
    fx = float(rates.get("fx_ngn_per_usd") or 0)
    names = {o["id"]: o.get("name") for o in _all(lambda: db.table("organisations").select("id, name"))}
    per: dict = {}

    def bucket(org_id):
        return per.setdefault(org_id, {"org_id": org_id, "name": names.get(org_id), "cash_in_kobo": 0,
                                       "ai_charged_kobo": 0, "ai_cost_kobo": 0, "fee_charged_kobo": 0,
                                       "meta_charged_kobo": 0, "meta_cost_kobo": 0, "expired_kobo": 0,
                                       "refunds_kobo": 0, "adjustments_kobo": 0, "ai_calls": 0})

    for r in rows:
        b, amt, kind, meta = bucket(r["org_id"]), int(r["amount_kobo"]), r["kind"], (r.get("meta") or {})
        if kind == "topup":
            b["cash_in_kobo"] += amt
        elif kind == "ai":
            b["ai_charged_kobo"] += -amt
            b["ai_cost_kobo"] += int(meta.get("base_kobo") or 0)
            b["ai_calls"] += 1
        elif kind == "fee":
            b["fee_charged_kobo"] += -amt
        elif kind == "meta":
            b["meta_charged_kobo"] += -amt
            b["meta_cost_kobo"] += int(round(float(meta.get("usd") or 0) * fx * 100)) if fx else 0
        elif kind == "expiry":
            b["expired_kobo"] += -amt
        elif kind == "refund":
            b["refunds_kobo"] += amt
        elif kind == "adjust":
            b["adjustments_kobo"] += amt
    orgs = []
    for b in per.values():
        b["margin_kobo"] = (b["ai_charged_kobo"] - b["ai_cost_kobo"]) + b["fee_charged_kobo"] \
            + (b["meta_charged_kobo"] - b["meta_cost_kobo"]) + b["expired_kobo"]
        orgs.append(b)
    orgs.sort(key=lambda b: -(b["ai_charged_kobo"] + b["fee_charged_kobo"] + b["meta_charged_kobo"]))
    keys = [k for k in (orgs[0] if orgs else {}) if k.endswith("_kobo") or k == "ai_calls"]
    totals = {k: sum(b[k] for b in orgs) for k in keys}
    return ok({"days": days, "since": since, "totals": totals, "orgs": orgs,
               "notes": ["Paystack fees are not included.", "Expired credit counts as income once it lapses.",
                         "AI cost uses the FX rate in force when each call was charged."]})


@router.get("/superadmin/credits/reconcile")
def reconcile(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    """Wallets whose balance disagrees with the ledger or the lots. Empty list = all good."""
    from app.workers.credit_worker import reconcile_wallets
    return ok({"mismatches": reconcile_wallets(db)})
