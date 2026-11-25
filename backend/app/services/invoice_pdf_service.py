"""
app/services/invoice_pdf_service.py
-----------------------------------
INV-1 - the printable PDF of a quote, invoice or receipt (WeasyPrint, same engine as owner_pdf_service).

  build_html(doc, settings, kind)  the HTML (every value from the database or the customer is escaped)
  render(doc, settings, kind)      (pdf_bytes | None, filename). S14: never raises; None when WeasyPrint fails.

Issued documents print the business details copied at issue (doc['issuer']), so editing the settings later never changes
an invoice the customer already has. Drafts print the current settings and a DRAFT mark.

Security: WeasyPrint only fetches the business logo, and only from this project's own Supabase public storage. Any other
URL (including ones a user might type into the logo field) is refused by _safe_fetcher, so a PDF can never be used to
make the server call an outside or internal address (SSRF).
"""
from __future__ import annotations

import html
import logging
import os
import re
from datetime import date
from typing import Any, Optional

logger = logging.getLogger(__name__)

TITLES = {"quote": "QUOTATION", "invoice": "INVOICE", "receipt": "RECEIPT"}
METHOD_LABELS = {"paystack": "Paystack (card / transfer)", "bank_transfer": "Bank transfer", "cash": "Cash",
                 "pos": "POS", "ussd": "USSD", "other": "Other"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _br(value: Any) -> str:
    return _e(value).replace("\n", "<br>")


def money(value: Any, currency: str = "NGN") -> str:
    try:
        amount = f"{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        amount = "0.00"
    return f"₦{amount}" if (currency or "NGN") == "NGN" else f"{_e(currency)} {amount}"


def _qty(value: Any) -> str:
    try:
        f = float(value)
        return f"{f:,.0f}" if f == int(f) else f"{f:,.2f}".rstrip("0")
    except (TypeError, ValueError):
        return _e(value)


def _nice_date(value: Any) -> str:
    try:
        d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        return d.strftime("%d %b %Y")
    except (TypeError, ValueError):
        return ""


def _storage_prefix() -> str:
    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    return f"{base}/storage/v1/object/public/" if base else ""


def _logo_allowed(url: Optional[str]) -> bool:
    prefix = _storage_prefix()
    return bool(url and prefix and url.startswith(prefix) and ".." not in url)


def _safe_fetcher(url: str, *args, **kwargs):
    if not _logo_allowed(url):
        raise ValueError("blocked url")
    from weasyprint import default_url_fetcher
    return default_url_fetcher(url, *args, timeout=5, **kwargs)


def _issuer(doc: dict, settings: dict) -> dict:
    return doc.get("issuer") or settings or {}


def build_html(doc: dict, settings: dict, kind: str) -> str:
    iss = _issuer(doc, settings)
    colour = iss.get("brand_colour") if _HEX.match(str(iss.get("brand_colour") or "")) else "#0d9488"
    cur = doc.get("currency") or "NGN"
    draft = kind != "receipt" and doc.get("status") == "draft"
    voided = doc.get("status") == "void" or bool(doc.get("voided_at"))

    logo = f'<img class="logo" src="{_e(iss.get("logo_url"))}">' if _logo_allowed(iss.get("logo_url")) else ""
    biz_lines = [f'<div class="biz-name">{_e(iss.get("business_name") or "")}</div>']
    for k in ("address", "phone", "email"):
        if iss.get(k):
            biz_lines.append(f"<div>{_br(iss.get(k))}</div>")
    ids = []
    if iss.get("rc_number"):
        rc = str(iss["rc_number"]).strip()
        ids.append(_e(rc) if rc.upper().startswith(("RC", "BN")) else f"RC {_e(rc)}")
    if iss.get("tin"):
        ids.append(f"TIN {_e(iss['tin'])}")
    if ids:
        biz_lines.append(f"<div>{' &middot; '.join(ids)}</div>")

    number = doc.get("number") or ("DRAFT" if draft else "")
    meta = [("Number", _e(number))]
    if kind == "receipt":
        meta.append(("Date paid", _nice_date(doc.get("paid_at"))))
        meta.append(("Method", _e(METHOD_LABELS.get(doc.get("method"), doc.get("method") or ""))))
        if doc.get("reference"):
            meta.append(("Reference", _e(doc.get("reference"))))
        if doc.get("invoice_number"):
            meta.append(("For invoice", _e(doc.get("invoice_number"))))
    else:
        meta.append(("Date", _nice_date(doc.get("issue_date")) or "—"))
        meta.append(("Valid until" if kind == "quote" else "Due date", _nice_date(doc.get("due_date")) or "—"))
    meta_html = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in meta)

    bill = [f'<div class="label">{"Received from" if kind == "receipt" else "Bill to"}</div>',
            f'<div class="cust">{_e(doc.get("customer_name") or "")}</div>']
    for k in ("customer_phone", "customer_email", "customer_address"):
        if doc.get(k):
            bill.append(f"<div>{_br(doc.get(k))}</div>")

    if kind == "receipt":
        body = (f'<table class="items"><thead><tr><th>Description</th><th class="r">Amount</th></tr></thead><tbody>'
                f'<tr><td>{_e(doc.get("description") or "Payment received")}</td>'
                f'<td class="r">{money(doc.get("amount"), cur)}</td></tr></tbody></table>'
                f'<table class="totals"><tr class="grand"><th>Amount paid</th><td>{money(doc.get("amount"), cur)}</td></tr>')
        if doc.get("invoice_balance") is not None:
            body += f'<tr><th>Balance still due</th><td>{money(doc.get("invoice_balance"), cur)}</td></tr>'
        body += "</table>"
    else:
        rows = "".join(
            f'<tr><td>{_e(it.get("description"))}</td><td class="r">{_qty(it.get("quantity"))}</td>'
            f'<td class="r">{money(it.get("unit_price"), cur)}</td><td class="r">{money(it.get("line_total"), cur)}</td></tr>'
            for it in (doc.get("items") or []))
        tot = [("Subtotal", money(doc.get("subtotal"), cur))]
        if float(doc.get("discount") or 0):
            tot.append(("Discount", "-" + money(doc.get("discount"), cur)))
        if float(doc.get("vat_amount") or 0):
            tot.append((f"VAT ({_qty(doc.get('vat_rate'))}%)", money(doc.get("vat_amount"), cur)))
        tot_html = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in tot)
        tot_html += f'<tr class="grand"><th>Total</th><td>{money(doc.get("total"), cur)}</td></tr>'
        if kind == "invoice" and float(doc.get("amount_paid") or 0):
            tot_html += f'<tr><th>Paid</th><td>{money(doc.get("amount_paid"), cur)}</td></tr>'
            tot_html += f'<tr class="grand"><th>Balance due</th><td>{money(doc.get("balance_due"), cur)}</td></tr>'
        body = (f'<table class="items"><thead><tr><th>Description</th><th class="r">Qty</th><th class="r">Unit price</th>'
                f'<th class="r">Amount</th></tr></thead><tbody>{rows}</tbody></table>'
                f'<table class="totals">{tot_html}</table>')

    extra = []
    if kind == "invoice" and iss.get("account_number"):
        extra.append('<div class="box"><div class="label">Pay by bank transfer</div>'
                     f'<div>{_e(iss.get("bank_name") or "")}</div>'
                     f'<div class="acct">{_e(iss.get("account_number"))}</div>'
                     f'<div>{_e(iss.get("account_name") or "")}</div></div>')
    if kind != "receipt" and doc.get("notes"):
        extra.append(f'<div class="box"><div class="label">Notes</div><div>{_br(doc.get("notes"))}</div></div>')
    if kind != "receipt" and doc.get("terms"):
        extra.append(f'<div class="box"><div class="label">Terms</div><div>{_br(doc.get("terms"))}</div></div>')
    if kind == "receipt":
        extra.append('<div class="thanks">Thank you for your payment.</div>')

    stamp = '<div class="stamp">VOID</div>' if voided else ('<div class="stamp">DRAFT</div>' if draft else "")
    footer = _e(iss.get("footer") or "")

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 18mm 16mm 20mm 16mm;
  @bottom-center {{ content: "{footer}"; font-family: 'Helvetica', 'Arial', 'DejaVu Sans', sans-serif;
    font-size: 8pt; color: #888; }} }}
body {{ font-family: 'Helvetica', 'Arial', 'DejaVu Sans', sans-serif; color: #1a1a1a; font-size: 10pt; }}
.top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
.logo {{ max-height: 60px; max-width: 180px; margin-bottom: 6px; }}
.biz-name {{ font-size: 13pt; font-weight: bold; }}
.title {{ font-size: 22pt; font-weight: bold; color: {colour}; text-align: right; letter-spacing: 1px; }}
.meta {{ margin-top: 6px; margin-left: auto; border-collapse: collapse; }}
.meta th {{ text-align: left; color: #666; font-weight: normal; padding: 1px 10px 1px 0; }}
.meta td {{ text-align: right; font-weight: bold; }}
.label {{ font-size: 8pt; text-transform: uppercase; color: #888; letter-spacing: .5px; margin-bottom: 3px; }}
.bill {{ margin: 22px 0 14px; }}
.cust {{ font-size: 12pt; font-weight: bold; }}
table.items {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
table.items th {{ background: {colour}; color: #fff; text-align: left; padding: 7px 8px; font-size: 9pt; }}
table.items td {{ padding: 7px 8px; border-bottom: 1px solid #e5e5e5; vertical-align: top; }}
.r {{ text-align: right !important; white-space: nowrap; }}
table.totals {{ margin: 10px 0 0 auto; border-collapse: collapse; min-width: 45%; }}
table.totals th {{ text-align: left; font-weight: normal; color: #555; padding: 4px 8px; }}
table.totals td {{ text-align: right; padding: 4px 8px; white-space: nowrap; }}
table.totals tr.grand th, table.totals tr.grand td {{ font-weight: bold; font-size: 12pt; border-top: 2px solid {colour}; }}
.box {{ margin-top: 18px; padding: 10px 12px; background: #f7f7f7; border-radius: 4px; }}
.acct {{ font-size: 13pt; font-weight: bold; letter-spacing: 1px; }}
.thanks {{ margin-top: 24px; font-size: 12pt; color: {colour}; font-weight: bold; }}
.stamp {{ position: fixed; top: 40%; left: 18%; font-size: 90pt; color: rgba(200,0,0,.12); transform: rotate(-30deg);
  font-weight: bold; letter-spacing: 8px; }}
</style></head><body>
{stamp}
<div class="top"><div>{logo}{''.join(biz_lines)}</div>
<div><div class="title">{TITLES.get(kind, '')}</div><table class="meta">{meta_html}</table></div></div>
<div class="bill">{''.join(bill)}</div>
{body}
{''.join(extra)}
</body></html>"""


def filename(doc: dict, kind: str) -> str:
    raw = doc.get("number") or f"draft-{str(doc.get('id', ''))[:8]}"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", str(raw)).strip("-") or kind
    return f"{TITLES.get(kind, kind).title()}-{safe}.pdf"


def render(doc: dict, settings: dict, kind: str) -> tuple[Optional[bytes], str]:
    name = filename(doc, kind)
    try:
        from weasyprint import HTML
        return HTML(string=build_html(doc, settings, kind), url_fetcher=_safe_fetcher).write_pdf(), name
    except Exception as exc:  # S14
        logger.error("invoice_pdf_service.render failed kind=%s doc=%s: %s", kind, doc.get("id"), exc)
        return None, name
