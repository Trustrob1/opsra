"""
app/services/site_addon_billing_service.py
--------------------------------------------
SITE-ADDONS A0-2 - what a client pays for a site's tier or add-on, and what happens to the money and the dates.
(Link mode: one Paystack payment link per month, with reminders. Automatic card billing is A0-2b.)

Who pays: the CLIENT (the business that owns the site), not the builder. The order and the site_addons row stay in the
site's own organisation, which owns the Paystack keys. The client has no Opsra login: staff or the builder send them a
private pay page (PUBLIC_API_URL/site-pay/{token}); the page shows what they get and the price, and its button creates (or
reuses) the Paystack link. Prices, setup fees and grace days come from Settings on the server every time; nothing the
browser sends can change an amount.

Money rules
  * First order of a tier = monthly price + that tier's set-up fee (once per site). Renewals = monthly price only.
  * Renewal paid early keeps the unused days (the new period starts when the old one ends).
  * UPGRADE (paid, running tier -> a dearer tier): pay the new tier's price minus a credit for the unused days of the old
    one; the new tier starts at once for a fresh period.
  * DOWNGRADE (paid, running tier -> a cheaper tier): nothing to pay now. It is scheduled (config.pending_key) and applies
    when the NEXT renewal is paid, at the lower price.
  * Any other change (unpaid, staff-granted or paused row): a plain switch to the new tier, no credit.
  * If a price changes in Settings while a link is open, the old link is expired and a new one made; a payment that lands
    on an expired order raises the existing "late payment" alert (site_order_service).

Lifecycle (run_cycle, daily): active -> grace at paid_until -> paused when the grace days are over. Features follow the
dates even if the worker is late (site_entitlement_service.effective_status). Reminders go to the client (email first;
WhatsApp only inside Meta's 24-hour window, or with an approved template named in SITE_ADDON_TEMPLATE), once per
reminder day (default 5 and 1 days before the end). The builder is told when the client lapses or pauses.

S14: on_paid and the worker never raise past their caller; message sends return a bool.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.services import site_entitlement_service as ent
from app.services import site_feature_registry as reg

logger = logging.getLogger(__name__)

KIND = "site_addon"
TEMPLATE_ENV = "SITE_ADDON_TEMPLATE"
WHATSAPP_WINDOW_HOURS = 24
LAGOS = timezone(timedelta(hours=1))
MIN_AMOUNT_NGN = 100


class AddonBillingError(ent.EntitlementError):
    """Typed, user-facing failure (router maps it to a 4xx)."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).astimezone(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _money(n) -> str:
    return f"₦{float(n):,.0f}"


def _pretty(dt: Optional[datetime]) -> str:
    return dt.astimezone(LAGOS).strftime("%d %b %Y") if dt else "soon"


def pay_url(raw_token: str) -> str:
    base = os.environ.get("PUBLIC_API_URL", "https://opsra.onrender.com").rstrip("/")
    return f"{base}/site-pay/{raw_token}"


def _settings(db: Any, org_id: str) -> dict:
    return ent._settings(db, org_id)


def _get_row(db: Any, org_id: str, addon_id: str) -> Optional[dict]:
    return _one((db.table("site_addons").select("*").eq("id", addon_id).eq("org_id", org_id).limit(1).execute()).data)


def _get_site(db: Any, org_id: str, site_id: str) -> dict:
    site = _one((db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).is_("deleted_at", "null")
                 .limit(1).execute()).data)
    if not site:
        raise ent.EntitlementNotFound("Site not found")
    return site


def _builder_of(db: Any, org_id: str, site: dict) -> Optional[dict]:
    if not site.get("builder_id"):
        return None
    return _one((db.table("site_builders").select("*").eq("id", site["builder_id"]).eq("org_id", org_id)
                 .limit(1).execute()).data)


def _defs(cfg: dict, kind: str) -> dict:
    return cfg["tiers"] if kind == "tier" else cfg["addons"]


def _business(site: dict) -> str:
    return site.get("client_business_name") or "your business"


# ---------------------------------------------------------------------------
# quote (what the next order will cost) and credit
# ---------------------------------------------------------------------------

