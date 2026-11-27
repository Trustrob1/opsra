"""
app/services/invoice_sales_service.py
-------------------------------------
INV-SALES-1 - paid invoices go into Sales Record (direct_sales), and the region a sale belongs to.

  Switch      invoice_settings.sales_record_enabled (off by default). Turning it on stamps sales_record_since; only
              invoices that become fully paid after that moment are added (no backfill).
  Invoice     When an invoice becomes fully paid: one direct_sales row per invoice line (variant = the line's size). amount = the line's share of
              the invoice total (after discount and VAT, the last line takes the rounding so the rows add up exactly),
              units = quantity, model = the commission model whose name is in the line text (longest wins), else the
              line text. rep_name = the invoice maker, region = the invoice region, sale_date = the day of the latest
              payment (Lagos), reconciliation_status Reconciled when any payment came through Paystack, else Pending.
              import_source 'invoice', channel 'invoice'. source_ref 'inv:<item id>' is unique per business, so a
              sale is never written twice.
  Undo        An invoice that is no longer fully paid (a receipt voided) loses its rows, even if the switch is off.
  Receipt     A receipt with no invoice: one row, amount only, source_ref 'rct:<receipt id>'. Voiding it removes it.
  Regions     The business's region names are the Data Sources list (organisations.sheet_sources.transactions.regions).
              A business with regions must put one on each invoice before issuing.
  Part paid   part_paid_summary() feeds the Sales Record card: invoices part-paid, money in so far, money still owed.

S14: writing or removing sales never stops a payment. sync_* never raise; the daily invoice worker retries.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from app.services import invoice_service as inv

logger = logging.getLogger(__name__)

SOURCE = "invoice"
RETRY_BATCH = 200


def _rows(res) -> list:
    return (res.data or []) if res else []


# ───────────────────────────── regions ─────────────────────────────

def regions(db, org_id: str) -> list:
    """Region names from Data Sources, in the saved order, no blanks or repeats."""
    try:
        res = db.table("organisations").select("sheet_sources").eq("id", org_id).limit(1).execute()
        rows = _rows(res)
        src = (rows[0].get("sheet_sources") if rows else None) or {}
        items = ((src.get("transactions") or {}).get("regions")) or [] if isinstance(src, dict) else []
    except Exception as exc:
        logger.warning("invoice_sales: regions lookup failed org=%s: %s", org_id, exc)
        return []
    out, seen = [], set()
    for r in items:
        name = (r.get("name") if isinstance(r, dict) else r) or ""
        name = str(name).strip()[:255]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def clean_region(db, org_id: str, value) -> Optional[str]:
    """The saved spelling of a region the business has, or None for blank. Unknown names are refused."""
    text = (str(value).strip() if value is not None else "")
    if not text:
        return None
    for name in regions(db, org_id):
        if name.lower() == text.lower():
            return name
    raise inv.InvoiceError("VALIDATION_ERROR", "Choose one of your regions.", 422, "region")


def region_required(db, org_id: str) -> bool:
    return bool(regions(db, org_id))


# REVISE-1: each sales rep can have a home region (users.sales_region). Their invoices use it and they pick only
# from that region's bank accounts. A region that no longer exists counts as none.

def rep_region(db, org_id: str, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    try:
        res = db.table("users").select("sales_region").eq("org_id", org_id).eq("id", str(user_id)).limit(1).execute()
        rows = _rows(res)
        want = str((rows[0].get("sales_region") if rows else None) or "").strip().lower()
    except Exception as exc:   # column not there yet: no home regions
        logger.warning("invoice_sales: rep_region failed org=%s: %s", org_id, exc)
        return None
    if not want:
        return None
    return next((name for name in regions(db, org_id) if name.lower() == want), None)


def set_rep_regions(db, org_id: str, data: dict) -> dict:
    """{user_id: region or None} for this business's people. Unknown people are refused; regions must exist."""
    data = dict(data or {})
    if len(data) > 500:
        raise inv.InvoiceError("VALIDATION_ERROR", "Too many people at once.", 422, "regions")
    ids = sorted(str(k) for k in data)
    found = {u["id"] for u in (_rows(db.table("users").select("id").eq("org_id", org_id).in_("id", ids).execute()) if ids else [])}
    if set(ids) - found:
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose people from your team.", 422, "regions")
    out = {}
    for uid in ids:
        region = clean_region(db, org_id, data[uid])
        db.table("users").update({"sales_region": region}).eq("org_id", org_id).eq("id", uid).execute()
        out[uid] = region
    return out


