"""
app/services/site_care_plan_service.py
---------------------------------------
SITE-4 (part B) — care plans, edit allowances and extra-edit packs. Spec: Opsra Context/website-business/SITE-4B_Spec.md.

  • consume_edit()          — called by the builder portal before every content save. Counts one edit
                              (saves within 30 minutes count once), or raises EditLimitReached.
  • allowance_view()        — what the portal / staff see: edits left, plan status, prices.
  • create_checkout()       — a Paystack link for a monthly care plan or an extra-edit pack.
  • on_paid()               — called from site_order_service.on_payment_confirmed for kind care_plan / edit_pack.
  • set_cancel()            — cancel at the end of the paid month (or take the cancellation back).
  • run_cycle()             — the daily sweep: active -> grace -> ended, and one payment reminder per period.

Edit allowance, used in this order: the site's free edits (settings.free_revisions, 5 per site, ever) →
the care plan's edits for the current month (10, no rollover) → purchased pack edits (never expire).
Free and plan edits only count once the site is live — a builder may polish a preview without limit.
Photo swaps, design changes, undo and staff edits never count and are never blocked.

Money: prices come from settings.pricing.care_plan (defaults below) and are never taken from a caller.
S14: run_cycle isolates every plan; message sends return a bool and never raise.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.services import site_renewal_service as renewal

logger = logging.getLogger(__name__)

DEFAULTS = {"price_ngn": 5000, "edits_per_month": 10, "pack_price_ngn": 1500, "pack_edits": 5,
            "grace_days": 5, "reminder_days": 5}
PLAN_DAYS = 30
SESSION_MINUTES = 30                       # saves inside one editing session count as one edit
COUNTING_SITE_STATUSES = ("live", "renewal_due", "lapsed")
CARE_TEMPLATE_ENV = "SITE_CARE_PLAN_TEMPLATE"
DEFAULT_CARE_TEMPLATE = "site_care_plan_reminder"


class CarePlanError(Exception):
    """Typed, user-facing failure (router maps it to a 4xx)."""


class CarePlanNotFound(CarePlanError):
    pass


class CarePlanBlocked(CarePlanError):
    pass


class EditLimitReached(CarePlanError):
    """Soft block: the builder is out of edits. Carries the offers shown in the editor."""
    def __init__(self, message: str, offer: Optional[dict] = None):
        super().__init__(message)
        self.offer = offer or {}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse(value) -> Optional[datetime]:
    return renewal._parse_iso(value)


def _money(n) -> str:
    return renewal._money(n)


def _pretty(dt: datetime) -> str:
    return renewal._pretty_date(renewal.lagos_today(dt))


def get_config(settings: Optional[dict]) -> dict:
    settings = settings or {}
    raw = ((settings.get("pricing") or {}).get("care_plan")) or {}
    cfg = dict(DEFAULTS)
    for key in DEFAULTS:
        try:
            if raw.get(key) is not None and float(raw[key]) >= 0:
                cfg[key] = int(float(raw[key]))
        except (TypeError, ValueError):
            pass
    try:
        cfg["free_edits"] = max(0, int(settings.get("free_revisions", 5)))
    except (TypeError, ValueError):
        cfg["free_edits"] = 5
    return cfg


def _settings(db: Any, org_id: str) -> dict:
    from app.services import pricing_service
    return pricing_service.get_settings(db, org_id)


def effective_status(row: Optional[dict], cfg: dict, now: datetime) -> Optional[str]:
    """active / grace / ended / None, worked out from the dates so it is right even before the daily sweep runs."""
    if not row or not row.get("plan_status") or row.get("plan_status") == "ended":
        return "ended" if row and row.get("plan_status") == "ended" else None
    end = _parse(row.get("period_end"))
    if not end:
        return None
    if now <= end:
        return "active"
    if row.get("cancel_at_period_end"):
        return "ended"
    return "grace" if now <= end + timedelta(days=cfg["grace_days"]) else "ended"


def _get_row(db: Any, org_id: str, site_id: str) -> Optional[dict]:
    return _one((db.table("site_care_plans").select("*").eq("org_id", org_id).eq("site_id", site_id).limit(1).execute()).data)


def _get_or_create_row(db: Any, org_id: str, site_id: str) -> dict:
    row = _get_row(db, org_id, site_id)
    if row:
        return row
    now = _iso()
    try:
        return _one(db.table("site_care_plans").insert({
            "org_id": org_id, "site_id": site_id, "free_edits_used": 0, "plan_edits_used": 0, "extra_edits": 0,
            "cancel_at_period_end": False, "created_at": now, "updated_at": now,
        }).execute().data) or {}
    except Exception:  # two requests raced on the unique(site_id) — the other one won
        row = _get_row(db, org_id, site_id)
        if not row:
            raise
        return row


def _load_site(db: Any, org_id: str, site_id: str, builder_id: Optional[str] = None) -> dict:
    q = db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).is_("deleted_at", "null")
    if builder_id:
        q = q.eq("builder_id", builder_id)
    site = _one(q.limit(1).execute().data)
    if not site:
        raise CarePlanNotFound("Site not found")
    return site


def _log(db: Any, org_id: str, site_id: str, event: str, detail: Optional[dict] = None, order_id: Optional[str] = None) -> None:
    renewal._log_event(db, org_id, site_id, "system", event, detail, order_id)


# ---------------------------------------------------------------------------
# What the builder / staff see
# ---------------------------------------------------------------------------

def allowance_view(row: Optional[dict], cfg: dict, now: Optional[datetime] = None) -> dict:
    now = now or _now()
    row = row or {}
    status = effective_status(row, cfg, now)
    free_left = max(0, cfg["free_edits"] - int(row.get("free_edits_used") or 0))
    plan_left = max(0, cfg["edits_per_month"] - int(row.get("plan_edits_used") or 0)) if status == "active" else 0
    extra = int(row.get("extra_edits") or 0)
    return {
        "plan_status": status, "period_end": row.get("period_end") if status in ("active", "grace") else None,
        "cancel_at_period_end": bool(row.get("cancel_at_period_end")) and status in ("active", "grace"),
        "free_edits_left": free_left, "plan_edits_left": plan_left, "extra_edits": extra,
        "edits_left": free_left + plan_left + extra, "edits_per_month": cfg["edits_per_month"],
        "plan_price": cfg["price_ngn"], "pack_price": cfg["pack_price_ngn"], "pack_edits": cfg["pack_edits"],
        "grace_days": cfg["grace_days"],
    }


def site_allowance(db: Any, org_id: str, site_id: str, now: Optional[datetime] = None) -> dict:
    cfg = get_config(_settings(db, org_id))
    return allowance_view(_get_row(db, org_id, site_id), cfg, now)


def summaries(db: Any, org_id: str, site_ids: list, now: Optional[datetime] = None) -> dict:
    """site_id -> allowance view for many sites in two queries (used by the site lists)."""
    now = now or _now()
    ids = [i for i in site_ids if i]
    cfg = get_config(_settings(db, org_id))
    rows = ((db.table("site_care_plans").select("*").eq("org_id", org_id).in_("site_id", ids).execute()).data or []) if ids else []
    by_site = {r["site_id"]: r for r in rows}
    return {sid: allowance_view(by_site.get(sid), cfg, now) for sid in ids}


def list_fields(view: dict) -> dict:
    return {"care_plan_status": view["plan_status"], "care_plan_ends": view["period_end"], "edits_left": view["edits_left"],
            "cancel_at_period_end": view["cancel_at_period_end"], "plan_price": view["plan_price"],
            "edits_per_month": view["edits_per_month"], "pack_price": view["pack_price"], "pack_edits": view["pack_edits"]}


# ---------------------------------------------------------------------------
# Counting an edit
# ---------------------------------------------------------------------------

def consume_edit(db: Any, org_id: str, site: dict, now: Optional[datetime] = None) -> dict:
    """Called before a builder's content save. Returns {"counted": bool, "source": ...} or raises EditLimitReached."""
    now = now or _now()
    if site.get("status") not in COUNTING_SITE_STATUSES:
        return {"counted": False, "source": "preview"}          # editing a draft is free
    cfg = get_config(_settings(db, org_id))
    for _attempt in range(2):                                   # one retry if a concurrent save changed the counters
        row = _get_or_create_row(db, org_id, site["id"])
        last = _parse(row.get("last_edit_counted_at"))
        if last and now - last <= timedelta(minutes=SESSION_MINUTES):
            return {"counted": False, "source": "session"}      # same editing session — already paid for
        status = effective_status(row, cfg, now)
        free_used = int(row.get("free_edits_used") or 0)
        plan_used = int(row.get("plan_edits_used") or 0)
        extra = int(row.get("extra_edits") or 0)

        if free_used < cfg["free_edits"]:
            source, field, old = "free", "free_edits_used", free_used
            updates = {"free_edits_used": free_used + 1}
        elif status == "active" and plan_used < cfg["edits_per_month"]:
            source, field, old = "plan", "plan_edits_used", plan_used
            updates = {"plan_edits_used": plan_used + 1}
        elif extra > 0:
            source, field, old = "pack", "extra_edits", extra
            updates = {"extra_edits": extra - 1}
        else:
            raise EditLimitReached(
                "You've used all the edits for this site. Add a care plan or buy extra edits to keep editing.",
                {"plan_price": cfg["price_ngn"], "edits_per_month": cfg["edits_per_month"],
                 "pack_price": cfg["pack_price_ngn"], "pack_edits": cfg["pack_edits"],
                 "plan_status": status})
        updates.update({"last_edit_counted_at": _iso(now), "updated_at": _iso(now)})
        claimed = (db.table("site_care_plans").update(updates).eq("id", row["id"]).eq(field, old).execute()).data
        if claimed:
            return {"counted": True, "source": source}
    raise CarePlanBlocked("Couldn't record that edit — please try again.")