def _credit_for_unused(row: dict, cfg: dict, now: datetime) -> int:
    """Naira credit for the unused days of a paid, still-running period (0 if none)."""
    paid_until = ent._parse(row.get("paid_until"))
    if row.get("source") != "paid" or paid_until is None or paid_until <= now:
        return 0
    if ent.effective_status(row, cfg, now) != "active":
        return 0
    period = cfg["billing"]["period_days"]
    price = float(row.get("price_ngn") or 0)
    if price <= 0:
        d = _defs(cfg, row["kind"]).get(row.get("key")) or {}
        price = float(d.get("monthly_ngn") or 0)
    remaining = min((paid_until - now).total_seconds() / 86400.0, float(period))
    return max(int(price * remaining / period), 0)


def quote_for(row: dict, cfg: dict, now: datetime) -> dict:
    """What the next order for this row costs. Everything comes from Settings and the row, never from a caller."""
    config = row.get("config") or {}
    change = config.get("change") if isinstance(config.get("change"), dict) else None
    key = row["key"]
    change_kind = None
    credit = 0
    picks = config.get("picks") or []
    if change:
        key, change_kind, picks = change["to"], change.get("kind") or "switch", change.get("picks") or []
        if change_kind == "upgrade":
            credit = _credit_for_unused(row, cfg, now)
    elif config.get("pending_key"):
        key, picks = config["pending_key"], config.get("pending_picks") or []
        change_kind = "downgrade"
    d = _defs(cfg, row["kind"]).get(key)
    if not d:
        raise AddonBillingError("That plan isn't available any more.")
    price = int(d["monthly_ngn"])
    setup = int(d.get("setup_fee_ngn") or 0) if (row["kind"] == "tier" and not config.get("setup_paid")) else 0
    total = max(price + setup - credit, 0)
    renewal = bool(config.get("setup_paid") or row.get("paid_until"))
    return {"key": key, "label": d["label"], "price": price, "setup_fee": setup, "credit": credit, "total": total,
            "days": cfg["billing"]["period_days"], "change_kind": change_kind, "picks": picks,
            "kind": "upgrade" if change_kind == "upgrade" else ("renewal" if renewal else "new")}


# ---------------------------------------------------------------------------
# start a purchase / change (staff or builder) and the private pay link
# ---------------------------------------------------------------------------

def _payer_from(site: dict, payer: Optional[dict]) -> dict:
    owner = site.get("legal_owner") if isinstance(site.get("legal_owner"), dict) else {}
    p = payer or {}
    out = {
        "name": (p.get("name") or owner.get("full_name") or "").strip() or None,
        "phone": (p.get("phone") or owner.get("phone") or "").strip() or None,
        "email": (p.get("email") or owner.get("email") or "").strip() or None,
    }
    if not out["phone"] and not out["email"]:
        raise AddonBillingError("Add the client's WhatsApp number or email so we can send the payment link.")
    return out


