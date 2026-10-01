"""
app/services/site_discount_service.py
--------------------------------------
SITE-DISCOUNT — discount codes for site-hosting orders.

A code takes a percentage or a fixed naira amount off the WHOLE order total
of an INITIAL order (renewals and care plans are not discounted). Codes can
have an expiry, a maximum number of uses and a one-use-per-builder rule.

Rules:
- The discount is always re-derived on the server from the code row; the
  client only ever sends the code text.
- The amount due never drops below MIN_PAYABLE_NGN, so the payment link is
  always valid. (A genuinely free hosting deal is done by setting the hosting
  price to 0 in Pricing, not with a code.)
- Uses are counted from PAID orders (site_discount_redemptions), recorded when
  the payment is confirmed. One redemption per order (unique index), so a
  repeated webhook can never count twice.
- S14: validate()/preview() raise DiscountError with a plain, friendly message
  (the caller shows it); record_redemption() never raises.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

MIN_PAYABLE_NGN = 100.0
KINDS = ("percent", "fixed")


class DiscountError(Exception):
    """A code can't be used — the message is safe to show to the builder."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def normalise_code(code: Optional[str]) -> str:
    return "".join((code or "").split()).upper()


def compute_discount(kind: str, value: float, total: float) -> float:
    """Naira taken off `total`; never leaves less than MIN_PAYABLE_NGN to pay."""
    total = float(total or 0)
    value = float(value or 0)
    if kind == "percent":
        raw = total * value / 100.0
    elif kind == "fixed":
        raw = value
    else:
        raw = 0.0
    ceiling = max(total - MIN_PAYABLE_NGN, 0.0)
    return round(max(min(raw, ceiling), 0.0), 2)


def _uses(db: Any, code_id: str, builder_id: Optional[str] = None) -> int:
    q = db.table("site_discount_redemptions").select("id").eq("code_id", code_id)
    if builder_id:
        q = q.eq("builder_id", builder_id)
    return len(q.execute().data or [])


def validate(db: Any, org_id: str, builder_id: Optional[str], code: str, total: float, now: Optional[datetime] = None) -> dict:
    """Returns {code_id, code, kind, value, discount, amount_due}. Raises DiscountError."""
    now = now or _now()
    norm = normalise_code(code)
    if not norm:
        raise DiscountError("Enter a code.")
    row = _one((db.table("site_discount_codes").select("*").eq("org_id", org_id)
                .eq("code", norm).limit(1).execute()).data)
    # One message for unknown AND switched-off codes, so codes can't be guessed.
    if not row or not row.get("active"):
        raise DiscountError("That code isn't valid.")
    exp = _parse_iso(row.get("expires_at"))
    if exp and exp <= now:
        raise DiscountError("That code has expired.")
    max_uses = row.get("max_uses")
    if max_uses is not None and _uses(db, row["id"]) >= int(max_uses):
        raise DiscountError("That code has been used up.")
    if row.get("one_per_builder") and builder_id and _uses(db, row["id"], builder_id) >= 1:
        raise DiscountError("You've already used that code.")

    discount = compute_discount(row["kind"], row["value"], total)
    if discount <= 0:
        raise DiscountError("That code doesn't reduce this order.")
    return {
        "code_id": row["id"],
        "code": row["code"],
        "kind": row["kind"],
        "value": float(row["value"]),
        "discount": discount,
        "amount_due": round(float(total) - discount, 2),
    }


def apply_to_quotes(db: Any, org_id: str, builder_id: Optional[str], code: Optional[str], quotes: dict) -> dict:
    """Adds a `discount` block and `amount_due` to each route quote in a quote_both_routes() result.
    A bad code never breaks pricing: the reason is returned as `discount_error`. Returns `quotes`."""
    norm = normalise_code(code)
    if not norm:
        return quotes
    error: Optional[str] = None
    applied_any = False
    for route in ("standard", "express"):
        q = quotes.get(route)
        if not isinstance(q, dict) or q.get("error"):
            continue
        try:
            d = validate(db, org_id, builder_id, norm, q["price"]["total"])
        except DiscountError as exc:
            error = str(exc)
            break
        q["discount"] = {k: d[k] for k in ("code", "kind", "value", "discount")}
        q["amount_due"] = d["amount_due"]
        applied_any = True
    if error:
        quotes["discount_error"] = error
    elif not applied_any:
        quotes["discount_error"] = "That code can't be used on this order."
    return quotes


def record_redemption(db: Any, org_id: str, order: dict) -> None:
    """Called when an order is paid. Reads the discount saved in order.quote. S14 — never raises."""
    try:
        d = ((order.get("quote") or {}).get("discount")) or None
        if not d or not d.get("code_id"):
            return
        db.table("site_discount_redemptions").insert({
            "org_id": org_id,
            "code_id": d["code_id"],
            "builder_id": order.get("builder_id"),
            "order_id": order.get("id"),
            "amount_ngn": float(d.get("discount") or 0),
        }).execute()
    except Exception as exc:  # duplicate webhook hits the unique index — fine
        logger.info("site_discount.record_redemption skipped order=%s: %s", order.get("id"), exc)


