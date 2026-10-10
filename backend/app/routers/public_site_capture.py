"""
app/routers/public_site_capture.py
------------------------------------
SITE-ADDONS A1-1 - what a client's website talks to. No login: the site KEY in the address is the only credential, and it
only opens the capture features that site's plan includes.

  POST /api/v1/public/site-leads/{key}   the enquiry form (a plain HTML form post, no script, no CORS needed)
  GET  /sl/{key}/wa                      tracked WhatsApp link: logs the click, redirects to the site's own wa.me address
  GET  /sl/{key}/l/{lead_id}              the owner's "Answer now" link: marks the lead answered, opens WhatsApp to the visitor

Unknown or switched-off keys all get the same "not valid" page. Nothing here returns lead data.
"""
from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_supabase
from app.routers.public_site_pay import _page
from app.services import site_capture_service as cap

logger = logging.getLogger(__name__)
router = APIRouter()


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _limit(request: Request, key: str, kind: str = "form") -> None:
    """Forms are limited tightly (spam); the WhatsApp and Answer-now links only against floods."""
    ip = _ip(request)
    ip_cap, key_cap = ((cap.SUBMIT_PER_IP_PER_HOUR, cap.SUBMIT_PER_KEY_PER_HOUR) if kind == "form"
                       else (cap.LINK_PER_IP_PER_HOUR, cap.LINK_PER_KEY_PER_HOUR))
    if cap.rate_limited(f"{kind}-ip:{ip}", ip_cap) or cap.rate_limited(f"{kind}-key:{key}", key_cap):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many requests"})


def _not_valid() -> HTMLResponse:
    return _page("Link not valid", "<h1>This link isn't valid</h1><p>Please contact the business directly.</p>", 404)


def _back(url) -> str:
    return f'<p><a href="{html.escape(url, quote=True)}">Back to the website</a></p>' if url else ""


@router.post("/api/v1/public/site-leads/{key}", include_in_schema=False)
def site_lead_form(
    key: str, request: Request, db=Depends(get_supabase),
    name: str = Form(""), phone: str = Form(""), email: str = Form(""), message: str = Form(""),
    consent: str = Form(""), src: str = Form(""), return_to: str = Form(""), website: str = Form(""),
):
    _limit(request, key)
    try:
        r = cap.submit(db, key, {"name": name, "phone": phone, "email": email, "message": message,
                                 "consent": consent.strip().lower() in ("on", "1", "true", "yes")},
                       ip=_ip(request), src=src, return_to=return_to, honeypot=website)
    except cap.CaptureError as exc:
        return _page("Please check your details",
                     f"<h1>Please check your details</h1><p>{html.escape(str(exc))}</p>"
                     "<p>Go back, fix it and send again.</p>", 422)
    except Exception:  # S14
        logger.exception("[SITE-CAPTURE] submit failed")
        return _page("Try again", "<h1>Something went wrong</h1><p>We couldn't send your message just now. "
                     "Please try again in a minute or message the business on WhatsApp.</p>", 503)
    if r["status"] == "unknown":
        return _not_valid()
    biz = html.escape(r.get("business") or "the business")
    if r["status"] == "off":
        wa = (f'<p><a href="{html.escape(r["wa_url"], quote=True)}">Message {biz} on WhatsApp</a></p>' if r.get("wa_url") else "")
        return _page("Not available", f"<h1>This form is not available right now</h1><p>Please contact {biz} directly.</p>"
                     f"{wa}{_back(r.get('back_url'))}")
    return _page("Message sent", f"<h1>Thank you</h1><p>Your message has been sent to {biz}. They will get back to you soon.</p>"
                 f"{_back(r.get('back_url'))}")


@router.get("/sl/{key}/wa", include_in_schema=False)
def tracked_whatsapp(key: str, request: Request, src: str = Query("", max_length=120), t: str = Query("", max_length=300),
                     db=Depends(get_supabase)):
    _limit(request, key, "link")
    try:
        url = cap.wa_redirect(db, key, src, t, ip=_ip(request))
    except Exception:  # S14: a logging problem must not strand a visitor
        logger.exception("[SITE-CAPTURE] wa redirect failed")
        url = None
    if not url or not url.startswith("https://wa.me/"):
        return _not_valid()
    return RedirectResponse(url=url, status_code=302, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/sl/{key}/l/{lead_id}", include_in_schema=False)
def answer_now(key: str, lead_id: str, request: Request, db=Depends(get_supabase)):
    _limit(request, key, "link")
    try:
        url = cap.answer_redirect(db, key, lead_id, ip=_ip(request))
    except Exception:  # S14
        logger.exception("[SITE-CAPTURE] answer redirect failed")
        url = None
    if not url or not (url.startswith("https://wa.me/") or url.startswith("mailto:")):
        return _not_valid()
    return RedirectResponse(url=url, status_code=302, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
