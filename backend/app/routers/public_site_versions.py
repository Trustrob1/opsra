"""
app/routers/public_site_versions.py
-------------------------------------
SITE-OPTIONS OPT-3 - the client's page for choosing between VERSIONS of their own website. No login: the long random
link is the only credential. Script-free list page (same look as /o/{token}); each version opens in its own tab as the
real page. Every value escaped, noindex, no-store.

  GET  /v/{token}                  the versions, each with "View full design" and "Choose this one"
  GET  /v/{token}/view/{item_id}   one version as a full page (the site's normal preview rules)
  POST /v/{token}/choose           first call shows "Confirm your choice"; the confirm call records it
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.database import get_supabase
from app.routers.public_site_options import _doc, _e, _limit, _not_valid
from app.routers.public_sites import _preview_headers
from app.services import site_option_service as opt
from app.services import site_version_share_service as ver

logger = logging.getLogger(__name__)
router = APIRouter()


def _heading(v: dict) -> str:
    who = _e(v.get("builder_name")) or "Your web designer"
    name = f" for {_e(v['client_name'])}" if v.get("client_name") else ""
    biz = f" The versions below are different looks for {_e(v['business_name'])}." if v.get("business_name") else ""
    return (f"<h1>Choose your website design{name}</h1>"
            f"<p>{who} has prepared the versions below.{biz} Open each one, then choose the one you like best.</p>")


def _cards(token: str, v: dict) -> str:
    out = ['<div class="grid">']
    for i in v["items"]:
        sel = i["chosen"]
        view = (f'<a class="btn" href="/v/{_e(token)}/view/{_e(i["id"])}" target="_blank" rel="noopener noreferrer">View full design</a>')
        choose = ""
        if v["can_choose"] and not sel:
            choose = (f'<form method="post" action="/v/{_e(token)}/choose"><input type="hidden" name="item_id" value="{_e(i["id"])}">'
                      f'<button type="submit">Choose this one</button></form>')
        pill = '<span class="pill">Your choice</span>' if sel else ""
        cost = f'<div style="font-size:20px;font-weight:700;margin-top:6px">₦{int(i["price"]):,}</div>' if i.get("price") else ""
        out.append(f'<section class="card{" sel" if sel else ""}"><div class="lab">{_e(i["label"])}</div>{cost}'
                   f'<div class="row" style="margin-top:12px">{view}{choose}{pill}</div></section>')
    out.append("</div>")
    return "".join(out)


@router.get("/v/{token}", include_in_schema=False)
def versions_page(token: str, request: Request, db=Depends(get_supabase)):
    _limit(request, token, "view")
    try:
        v = ver.public_view(db, token)
    except Exception:  # S14
        logger.exception("[SITE-VERSIONS] view failed")
        return _doc("Try again", "<h1>Something went wrong</h1><p>Please try again in a minute.</p>", 503)
    if not v:
        return _not_valid()
    if v["expired"]:
        return _doc("Link expired", "<h1>This link has expired</h1><p>Please ask for a new link.</p>", 410)
    if v["status"] == "closed" and not v["paid"]:
        return _doc("Closed", "<h1>This choice is closed</h1><p>Please contact your designer.</p>", 410)
    if not v["items"]:
        return _doc("Nothing to show yet", "<h1>No versions yet</h1><p>Your designer is still preparing them. Please check back soon.</p>")
    note = ""
    if v["paid"]:
        note = '<p class="note">Thank you. Your choice is confirmed and payment is received.</p>'
    elif v["chosen_design_id"] and v["can_choose"]:
        note = ('<p class="note">Your choice has been sent to your designer. You can still change it, '
                'until payment is made.</p>')
    return _doc("Choose your website design", _heading(v) + note + _cards(token, v))


@router.get("/v/{token}/view/{item_id}", include_in_schema=False)
def version_page(token: str, item_id: str, request: Request, db=Depends(get_supabase)):
    _limit(request, token, "view")
    try:
        html = ver.render_version(db, token, item_id)
    except opt.OptionNotFound:
        return _not_valid()
    except Exception:  # S14
        logger.exception("[SITE-VERSIONS] render failed")
        raise HTTPException(status_code=503, detail="This version couldn't be shown right now")
    headers = ver.preview_headers_for(db, token) or _preview_headers()      # an uploaded site's scripts run, sandboxed
    return HTMLResponse(content=html, status_code=200, headers=headers)


@router.post("/v/{token}/choose", include_in_schema=False)
def versions_choose(token: str, request: Request, db=Depends(get_supabase),
                    item_id: str = Form(""), confirm: str = Form("")):
    _limit(request, token, "choose")
    try:
        v = ver.public_view(db, token)
        if not v:
            return _not_valid()
        item = next((i for i in v["items"] if i["id"] == item_id), None)
        if not item or not v["can_choose"]:
            return _doc("Not available", f'<h1>This choice is closed</h1><p>Please contact {_e(v.get("builder_name")) or "your designer"}.</p>', 409)
        if confirm != "1":
            return _doc("Confirm your choice",
                        f'<h1>Confirm your choice</h1><p>You are choosing <strong>{_e(item["label"])}</strong>{(" at ₦" + format(int(item["price"]), ",")) if item.get("price") else ""}. '
                        'You can still change your mind later, until payment is made.</p>'
                        f'<form method="post" action="/v/{_e(token)}/choose"><input type="hidden" name="item_id" value="{_e(item_id)}">'
                        '<input type="hidden" name="confirm" value="1"><div class="row"><button type="submit">Yes, choose this design</button>'
                        f'<a class="btn" href="/v/{_e(token)}">Go back</a></div></form>')
        r = ver.choose_by_token(db, token, item_id)
    except opt.OptionNotFound:
        return _not_valid()
    except opt.OptionError as exc:
        return _doc("Not available", f"<h1>We couldn't save your choice</h1><p>{_e(exc)}</p>"
                    f'<p><a class="btn" href="/v/{_e(token)}">Back to the versions</a></p>', 409)
    except Exception:  # S14
        logger.exception("[SITE-VERSIONS] choose failed")
        return _doc("Try again", "<h1>Something went wrong</h1><p>We couldn't save your choice just now. Please try again in a minute.</p>", 503)
    return _doc("Thank you", f'<h1>Thank you</h1><p>You chose <strong>{_e(r["label"])}</strong>. '
                'Your designer has been told and will send you the next step (the payment link) shortly.</p>'
                f'<p><a class="btn" href="/v/{_e(token)}">See the versions</a></p>')