# ───────────────────────────── models ─────────────────────────────

def commission_models(db, org_id: str) -> list:
    try:
        res = db.table("organisations").select("commission_rates").eq("id", org_id).limit(1).execute()
        rows = _rows(res)
        rates = (rows[0].get("commission_rates") if rows else None) or []
    except Exception as exc:
        logger.warning("invoice_sales: commission rates lookup failed org=%s: %s", org_id, exc)
        return []
    return [str(r.get("product_name")).strip() for r in rates
            if isinstance(r, dict) and str(r.get("product_name") or "").strip()]


def match_model(text: Optional[str], models: list) -> Optional[str]:
    """The commission model named in the text (longest name wins, any letter case), else the text itself."""
    text = (text or "").strip()
    if not text:
        return None
    low = text.lower()
    hits = [m for m in models if m.lower() in low]
    return max(hits, key=len) if hits else text[:200]


# ───────────────────────────── helpers ─────────────────────────────

def _settings(db, org_id: str) -> dict:
    rows = _rows(db.table("invoice_settings").select("sales_record_enabled, sales_record_since")
                 .eq("org_id", org_id).limit(1).execute())
    return rows[0] if rows else {}


def _ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _lagos_day(value) -> date:
    d = _ts(value)
    return d.astimezone(inv.LAGOS).date() if d else inv.today()