# ---------------------------------------------------------------------------
# Buying: a Paystack link for a plan month or an extra-edit pack
# ---------------------------------------------------------------------------

def create_checkout(db: Any, org_id: str, builder: dict, site_id: str, what: str) -> dict:
    """what: 'plan' | 'pack'. Returns {"checkout_url", "amount", "kind", "reused"}."""
    from app.services import paystack_storefront_service
    if what not in ("plan", "pack"):
        raise CarePlanBlocked("Unknown purchase.")
    site = _load_site(db, org_id, site_id, builder.get("id"))
    if site.get("status") not in COUNTING_SITE_STATUSES:
        raise CarePlanBlocked("Care plans and extra edits are available once the site is live.")
    lead_id = builder.get("lead_id")
    if not lead_id:
        raise CarePlanBlocked("This builder has no linked CRM lead yet — a payment link can't be created.")
    return _checkout_for(db, org_id, site, builder, what, paystack_storefront_service)


def _checkout_for(db: Any, org_id: str, site: dict, builder: dict, what: str, paystack) -> dict:
    cfg = get_config(_settings(db, org_id))
    kind = "care_plan" if what == "plan" else "edit_pack"
    amount = cfg["price_ngn"] if what == "plan" else cfg["pack_price_ngn"]
    edits = cfg["edits_per_month"] if what == "plan" else cfg["pack_edits"]
    if amount <= 0:
        raise CarePlanBlocked("This isn't available right now.")

    open_orders = [o for o in ((db.table("site_orders").select("*").eq("org_id", org_id).eq("site_id", site["id"])
                                .eq("kind", kind).eq("status", "pending_payment").execute()).data or [])
                   if o.get("payment_link_id") and float(o.get("amount") or 0) == float(amount)]
    open_orders.sort(key=lambda o: str(o.get("created_at") or ""), reverse=True)
    for order in open_orders:
        link = _one((db.table("payment_links").select("checkout_url").eq("id", order["payment_link_id"])
                     .eq("org_id", org_id).limit(1).execute()).data)
        if link and link.get("checkout_url"):
            return {"checkout_url": link["checkout_url"], "amount": amount, "kind": kind, "reused": True, "order": order}

    try:
        link = paystack.generate_payment_link(
            db=db, org_id=org_id, lead_id=builder["lead_id"], amount=amount, payment_type="full", currency="NGN",
            trigger_stage=None, target_stage_on_paid=None, created_by=None,
        )
    except paystack.PaystackLinkError as exc:
        raise CarePlanBlocked(str(exc))

    try:                                                        # rough profit: price minus the gateway's cut
        from app.services import pricing_service
        gw = (_settings(db, org_id).get("pricing") or {}).get("gateway") or {}
        profit = round(amount - float(pricing_service._gateway_fee(amount, gw)), 2)
    except Exception:
        profit = amount
    now = _iso()
    row = {
        "org_id": org_id, "site_id": site["id"], "builder_id": builder["id"], "lead_id": builder["lead_id"],
        "kind": kind, "route": "standard", "domain": None, "backup_domain": None,
        "quote": {"kind": kind, "edits": edits, "price": amount}, "amount": amount, "cost_snapshot": {},
        "expected_profit": profit, "payment_link_id": link.get("payment_link_id"), "payment_reference": link["reference"],
        "status": "pending_payment", "approval_required": False, "created_at": now, "updated_at": now,
    }
    order = _one(db.table("site_orders").insert(row).execute().data) or row
    _log(db, org_id, site["id"], f"{kind}_order_created", {"amount": amount}, order.get("id"))
    return {"checkout_url": link["checkout_url"], "amount": amount, "kind": kind, "reused": False, "order": order}