# ---------------------------------------------------------------------------
# Staff management (routers/sites.py)
# ---------------------------------------------------------------------------

def _clean_payload(payload: dict, creating: bool) -> dict:
    out: dict = {}
    if creating or "code" in payload:
        code = normalise_code(payload.get("code"))
        if not (3 <= len(code) <= 40) or not all(c.isalnum() or c in "-_" for c in code):
            raise DiscountError("Code must be 3-40 letters, numbers, - or _ (no spaces).")
        out["code"] = code
    if creating or "kind" in payload:
        if payload.get("kind") not in KINDS:
            raise DiscountError("Choose percent or fixed amount.")
        out["kind"] = payload["kind"]
    if creating or "value" in payload:
        try:
            value = float(payload.get("value"))
        except (TypeError, ValueError):
            raise DiscountError("Enter the discount amount.")
        if value <= 0:
            raise DiscountError("The discount must be more than zero.")
        out["value"] = value
    kind = out.get("kind") or payload.get("kind")
    if kind == "percent" and out.get("value", 0) > 100:
        raise DiscountError("A percentage can't be more than 100.")
    if "note" in payload:
        out["note"] = (payload.get("note") or "").strip()[:200] or None
    if "active" in payload:
        out["active"] = bool(payload["active"])
    if "one_per_builder" in payload:
        out["one_per_builder"] = bool(payload["one_per_builder"])
    if "max_uses" in payload:
        mu = payload.get("max_uses")
        if mu in (None, ""):
            out["max_uses"] = None
        else:
            try:
                mu = int(mu)
            except (TypeError, ValueError):
                raise DiscountError("Max uses must be a whole number.")
            if mu <= 0:
                raise DiscountError("Max uses must be at least 1.")
            out["max_uses"] = mu
    if "expires_at" in payload:
        ea = payload.get("expires_at")
        if ea in (None, ""):
            out["expires_at"] = None
        else:
            if not _parse_iso(ea):
                raise DiscountError("That expiry date isn't valid.")
            out["expires_at"] = _parse_iso(ea).isoformat()
    return out


def list_codes(db: Any, org_id: str) -> list[dict]:
    rows = (db.table("site_discount_codes").select("*").eq("org_id", org_id)
            .order("created_at", desc=True).execute().data) or []
    reds = (db.table("site_discount_redemptions").select("code_id, amount_ngn").eq("org_id", org_id).execute().data) or []
    used: dict[str, int] = {}
    given: dict[str, float] = {}
    for r in reds:
        used[r["code_id"]] = used.get(r["code_id"], 0) + 1
        given[r["code_id"]] = given.get(r["code_id"], 0.0) + float(r.get("amount_ngn") or 0)
    for row in rows:
        row["uses"] = used.get(row["id"], 0)
        row["discount_given_ngn"] = round(given.get(row["id"], 0.0), 2)
    return rows


def create_code(db: Any, org_id: str, payload: dict) -> dict:
    data = _clean_payload(payload or {}, creating=True)
    exists = _one((db.table("site_discount_codes").select("id").eq("org_id", org_id)
                   .eq("code", data["code"]).limit(1).execute()).data)
    if exists:
        raise DiscountError("You already have a code with that name.")
    data["org_id"] = org_id
    data.setdefault("active", True)
    data.setdefault("one_per_builder", False)
    res = db.table("site_discount_codes").insert(data).execute()
    return _one(res.data) or data


def update_code(db: Any, org_id: str, code_id: str, payload: dict) -> dict:
    data = _clean_payload(payload or {}, creating=False)
    row = _one((db.table("site_discount_codes").select("*").eq("id", code_id).eq("org_id", org_id).limit(1).execute()).data)
    if not row:
        raise DiscountError("Code not found.")
    # Re-check percent range against the stored kind when only the value changes.
    if "value" in data and "kind" not in data and row["kind"] == "percent" and data["value"] > 100:
        raise DiscountError("A percentage can't be more than 100.")
    if "code" in data and data["code"] != row["code"]:
        clash = _one((db.table("site_discount_codes").select("id").eq("org_id", org_id)
                      .eq("code", data["code"]).limit(1).execute()).data)
        if clash:
            raise DiscountError("You already have a code with that name.")
    data["updated_at"] = _now().isoformat()
    db.table("site_discount_codes").update(data).eq("id", code_id).eq("org_id", org_id).execute()
    return _one((db.table("site_discount_codes").select("*").eq("id", code_id).eq("org_id", org_id).limit(1).execute()).data)


def delete_code(db: Any, org_id: str, code_id: str) -> None:
    """Hard-delete. Codes that were already used are switched off instead so history stays."""
    if _uses(db, code_id) > 0:
        db.table("site_discount_codes").update({"active": False, "updated_at": _now().isoformat()}) \
            .eq("id", code_id).eq("org_id", org_id).execute()
        return
    db.table("site_discount_codes").delete().eq("id", code_id).eq("org_id", org_id).execute()
