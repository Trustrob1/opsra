"""
app/routers/public_site_pay.py
--------------------------------
SITE-ADDONS A0-2 - the private pay page a CLIENT opens to pay for their site's tier or add-on. No login: the token in the
link is the only credential (it is stored hashed, like the brief-form links). Prefix: "" (served at the API origin like
GET /f/{token} and GET /s/{slug}).

  GET /site-pay/{token}      a plain, script-free page: what the plan includes, the price and a Pay button
  GET /site-pay/{token}/go   makes (or reuses) the Paystack link and redirects to it

Unknown, cancelled or malformed tokens all get the same "link isn't valid" page. The price shown is read from Settings on
the server; nothing in the URL can change an amount.
"""
from __future__ import annotations

import html
import logging
import time
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_supabase
from app.services import site_addon_billing_service as billing
from app.services import site_entitlement_service as ent

logger = logging.getLogger(__name__)
router = APIRouter()

_rate_store: dict[str, list[float]] = {}
_RATE_LIMIT = 30
_RATE_WINDOW = 60.0
LAGOS = timezone(timedelta(hours=1))


def _check_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    calls = [t for t in _rate_store.get(ip, []) if t > now - _RATE_WINDOW]
    if len(calls) >= _RATE_LIMIT:
        _rate_store[ip] = calls
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many requests"})
    calls.append(now)
    _rate_store[ip] = calls
    if len(_rate_store) > 10_000:
        _rate_store.clear()


