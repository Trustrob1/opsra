"""
app/services/business_report_service.py
---------------------------------------
REPORT-1 - the sales report and the inventory report an admin downloads (PDF or CSV) and the owner gets by email.

  sales_data(db, org_id, start, end, region=, location_id=, rep_id=)
      invoices issued in the period (not draft, not void): number, value, paid on them, still owed;
      payments received in the period by method; by rep, by region, by location, by product + size;
      part-paid invoices with their balance; every sale in the period.
  inventory_data(db, org_id, start, end, location_id=)
      stock now per product + size (on hand, held, to deliver, available, in transit, value at cost);
      stock moves in the period by kind; low stock; paid orders waiting delivery.
  sales_pdf / inventory_pdf  -> (bytes | None, filename)   S14: never raises, None when WeasyPrint fails
  sales_csv / inventory_csv  -> str                         cells starting = + - @ are made safe for spreadsheets

Every value from the database is escaped in the PDF. Money is summed as Decimal. org_id always comes from the JWT (S1).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from app.services import invoice_pdf_service as pdf
from app.services import invoice_report_service as rep
from app.services import invoice_service as inv

logger = logging.getLogger(__name__)

MAX_ROWS = rep.MAX_ROWS
NO_REGION = "No region"
NO_LOCATION = "No location"
_Z = Decimal("0")


def _rows(res) -> list:
    return (res.data or []) if res else []


def _in(db, table: str, cols: str, org_id: str, column: str, ids: list) -> list:
    out = []
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), 200):
        out += _rows(db.table(table).select(cols).eq("org_id", org_id).in_(column, ids[i:i + 200]).execute())
    return out


def _names(db, org_id: str, ids) -> dict:
    return {u["id"]: (u.get("full_name") or u.get("email") or "Unknown") for u in
            _in(db, "users", "id, full_name, email", org_id, "id", list(ids))}


def _locations(db, org_id: str) -> dict:
    try:
        from app.services import inventory_service as stock
        return {l["id"]: l for l in stock.list_locations(db, org_id)}
    except Exception as exc:   # inventory tables missing -> the sales report still works
        logger.warning("business_report: locations failed org=%s: %s", org_id, exc)
        return {}


def _group(acc: dict, key: str, d: dict) -> None:
    g = acc.setdefault(key, {"name": key, "count": 0, "value": _Z, "paid": _Z, "owed": _Z})
    g["count"] += 1
    g["value"] += d["_total"]
    g["paid"] += d["_paid"]
    g["owed"] += d["_owed"]


def _out(groups: dict) -> list:
    rows = sorted(groups.values(), key=lambda g: (-g["value"], str(g["name"]).lower()))
    return [{**g, "value": inv._f(g["value"]), "paid": inv._f(g["paid"]), "owed": inv._f(g["owed"])} for g in rows]


# ───────────────────────────── sales ─────────────────────────────

def sales_data(db, org_id: str, start: Optional[date] = None, end: Optional[date] = None, region: Optional[str] = None,
               location_id: Optional[str] = None, rep_id: Optional[str] = None) -> dict:
    start, end = rep.check_period(start, end)
    region = (region or "").strip() or None
    q = db.table("invoices").select("id, number, issue_date, customer_name, total, amount_paid, status, region, "
                                    "location_id, created_by") \
        .eq("org_id", org_id).eq("doc_type", "invoice").gte("issue_date", str(start)).lte("issue_date", str(end))
    if rep_id:
        q = q.eq("created_by", str(rep_id))
    if location_id:
        q = q.eq("location_id", str(location_id))
    docs = [d for d in _rows(q.order("issue_date").limit(MAX_ROWS).execute())
            if d.get("status") not in ("draft", "void")]
    if region:
        docs = [d for d in docs if str(d.get("region") or "").strip().lower() == region.lower()]

    locs = _locations(db, org_id)
    names = _names(db, org_id, {d.get("created_by") for d in docs})
    totals = {"count": 0, "value": _Z, "paid": _Z, "owed": _Z}
    by_rep: dict = {}
    by_region: dict = {}
    by_location: dict = {}
    sales, part_paid = [], []
    for d in docs:
        total, paid = inv._money(d.get("total")), inv._money(d.get("amount_paid"))
        d.update({"_total": total, "_paid": paid, "_owed": max(total - paid, _Z)})
        totals["count"] += 1
        totals["value"] += total
        totals["paid"] += paid
        totals["owed"] += d["_owed"]
        rep_name = names.get(d.get("created_by")) or "Unknown"
        loc_name = (locs.get(d.get("location_id")) or {}).get("name") or NO_LOCATION
        reg = str(d.get("region") or "").strip() or NO_REGION
        _group(by_rep, rep_name, d)
        _group(by_region, reg, d)
        _group(by_location, loc_name, d)
        row = {"id": d["id"], "number": d.get("number"), "date": d.get("issue_date"), "customer": d.get("customer_name"),
               "rep": rep_name, "region": None if reg == NO_REGION else reg,
               "location": None if loc_name == NO_LOCATION else loc_name, "status": d.get("status"),
               "total": inv._f(total), "paid": inv._f(paid), "owed": inv._f(d["_owed"])}
        sales.append(row)
        if paid > 0 and d["_owed"] > 0:
            part_paid.append(row)

    # products + sizes on these invoices
    products: dict = {}
    for it in _in(db, "invoice_items", "invoice_id, product_id, description, variant, quantity, line_total", org_id,
                  "invoice_id", [d["id"] for d in docs]):
        variant = str(it.get("variant") or "").strip()
        key = (it.get("product_id") or str(it.get("description") or "").strip().lower(), variant.lower())
        p = products.setdefault(key, {"name": str(it.get("description") or "Item").strip(), "size": variant,
                                      "units": _Z, "value": _Z})
        p["units"] += inv._money(it.get("quantity"))
        p["value"] += inv._money(it.get("line_total"))
    by_product = [{**p, "units": float(p["units"]), "value": inv._f(p["value"])}
                  for p in sorted(products.values(), key=lambda p: (-p["value"], p["name"].lower()))]

    # money received in the period (receipts), with the same filters
    doc_ids = {d["id"] for d in docs}
    rq = db.table("receipts").select("invoice_id, amount, method, paid_at, voided_at, owner_id").eq("org_id", org_id) \
        .gte("paid_at", rep._iso_start(start)).lt("paid_at", rep._iso_start(end + timedelta(days=1)))
    if rep_id:
        rq = rq.eq("owner_id", str(rep_id))
    receipts = [r for r in _rows(rq.limit(MAX_ROWS).execute()) if not r.get("voided_at")]
    if region or location_id:   # receipts for invoices outside the filter (or with no invoice) don't count
        allowed = {d["id"] for d in _in(db, "invoices", "id, region, location_id", org_id, "id",
                                        [r.get("invoice_id") for r in receipts])
                   if (not location_id or d.get("location_id") == str(location_id))
                   and (not region or str(d.get("region") or "").strip().lower() == region.lower())} | doc_ids
        receipts = [r for r in receipts if r.get("invoice_id") in allowed]
    received = _Z
    by_method: dict = {}
    for r in receipts:
        amt = inv._money(r.get("amount"))
        received += amt
        m = r.get("method") or "other"
        by_method[m] = by_method.get(m, _Z) + amt
    methods = [{"method": m, "name": pdf.METHOD_LABELS.get(m, m), "amount": inv._f(v)}
               for m, v in sorted(by_method.items(), key=lambda kv: -kv[1])]

    filters = {"region": region, "location": (locs.get(str(location_id)) or {}).get("name") if location_id else None,
               "rep": (_names(db, org_id, [rep_id]).get(str(rep_id)) or "Unknown") if rep_id else None}
    return {"start": str(start), "end": str(end), "filters": filters,
            "totals": {"count": totals["count"], "value": inv._f(totals["value"]), "paid": inv._f(totals["paid"]),
                       "owed": inv._f(totals["owed"]), "received": inv._f(received), "payments": len(receipts)},
            "by_method": methods, "by_rep": _out(by_rep), "by_region": _out(by_region),
            "by_location": _out(by_location), "by_product": by_product,
            "part_paid": sorted(part_paid, key=lambda r: -r["owed"]), "sales": sales}


def sales_csv(data: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Invoice", "Date", "Customer", "Rep", "Region", "Location", "Status", "Total (NGN)", "Paid (NGN)",
                "Owed (NGN)"])
    for s in data["sales"]:
        w.writerow([rep._cell(s["number"]), s["date"] or "", rep._cell(s["customer"]), rep._cell(s["rep"]),
                    rep._cell(s["region"] or ""), rep._cell(s["location"] or ""), s["status"] or "",
                    f"{s['total']:.2f}", f"{s['paid']:.2f}", f"{s['owed']:.2f}"])
    return buf.getvalue()


# ───────────────────────────── inventory ─────────────────────────────

def inventory_data(db, org_id: str, start: Optional[date] = None, end: Optional[date] = None,
                   location_id: Optional[str] = None) -> dict:
    from app.services import inventory_service as stock
    from app.services import invoice_stock_service as inv_stock
    start, end = rep.check_period(start, end)
    ov = stock.overview(db, org_id, True, location_id=location_id)
    items = [{"title": r["title"], "size": r["variant"], "sku": r.get("sku"), "on_hand": r["on_hand"],
              "held": r["held"], "to_deliver": r["sold_pending"], "available": r["available"],
              "in_transit": r["in_transit_in"], "reorder_level": r["reorder_level"], "low": r["low"],
              "cost": r.get("cost_price"),
              "value": round((r.get("cost_price") or 0) * r["on_hand"], 2)} for r in ov["items"]]

    q = db.table("stock_moves").select("item_id, kind, d_on_hand, location_id, created_at").eq("org_id", org_id) \
        .gte("created_at", rep._iso_start(start)).lt("created_at", rep._iso_start(end + timedelta(days=1)))
    if location_id:
        q = q.eq("location_id", str(location_id))
    moves = _rows(q.limit(MAX_ROWS).execute())
    kinds: dict = {}
    for m in moves:
        k = kinds.setdefault(m.get("kind") or "other", {"kind": m.get("kind") or "other",
                                                        "name": stock.KIND_LABEL.get(m.get("kind"), m.get("kind") or "Other"),
                                                        "moves": 0, "units": 0})
        k["moves"] += 1
        k["units"] += stock._num(m.get("d_on_hand"))
    waiting = inv_stock.to_deliver_list(db, org_id, location_id)
    loc_name = next((l["name"] for l in ov["locations"] if l["id"] == str(location_id)), None) if location_id else None
    return {"start": str(start), "end": str(end), "filters": {"location": loc_name},
            "summary": {**ov["summary"]}, "items": items, "low": [i for i in items if i["low"]],
            "moves": sorted(kinds.values(), key=lambda k: -k["moves"]),
            "waiting": [{"number": w.get("number"), "customer": w.get("customer_name"), "date": w.get("issue_date"),
                         "location": w.get("location"), "units": w.get("units"),
                         "lines": ", ".join(f"{l['description']} x{l['units']}" for l in w.get("lines") or [])}
                        for w in waiting]}


def inventory_csv(data: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Product", "Size", "SKU", "On hand", "Held", "To deliver", "Available", "In transit",
                "Reorder at", "Low", "Cost (NGN)", "Value at cost (NGN)"])
    for i in data["items"]:
        w.writerow([rep._cell(i["title"]), rep._cell(i["size"]), rep._cell(i["sku"] or ""), i["on_hand"], i["held"],
                    i["to_deliver"], i["available"], i["in_transit"], i["reorder_level"], "yes" if i["low"] else "",
                    "" if i["cost"] is None else f"{i['cost']:.2f}", f"{i['value']:.2f}"])
    return buf.getvalue()


# ───────────────────────────── PDF ─────────────────────────────

_e = pdf._e
_m = pdf.money


def _period(data: dict) -> str:
    s, e = pdf._nice_date(data["start"]), pdf._nice_date(data["end"])
    return s if s == e else f"{s} to {e}"


def _table(head: list, rows: list, right: tuple = ()) -> str:
    if not rows:
        return '<p class="none">Nothing in this period.</p>'
    th = "".join(f'<th class="{"r" if i in right else ""}">{_e(h)}</th>' for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f'<td class="{"r" if i in right else ""}">{c}</td>' for i, c in enumerate(r))
                   + "</tr>" for r in rows)
    return f'<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def _tiles(tiles: list) -> str:
    return '<table class="tiles"><tr>' + "".join(
        f'<td><div class="k">{_e(k)}</div><div class="v">{v}</div></td>' for k, v in tiles) + "</tr></table>"


def _page(settings: dict, title: str, data: dict, body: str) -> str:
    colour = settings.get("brand_colour") if pdf._HEX.match(str(settings.get("brand_colour") or "")) else "#0d9488"
    logo = f'<img class="logo" src="{_e(settings.get("logo_url"))}">' if pdf._logo_allowed(settings.get("logo_url")) else ""
    f = {k: v for k, v in (data.get("filters") or {}).items() if v}
    filt = " &middot; ".join(f"{_e(k.title())}: {_e(v)}" for k, v in f.items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 16mm 14mm; @bottom-right {{ content: "Page " counter(page) " of " counter(pages);
  font-size: 8pt; color: #888; font-family: "DejaVu Sans", Arial, sans-serif; }} }}
body {{ font-family: "DejaVu Sans", Arial, sans-serif; font-size: 9pt; color: #222; }}
.head {{ border-bottom: 3px solid {colour}; padding-bottom: 8px; margin-bottom: 12px; }}
.logo {{ max-height: 42px; max-width: 160px; float: right; }}
.biz {{ font-size: 11pt; font-weight: bold; }} h1 {{ font-size: 16pt; margin: 4px 0 2px; color: {colour}; }}
.sub {{ color: #555; }} h2 {{ font-size: 11pt; margin: 16px 0 6px; color: {colour}; }}
table {{ width: 100%; border-collapse: collapse; }} th {{ text-align: left; font-size: 8pt; color: #555;
  border-bottom: 1px solid #ccc; padding: 4px; }} td {{ padding: 4px; border-bottom: 1px solid #eee; }}
.r {{ text-align: right; }} .none {{ color: #777; font-style: italic; }}
.tiles td {{ border: 1px solid #ddd; padding: 8px; width: 25%; }} .tiles .k {{ font-size: 8pt; color: #666; }}
.tiles .v {{ font-size: 12pt; font-weight: bold; margin-top: 2px; }}
</style></head><body><div class="head">{logo}<div class="biz">{_e(settings.get("business_name") or "")}</div>
<h1>{_e(title)}</h1><div class="sub">{_e(_period(data))}{(" &middot; " + filt) if filt else ""}</div></div>
{body}</body></html>"""


