"""
app/services/credit_order_service.py
------------------------------------
CREDITS-2 — what a business sees and does with its credit wallet.

  * summary / usage / ledger  : read-only views of the CREDITS-1 tables (always scoped to the caller's org)
  * create_order              : a pack or a custom amount -> a Paystack checkout on OPSRA's own keys
                                (env PAYSTACK_SECRET_KEY, the same account the platform webhook already verifies)
  * mark_paid / verify        : the money arrives -> credit the wallet, once. Two routes can report a payment
                                (the Paystack webhook, and the customer coming back to the page); both end in
                                mark_paid, which is idempotent on the Paystack reference.

Money rules
  * Everything is kobo. A pack gives credit_kobo (equal to its price; no bonus). A custom amount gives exactly
    what was paid. Credit expires 12 months after purchase (the CREDITS-1 lots do that).
  * The amount credited is the amount of the ORDER we stored, and only if Paystack says at least that much was
    paid. Nothing the browser sends can change an amount.
  * Credits only leave a wallet through metering (CREDITS-1) or a superadmin adjustment.

S14: read helpers never raise. create_order / verify raise CreditOrderError with a message safe to show.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.services import credit_service

logger = logging.getLogger(__name__)

PAYSTACK_API = "https://api.paystack.co"
MIN_CUSTOM_KOBO = 200_000          # N2,000
MAX_ORDER_KOBO = 100_000_000       # N1,000,000
LEDGER_PAGE = 50
USAGE_ROW_CAP = 5000


class CreditOrderError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _rows(res) -> list:
    return list(getattr(res, "data", None) or [])


def _secret() -> str:
    return os.getenv("PAYSTACK_SECRET_KEY", "").strip()


# ── Reads ───────────────────────────────────────────────────────────────────

def list_packs(db) -> list[dict]:
    try:
        rows = _rows(db.table("credit_packs").select("id, name, price_kobo, credit_kobo")
                     .eq("active", True).order("sort_order").limit(20).execute())
        return [{"id": r["id"], "name": r["name"], "price_kobo": int(r["price_kobo"]),
                 "credit_kobo": int(r["credit_kobo"])} for r in rows]
    except Exception as exc:
        logger.warning("credit_order_service.list_packs failed: %s", exc)
        return []


def summary(db, org_id: str) -> dict:
    """Balance, what is about to expire, and this month's spend by kind."""
    wallet = credit_service.get_wallet(db, org_id) or {}
    now = _now()
    out = {
        "balance_kobo": int(wallet.get("balance_kobo") or 0),
        "metering_enabled": bool(wallet.get("metering_enabled")),
        "ai_monthly_budget_kobo": wallet.get("ai_monthly_budget_kobo"),
        "low_balance_kobo": int(wallet.get("low_balance_kobo") or 0),
        "expiring": None, "month_spend_kobo": {"ai": 0, "meta": 0, "fee": 0}, "month_spend_total_kobo": 0,
        "min_custom_kobo": MIN_CUSTOM_KOBO, "max_order_kobo": MAX_ORDER_KOBO,
    }
    try:
        lots = _rows(db.table("credit_lots").select("remaining_kobo, expires_at").eq("org_id", org_id)
                     .gt("remaining_kobo", 0).order("expires_at").limit(1).execute())
        if lots:
            out["expiring"] = {"kobo": int(lots[0]["remaining_kobo"]), "at": lots[0]["expires_at"]}
    except Exception as exc:
        logger.warning("credit summary lots failed org=%s: %s", org_id, exc)
    try:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = _rows(db.table("credit_ledger").select("kind, amount_kobo").eq("org_id", org_id)
                     .gte("created_at", _iso(start)).limit(USAGE_ROW_CAP).execute())
        for r in rows:
            if r["kind"] in out["month_spend_kobo"] and int(r["amount_kobo"]) < 0:
                out["month_spend_kobo"][r["kind"]] += -int(r["amount_kobo"])
        out["month_spend_total_kobo"] = sum(out["month_spend_kobo"].values())
    except Exception as exc:
        logger.warning("credit summary spend failed org=%s: %s", org_id, exc)
    return out


