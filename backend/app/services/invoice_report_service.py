"""
app/services/invoice_report_service.py
--------------------------------------
INV-5 - the revenue report on the Invoices page, for one business (org_id from the JWT, S1).

  report(db, org_id, start, end)
    invoiced      invoices issued in the period (issue_date), not void: count and total
    collected     receipts paid in the period (paid_at, Lagos dates), not void: total, count, by method
    owed_now      issued / part-paid invoices today: balance, and the overdue part by how late it is
                  (not yet due, 1-30, 31-60, 61-90, over 90 days)
    quotes        quotes issued in the period: count, accepted (customer or staff), declined, expired, win rate
    months        up to 12 calendar months ending with the period's last month: invoiced vs collected per month
    top_customers the 5 customers who paid the most in the period
  receipts_csv(db, org_id, start, end)  the period's receipts for an accountant (cells that start with = + - @ are
                  prefixed with ' so a spreadsheet does not run them).

Money is summed as Decimal and returned as float (2 places). Reads at most 20,000 rows per table per call.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from app.services import invoice_service as inv

MAX_ROWS = 20000
MAX_DAYS = 731
BUCKETS = (("not_due", "Not due yet"), ("d1_30", "1-30 days late"), ("d31_60", "31-60 days late"),
           ("d61_90", "61-90 days late"), ("d90_plus", "Over 90 days late"))
METHODS = ("paystack", "bank_transfer", "cash", "pos", "ussd", "other")


def _rows(res) -> list:
    return (res.data or []) if res else []


def check_period(start: Optional[date], end: Optional[date]) -> tuple[date, date]:
    today = inv.today()
    end = end or today
    start = start or end.replace(day=1)
    if start > end:
        raise inv.InvoiceError("VALIDATION_ERROR", "The start date is after the end date.", 422, "start")
    if (end - start).days > MAX_DAYS:
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose a period of 2 years or less.", 422, "start")
    return start, end


def _lagos_day(value) -> Optional[date]:
    if not value:
        return None
    try:
        s = str(value)
        if "T" not in s and " " not in s:
            return date.fromisoformat(s[:10])
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
        if dt.tzinfo is None:
            return dt.date()
        return dt.astimezone(inv.LAGOS).date()
    except ValueError:
        return None


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _months_back(end: date, n: int) -> list[str]:
    keys, y, m = [], end.year, end.month
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(keys))


def _iso_start(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=inv.LAGOS).isoformat()


def _receipts(db, org_id: str, start: date, end: date) -> list:
    res = db.table("receipts").select("number, invoice_id, customer_name, amount, method, reference, paid_at, voided_at") \
        .eq("org_id", org_id).gte("paid_at", _iso_start(start)).lt("paid_at", _iso_start(end + timedelta(days=1))) \
        .order("paid_at").limit(MAX_ROWS).execute()
    return [r for r in _rows(res) if not r.get("voided_at")]


def report(db, org_id: str, start: Optional[date] = None, end: Optional[date] = None) -> dict:
    start, end = check_period(start, end)
    today = inv.today()
    months = _months_back(end, 12)
    m_start = date(int(months[0][:4]), int(months[0][5:]), 1)
    wide_start = min(start, m_start)

    docs = _rows(db.table("invoices").select("doc_type, status, total, amount_paid, issue_date, due_date, accepted_at, "
                                             "declined_at, customer_name")
                 .eq("org_id", org_id).neq("status", "draft").gte("issue_date", str(wide_start))
                 .lte("issue_date", str(end)).limit(MAX_ROWS).execute())
    receipts = _receipts(db, org_id, wide_start, end)

    per_month = {k: {"month": k, "invoiced": Decimal("0"), "collected": Decimal("0")} for k in months}
    invoiced = Decimal("0")
    invoiced_count = 0
    q = {"issued": 0, "accepted": 0, "declined": 0, "expired": 0, "open": 0}
    for d in docs:
        day = inv._as_date(d.get("issue_date"))
        if not day:
            continue
        if d.get("doc_type") == "invoice" and d.get("status") != "void":
            k = _month_key(day)
            if k in per_month:
                per_month[k]["invoiced"] += inv._money(d.get("total"))
            if start <= day <= end:
                invoiced += inv._money(d.get("total"))
                invoiced_count += 1
        elif d.get("doc_type") == "quote" and start <= day <= end and d.get("status") != "void":
            q["issued"] += 1
            st = inv.display_status(d, today)
            if st in ("accepted",) or d.get("accepted_at"):
                q["accepted"] += 1
            elif st == "declined":
                q["declined"] += 1
            elif st == "expired":
                q["expired"] += 1
            else:
                q["open"] += 1
    answered = q["accepted"] + q["declined"] + q["expired"]
    q["win_rate"] = round(100 * q["accepted"] / answered) if answered else None

    collected = Decimal("0")
    by_method = {m: Decimal("0") for m in METHODS}
    by_customer: dict = {}
    count = 0
    for r in receipts:
        day = _lagos_day(r.get("paid_at"))
        if not day:
            continue
        amt = inv._money(r.get("amount"))
        k = _month_key(day)
        if k in per_month:
            per_month[k]["collected"] += amt
        if start <= day <= end:
            collected += amt
            count += 1
            by_method[r.get("method") if r.get("method") in by_method else "other"] += amt
            name = (r.get("customer_name") or "Unknown").strip() or "Unknown"
            by_customer[name] = by_customer.get(name, Decimal("0")) + amt

    # owed now: every open invoice, whatever its date
    open_docs = _rows(db.table("invoices").select("total, amount_paid, due_date").eq("org_id", org_id)
                      .eq("doc_type", "invoice").in_("status", ["issued", "part_paid"]).limit(MAX_ROWS).execute())
    aging = {k: Decimal("0") for k, _ in BUCKETS}
    aging_count = {k: 0 for k, _ in BUCKETS}
    for d in open_docs:
        bal = inv._money(d.get("total")) - inv._money(d.get("amount_paid"))
        if bal <= 0:
            continue
        due = inv._as_date(d.get("due_date"))
        late = (today - due).days if due else 0
        key = "not_due" if late <= 0 else "d1_30" if late <= 30 else "d31_60" if late <= 60 else \
            "d61_90" if late <= 90 else "d90_plus"
        aging[key] += bal
        aging_count[key] += 1
    owed = sum(aging.values(), Decimal("0"))

    top = sorted(by_customer.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "start": str(start), "end": str(end),
        "invoiced": {"amount": inv._f(invoiced), "count": invoiced_count},
        "collected": {"amount": inv._f(collected), "count": count,
                      "by_method": [{"method": m, "amount": inv._f(v)} for m, v in by_method.items() if v > 0]},
        "owed_now": {"amount": inv._f(owed), "overdue": inv._f(owed - aging["not_due"]),
                     "aging": [{"key": k, "label": label, "amount": inv._f(aging[k]), "count": aging_count[k]}
                               for k, label in BUCKETS]},
        "quotes": q,
        "months": [{"month": v["month"], "invoiced": inv._f(v["invoiced"]), "collected": inv._f(v["collected"])}
                   for v in per_month.values()],
        "top_customers": [{"name": n, "amount": inv._f(v)} for n, v in top],
    }


def _cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def receipts_csv(db, org_id: str, start: Optional[date] = None, end: Optional[date] = None) -> str:
    start, end = check_period(start, end)
    res = db.table("receipts").select("number, invoice_id, customer_name, amount, method, reference, paid_at, voided_at") \
        .eq("org_id", org_id).gte("paid_at", _iso_start(start)).lt("paid_at", _iso_start(end + timedelta(days=1))) \
        .order("paid_at").limit(MAX_ROWS).execute()
    rows = _rows(res)
    numbers = {}
    ids = sorted({r["invoice_id"] for r in rows if r.get("invoice_id")})
    for i in range(0, len(ids), 200):
        for x in _rows(db.table("invoices").select("id, number").eq("org_id", org_id).in_("id", ids[i:i + 200]).execute()):
            numbers[x["id"]] = x.get("number")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Receipt", "Date paid", "Customer", "Invoice", "Method", "Reference", "Amount (NGN)", "Void"])
    for r in rows:
        w.writerow([_cell(r.get("number")), str(_lagos_day(r.get("paid_at")) or ""), _cell(r.get("customer_name")),
                    _cell(numbers.get(r.get("invoice_id")) or ""), _cell(r.get("method")), _cell(r.get("reference")),
                    f"{inv._money(r.get('amount')):.2f}", "yes" if r.get("voided_at") else ""])
    return buf.getvalue()
