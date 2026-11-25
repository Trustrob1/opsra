"""
app/services/invoice_followup_service.py
----------------------------------------
INV-5 - the daily follow-up on quotes and invoices (run by workers/invoice_worker.py, 10:00 Lagos time).

  Overdue reminders  Only for businesses that turned on invoice_settings.reminders_enabled (off by default).
                     An issued / part-paid invoice gets at most 3 reminders: when it is 1, 7 and 14 days late, never
                     two within 5 days. Channel: WhatsApp when the customer's 24-hour window is open, otherwise email
                     when there is an address. With neither, the invoice is skipped (counted as no_channel) and the
                     person who made it gets ONE task to chase it by hand (reminder_count is set to 3 so it is not
                     tried again). Each reminder carries the PDF and the customer's /i/<token> link (Pay now there).
  Quote expiry       For every business on the invoices plan: an issued quote whose date passed in the last 3 days
                     gives its maker one task "Quote X for Y expired" (expiry_notified_at, so once).

Gates per business: subscription active or grace (org_gates.is_org_active) and the plan includes `invoices`.
dry_run=True reads everything and returns the same counts, but sends and writes nothing.
S14: one document failing never stops the run; run() never raises.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.services import invoice_service as inv

logger = logging.getLogger(__name__)

REMINDER_DAYS = (1, 7, 14)      # days late for reminder 1, 2, 3
MIN_GAP = timedelta(days=5)
QUOTE_LOOKBACK_DAYS = 3
BATCH = 500


def _rows(res) -> list:
    return (res.data or []) if res else []


def _active_orgs(db, org_ids: list) -> dict:
    """{org_id: name} for businesses whose subscription lets automations run."""
    if not org_ids:
        return {}
    from app.utils.org_gates import is_org_active
    out = {}
    for i in range(0, len(org_ids), 200):
        res = db.table("organisations").select("id, name, subscription_status").in_("id", org_ids[i:i + 200]).execute()
        for o in _rows(res):
            if is_org_active(o):
                out[o["id"]] = o.get("name")
    return out


def _allowed(db, org_id: str) -> bool:
    from app.services import plan_gate_service as plan_gate
    return plan_gate.allowed(db, org_id, "invoices")


def _task(db, doc: dict, title: str, priority: str = "medium") -> None:
    who = doc.get("created_by") or doc.get("issued_by")
    if not who:
        return
    row = {"org_id": doc["org_id"], "title": title[:200], "task_type": "system_event", "assigned_to": who,
           "priority": priority, "status": "pending",
           "due_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(), "created_at": inv._now_iso()}
    if doc.get("lead_id"):
        row.update(source_module="leads", source_record_id=doc["lead_id"])
    db.table("tasks").insert(row).execute()


def reminder_due(doc: dict, on: date, now: Optional[datetime] = None) -> bool:
    """Is this invoice due its next reminder today?"""
    now = now or datetime.now(timezone.utc)
    count = int(doc.get("reminder_count") or 0)
    if count >= len(REMINDER_DAYS):
        return False
    due = inv._as_date(doc.get("due_date"))
    if not due or (on - due).days < REMINDER_DAYS[count]:
        return False
    last = doc.get("last_reminder_at")
    if last:
        try:
            if now - datetime.fromisoformat(str(last).replace("Z", "+00:00")) < MIN_GAP:
                return False
        except ValueError:
            pass
    if inv._money(doc.get("total") or 0) - inv._money(doc.get("amount_paid") or 0) <= 0:
        return False
    return True


def run(db, dry_run: bool = False, on: Optional[date] = None) -> dict:
    on = on or inv.today()
    out = {"dry_run": dry_run, "orgs": 0, "reminders_sent": 0, "no_channel": 0, "quotes_expired": 0,
           "skipped_plan": 0, "failed": 0}
    try:
        _reminders(db, on, dry_run, out)
    except Exception as exc:
        logger.error("invoice_followup: reminders step failed: %s", exc)
        out["failed"] += 1
    try:
        _quote_expiry(db, on, dry_run, out)
    except Exception as exc:
        logger.error("invoice_followup: quote expiry step failed: %s", exc)
        out["failed"] += 1
    # INV-SALES-1: paid invoices that did not reach Sales Record when they were paid
    from app.services import invoice_sales_service as sales
    r = sales.retry_missing(db, dry_run=dry_run)
    out["sales_missing"], out["sales_added"] = r["checked"], r["added"]
    out["failed"] += r["failed"]
    return out


def _reminders(db, on: date, dry_run: bool, out: dict) -> None:
    from app.services import invoice_delivery_service as delivery
    settings = _rows(db.table("invoice_settings").select("org_id").eq("reminders_enabled", True).execute())
    orgs = _active_orgs(db, [s["org_id"] for s in settings])
    for org_id in orgs:
        if not _allowed(db, org_id):
            out["skipped_plan"] += 1
            continue
        out["orgs"] += 1
        late_by = str(on - timedelta(days=REMINDER_DAYS[0]))
        docs = _rows(db.table("invoices").select("*").eq("org_id", org_id).eq("doc_type", "invoice")
                     .in_("status", ["issued", "part_paid"]).lte("due_date", late_by)
                     .lt("reminder_count", len(REMINDER_DAYS)).order("due_date", desc=True).limit(BATCH).execute())
        for d in docs:
            if not reminder_due(d, on):
                continue
            try:
                res = delivery.send_reminder(db, org_id, d["id"], dry_run=dry_run)
                if res.get("channel"):
                    out["reminders_sent"] += 1
                    if not dry_run:
                        db.table("invoices").update({"reminder_count": int(d.get("reminder_count") or 0) + 1,
                                                     "last_reminder_at": inv._now_iso()}) \
                            .eq("id", d["id"]).eq("org_id", org_id).execute()
                else:
                    out["no_channel"] += 1
                    if not dry_run:
                        _task(db, d, f"Invoice {d.get('number')} for {d.get('customer_name') or 'a customer'} is overdue "
                                     f"and could not be sent a reminder (no open WhatsApp chat or email). Chase it by hand.",
                              "high")
                        db.table("invoices").update({"reminder_count": len(REMINDER_DAYS),
                                                     "last_reminder_at": inv._now_iso()}) \
                            .eq("id", d["id"]).eq("org_id", org_id).execute()
            except Exception as exc:  # S14
                out["failed"] += 1
                logger.warning("invoice_followup: reminder failed org=%s doc=%s: %s", org_id, d.get("id"), exc)


def _quote_expiry(db, on: date, dry_run: bool, out: dict) -> None:
    since = str(on - timedelta(days=QUOTE_LOOKBACK_DAYS))
    quotes = _rows(db.table("invoices").select("id, org_id, number, customer_name, lead_id, created_by, issued_by, due_date")
                   .eq("doc_type", "quote").eq("status", "issued").is_("expiry_notified_at", "null")
                   .lt("due_date", str(on)).gte("due_date", since).limit(2000).execute())
    if not quotes:
        return
    orgs = _active_orgs(db, sorted({q["org_id"] for q in quotes}))
    plan_ok: dict = {}
    for q in quotes:
        org_id = q["org_id"]
        if org_id not in orgs:
            continue
        if org_id not in plan_ok:
            plan_ok[org_id] = _allowed(db, org_id)
        if not plan_ok[org_id]:
            continue
        try:
            out["quotes_expired"] += 1
            if dry_run:
                continue
            _task(db, q, f"Quote {q.get('number')} for {q.get('customer_name') or 'a customer'} expired without an "
                         f"answer. Follow up, or send a new quote.")
            db.table("invoices").update({"expiry_notified_at": inv._now_iso()}) \
                .eq("id", q["id"]).eq("org_id", org_id).execute()
        except Exception as exc:  # S14
            out["failed"] += 1
            logger.warning("invoice_followup: quote expiry failed org=%s doc=%s: %s", org_id, q.get("id"), exc)