# ---------------------------------------------------------------------------
# Payment confirmed (called from site_order_service.on_payment_confirmed; never raises there)
# ---------------------------------------------------------------------------

def on_paid(db: Any, org_id: str, order: dict, now: Optional[datetime] = None) -> None:
    now = now or _now()
    cfg = get_config(_settings(db, org_id))
    site_id = order["site_id"]
    row = _get_or_create_row(db, org_id, site_id)
    site = _one((db.table("sites").select("client_business_name").eq("id", site_id).eq("org_id", org_id).limit(1).execute()).data) or {}
    name = site.get("client_business_name") or "your client's site"

    if order.get("kind") == "edit_pack":
        edits = int(((order.get("quote") or {}).get("edits")) or cfg["pack_edits"])
        db.table("site_care_plans").update({"extra_edits": int(row.get("extra_edits") or 0) + edits, "updated_at": _iso(now)}) \
            .eq("id", row["id"]).execute()
        _log(db, org_id, site_id, "edit_pack_paid", {"edits": edits}, order.get("id"))
        text = f"{edits} extra edits added to {name}. They don't expire."
    else:
        old_end = _parse(row.get("period_end"))
        still_running = effective_status(row, cfg, now) in ("active", "grace") and old_end and old_end > now
        start = old_end if still_running else now
        end = start + timedelta(days=PLAN_DAYS)
        db.table("site_care_plans").update({
            "plan_status": "active", "period_start": _iso(start), "period_end": _iso(end),
            "plan_edits_used": 0, "cancel_at_period_end": False, "updated_at": _iso(now),
        }).eq("id", row["id"]).execute()
        _log(db, org_id, site_id, "care_plan_paid", {"period_end": _iso(end)}, order.get("id"))
        text = (f"Care plan active for {name} until {_pretty(end)}. You have {cfg['edits_per_month']} edits "
                f"this month, and they refresh each month you renew.")
    try:
        from app.services import site_order_service
        site_order_service._message_builder(db, org_id, order, text)
    except Exception as exc:  # S14
        logger.warning("site_care_plan: builder message failed order=%s: %s", order.get("id"), exc)


