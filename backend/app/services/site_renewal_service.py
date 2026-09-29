"""
app/services/site_renewal_service.py
-------------------------------------
SITE-4 (part A) — the renewal cycle. Detailed spec: Opsra Context/website-business/SITE-4_Spec.md.

  • run_cycle()            — the daily sweep behind site_worker.run_renewal_cycle:
                              persist domain/site status, builder reminders at 30 / 14 / 7 days
                              (each with a renewal payment link), an automatic WhatsApp to the
                              client at <= 5 days, and a one-off alert when a domain lapses.
  • get_or_create_renewal_link() — the renewal order + Paystack link (reused while it is still
                              unpaid, so all three reminders carry the same link). Also used by
                              the builder portal's "Renew now" and the staff "Send renewal link".
  • send_builder_reminder() — one reminder to the builder (pay button inside the 24h window,
                              approved template outside it).

Money: the price is always re-derived from pricing_service (kind="renewal"), never trusted.
S14: run_cycle isolates every domain in its own try/except; every message send returns a bool and
never raises; a failed send falls back to an in-app alert for the managers, who get the link.
Renewals skip approval (Trust's decision): the order is created with approval_required=False.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

REMINDER_BRACKETS = (30, 14, 7)        # days before expiry (spec §14)
CLIENT_CONTACT_DAYS = 5                # L19 — Opsra may contact the client directly 5 days before expiry
BUILDER_RENEW_WINDOW_DAYS = 60         # the builder portal offers "Renew now" this early, or after a lapse
_WHATSAPP_WINDOW_HOURS = 23            # a little inside Meta's 24h free-messaging window
_MANAGED_STATUSES = ["active", "expiring", "lapsed"]   # `transferred` is never touched

BUILDER_TEMPLATE_ENV = "SITE_RENEWAL_BUILDER_TEMPLATE"
CLIENT_TEMPLATE_ENV = "SITE_RENEWAL_CLIENT_TEMPLATE"
DEFAULT_BUILDER_TEMPLATE = "site_renewal_reminder"
DEFAULT_CLIENT_TEMPLATE = "site_renewal_client_notice"

# spec SITE-4 §5 — the renewal job's checklist (the dates are recorded by "Mark renewed").
RENEWAL_CHECKLIST = [
    {"key": "renew_domain", "label": "Renew the domain at the registrar.", "done": False},
    {"key": "renew_hosting", "label": "Renew the hosting package.", "done": False},
    {"key": "confirm_site", "label": "Confirm the site still loads over https.", "done": False},
]


class RenewalError(Exception):
    """Typed, user-facing failure (router maps it to a 4xx)."""


class RenewalNotFound(RenewalError):
    pass


class RenewalBlocked(RenewalError):
    pass


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def lagos_today(now: Optional[datetime] = None) -> date:
    now = now or _now()
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo("Africa/Lagos")).date()
    except Exception:
        return now.astimezone(timezone(timedelta(hours=1))).date()


def _money(n) -> str:
    try:
        return f"₦{round(float(n)):,}"
    except (TypeError, ValueError):
        return "₦0"


def _pretty_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def expiry_of(domain_row: dict) -> Optional[date]:
    """The earlier of the domain and hosting renewal dates."""
    dates = [d for d in (_parse_date(domain_row.get("renews_on")), _parse_date(domain_row.get("hosting_renews_on"))) if d]
    return min(dates) if dates else None


def days_left(domain_row: dict, today: date) -> Optional[int]:
    expiry = expiry_of(domain_row)
    return (expiry - today).days if expiry else None


def bracket_for(days: int) -> Optional[int]:
    """Which reminder bracket (30 / 14 / 7) a domain is currently in; None outside 0..30."""
    if days < 0 or days > REMINDER_BRACKETS[0]:
        return None
    if days > REMINDER_BRACKETS[1]:
        return REMINDER_BRACKETS[0]
    if days > REMINDER_BRACKETS[2]:
        return REMINDER_BRACKETS[1]
    return REMINDER_BRACKETS[2]


def status_for(days: int) -> str:
    if days < 0:
        return "lapsed"
    return "expiring" if days <= REMINDER_BRACKETS[0] else "active"


def days_text(days: int) -> str:
    if days < 0:
        return f"lapsed {abs(days)} day{'s' if abs(days) != 1 else ''} ago"
    if days == 0:
        return "today"
    return f"in {days} day{'s' if days != 1 else ''}"


# ---------------------------------------------------------------------------
# Event ledger (site_events doubles as the "already sent" record — no migration needed)
# ---------------------------------------------------------------------------

def _log_event(db: Any, org_id: str, site_id: Optional[str], actor: str, event: str,
               detail: Optional[dict] = None, order_id: Optional[str] = None) -> None:
    try:
        db.table("site_events").insert({
            "org_id": org_id, "site_id": site_id, "order_id": order_id, "actor": actor,
            "event": event, "detail": detail or {}, "created_at": _iso(),
        }).execute()
    except Exception as exc:  # S14
        logger.warning("site_renewal: site_events insert failed event=%s: %s", event, exc)


def _already_logged(db: Any, org_id: str, site_id: str, event: str, expiry_iso: str) -> bool:
    rows = (db.table("site_events").select("id, detail").eq("org_id", org_id).eq("site_id", site_id)
            .eq("event", event).execute()).data or []
    return any((r.get("detail") or {}).get("expiry") == expiry_iso for r in rows)   # Pattern 33: filter in Python


def _notify_managers(db: Any, org_id: str, title: str, body: str, notif_type: str) -> None:
    try:
        from app.services import funnel_service
        funnel_service.notify_managers(db, org_id, title, body, notif_type, None)
    except Exception as exc:  # S14
        logger.warning("site_renewal: manager notify failed type=%s: %s", notif_type, exc)


def _create_task(db: Any, org_id: str, title: str, description: str, source_record_id: str) -> None:
    try:
        now = _iso()
        db.table("tasks").insert({
            "org_id": org_id, "title": title[:200], "description": description[:1000],
            "task_type": "renewal_client_contact", "source_module": "site_renewal",
            "source_record_id": source_record_id, "priority": "high", "status": "pending",
            "created_at": now, "updated_at": now, "created_by": None,
        }).execute()
    except Exception as exc:  # S14
        logger.warning("site_renewal: task insert failed: %s", exc)


# ---------------------------------------------------------------------------
# Renewal order + payment link
# ---------------------------------------------------------------------------

def _load_site_and_builder(db: Any, org_id: str, domain_row: dict) -> tuple:
    site = _one((db.table("sites").select("*").eq("id", domain_row["site_id"]).eq("org_id", org_id)
                 .is_("deleted_at", "null").limit(1).execute()).data)
    if not site:
        raise RenewalNotFound("Site not found")
    builder = _one((db.table("site_builders").select("*").eq("id", site.get("builder_id"))
                    .eq("org_id", org_id).limit(1).execute()).data)
    if not builder:
        raise RenewalNotFound("Builder not found")
    return site, builder


def get_or_create_renewal_link(db: Any, org_id: str, domain_row: dict) -> dict:
    """
    Returns {"order", "checkout_url", "amount", "reused"}.
    Raises RenewalNotFound / RenewalBlocked (and pricing_service.PricingError) — a synchronous,
    user-facing action, so it may fail loudly (unlike the webhook path).
    """
    from app.services import pricing_service, paystack_storefront_service

    if domain_row.get("status") == "transferred":
        raise RenewalBlocked("This domain has been transferred away, so there is nothing to renew.")
    site, builder = _load_site_and_builder(db, org_id, domain_row)
    lead_id = builder.get("lead_id")
    if not lead_id:
        raise RenewalBlocked("This builder has no linked CRM lead yet — a payment link can't be created.")

    domain = (domain_row.get("domain") or "").lower()
    open_orders = [o for o in ((db.table("site_orders").select("*").eq("org_id", org_id).eq("site_id", site["id"])
                                .eq("kind", "renewal").eq("status", "pending_payment").execute()).data or [])
                   if (o.get("domain") or "").lower() == domain and o.get("payment_link_id")]
    open_orders.sort(key=lambda o: str(o.get("created_at") or ""), reverse=True)
    for order in open_orders:
        link = _one((db.table("payment_links").select("checkout_url").eq("id", order["payment_link_id"])
                     .eq("org_id", org_id).limit(1).execute()).data)
        if link and link.get("checkout_url"):
            return {"order": order, "checkout_url": link["checkout_url"], "amount": order.get("amount"), "reused": True}

    settings = pricing_service.get_settings(db, org_id)
    route = domain_row.get("route") or "standard"
    quoted = pricing_service.quote(db, org_id, domain, route, "renewal", settings=settings)   # never trusted from a caller
    amount = quoted["price"]["total"]

    try:
        link = paystack_storefront_service.generate_payment_link(
            db=db, org_id=org_id, lead_id=lead_id, amount=amount, payment_type="full", currency="NGN",
            trigger_stage=None, target_stage_on_paid=None, created_by=None,
        )
    except paystack_storefront_service.PaystackLinkError as exc:
        raise RenewalBlocked(str(exc))

    now = _iso()
    row = {
        "org_id": org_id, "site_id": site["id"], "builder_id": builder["id"], "lead_id": lead_id,
        "kind": "renewal", "route": route, "domain": domain, "backup_domain": None,
        "quote": quoted, "amount": amount, "cost_snapshot": quoted["cost"], "expected_profit": quoted["profit"],
        "payment_link_id": link.get("payment_link_id"), "payment_reference": link["reference"],
        "status": "pending_payment", "approval_required": False,     # renewals skip approval
        "legal_owner": site.get("legal_owner"), "created_at": now, "updated_at": now,
    }
    order = _one(db.table("site_orders").insert(row).execute().data) or row
    _log_event(db, org_id, site["id"], "system", "renewal_order_created",
               {"domain": domain, "amount": amount, "expiry": (expiry_of(domain_row) or date.min).isoformat()}, order.get("id"))
    return {"order": order, "checkout_url": link["checkout_url"], "amount": amount, "reused": False}


def builder_renewal_checkout(db: Any, org_id: str, builder: dict, site_id: str, now: Optional[datetime] = None) -> dict:
    """The builder portal's "Renew now". Only the builder's own site; only within 60 days of expiry or
    after a lapse (so nobody pays for a renewal a year early)."""
    site = _one((db.table("sites").select("id, builder_id").eq("id", site_id).eq("org_id", org_id)
                 .eq("builder_id", builder["id"]).is_("deleted_at", "null").limit(1).execute()).data)
    if not site:
        raise RenewalNotFound("Site not found")
    rows = [r for r in ((db.table("site_domains").select("*").eq("org_id", org_id).eq("site_id", site_id)
                         .execute()).data or []) if r.get("status") in _MANAGED_STATUSES and expiry_of(r)]
    if not rows:
        raise RenewalBlocked("This site has no hosting to renew yet.")
    rows.sort(key=lambda r: expiry_of(r))
    row = rows[0]
    days = days_left(row, lagos_today(now))
    if days is not None and days > BUILDER_RENEW_WINDOW_DAYS:
        raise RenewalBlocked(f"Renewal opens {BUILDER_RENEW_WINDOW_DAYS} days before the expiry date "
                             f"({_pretty_date(expiry_of(row))}).")
    if _renewal_in_progress(db, org_id, row):
        raise RenewalBlocked("A renewal has already been paid for and is being processed.")
    link = get_or_create_renewal_link(db, org_id, row)
    return {"checkout_url": link["checkout_url"], "amount": link["amount"], "domain": row.get("domain"),
            "expires_on": expiry_of(row).isoformat(), "reused": link["reused"]}


def builder_view(row: Optional[dict], today: date) -> dict:
    """Extra fields for the builder's site list: days_to_renewal + renewal_status."""
    if not row:
        return {"days_to_renewal": None, "renewal_status": None}
    days = days_left(row, today)
    return {"days_to_renewal": days, "renewal_status": status_for(days) if days is not None else None}