def start_purchase(db: Any, org_id: str, site_id: str, actor: str, kind: str, key: str, *,
                   payer: Optional[dict] = None, picks: Optional[list] = None, billing_mode: str = "link",
                   now: Optional[datetime] = None) -> dict:
    """Prepare (or change) what a site will pay for and return its private pay link. Does not charge anything.
    Returns {addon_id, pay_url, scheduled, quote}. `scheduled` is True for a downgrade (nothing to pay now)."""
    now = now or _now()
    if kind not in ("tier", "addon"):
        raise AddonBillingError("Choose a tier or an add-on.")
    if billing_mode not in ("link", "auto"):
        raise AddonBillingError("Billing mode must be link or auto.")
    cfg = ent.get_config(_settings(db, org_id))
    defs = _defs(cfg, kind)
    if key not in defs:
        raise AddonBillingError("Unknown tier." if kind == "tier" else "Unknown add-on.")
    if defs[key]["monthly_ngn"] <= 0:
        raise AddonBillingError("This isn't for sale yet. Set its monthly price in Settings first.")
    site = _get_site(db, org_id, site_id)
    if not site.get("builder_id"):
        raise AddonBillingError("This site has no builder, so a payment can't be set up yet.")
    who = _payer_from(site, payer)
    clean_picks = ent._clean_picks(defs[key], picks) if kind == "tier" else []

    q = db.table("site_addons").select("*").eq("org_id", org_id).eq("site_id", site_id).eq("kind", kind).neq("status", "cancelled")
    if kind == "addon":
        q = q.eq("key", key)
    existing = _one(q.limit(1).execute().data)

    scheduled = False
    if existing is None:
        raw, hashed = _new_token()
        db.table("site_addons").insert({
            "org_id": org_id, "site_id": site_id, "kind": kind, "key": key, "status": "pending", "source": "paid",
            "billing_mode": billing_mode, "price_ngn": 0, "payer_name": who["name"], "payer_phone": who["phone"],
            "payer_email": who["email"], "payer_token_hash": hashed,
            "config": {"picks": clean_picks, "pay_token": raw}, "created_at": _iso(now), "updated_at": _iso(now)}).execute()
        row = _one((db.table("site_addons").select("*").eq("org_id", org_id).eq("payer_token_hash", hashed)
                    .limit(1).execute()).data)
        event = "site_addon_purchase_started"
    else:
        row = existing
        config = dict(row.get("config") or {})
        patch: dict = {"payer_name": who["name"], "payer_phone": who["phone"], "payer_email": who["email"],
                       "billing_mode": billing_mode, "updated_at": _iso(now)}
        if not config.get("pay_token"):
            raw, hashed = _new_token()
            config["pay_token"] = raw
            patch["payer_token_hash"] = hashed
        event = "site_addon_purchase_started"
        if kind == "tier" and row["key"] != key:
            old = defs.get(row["key"]) or {}
            paid_live = (row.get("source") == "paid" and row.get("paid_until")
                         and ent.effective_status(row, cfg, now) in ent.LIVE_STATES)
            if paid_live and defs[key]["monthly_ngn"] <= int(old.get("monthly_ngn") or 0):
                config["pending_key"], config["pending_picks"] = key, clean_picks      # applies when the next renewal is paid
                config.pop("change", None)
                scheduled = True
                event = "site_addon_downgrade_scheduled"
            else:
                is_up = bool(paid_live)
                config["change"] = {"to": key, "kind": "upgrade" if is_up else "switch", "picks": clean_picks}
                config.pop("pending_key", None)
                config.pop("pending_picks", None)
                event = "site_addon_change_started"
        else:
            if kind == "tier" and picks is not None:
                config["picks"] = clean_picks
            config.pop("change", None)
            if config.get("pending_key") and config["pending_key"] == key:
                config.pop("pending_key", None)
                config.pop("pending_picks", None)
        patch["config"] = config
        db.table("site_addons").update(patch).eq("id", row["id"]).eq("org_id", org_id).execute()
        row = _get_row(db, org_id, row["id"])

    ent._log_event(db, org_id, site_id, actor, event, {"kind": kind, "key": key, "addon_id": row["id"]})
    return {"addon_id": row["id"], "pay_url": pay_url((row.get("config") or {}).get("pay_token")),
            "scheduled": scheduled, "quote": quote_for(row, cfg, now)}


def _new_token() -> tuple:
    from app.models.sites import generate_form_token
    return generate_form_token()


# ---------------------------------------------------------------------------
# the public pay page (token is the only credential)
# ---------------------------------------------------------------------------

def _row_by_token(db: Any, token: str) -> Optional[dict]:
    from app.models.sites import hash_form_token
    if not token or len(token) > 200:
        return None
    return _one((db.table("site_addons").select("*").eq("payer_token_hash", hash_form_token(token)).limit(1).execute()).data)