# ---------------------------------------------------------------------------
# Staff: send a builder a plan or pack link
# ---------------------------------------------------------------------------

def send_care_link(db: Any, org_id: str, site_id: str, what: str, now: Optional[datetime] = None) -> dict:
    """The staff "Send care link" button. Returns {"checkout_url", "amount", "kind", "sent"}; the link is always
    returned so staff can paste it themselves when WhatsApp can't deliver."""
    from app.services import funnel_messaging, paystack_storefront_service
    now = now or _now()
    if what not in ("plan", "pack"):
        raise CarePlanBlocked("Unknown purchase.")
    site = _load_site(db, org_id, site_id)
    if site.get("status") not in COUNTING_SITE_STATUSES:
        raise CarePlanBlocked("Care plans and extra edits are available once the site is live.")
    builder = _one((db.table("site_builders").select("*").eq("id", site.get("builder_id")).eq("org_id", org_id)
                    .limit(1).execute()).data)
    if not builder or not builder.get("lead_id"):
        raise CarePlanBlocked("This site's builder has no linked CRM lead yet — a payment link can't be created.")
    link = _checkout_for(db, org_id, site, builder, what, paystack_storefront_service)
    cfg = get_config(_settings(db, org_id))
    sent = False
    if what == "plan":
        sent = _send_reminder(db, org_id, builder, site, link["checkout_url"], link["amount"], now + timedelta(days=PLAN_DAYS),
                              now, cfg["edits_per_month"])
    else:
        try:
            number = renewal._number_row(db, org_id)
            phone = builder.get("phone_number")
            if number and phone and renewal._in_free_window(db, org_id, phone, now):
                sent = funnel_messaging.send_cta_url(
                    db, org_id, number, phone,
                    f"{cfg['pack_edits']} extra edits for {site.get('client_business_name')}: {_money(link['amount'])}.",
                    "Buy extra edits", link["checkout_url"], builder.get("lead_id"))
        except Exception as exc:  # S14
            logger.warning("site_care_plan: pack link send failed site=%s: %s", site_id, exc)
    _log(db, org_id, site_id, "care_link_sent", {"what": what, "sent": bool(sent)}, (link.get("order") or {}).get("id"))
    return {"checkout_url": link["checkout_url"], "amount": link["amount"], "kind": link["kind"], "sent": bool(sent)}