def _page(title: str, body_html: str, status_code: int = 200) -> HTMLResponse:
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)}</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7f9;color:#111;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px;box-sizing:border-box}}
.card{{background:#fff;max-width:440px;width:100%;border-radius:14px;padding:28px;box-shadow:0 2px 12px rgba(0,0,0,.06)}}
h1{{font-size:20px;margin:0 0 6px}} p{{line-height:1.5;color:#444;margin:0 0 14px}}
ul{{margin:0 0 16px;padding-left:20px;color:#333;line-height:1.6}}
.row{{display:flex;justify-content:space-between;color:#333;padding:4px 0}} .tot{{font-weight:700;border-top:1px solid #e5e7eb;margin-top:6px;padding-top:10px}}
a.btn{{display:block;text-align:center;background:#028090;color:#fff;text-decoration:none;padding:14px 20px;border-radius:10px;font-weight:600;margin-top:18px}}
.small{{font-size:13px;color:#666}}
@media (prefers-color-scheme:dark){{body{{background:#111;color:#eee}}.card{{background:#1c1c1c}}p,.row,ul{{color:#bbb}}.tot{{border-color:#333}}.small{{color:#999}}}}
</style></head><body><div class="card">{body_html}</div></body></html>"""
    return HTMLResponse(content=doc, status_code=status_code,
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _money(n) -> str:
    return f"₦{float(n):,.0f}"


def _date(value) -> str:
    dt = ent._parse(value)
    return dt.astimezone(LAGOS).strftime("%d %b %Y") if dt else ""


def _not_valid() -> HTMLResponse:
    return _page("Link not valid", "<h1>This link isn't valid</h1><p>Please ask the person who sent it to you "
                 "for a fresh payment link.</p>", 404)


@router.get("/site-pay/{token}", include_in_schema=False)
def site_pay_page(token: str, request: Request, db=Depends(get_supabase)):
    _check_rate_limit(request)
    try:
        code = (request.query_params.get("code") or "").strip()[:40]
        v = billing.pay_view(db, token, code=code or None)
    except Exception:  # S14
        logger.exception("[SITE-PAY] view failed")
        return _page("Try again", "<h1>Something went wrong</h1><p>We couldn't open this page right now. "
                     "Please try again in a minute.</p>", 503)
    if v is None:
        return _not_valid()
    biz = html.escape(v.get("business") or "your business")
    if v["state"] == "unavailable":
        return _page("Not available", f"<h1>Not available right now</h1><p>This plan for {biz} can't be paid for at the "
                     "moment. Please contact the person who sent you this link.</p>")
    label = html.escape(v["label"])
    items = "".join(f"<li>{html.escape(x)}</li>" for x in v["includes"])
    includes = f"<p class=\"small\">Includes:</p><ul>{items}</ul>" if items else ""
    if v["state"] == "paid_up":
        return _page("All paid up", f"<h1>{label} is active ✅</h1><p>{biz} is paid up until "
                     f"<strong>{html.escape(_date(v['paid_until']))}</strong>. You will be able to renew a few days before "
                     f"then.</p>{includes}")
    lines = [f"<div class=\"row\"><span>{label} for {v['days']} days</span><span>{_money(v['price'])}</span></div>"]
    if v["setup_fee"]:
        lines.append(f"<div class=\"row\"><span>One-time set-up</span><span>{_money(v['setup_fee'])}</span></div>")
    if v["credit"]:
        lines.append(f"<div class=\"row\"><span>Credit for unused days</span><span>−{_money(v['credit'])}</span></div>")
    if v.get("discount"):
        lines.append(f"<div class=\"row\"><span>Code {html.escape(v['discount']['code'])}</span>"
                     f"<span>−{_money(v['discount']['discount'])}</span></div>")
    lines.append(f"<div class=\"row tot\"><span>To pay now</span><span>{_money(v['amount_due'])}</span></div>")
    applied = v["discount"]["code"] if v.get("discount") else ""
    err = f"<p class=\"small\" style=\"color:#b3261e\">{html.escape(v['discount_error'])}</p>" if v.get("discount_error") else ""
    codebox = ("" if v["kind"] != "new" else
               f"<form method=\"get\" action=\"/site-pay/{html.escape(token, quote=True)}\" style=\"margin-top:14px\">"
               f"<label class=\"small\" for=\"code\">Have a discount code?</label>"
               f"<div style=\"display:flex;gap:8px;margin-top:6px\"><input id=\"code\" name=\"code\" maxlength=\"40\" autocomplete=\"off\" "
               f"value=\"{html.escape(applied or code, quote=True)}\" style=\"flex:1;min-height:44px;padding:0 12px;font:inherit;border:1px solid #c9d6de;border-radius:8px;box-sizing:border-box\">"
               f"<button type=\"submit\" style=\"min-height:44px;padding:0 16px;font:inherit;font-weight:600;border:1px solid #028090;background:#fff;color:#028090;border-radius:8px;cursor:pointer\">Apply</button></div>{err}</form>")
    go = f"/site-pay/{html.escape(token, quote=True)}/go" + (f"?code={html.escape(quote(applied), quote=True)}" if applied else "")
    verb = {"upgrade": "Upgrade to", "renewal": "Renew"}.get(v["kind"], "Start")
    return _page(f"Pay for {v['label']}",
                 f"<h1>{verb} {label}</h1><p>For {biz}.</p>{includes}{''.join(lines)}{codebox}"
                 f"<a class=\"btn\" href=\"{go}\">Pay {_money(v['amount_due'])} securely</a>"
                 "<p class=\"small\" style=\"margin-top:14px\">You will pay on Paystack. Your plan starts as soon as the "
                 "payment is confirmed.</p>")


@router.get("/site-pay/{token}/go", include_in_schema=False)
def site_pay_go(token: str, request: Request, db=Depends(get_supabase)):
    _check_rate_limit(request)
    try:
        r = billing.pay_checkout(db, token, code=(request.query_params.get("code") or "").strip()[:40] or None)
    except ent.EntitlementError as exc:
        return _page("Can't pay yet", f"<h1>We can't open the payment page</h1><p>{html.escape(str(exc))}</p>", 422)
    except Exception:  # S14
        logger.exception("[SITE-PAY] checkout failed")
        return _page("Try again", "<h1>Something went wrong</h1><p>We couldn't open the payment page right now. "
                     "Please try again in a minute.</p>", 503)
    if r is None:
        return _not_valid()
    url = r.get("checkout_url") or ""
    if not url.startswith("https://"):
        return _page("Try again", "<h1>Something went wrong</h1><p>Please try again in a minute.</p>", 503)
    return RedirectResponse(url=url, status_code=302, headers={"Cache-Control": "no-store"})