def pay_view(db: Any, token: str, now: Optional[datetime] = None) -> Optional[dict]:
    """What the client sees. None = unknown link. Never returns org ids, prices of other plans or other clients' data."""
    now = now or _now()
    row = _row_by_token(db, token)
    if not row or row.get("status") == "cancelled":
        return None
    org_id = row["org_id"]
    cfg = ent.get_config(_settings(db, org_id))
    site = _get_site(db, org_id, row["site_id"])
    eff = ent.effective_status(row, cfg, now)
    try:
        qt = quote_for(row, cfg, now)
    except AddonBillingError:
        return {"state": "unavailable", "business": _business(site)}
    d = _defs(cfg, row["kind"]).get(qt["key"]) or {}
    if int(d.get("monthly_ngn") or 0) <= 0:
        return {"state": "unavailable", "business": _business(site)}
    feats = list(d.get("features") or [])
    feats += [p for p in qt["picks"] if p not in feats]
    paid_until = ent._parse(row.get("paid_until"))
    # A running period that still has plenty of time left needs no payment yet (the renewal window opens before it ends).
    renew_window = max(cfg["billing"]["reminder_days"] or [5])
    state = "pay"
    if eff == "active" and not qt["change_kind"] and paid_until and (paid_until - now) > timedelta(days=renew_window):
        state = "paid_up"
    return {
        "state": state, "business": _business(site), "label": qt["label"], "payer_name": row.get("payer_name"),
        "amount_due": qt["total"], "price": qt["price"], "setup_fee": qt["setup_fee"], "credit": qt["credit"],
        "days": qt["days"], "kind": qt["kind"], "status": eff, "paid_until": row.get("paid_until"),
        "includes": [reg.FEATURES[k]["label"] for k in feats if k in reg.FEATURES],
    }


def pay_checkout(db: Any, token: str, now: Optional[datetime] = None) -> Optional[dict]:
    """The pay page button: make (or reuse) the Paystack link and return {checkout_url}. None = unknown link."""
    now = now or _now()
    row = _row_by_token(db, token)
    if not row or row.get("status") == "cancelled":
        return None
    return create_order(db, row["org_id"], row, now)


# ---------------------------------------------------------------------------
# the order and the Paystack link
# ---------------------------------------------------------------------------

def create_order(db: Any, org_id: str, row: dict, now: Optional[datetime] = None) -> dict:
    from app.services import paystack_storefront_service as paystack
    from app.services import site_access_service
    now = now or _now()
    cfg = ent.get_config(_settings(db, org_id))
    qt = quote_for(row, cfg, now)
    d = _defs(cfg, row["kind"]).get(qt["key"]) or {}
    if int(d.get("monthly_ngn") or 0) <= 0:
        raise AddonBillingError("This isn't for sale right now.")
    amount = qt["total"]
    if amount < MIN_AMOUNT_NGN:
        raise AddonBillingError("There is nothing to pay for this change.")
    site = _get_site(db, org_id, row["site_id"])
    builder = _builder_of(db, org_id, site)
    if not builder:
        raise AddonBillingError("This site has no builder, so a payment can't be set up yet.")
    lead_id = site_access_service.ensure_lead(db, org_id, builder)
    if not lead_id:
        raise AddonBillingError("We couldn't set up your payment link yet. Please try again in a moment.")

    open_orders = [o for o in ((db.table("site_orders").select("*").eq("org_id", org_id).eq("kind", KIND)
                                .eq("status", "pending_payment").execute()).data or [])
                   if (o.get("quote") or {}).get("addon_id") == row["id"]]
    open_orders.sort(key=lambda o: str(o.get("created_at") or ""), reverse=True)
    for o in open_orders:
        same = float(o.get("amount") or 0) == float(amount) and (o.get("quote") or {}).get("key") == qt["key"]
        if same and o.get("payment_link_id"):
            link = _one((db.table("payment_links").select("checkout_url").eq("id", o["payment_link_id"])
                         .eq("org_id", org_id).limit(1).execute()).data)
            if link and link.get("checkout_url"):
                return {"checkout_url": link["checkout_url"], "amount": amount, "reused": True}
    for o in open_orders:        # a different amount or plan: the old link must not be paid by mistake
        db.table("site_orders").update({"status": "expired", "updated_at": _iso(now)}) \
            .eq("id", o["id"]).eq("org_id", org_id).eq("status", "pending_payment").execute()

    try:
        link = paystack.generate_payment_link(
            db=db, org_id=org_id, lead_id=lead_id, amount=amount, payment_type="full", currency="NGN",
            trigger_stage=None, target_stage_on_paid=None, created_by=None)
    except paystack.PaystackLinkError as exc:
        raise AddonBillingError(str(exc))

    db.table("site_orders").insert({
        "org_id": org_id, "site_id": row["site_id"], "builder_id": site["builder_id"], "lead_id": lead_id,
        "kind": KIND, "route": "standard", "domain": None, "backup_domain": None,
        "quote": {"kind": KIND, "addon_id": row["id"], "addon_kind": row["kind"], "key": qt["key"], "label": qt["label"],
                  "days": qt["days"], "price": qt["price"], "setup_fee": qt["setup_fee"], "credit": qt["credit"],
                  "change_kind": qt["change_kind"], "picks": qt["picks"], "billing_mode": row.get("billing_mode")},
        "amount": amount, "cost_snapshot": {}, "expected_profit": amount,
        "payment_link_id": link.get("payment_link_id"), "payment_reference": link["reference"],
        "status": "pending_payment", "approval_required": False, "created_at": _iso(now), "updated_at": _iso(now),
    }).execute()
    return {"checkout_url": link["checkout_url"], "amount": amount, "reused": False}


