"""
app/routers/public_funnels.py
------------------------------
FUNNEL-1A — public pay link for Event Funnel leads. NO auth dependency.

  GET /f/{token}            → 302 to a Paystack checkout at the price valid NOW
  GET /f/{token}?seats=3    → group deal (only if the funnel's group_size matches)

Security:
  • token = 192-bit random, per registration; the only thing it can do is start a payment.
  • Never returns org_id, lead data or prices in JSON — only a redirect or a fixed HTML page.
  • All page text HTML-escaped. Rate limit 30 req/min per IP (in-process, same
    pattern as public_catalog.py).
  • Register in main.py with prefix="" (like public_catalog_og).
"""
from __future__ import annotations

import html
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_supabase
from app.services import funnel_service

logger = logging.getLogger(__name__)
router = APIRouter()

_rate_store: dict[str, list[float]] = {}
_RATE_LIMIT = 30
_RATE_WINDOW = 60.0


def _check_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    calls = [t for t in _rate_store.get(ip, []) if t > now - _RATE_WINDOW]
    if len(calls) >= _RATE_LIMIT:
        _rate_store[ip] = calls
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many requests"})
    calls.append(now)
    _rate_store[ip] = calls
    if len(_rate_store) > 10_000:  # bound memory
        _rate_store.clear()


def _page(title: str, body_html: str, status_code: int = 200) -> HTMLResponse:
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)}</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7f9;color:#111;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px}}
.card{{background:#fff;max-width:420px;width:100%;border-radius:14px;padding:28px;box-shadow:0 2px 12px rgba(0,0,0,.06);text-align:center}}
h1{{font-size:20px;margin:0 0 10px}} p{{line-height:1.5;color:#444;margin:0 0 14px}}
a.btn{{display:inline-block;background:#25D366;color:#fff;text-decoration:none;padding:12px 20px;border-radius:10px;font-weight:600}}
@media (prefers-color-scheme:dark){{body{{background:#111;color:#eee}}.card{{background:#1c1c1c}}p{{color:#bbb}}}}
</style></head><body><div class="card">{body_html}</div></body></html>"""
    return HTMLResponse(content=doc, status_code=status_code,
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    # CSP / nosniff come from the global security-headers middleware in main.py
    # (style-src allows 'unsafe-inline'; no scripts on these pages).


@router.get("/f/{token}", include_in_schema=False)
def funnel_pay_link(
    token: str,
    request: Request,
    seats: int = Query(1, ge=1, le=20),
    db=Depends(get_supabase),
):
    _check_rate_limit(request)
    result = funnel_service.get_pay_redirect(db, token, seats=seats)
    event = html.escape(result.event or "the class")

    if result.kind == "redirect" and result.url and result.url.startswith("https://"):
        return RedirectResponse(url=result.url, status_code=302, headers={"Cache-Control": "no-store"})
    if result.kind == "closed":
        return _page("Registration closed", f"<h1>Registration has closed</h1><p>Registration for {event} "
                     "has closed. Thank you for your interest 🙏</p>")
    if result.kind == "already_paid":
        link = result.group_link or ""
        btn = (f'<a class="btn" href="{html.escape(link, quote=True)}">Open the class group</a>'
               if link.startswith("https://") else "")
        return _page("You're registered", f"<h1>You're already registered ✅</h1><p>Your seat for {event} "
                     f"is confirmed.</p>{btn}")
    if result.kind == "not_found":
        return _page("Link not found", "<h1>This link isn't valid</h1><p>Please message us on WhatsApp "
                     "and we'll send you a fresh payment link.</p>", 404)
    return _page("Try again", "<h1>Something went wrong</h1><p>We couldn't open the payment page right now. "
                 "Please try again in a minute, or message us on WhatsApp.</p>", 503)