# ---------------------------------------------------------------------------
# Cancel / keep
# ---------------------------------------------------------------------------

def set_cancel(db: Any, org_id: str, builder: dict, site_id: str, cancel: bool, now: Optional[datetime] = None) -> dict:
    now = now or _now()
    _load_site(db, org_id, site_id, builder.get("id"))
    cfg = get_config(_settings(db, org_id))
    row = _get_row(db, org_id, site_id)
    status = effective_status(row, cfg, now)
    if status not in ("active", "grace"):
        raise CarePlanBlocked("There is no active care plan on this site.")
    db.table("site_care_plans").update({"cancel_at_period_end": bool(cancel), "updated_at": _iso(now)}).eq("id", row["id"]).execute()
    _log(db, org_id, site_id, "care_plan_cancel_requested" if cancel else "care_plan_cancel_withdrawn", {})
    return allowance_view(_get_row(db, org_id, site_id), cfg, now)


# ---------------------------------------------------------------------------
# The daily sweep
# ---------------------------------------------------------------------------

def _send_reminder(db: Any, org_id: str, builder: dict, site: dict, checkout_url: str, price, end: datetime,
                   now: datetime, edits: int = DEFAULTS["edits_per_month"]) -> bool:
    try:
        from app.services import funnel_messaging
        phone = builder.get("phone_number")
        number = renewal._number_row(db, org_id)
        if not phone or not number:
            return False
        name = site.get("client_business_name") or "your client's site"
        if renewal._in_free_window(db, org_id, phone, now):
            text = (f"Care plan for {name} renews on {_pretty(end)} — {_money(price)} a month for "
                    f"{edits} edits.")
            return funnel_messaging.send_cta_url(db, org_id, number, phone, text, "Renew care plan", checkout_url,
                                                 builder.get("lead_id"))
        template = os.getenv(CARE_TEMPLATE_ENV) or DEFAULT_CARE_TEMPLATE
        return funnel_messaging.send_template(
            db, org_id, number, phone, template,
            [builder.get("full_name") or builder.get("business_name") or "there", name, _money(price), checkout_url],
            lead_id=builder.get("lead_id"))
    except Exception as exc:  # S14
        logger.warning("site_care_plan: reminder failed site=%s: %s", site.get("id"), exc)
        return False