# ---------------------------------------------------------------------------
# WhatsApp sends (each returns bool, never raises)
# ---------------------------------------------------------------------------

def _number_row(db: Any, org_id: str) -> Optional[dict]:
    return _one((db.table("whatsapp_numbers").select("*").eq("org_id", org_id)
                 .eq("wa_sales_mode", "site_builder").limit(1).execute()).data)


def _in_free_window(db: Any, org_id: str, phone: str, now: datetime) -> bool:
    chat = _one((db.table("site_chats").select("last_inbound_at").eq("org_id", org_id)
                 .eq("phone_number", phone).limit(1).execute()).data)
    last = _parse_iso((chat or {}).get("last_inbound_at"))
    return bool(last and (now - last) <= timedelta(hours=_WHATSAPP_WINDOW_HOURS))


def send_builder_reminder(db: Any, org_id: str, builder: dict, site: dict, domain_row: dict,
                          checkout_url: str, amount, days: int, now: Optional[datetime] = None) -> bool:
    try:
        from app.services import funnel_messaging
        now = now or _now()
        phone = builder.get("phone_number")
        number = _number_row(db, org_id)
        if not phone or not number:
            return False
        expiry = expiry_of(domain_row)
        expiry_txt = _pretty_date(expiry) if expiry else "soon"
        domain = domain_row.get("domain")
        client = site.get("client_business_name") or domain
        lead_id = builder.get("lead_id")
        if _in_free_window(db, org_id, phone, now):
            text = (f"Renewal reminder: {domain} ({client}) expires on {expiry_txt} — {days_text(days)}.\n"
                    f"Renewing costs {_money(amount)} and covers the domain and hosting.")
            return funnel_messaging.send_cta_url(db, org_id, number, phone, text, "Renew now", checkout_url, lead_id)
        template = os.getenv(BUILDER_TEMPLATE_ENV) or DEFAULT_BUILDER_TEMPLATE
        return funnel_messaging.send_template(
            db, org_id, number, phone, template,
            [builder.get("full_name") or builder.get("business_name") or "there", domain, expiry_txt,
             _money(amount), checkout_url],
            lead_id=lead_id,
        )
    except Exception as exc:  # S14
        logger.warning("site_renewal: builder reminder failed domain=%s: %s", domain_row.get("domain"), exc)
        return False