def usage(db, org_id: str, days: int = 30) -> dict:
    """Spend per day and per kind over the last `days` (1-90)."""
    days = max(1, min(int(days or 30), 90))
    since = _now() - timedelta(days=days)
    try:
        rows = _rows(db.table("credit_ledger").select("kind, amount_kobo, created_at").eq("org_id", org_id)
                     .gte("created_at", _iso(since)).limit(USAGE_ROW_CAP).execute())
    except Exception as exc:
        logger.warning("credit usage failed org=%s: %s", org_id, exc)
        rows = []
    per_day: dict[str, dict] = {}
    totals = {"ai": 0, "meta": 0, "fee": 0}
    topped_up = 0
    for r in rows:
        amt, kind = int(r["amount_kobo"]), r["kind"]
        day = str(r["created_at"])[:10]
        if amt < 0 and kind in totals:
            d = per_day.setdefault(day, {"day": day, "ai": 0, "meta": 0, "fee": 0})
            d[kind] += -amt
            totals[kind] += -amt
        elif amt > 0 and kind == "topup":
            topped_up += amt
    series = []
    for i in range(days):
        day = (since + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        series.append(per_day.get(day, {"day": day, "ai": 0, "meta": 0, "fee": 0}))
    return {"days": days, "series": series, "totals_kobo": totals, "spent_kobo": sum(totals.values()),
            "topped_up_kobo": topped_up}


def ledger(db, org_id: str, before: Optional[str] = None, limit: int = LEDGER_PAGE) -> dict:
    limit = max(1, min(int(limit or LEDGER_PAGE), 100))
    try:
        q = (db.table("credit_ledger").select("id, kind, amount_kobo, balance_after_kobo, unit, created_at")
             .eq("org_id", org_id).order("created_at", desc=True).limit(limit))
        if before:
            q = q.lt("created_at", before)
        rows = _rows(q.execute())
    except Exception as exc:
        logger.warning("credit ledger failed org=%s: %s", org_id, exc)
        rows = []
    return {"entries": rows, "next": rows[-1]["created_at"] if len(rows) == limit else None}


def orders(db, org_id: str, limit: int = 10) -> list[dict]:
    try:
        return _rows(db.table("credit_orders").select("id, amount_kobo, status, created_at, paid_at, paystack_reference")
                     .eq("org_id", org_id).order("created_at", desc=True).limit(limit).execute())
    except Exception as exc:
        logger.warning("credit orders failed org=%s: %s", org_id, exc)
        return []


# ── Buying ──────────────────────────────────────────────────────────────────

def create_order(db, org_id: str, email: str, *, pack_id: Optional[str] = None,
                 amount_kobo: Optional[int] = None, callback_url: Optional[str] = None) -> dict:
    """Store a pending order and start a Paystack checkout. Returns {order_id, reference, checkout_url}."""
    secret = _secret()
    if not secret:
        raise CreditOrderError("Online payment is not available right now. Please contact support.")
    pack_name = None
    if pack_id:
        pack = next((p for p in list_packs(db) if p["id"] == pack_id), None)
        if not pack:
            raise CreditOrderError("That pack is no longer available. Please choose another.")
        price, credit, pack_name = pack["price_kobo"], pack["credit_kobo"], pack["name"]
    else:
        try:
            price = int(amount_kobo)
        except (TypeError, ValueError):
            raise CreditOrderError("Enter an amount in naira.")
        if price < MIN_CUSTOM_KOBO:
            raise CreditOrderError(f"The smallest top-up is N{MIN_CUSTOM_KOBO // 100:,}.")
        if price > MAX_ORDER_KOBO:
            raise CreditOrderError(f"The largest single top-up is N{MAX_ORDER_KOBO // 100:,}. Contact us for more.")
        if price % 100:
            raise CreditOrderError("Enter a whole number of naira.")
        credit = price
    reference = f"cr_{org_id[:8]}_{uuid.uuid4().hex[:12]}"
    row = {"org_id": org_id, "pack_id": pack_id, "pack_name": pack_name, "amount_kobo": price, "credit_kobo": credit,
           "status": "pending", "paystack_reference": reference}
    try:
        order = (_rows(db.table("credit_orders").insert(row).execute()) or [row])[0]
    except Exception as exc:
        logger.error("credit order insert failed org=%s: %s", org_id, exc)
        raise CreditOrderError("Could not start your payment. Please try again.")
    body = {"email": (email or "").strip() or f"org-{org_id[:8]}@example.com", "amount": price, "currency": "NGN",
            "reference": reference, "metadata": {"kind": "credit_topup", "org_id": org_id, "order_id": order.get("id")}}
    if callback_url:
        body["callback_url"] = callback_url
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(f"{PAYSTACK_API}/transaction/initialize",
                               headers={"Authorization": f"Bearer {secret}"}, json=body)
        data = resp.json()
        if resp.status_code != 200 or not data.get("status"):
            raise ValueError(data.get("message") or "Paystack refused")
        url = (data.get("data") or {}).get("authorization_url")
        if not url:
            raise ValueError("no checkout url")
    except Exception as exc:
        logger.warning("credit checkout failed org=%s: %s", org_id, exc)
        try:
            db.table("credit_orders").update({"status": "failed"}).eq("id", order.get("id")).eq("org_id", org_id).execute()
        except Exception:
            pass
        raise CreditOrderError("Could not reach Paystack right now. Please try again shortly.")
    try:
        db.table("credit_orders").update({"checkout_url": url}).eq("id", order.get("id")).eq("org_id", org_id).execute()
    except Exception:
        pass
    return {"order_id": order.get("id"), "reference": reference, "checkout_url": url}


def mark_paid(db, reference: str, paid_kobo: int) -> dict:
    """
    Credit the wallet for a paid order. Safe to call any number of times and from both the webhook and
    the return page. Returns {"credited": bool, "reason": str}.
    """
    if not reference or not str(reference).startswith("cr_"):
        return {"credited": False, "reason": "not_a_credit_order"}
    rows = _rows(db.table("credit_orders").select("*").eq("paystack_reference", reference).limit(1).execute())
    if not rows:
        return {"credited": False, "reason": "unknown_reference"}
    order = rows[0]
    if int(paid_kobo or 0) < int(order["amount_kobo"]):
        logger.warning("credit order %s underpaid: paid=%s expected=%s", reference, paid_kobo, order["amount_kobo"])
        return {"credited": False, "reason": "underpaid"}
    # The wallet credit is idempotent on its ref, so a repeat call cannot add credit twice even if the
    # order row is already marked paid. Credit first, then mark the order.
    res = credit_service.add_credit(db, order["org_id"], int(order["credit_kobo"]), "topup", f"order:{reference}",
                                    meta={"order_id": order.get("id"), "pack": order.get("pack_name"),
                                          "paid_kobo": int(paid_kobo)})
    if res is None:
        return {"credited": False, "reason": "credit_failed"}
    try:
        (db.table("credit_orders").update({"status": "paid", "paid_at": _iso(_now())})
         .eq("id", order["id"]).eq("org_id", order["org_id"]).neq("status", "paid").execute())
    except Exception as exc:
        logger.warning("credit order %s paid-mark failed: %s", reference, exc)
    return {"credited": bool(res.get("applied", True)), "reason": "ok" if res.get("applied", True) else "already_credited"}


def verify(db, org_id: str, reference: str) -> dict:
    """The customer came back from Paystack: ask Paystack, and credit if it was paid. Own-org orders only."""
    if not reference or not str(reference).startswith("cr_"):
        raise CreditOrderError("That payment reference is not valid.")
    rows = _rows(db.table("credit_orders").select("id, status, org_id, amount_kobo")
                 .eq("paystack_reference", reference).eq("org_id", org_id).limit(1).execute())
    if not rows:
        raise CreditOrderError("We could not find that payment.")
    if rows[0]["status"] == "paid":
        return {"status": "paid"}
    secret = _secret()
    if not secret:
        return {"status": rows[0]["status"]}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{PAYSTACK_API}/transaction/verify/{reference}", headers={"Authorization": f"Bearer {secret}"})
        data = (resp.json() or {}).get("data") or {}
    except Exception as exc:
        logger.warning("credit verify failed ref=%s: %s", reference, exc)
        return {"status": "pending"}
    if data.get("status") == "success":
        res = mark_paid(db, reference, int(data.get("amount") or 0))
        return {"status": "paid" if res["reason"] in ("ok", "already_credited") else "pending"}
    if data.get("status") in ("failed", "abandoned"):
        return {"status": "failed"}
    return {"status": "pending"}