# ---------------------------------------------------------------------------
# payment confirmed (called from site_order_service after it claims the order)
# ---------------------------------------------------------------------------

def on_paid(db: Any, org_id: str, order: dict, now: Optional[datetime] = None) -> None:
    now = now or _now()
    q = order.get("quote") or {}
    row = _get_row(db, org_id, q.get("addon_id") or "")
    if not row:
        raise AddonBillingError("add-on row not found for payment")
    days = ent._int(q.get("days"), 30, 1, 366)
    key = q.get("key") or row["key"]
    change_kind = q.get("change_kind")
    current_until = ent._parse(row.get("paid_until"))
    running = row.get("source") == "paid" and current_until and current_until > now
    # An upgrade or a plain switch starts a fresh period now (an upgrade's unused days were already credited).
    # A renewal or an add-on payment starts when the running period ends, so paying early loses no days.
    start = current_until if (running and change_kind not in ("upgrade", "switch")) else now
    end = start + timedelta(days=days)

    config = dict(row.get("config") or {})
    config["setup_paid"] = True
    for k in ("change", "pending_key", "pending_picks", "reminded"):
        config.pop(k, None)
    if row["kind"] == "tier":
        config["picks"] = q.get("picks") if q.get("picks") is not None else config.get("picks", [])
    db.table("site_addons").update({
        "key": key, "status": "active", "source": "paid", "price_ngn": q.get("price") or order.get("amount") or 0,
        "paid_until": ent._iso(end), "grace_until": None, "next_reminder_at": None, "config": config,
        "updated_at": ent._iso(now)}).eq("id", row["id"]).eq("org_id", org_id).execute()
    ent._log_event(db, org_id, row["site_id"], "system", "site_addon_paid",
                   {"addon_id": row["id"], "key": key, "until": ent._iso(end), "amount": order.get("amount"),
                    "change_kind": change_kind})

    fresh = _get_row(db, org_id, row["id"])
    site = _get_site(db, org_id, row["site_id"])
    builder = _builder_of(db, org_id, site)
    label = q.get("label") or key
    _notify_payer(db, org_id, fresh, site, builder,
                  f"Payment received. {label} for {_business(site)} is active until {_pretty(end)}. Thank you.", None)
    _tell_builder(db, org_id, site, order,
                  f"{_business(site)} paid {_money(order.get('amount') or 0)} for {label}. It is active until {_pretty(end)}.")


# ---------------------------------------------------------------------------
# messages to the client (and the builder)
# ---------------------------------------------------------------------------