def sales_html(data: dict, settings: dict) -> str:
    t = data["totals"]
    grp = lambda rows: _table(["", "Sales", "Value", "Paid", "Owed"],   # noqa: E731
                              [[_e(g["name"]), g["count"], _m(g["value"]), _m(g["paid"]), _m(g["owed"])] for g in rows],
                              (1, 2, 3, 4))
    body = _tiles([("Sales", t["count"]), ("Sales value", _m(t["value"])), ("Money received", _m(t["received"])),
                   ("Still owed", _m(t["owed"]))])
    body += "<h2>Money received by method</h2>" + _table(["Method", "Amount"],
                                                         [[_e(m["name"]), _m(m["amount"])] for m in data["by_method"]], (1,))
    body += "<h2>By rep</h2>" + grp(data["by_rep"])
    body += "<h2>By region</h2>" + grp(data["by_region"])
    body += "<h2>By location</h2>" + grp(data["by_location"])
    body += "<h2>By product and size</h2>" + _table(
        ["Product", "Size", "Units", "Value"],
        [[_e(p["name"]), _e(p["size"] or "—"), pdf._qty(p["units"]), _m(p["value"])] for p in data["by_product"]], (2, 3))
    body += "<h2>Part-paid invoices</h2>" + _table(
        ["Invoice", "Customer", "Rep", "Total", "Paid", "Owed"],
        [[_e(s["number"]), _e(s["customer"]), _e(s["rep"]), _m(s["total"]), _m(s["paid"]), _m(s["owed"])]
         for s in data["part_paid"]], (3, 4, 5))
    body += "<h2>All sales</h2>" + _table(
        ["Date", "Invoice", "Customer", "Rep", "Region", "Total", "Owed"],
        [[pdf._nice_date(s["date"]), _e(s["number"]), _e(s["customer"]), _e(s["rep"]), _e(s["region"] or "—"),
          _m(s["total"]), _m(s["owed"])] for s in data["sales"]], (5, 6))
    return _page(settings, "Sales report", data, body)