def _process_plan(db: Any, row: dict, now: datetime, org_active: Callable[[str], bool], result: dict) -> None:
    org_id = row["org_id"]
    if not org_active(org_id):
        return
    cfg = get_config(_settings(db, org_id))
    status = effective_status(row, cfg, now)
    end = _parse(row.get("period_end"))
    if not end or status is None:
        return
    result["checked"] += 1

    if status != row.get("plan_status"):
        db.table("site_care_plans").update({"plan_status": status, "updated_at": _iso(now)}).eq("id", row["id"]).execute()
        result["status_updates"] += 1
        if status == "ended":
            _log(db, org_id, row["site_id"], "care_plan_ended", {"period_end": _iso(end)})
            renewal._notify_managers(db, org_id, "Care plan ended", f"A care plan ended on {_pretty(end)}; "
                                     "the site is back on its free edits.", "site_care_plan_ended")
            result["ended"] += 1
            return
    if status == "ended" or row.get("cancel_at_period_end"):
        return

    days_to_end = (end - now).total_seconds() / 86400
    if days_to_end > cfg["reminder_days"]:
        return
    expiry_iso = end.date().isoformat()
    done, attempts = renewal._send_state(db, org_id, row["site_id"], "care_plan_reminder", expiry_iso)
    if done:
        return
    site = _one((db.table("sites").select("*").eq("id", row["site_id"]).eq("org_id", org_id)
                 .is_("deleted_at", "null").limit(1).execute()).data)
    builder = _one((db.table("site_builders").select("*").eq("id", (site or {}).get("builder_id")).eq("org_id", org_id)
                    .limit(1).execute()).data) if site else None
    if not site or not builder or not builder.get("lead_id"):
        raise CarePlanBlocked("Site or builder is missing a CRM lead.")
    from app.services import paystack_storefront_service
    link = _checkout_for(db, org_id, site, builder, "plan", paystack_storefront_service)
    sent = _send_reminder(db, org_id, builder, site, link["checkout_url"], link["amount"], end, now, cfg["edits_per_month"])
    attempt = attempts + 1
    if not sent and attempt in (1, renewal.MAX_SEND_ATTEMPTS):
        result["needs_attention"] += 1
        renewal._notify_managers(
            db, org_id, f"Care plan reminder not delivered: {site.get('client_business_name')}",
            f"The plan ends {_pretty(end)}. Couldn't message {builder.get('full_name') or 'the builder'} "
            f"(try {attempt} of {renewal.MAX_SEND_ATTEMPTS}) — send them this link: {link['checkout_url']}",
            "site_care_plan_attention")
    _log(db, org_id, row["site_id"], "care_plan_reminder",
         {"expiry": expiry_iso, "sent": bool(sent), "attempt": attempt}, (link.get("order") or {}).get("id"))
    if sent:
        result["reminders"] += 1


def run_cycle(db: Any, now: datetime, org_active: Callable[[str], bool]) -> dict:
    result = {"checked": 0, "status_updates": 0, "reminders": 0, "ended": 0, "needs_attention": 0, "failed": 0}
    rows = (db.table("site_care_plans").select("*").in_("plan_status", ["active", "grace"]).execute()).data or []
    for row in rows:
        try:
            _process_plan(db, row, now, org_active, result)
        except Exception:  # S14 — one plan never stops the rest
            result["failed"] += 1
            logger.exception("[site_care_plan] plan failed id=%s", row.get("id"))
    return result