def send_client_notice(db: Any, org_id: str, builder: dict, site: dict, domain_row: dict) -> tuple:
    """Returns (sent, reason_if_not). Template only — the client has never messaged this number."""
    try:
        from app.services import funnel_messaging
        from app.utils.phone import normalize_phone
        owner = site.get("legal_owner") or {}
        raw_phone = owner.get("phone") if isinstance(owner, dict) else None
        if not raw_phone:
            return False, "no client phone number on file"
        number = _number_row(db, org_id)
        if not number:
            return False, "no site-builder WhatsApp number is set up"
        expiry = expiry_of(domain_row)
        template = os.getenv(CLIENT_TEMPLATE_ENV) or DEFAULT_CLIENT_TEMPLATE
        sent = funnel_messaging.send_template(
            db, org_id, number, normalize_phone(raw_phone), template,
            [owner.get("full_name") or site.get("client_business_name") or "there", domain_row.get("domain"),
             _pretty_date(expiry) if expiry else "soon",
             builder.get("business_name") or builder.get("full_name") or "your web designer"],
            lead_id=None,
        )
        return (True, None) if sent else (False, "WhatsApp rejected the message (is the template approved?)")
    except Exception as exc:  # S14
        logger.warning("site_renewal: client notice failed domain=%s: %s", domain_row.get("domain"), exc)
        return False, "the message could not be sent"