def _send_email(to_email: str, subject: str, text: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key or not to_email:
        return False
    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({"from": os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io"),
                            "to": [to_email], "subject": subject, "text": text})
        return True
    except Exception as exc:  # S14
        logger.warning("site_addon: email failed: %s", exc)
        return False


def _notify_payer(db: Any, org_id: str, row: dict, site: dict, builder: Optional[dict], text: str,
                  url: Optional[str], template_params: Optional[list] = None) -> bool:
    """Email always (if there is an address); WhatsApp only inside the 24-hour window, or by the approved template named in
    SITE_ADDON_TEMPLATE. True if at least one channel delivered."""
    delivered = False
    body = text + (f"\n\nPay here: {url}" if url else "")
    if row.get("payer_email"):
        delivered = _send_email(row["payer_email"], "Your Opsra plan", body) or delivered
    phone = (row.get("payer_phone") or "").strip()
    if phone:
        try:
            from app.services import funnel_messaging, site_renewal_service as renewal
            from app.utils.phone import normalize_phone
            number = renewal._number_row(db, org_id)
            to = normalize_phone(phone)
            if number and to:
                if renewal._in_free_window(db, org_id, to, _now()):
                    if url:
                        delivered = funnel_messaging.send_cta_url(db, org_id, number, to, text, "Pay now", url, None) or delivered
                    else:
                        delivered = funnel_messaging.send_text(db, org_id, number, to, text, None) or delivered
                elif os.getenv(TEMPLATE_ENV) and template_params:
                    delivered = funnel_messaging.send_template(
                        db, org_id, number, to, os.getenv(TEMPLATE_ENV), template_params, lead_id=None) or delivered
        except Exception as exc:  # S14
            logger.warning("site_addon: whatsapp to payer failed addon=%s: %s", row.get("id"), exc)
    return delivered


def _tell_builder(db: Any, org_id: str, site: dict, order_like: dict, text: str) -> None:
    try:
        from app.services import site_order_service
        site_order_service._message_builder(
            db, org_id, {"builder_id": site.get("builder_id"), "lead_id": order_like.get("lead_id"),
                         "site_id": site.get("id"), "id": order_like.get("id")}, text)
    except Exception as exc:  # S14
        logger.warning("site_addon: builder message failed site=%s: %s", site.get("id"), exc)


def send_link(db: Any, org_id: str, site_id: str, addon_id: str, actor: str) -> dict:
    """Staff or builder press 'Send payment link to client'. Returns {sent, pay_url}."""
    row = _get_row(db, org_id, addon_id)
    if not row or row["site_id"] != site_id or row.get("status") == "cancelled":
        raise ent.EntitlementNotFound("Add-on not found")
    now = _now()
    cfg = ent.get_config(_settings(db, org_id))
    site = _get_site(db, org_id, site_id)
    qt = quote_for(row, cfg, now)
    url = pay_url((row.get("config") or {}).get("pay_token"))
    text = (f"Hi {row.get('payer_name') or 'there'}, here is the payment link for {qt['label']} for {_business(site)}: "
            f"{_money(qt['total'])}.")
    sent = _notify_payer(db, org_id, row, site, _builder_of(db, org_id, site), text, url,
                         [row.get("payer_name") or "there", qt["label"], _business(site), _money(qt["total"]), url])
    ent._log_event(db, org_id, site_id, actor, "site_addon_link_sent", {"addon_id": addon_id, "delivered": sent})
    return {"sent": sent, "pay_url": url}


# ---------------------------------------------------------------------------
# the daily sweep
# ---------------------------------------------------------------------------

def run_cycle(db: Any, now: datetime, org_active: Callable[[str], bool]) -> dict:
    """Daily. active -> grace at paid_until -> paused when the grace days are over; reminders to the client before the end.
    Each row is isolated (S14). Rows on automatic card billing still change status here; A0-2b does the charging."""
    result = {"checked": 0, "to_grace": 0, "paused": 0, "reminders": 0, "failed": 0}
    try:
        rows = (db.table("site_addons").select("*").in_("status", ["active", "grace"]).eq("source", "paid").execute()).data or []
    except Exception as exc:  # S14
        logger.warning("site_addon cycle: list failed: %s", exc)
        result["failed"] += 1
        return result
    cfgs: dict = {}
    for row in rows:
        result["checked"] += 1
        try:
            org_id = row["org_id"]
            if not org_active(org_id):
                continue
            if org_id not in cfgs:
                cfgs[org_id] = ent.get_config(_settings(db, org_id))
            _process(db, row, cfgs[org_id], now, result)
        except Exception as exc:  # S14
            result["failed"] += 1
            logger.warning("site_addon cycle: row failed addon=%s: %s", row.get("id"), exc)
    return result


def _process(db: Any, row: dict, cfg: dict, now: datetime, result: dict) -> None:
    org_id = row["org_id"]
    paid_until = ent._parse(row.get("paid_until"))
    if paid_until is None:
        return
    grace_end = ent._parse(row.get("grace_until")) or (paid_until + timedelta(days=cfg["billing"]["grace_days"]))
    site = _get_site(db, org_id, row["site_id"])
    builder = _builder_of(db, org_id, site)
    d = _defs(cfg, row["kind"]).get(row["key"]) or {}
    label = d.get("label") or row["key"]
    url = pay_url((row.get("config") or {}).get("pay_token") or "") if (row.get("config") or {}).get("pay_token") else None
    price = _money(d.get("monthly_ngn") or row.get("price_ngn") or 0)
    name = row.get("payer_name") or "there"
    params = [name, label, _business(site), _pretty(paid_until), url or ""]

    if now > grace_end:
        res = (db.table("site_addons").update({"status": "paused", "updated_at": ent._iso(now)})
               .eq("id", row["id"]).eq("org_id", org_id).in_("status", ["active", "grace"]).execute())
        if res.data:
            result["paused"] += 1
            ent._log_event(db, org_id, row["site_id"], "system", "site_addon_paused_unpaid", {"addon_id": row["id"]})
            _notify_payer(db, org_id, row, site, builder,
                          f"Hi {name}, the {label} tools for {_business(site)} are paused because the plan wasn't renewed. "
                          f"Renew ({price}) to switch them back on.", url, params)
            _tell_builder(db, org_id, site, {}, f"{_business(site)}'s {label} plan is paused (not renewed).")
            _notify_managers(db, org_id, f"Plan paused: {_business(site)}", f"{label} was not renewed.")
        return
    if now > paid_until:
        if row.get("status") == "active":
            res = (db.table("site_addons").update({"status": "grace", "grace_until": ent._iso(grace_end),
                                                   "updated_at": ent._iso(now)})
                   .eq("id", row["id"]).eq("org_id", org_id).eq("status", "active").execute())
            if res.data:
                result["to_grace"] += 1
                ent._log_event(db, org_id, row["site_id"], "system", "site_addon_grace", {"addon_id": row["id"]})
                _notify_payer(db, org_id, row, site, builder,
                              f"Hi {name}, the {label} plan for {_business(site)} ended on {_pretty(paid_until)}. "
                              f"Your tools stay on until {_pretty(grace_end)}. Renew ({price}) to keep them.", url, params)
                _tell_builder(db, org_id, site, {}, f"{_business(site)}'s {label} plan has ended. It stays on until "
                                                    f"{_pretty(grace_end)} unless renewed.")
        return
    if row.get("billing_mode") == "auto" or not url:
        return
    days_left = (paid_until - now).total_seconds() / 86400.0
    config = dict(row.get("config") or {})
    reminded = config.get("reminded") if isinstance(config.get("reminded"), dict) else {}
    sent = list(reminded.get("days") or []) if reminded.get("for") == ent._iso(paid_until) else []
    due = [rd for rd in sorted(cfg["billing"]["reminder_days"], reverse=True) if days_left <= rd and rd not in sent]
    if not due:
        return
    ok = _notify_payer(db, org_id, row, site, builder,
                       f"Hi {name}, the {label} plan for {_business(site)} ends on {_pretty(paid_until)}. "
                       f"Renew for {price} to keep it going.", url, params)
    if ok:
        config["reminded"] = {"for": ent._iso(paid_until), "days": sorted(set(sent + due))}
        db.table("site_addons").update({"config": config, "updated_at": ent._iso(now)}) \
            .eq("id", row["id"]).eq("org_id", org_id).execute()
        result["reminders"] += 1


def _notify_managers(db: Any, org_id: str, title: str, body: str) -> None:
    try:
        from app.services import funnel_service
        funnel_service.notify_managers(db, org_id, title, body, "site_order_paid", None)
    except Exception as exc:  # S14
        logger.warning("site_addon: manager notify failed: %s", exc)