def inventory_html(data: dict, settings: dict) -> str:
    s = data["summary"]
    body = _tiles([("Products and sizes", s.get("lines", 0)), ("Units on hand", s.get("units_on_hand", 0)),
                   ("Value at cost", _m(s.get("stock_value", 0))), ("Running low", s.get("low", 0))])
    if s.get("missing_cost"):
        body += f'<p class="none">{s["missing_cost"]} item(s) in stock have no cost price, so the value is too low.</p>'
    body += "<h2>Running low</h2>" + _table(
        ["Product", "Size", "Available", "Reorder at"],
        [[_e(i["title"]), _e(i["size"] or "—"), i["available"], i["reorder_level"]] for i in data["low"]], (2, 3))
    body += "<h2>Paid, waiting delivery</h2>" + _table(
        ["Invoice", "Customer", "Location", "Items"],
        [[_e(w["number"]), _e(w["customer"]), _e(w["location"] or "—"), _e(w["lines"])] for w in data["waiting"]])
    body += "<h2>Stock moves in the period</h2>" + _table(
        ["Kind", "Moves", "Units in / out"],
        [[_e(k["name"]), k["moves"], f'{k["units"]:+d}' if k["units"] else "0"] for k in data["moves"]], (1, 2))
    body += "<h2>Stock now</h2>" + _table(
        ["Product", "Size", "On hand", "Held", "To deliver", "Available", "In transit", "Value"],
        [[_e(i["title"]), _e(i["size"] or "—"), i["on_hand"], i["held"], i["to_deliver"], i["available"],
          i["in_transit"], _m(i["value"])] for i in data["items"]], (2, 3, 4, 5, 6, 7))
    return _page(settings, "Inventory report", data, body)


def _render(html_text: str, name: str) -> tuple[Optional[bytes], str]:
    try:
        from weasyprint import HTML
        return HTML(string=html_text, url_fetcher=pdf.pdf_url_fetcher()).write_pdf(), name
    except Exception as exc:  # S14
        logger.error("business_report: PDF failed %s: %s", name, exc)
        return None, name


def filename(kind: str, data: dict, ext: str) -> str:
    s, e = data["start"], data["end"]
    return f"{kind}-report-{s}.{ext}" if s == e else f"{kind}-report-{s}-to-{e}.{ext}"


def sales_pdf(data: dict, settings: dict) -> tuple[Optional[bytes], str]:
    return _render(sales_html(data, settings), filename("sales", data, "pdf"))


def inventory_pdf(data: dict, settings: dict) -> tuple[Optional[bytes], str]:
    return _render(inventory_html(data, settings), filename("inventory", data, "pdf"))