def _user_name(db, org_id: str, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    try:
        rows = _rows(db.table("users").select("full_name, email").eq("id", user_id).eq("org_id", org_id).limit(1).execute())
    except Exception:
        return None
    if not rows:
        return None
    return (rows[0].get("full_name") or rows[0].get("email") or "").strip() or None


def split_total(line_totals: list, total: Decimal) -> list:
    """Share `total` across the lines in proportion to their line totals; the last line takes the rounding."""
    base = sum(line_totals, Decimal("0"))
    if not line_totals:
        return []
    if base <= 0:
        out = [Decimal("0")] * len(line_totals)
        out[-1] = total
        return out
    out, given = [], Decimal("0")
    for lt in line_totals[:-1]:
        share = inv._money(total * lt / base)
        out.append(share)
        given += share
    out.append(inv._money(total - given))
    return out


def _delete(db, org_id: str, column: str, value: str) -> int:
    res = db.table("direct_sales").delete().eq("org_id", org_id).eq(column, value).eq("import_source", SOURCE).execute()
    return len(_rows(res))


def _insert(db, rows: list) -> int:
    if not rows:
        return 0
    try:
        db.table("direct_sales").insert(rows).execute()
        return len(rows)
    except Exception as exc:
        # another worker wrote the same sale a moment ago (unique source_ref): nothing to do
        if "duplicate" in str(exc).lower() or "23505" in str(exc):
            return 0
        raise


# ───────────────────────────── invoice ─────────────────────────────

def build_invoice_rows(db, org_id: str, doc: dict, receipts: list) -> list:
    items = _rows(db.table("invoice_items").select("*").eq("invoice_id", doc["id"]).eq("org_id", org_id)
                  .order("position").execute())
    if not items:
        return []
    live = [r for r in receipts if not r.get("voided_at")]
    shares = split_total([inv._money(i.get("line_total") or 0) for i in items], inv._money(doc.get("total") or 0))
    models = commission_models(db, org_id)
    maker = doc.get("created_by") or doc.get("issued_by")
    rep = _user_name(db, org_id, maker)
    last_paid = max((r.get("paid_at") or "" for r in live), default="")
    status = "Reconciled" if any(r.get("method") == "paystack" for r in live) else "Pending"
    rows = []
    for item, amount in zip(items, shares):
        rows.append({
            "org_id": org_id, "customer_id": doc.get("customer_id"), "customer_name": doc.get("customer_name"),
            "phone": (doc.get("customer_phone") or None), "amount": inv._f(amount),
            "currency": doc.get("currency") or "NGN", "sale_date": str(_lagos_day(last_paid)),
            "channel": SOURCE, "import_source": SOURCE, "region": doc.get("region"), "rep_name": rep,
            "recorded_by": maker, "model": match_model(item.get("description"), models),
            "units": inv._f(inv._d(item.get("quantity") or 0)), "variant": item.get("variant"),
            "reconciliation_status": status,
            "notes": f"Invoice {doc.get('number') or ''}".strip(),
            "invoice_id": doc["id"], "source_ref": f"inv:{item['id']}",
        })
    return rows


def sync_invoice(db, org_id: str, invoice_id: str) -> dict:
    """Make Sales Record match the invoice: rows when fully paid (switch on, paid after the switch), none otherwise.
    Never raises."""
    try:
        doc = inv._one(db, "invoices", org_id, invoice_id)
        if not doc:
            return {"action": "none"}
        if doc.get("status") != "paid":
            n = _delete(db, org_id, "invoice_id", doc["id"])
            return {"action": "removed" if n else "none", "rows": n}
        existing = _rows(db.table("direct_sales").select("id").eq("org_id", org_id).eq("invoice_id", doc["id"])
                         .limit(1).execute())
        if existing:
            return {"action": "none"}
        s = _settings(db, org_id)
        if not s.get("sales_record_enabled"):
            return {"action": "off"}
        receipts = _rows(db.table("receipts").select("paid_at, created_at, method, voided_at").eq("org_id", org_id)
                         .eq("invoice_id", doc["id"]).execute())
        since = _ts(s.get("sales_record_since"))
        settled = max((_ts(r.get("created_at")) for r in receipts if not r.get("voided_at") and _ts(r.get("created_at"))),
                      default=None)
        if since and settled and settled < since:
            return {"action": "before_switch"}
        n = _insert(db, build_invoice_rows(db, org_id, doc, receipts))
        return {"action": "added" if n else "none", "rows": n}
    except Exception as exc:  # S14
        logger.warning("invoice_sales: sync failed org=%s invoice=%s: %s", org_id, invoice_id, exc)
        return {"action": "failed"}


# ───────────────────────────── standalone receipt ─────────────────────────────

def sync_receipt(db, org_id: str, receipt: dict) -> dict:
    """A receipt with no invoice: one sale while it stands and the switch is on; removed once void. Never raises."""
    try:
        if receipt.get("invoice_id"):
            return {"action": "none"}
        if receipt.get("voided_at"):
            n = _delete(db, org_id, "receipt_id", receipt["id"])
            return {"action": "removed" if n else "none", "rows": n}
        if not _settings(db, org_id).get("sales_record_enabled"):
            return {"action": "off"}
        existing = _rows(db.table("direct_sales").select("id").eq("org_id", org_id).eq("receipt_id", receipt["id"])
                         .limit(1).execute())
        if existing:
            return {"action": "none"}
        row = {
            "org_id": org_id, "customer_id": receipt.get("customer_id"), "customer_name": receipt.get("customer_name"),
            "phone": ((receipt.get("_contact") or {}).get("customer_phone") or None),
            "amount": inv._f(inv._money(receipt.get("amount") or 0)), "currency": receipt.get("currency") or "NGN",
            "sale_date": str(_lagos_day(receipt.get("paid_at"))), "channel": SOURCE, "import_source": SOURCE,
            "region": receipt.get("region"), "rep_name": _user_name(db, org_id, receipt.get("recorded_by")),
            "recorded_by": receipt.get("recorded_by"), "model": None, "units": None,
            "reconciliation_status": "Pending",
            "notes": f"Receipt {receipt.get('number') or ''}: {receipt.get('description') or ''}".strip()[:500],
            "receipt_id": receipt["id"], "source_ref": f"rct:{receipt['id']}",
        }
        n = _insert(db, [row])
        return {"action": "added" if n else "none", "rows": n}
    except Exception as exc:  # S14
        logger.warning("invoice_sales: receipt sync failed org=%s receipt=%s: %s", org_id, receipt.get("id"), exc)
        return {"action": "failed"}


# ───────────────────────────── retry (daily worker) ─────────────────────────────

def retry_missing(db, dry_run: bool = False) -> dict:
    """Fully paid invoices (after each business's switch) with no Sales Record rows yet. Never raises."""
    out = {"checked": 0, "added": 0, "failed": 0}
    try:
        on = _rows(db.table("invoice_settings").select("org_id, sales_record_since").eq("sales_record_enabled", True).execute())
    except Exception as exc:
        logger.error("invoice_sales: retry settings read failed: %s", exc)
        out["failed"] += 1
        return out
    for s in on:
        org_id = s["org_id"]
        try:
            q = db.table("invoices").select("id").eq("org_id", org_id).eq("doc_type", "invoice").eq("status", "paid")
            if s.get("sales_record_since"):
                q = q.gte("updated_at", s["sales_record_since"])
            docs = _rows(q.order("updated_at", desc=True).limit(RETRY_BATCH).execute())
            if not docs:
                continue
            ids = [d["id"] for d in docs]
            have = {r["invoice_id"] for r in _rows(db.table("direct_sales").select("invoice_id").eq("org_id", org_id)
                                                   .in_("invoice_id", ids).execute())}
            for i in ids:
                if i in have:
                    continue
                out["checked"] += 1
                if dry_run:
                    continue
                res = sync_invoice(db, org_id, i)
                if res.get("action") == "added":
                    out["added"] += 1
                elif res.get("action") == "failed":
                    out["failed"] += 1
        except Exception as exc:  # S14
            out["failed"] += 1
            logger.warning("invoice_sales: retry failed org=%s: %s", org_id, exc)
    return out


# ───────────────────────────── part-paid card ─────────────────────────────

def part_paid_summary(db, org_id: str, start: Optional[date] = None, end: Optional[date] = None,
                      rep: Optional[str] = None, region: Optional[str] = None, limit: int = 200,
                      mine: Optional[str] = None) -> dict:
    """Invoices part-paid now, issued in the period, for the Sales Record card. rep matches the maker's name."""
    q = db.table("invoices").select("id, number, customer_name, region, total, amount_paid, issue_date, due_date, "
                                    "created_by, issued_by") \
        .eq("org_id", org_id).eq("doc_type", "invoice").eq("status", "part_paid")
    if mine:   # SALE-1: a rep sees only their own
        q = q.eq("created_by", mine)
    if start:
        q = q.gte("issue_date", str(start))
    if end:
        q = q.lte("issue_date", str(end))
    if region:
        q = q.eq("region", region)
    docs = _rows(q.order("issue_date", desc=True).limit(2000).execute())
    makers = sorted({d.get("created_by") or d.get("issued_by") for d in docs if d.get("created_by") or d.get("issued_by")})
    names: dict = {}
    for i in range(0, len(makers), 200):
        for u in _rows(db.table("users").select("id, full_name, email").eq("org_id", org_id).in_("id", makers[i:i + 200]).execute()):
            names[u["id"]] = (u.get("full_name") or u.get("email") or "").strip()
    received = owed = Decimal("0")
    items = []
    want = (rep or "").strip().lower()
    for d in docs:
        who = names.get(d.get("created_by") or d.get("issued_by")) or ""
        if want and who.lower() != want:
            continue
        total, paid = inv._money(d.get("total") or 0), inv._money(d.get("amount_paid") or 0)
        received += paid
        owed += max(total - paid, Decimal("0"))
        if len(items) < limit:
            items.append({"id": d["id"], "number": d.get("number"), "customer_name": d.get("customer_name"),
                          "rep_name": who or None, "region": d.get("region"), "total": inv._f(total),
                          "amount_paid": inv._f(paid), "balance": inv._f(max(total - paid, Decimal("0"))),
                          "issue_date": d.get("issue_date"), "due_date": d.get("due_date")})
    count = sum(1 for d in docs if not want or (names.get(d.get("created_by") or d.get("issued_by")) or "").lower() == want)
    return {"count": count, "received": inv._f(received), "owed": inv._f(owed), "items": items}
