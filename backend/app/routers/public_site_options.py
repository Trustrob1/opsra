"""
app/routers/public_site_options.py
------------------------------------
SITE-OPTIONS OPT-1 - the client's page for choosing between the designs made for them. No login: the long random
link is the only credential (like a payment link). Script-free, noindex, no-store, every value escaped, neutral
branding (the builder's business name only).

  GET  /o/{token}          the designs, each with "View full design" (opens the preview) and "Choose this one"
  POST /o/{token}/choose   first call shows "Confirm your choice"; the confirm call records it

Unknown, expired or closed links get a plain page. Nothing here reveals ids other than the option's own id.
"""
from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.database import get_supabase
from app.services import site_capture_service as cap
from app.services import site_option_service as opt

logger = logging.getLogger(__name__)
router = APIRouter()

_VIEW_PER_IP_PER_HOUR = 120
_CHOOSE_PER_IP_PER_HOUR = 30
_CHOOSE_PER_TOKEN_PER_HOUR = 60


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _doc(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#111;--mut:#555;--line:#e5e7eb;--acc:#028090;--accd:#015f6b;--ok:#0a7a3d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--card:#1c1c1c;--ink:#eee;--mut:#aaa;--line:#333;--acc:#3fb8c4;--accd:#7fd8e3;--ok:#59d68b}}}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink);padding:16px}}
main{{max-width:760px;margin:0 auto}}
h1{{font-size:22px;margin:8px 0 6px}} p{{line-height:1.5;color:var(--mut);margin:0 0 14px}}
.grid{{display:grid;gap:14px;margin-top:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}}
.card.sel{{border-color:var(--ok);box-shadow:0 0 0 2px var(--ok) inset}}
.lab{{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--acc);font-weight:700}}
.name{{font-size:18px;font-weight:700;margin:4px 0}} .hl{{color:var(--mut);margin:0 0 12px}}
.row{{display:flex;flex-wrap:wrap;gap:10px}}
a.btn,button{{font:inherit;font-weight:600;border-radius:10px;padding:12px 16px;min-height:44px;text-decoration:none;cursor:pointer;border:1px solid var(--acc);display:inline-flex;align-items:center}}
a.btn{{color:var(--acc);background:transparent}} button{{color:#fff;background:var(--acc)}}
button:hover{{background:var(--accd)}} a.btn:focus-visible,button:focus-visible{{outline:3px solid var(--accd);outline-offset:2px}}
.pill{{display:inline-block;background:var(--ok);color:#fff;border-radius:999px;padding:4px 10px;font-size:13px;font-weight:600}}
.note{{font-size:13px}}
</style></head><body><main>{body}</main></body></html>"""
    return HTMLResponse(content=page, status_code=status_code, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"})


def _not_valid() -> HTMLResponse:
    return _doc("Link not valid", "<h1>This link isn't valid</h1><p>Please ask the person who sent it to you for a new link.</p>", 404)


def _limit(request: Request, token: str, kind: str) -> None:
    ip = _ip(request)
    over = (cap.rate_limited(f"opt-view-ip:{ip}", _VIEW_PER_IP_PER_HOUR) if kind == "view" else
            (cap.rate_limited(f"opt-choose-ip:{ip}", _CHOOSE_PER_IP_PER_HOUR) or
             cap.rate_limited(f"opt-choose-tok:{token[:16]}", _CHOOSE_PER_TOKEN_PER_HOUR)))
    if over:
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many requests"})


def _e(v) -> str:
    return html.escape(str(v or ""), quote=True)


def _heading(v: dict) -> str:
    who = _e(v.get("builder_name")) or "Your web designer"
    name = f" for {_e(v['client_name'])}" if v.get("client_name") else ""
    return f"<h1>Choose your website design{name}</h1><p>{who} has prepared the designs below. Open each one, then choose the one you like best.</p>"


def _cards(token: str, v: dict) -> str:
    out = ['<div class="grid">']
    for i in v["items"]:
        sel = i["chosen"]
        view = (f'<a class="btn" href="{_e(i["preview_url"])}" target="_blank" rel="noopener noreferrer">View full design</a>'
                if i.get("preview_url") else "")
        choose = ""
        if v["can_choose"] and not sel:
            choose = (f'<form method="post" action="/o/{_e(token)}/choose"><input type="hidden" name="item_id" value="{_e(i["id"])}">'
                      f'<button type="submit">Choose this one</button></form>')
        pill = '<span class="pill">Your choice</span>' if sel else ""
        out.append(f'<section class="card{" sel" if sel else ""}"><div class="lab">{_e(i["label"])}</div>'
                   f'<div class="name">{_e(i["business_name"]) or "Your website"}</div>'
                   f'<p class="hl">{_e(i["headline"])}</p><div class="row">{view}{choose}{pill}</div></section>')
    out.append("</div>")
    return "".join(out)


@router.get("/o/{token}", include_in_schema=False)
def options_page(token: str, request: Request, db=Depends(get_supabase)):
    _limit(request, token, "view")
    try:
        v = opt.public_view(db, token)
    except Exception:  # S14
        logger.exception("[SITE-OPTIONS] view failed")
        return _doc("Try again", "<h1>Something went wrong</h1><p>Please try again in a minute.</p>", 503)
    if not v:
        return _not_valid()
    if v["expired"] or v["status"] in ("expired",):
        return _doc("Link expired", "<h1>This link has expired</h1><p>Please ask for a new link.</p>", 410)
    if not v["items"]:
        return _doc("Nothing to show yet", "<h1>No designs yet</h1><p>Your designer is still preparing them. Please check back soon.</p>")
    note = ""
    if v["paid"]:
        note = '<p class="note">Thank you. Your choice is confirmed and payment is received.</p>'
    elif v["chosen_site_id"] and v["can_choose"]:
        note = ('<p class="note">Your choice has been sent to your designer. You can still change it, '
                'until payment is made.</p>')
    elif v["status"] == "closed":
        note = '<p class="note">This choice is now closed.</p>'
    return _doc("Choose your website design", _heading(v) + note + _cards(token, v))


@router.post("/o/{token}/choose", include_in_schema=False)
def options_choose(token: str, request: Request, db=Depends(get_supabase),
                   item_id: str = Form(""), confirm: str = Form("")):
    _limit(request, token, "choose")
    try:
        v = opt.public_view(db, token)
        if not v:
            return _not_valid()
        item = next((i for i in v["items"] if i["id"] == item_id), None)
        if not item or not v["can_choose"]:
            return _doc("Not available", f'<h1>This choice is closed</h1><p>Please contact {_e(v.get("builder_name")) or "your designer"}.</p>', 409)
        if confirm != "1":
            return _doc("Confirm your choice",
                        f'<h1>Confirm your choice</h1><p>You are choosing <strong>{_e(item["label"])}</strong>'
                        f'{" ("+_e(item["business_name"])+")" if item.get("business_name") else ""}. '
                        'You can still change your mind later, until payment is made.</p>'
                        f'<form method="post" action="/o/{_e(token)}/choose"><input type="hidden" name="item_id" value="{_e(item_id)}">'
                        '<input type="hidden" name="confirm" value="1"><div class="row"><button type="submit">Yes, choose this design</button>'
                        f'<a class="btn" href="/o/{_e(token)}">Go back</a></div></form>')
        r = opt.choose_by_token(db, token, item_id)
    except opt.OptionNotFound:
        return _not_valid()
    except opt.OptionError as exc:
        return _doc("Not available", f"<h1>We couldn't save your choice</h1><p>{_e(exc)}</p>"
                    f'<p><a class="btn" href="/o/{_e(token)}">Back to the designs</a></p>', 409)
    except Exception:  # S14
        logger.exception("[SITE-OPTIONS] choose failed")
        return _doc("Try again", "<h1>Something went wrong</h1><p>We couldn't save your choice just now. Please try again in a minute.</p>", 503)
    return _doc("Thank you", f'<h1>Thank you</h1><p>You chose <strong>{_e(r["label"])}</strong>. '
                'Your designer has been told and will send you the next step (the payment link) shortly.</p>'
                f'<p><a class="btn" href="/o/{_e(token)}">See the designs</a></p>')