# ---------------------------------------------------------------------------
# The daily sweep
# ---------------------------------------------------------------------------

def _sync_site_status(db: Any, org_id: str, site_id: str, domain_status: str) -> None:
    target = {"lapsed": "lapsed", "expiring": "renewal_due", "active": "live"}[domain_status]
    (db.table("sites").update({"status": target, "updated_at": _iso()})
     .eq("id", site_id).eq("org_id", org_id).in_("status", ["live", "renewal_due", "lapsed"]).execute())


def _renewal_in_progress(db: Any, org_id: str, domain_row: dict) -> bool:
    domain = (domain_row.get("domain") or "").lower()
    rows = (db.table("site_orders").select("id, domain").eq("org_id", org_id).eq("site_id", domain_row["site_id"])
            .eq("kind", "renewal").eq("status", "fulfilling").execute()).data or []
    return any((r.get("domain") or "").lower() == domain for r in rows)


def _process_domain(db: Any, row: dict, now: datetime, org_active: Callable[[str], bool], result: dict) -> None:
    org_id = row["org_id"]
    if not org_active(org_id):
        return
    today = lagos_today(now)
    days = days_left(row, today)
    expiry = expiry_of(row)
    if days is None or expiry is None:
        return
    result["checked"] += 1
    expiry_iso = expiry.isoformat()
    domain = row.get("domain")

    new_status = status_for(days)
    if row.get("status") != new_status:
        db.table("site_domains").update({"status": new_status, "updated_at": _iso(now)}).eq("id", row["id"]).execute()
        _sync_site_status(db, org_id, row["site_id"], new_status)
        result["status_updates"] += 1

    if _renewal_in_progress(db, org_id, row):
        return

    if days < 0:
        if not _already_logged(db, org_id, row["site_id"], "renewal_lapsed", expiry_iso):
            _notify_managers(db, org_id, f"Domain lapsed: {domain}",
                             f"{domain} expired {abs(days)} day(s) ago and hasn't been renewed.", "site_renewal_lapsed")
            _log_event(db, org_id, row["site_id"], "system", "renewal_lapsed", {"expiry": expiry_iso, "domain": domain})
            result["lapsed"] += 1
        return

    site, builder = _load_site_and_builder(db, org_id, row)

    bracket = bracket_for(days)
    if bracket and not _already_logged(db, org_id, row["site_id"], f"renewal_reminder_{bracket}", expiry_iso):
        link = get_or_create_renewal_link(db, org_id, row)     # raises -> counted as failed, retried tomorrow
        sent = send_builder_reminder(db, org_id, builder, site, row, link["checkout_url"], link["amount"], days, now)
        if not sent:
            result["needs_attention"] += 1
            _notify_managers(db, org_id, f"Renewal reminder not delivered: {domain}",
                             f"{domain} renews {days_text(days)}. Couldn't message {builder.get('full_name') or 'the builder'} — "
                             f"send them this link: {link['checkout_url']}", "site_renewal_attention")
        _log_event(db, org_id, row["site_id"], "system", f"renewal_reminder_{bracket}",
                   {"expiry": expiry_iso, "days": days, "sent": bool(sent)}, (link["order"] or {}).get("id"))
        result["reminders"] += 1

    if days <= CLIENT_CONTACT_DAYS and not _already_logged(db, org_id, row["site_id"], "renewal_client_contact", expiry_iso):
        sent, reason = send_client_notice(db, org_id, builder, site, row)
        if not sent:
            owner = site.get("legal_owner") or {}
            owner = owner if isinstance(owner, dict) else {}
            detail = (f"{domain} renews {days_text(days)} and isn't paid. Contact the client: "
                      f"{owner.get('full_name') or site.get('client_business_name') or 'unknown'} · "
                      f"{owner.get('phone') or 'no phone'} · {owner.get('email') or 'no email'} "
                      f"(builder: {builder.get('full_name') or builder.get('business_name')}). Reason: {reason}.")
            _create_task(db, org_id, f"Contact client about renewal: {domain}", detail, row["id"])
            _notify_managers(db, org_id, f"Contact the client: {domain}", detail, "site_renewal_attention")
            result["needs_attention"] += 1
        _log_event(db, org_id, row["site_id"], "system", "renewal_client_contact",
                   {"expiry": expiry_iso, "days": days, "sent": bool(sent), "reason": reason})
        result["client_contacts"] += 1


def run_cycle(db: Any, now: datetime, org_active: Callable[[str], bool]) -> dict:
    """One daily pass over every managed domain. Returns counts; failed > 0 means some domain raised."""
    result = {"checked": 0, "status_updates": 0, "reminders": 0, "client_contacts": 0,
              "lapsed": 0, "needs_attention": 0, "failed": 0}
    rows = (db.table("site_domains").select("*").in_("status", _MANAGED_STATUSES).execute()).data or []
    for row in rows:
        try:
            _process_domain(db, row, now, org_active, result)
        except Exception:  # S14 — one domain never stops the rest
            result["failed"] += 1
            logger.exception("[site_renewal] domain failed id=%s", row.get("id"))
    return result