# ---------------------------------------------------------------------------
# 90-day clean-up (images only)
# ---------------------------------------------------------------------------

CLEANUP_DAYS = 90
CLEANUP_WARN_DAYS = 7


def _cleanup_candidates(db: Any, now: datetime) -> dict:
    """site_id -> {"org_id", "due_on": date}. A site is due when it was cancelled, or every one of its domains
    has been past its expiry date, for 90 days."""
    today = renewal.lagos_today(now)
    out: dict = {}
    for s in (db.table("sites").select("id, org_id, status, updated_at").eq("status", "cancelled").execute()).data or []:
        cancelled = _parse(s.get("updated_at"))
        if cancelled:
            out[s["id"]] = {"org_id": s["org_id"], "due_on": renewal.lagos_today(cancelled) + timedelta(days=CLEANUP_DAYS)}
    by_site: dict = {}
    for d in (db.table("site_domains").select("*").neq("status", "transferred").execute()).data or []:
        by_site.setdefault(d["site_id"], []).append(d)
    for site_id, domains in by_site.items():
        expiries = [renewal.expiry_of(d) for d in domains]
        if not expiries or any(e is None for e in expiries) or max(expiries) >= today:
            continue                                            # something is still current
        due = max(expiries) + timedelta(days=CLEANUP_DAYS)
        out.setdefault(site_id, {"org_id": domains[0]["org_id"], "due_on": due})
    return out


def run_cleanup(db: Any, now: datetime, org_active: Callable[[str], bool]) -> dict:
    """Deletes uploaded images (storage + site_assets rows) 90 days after cancellation or lapse.
    Warns the managers once, 7 days before. Text content and the site record are kept."""
    result = {"checked": 0, "warned": 0, "cleaned_sites": 0, "files_removed": 0, "failed": 0}
    today = renewal.lagos_today(now)
    for site_id, info in _cleanup_candidates(db, now).items():
        try:
            org_id = info["org_id"]
            if not org_active(org_id):
                continue
            assets = (db.table("site_assets").select("id, storage_path").eq("site_id", site_id).execute()).data or []
            if not assets:
                continue
            result["checked"] += 1
            days_left = (info["due_on"] - today).days
            site = _one((db.table("sites").select("client_business_name").eq("id", site_id).limit(1).execute()).data) or {}
            name = site.get("client_business_name") or "a site"
            if 0 < days_left <= CLEANUP_WARN_DAYS:
                if not renewal._already_logged(db, org_id, site_id, "cleanup_warning", info["due_on"].isoformat()):
                    renewal._notify_managers(
                        db, org_id, f"Images will be deleted soon: {name}",
                        f"{name}'s uploaded images are deleted on {renewal._pretty_date(info['due_on'])} "
                        "unless the site is renewed. Text and the site record are kept.", "site_cleanup_warning")
                    _log(db, org_id, site_id, "cleanup_warning", {"expiry": info["due_on"].isoformat()})
                    result["warned"] += 1
                continue
            if days_left > 0:
                continue
            paths = [a["storage_path"] for a in assets if a.get("storage_path")]
            try:
                if paths:
                    db.storage.from_("site-assets").remove(paths)
            except Exception as exc:                            # keep the rows so tomorrow's run retries the files
                raise RuntimeError(f"storage delete failed: {exc}")
            db.table("site_assets").delete().eq("site_id", site_id).execute()
            _log(db, org_id, site_id, "assets_cleaned", {"files": len(paths)})
            result["cleaned_sites"] += 1
            result["files_removed"] += len(paths)
        except Exception:  # S14
            result["failed"] += 1
            logger.exception("[site_care_plan] cleanup failed site=%s", site_id)
    return result
