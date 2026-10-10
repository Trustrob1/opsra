"""
app/routers/public_site_capture.py
------------------------------------
SITE-ADDONS A1-1 - what a client's website talks to. No login: the site KEY in the address is the only credential, and it
only opens the capture features that site's plan includes.

  POST /api/v1/public/site-leads/{key}   the enquiry form (a plain HTML form post, no script, no CORS needed)
  GET  /sl/{key}/wa                      tracked WhatsApp link: logs the click, redirects to the site's own wa.me address
  GET  /my-leads/{token}                 the owner's private list of enquiries (script-free page)
  GET  /sl/{key}/l/{lead_id}              the owner's "Answer now" link: marks the lead answered, opens WhatsApp to the visitor

Unknown or switched-off keys all get the same "not valid" page. Nothing here returns lead data.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone

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


# ---------------------------------------------------------------- the owner's My leads page

_LAGOS = timezone(timedelta(hours=1))
_LEADS_CSS = """
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7f9;color:#111;padding:16px;box-sizing:border-box}
.wrap{max-width:720px;margin:0 auto}
h1{font-size:20px;margin:8px 0 4px} .sub{color:#555;margin:0 0 16px;font-size:14px}
.lead{background:#fff;border-radius:12px;padding:16px;margin:0 0 12px;box-shadow:0 1px 6px rgba(0,0,0,.06)}
.top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap}
.name{font-weight:700;font-size:16px;margin:0} .when{color:#666;font-size:12.5px}
.msg{margin:8px 0;line-height:1.5;color:#333;white-space:pre-wrap;overflow-wrap:anywhere}
.meta{font-size:13px;color:#555;margin:4px 0} .tag{display:inline-block;font-size:12px;font-weight:600;padding:2px 9px;border-radius:99px}
.waiting{background:#fdf4e3;color:#9a6200} .done{background:#e8f6ee;color:#1e8e4f}
a.btn{display:inline-block;margin-top:8px;margin-right:8px;background:#028090;color:#fff;text-decoration:none;padding:11px 16px;border-radius:9px;font-weight:600;font-size:14px}
a.btn.alt{background:#fff;color:#028090;border:1px solid #028090}
.empty{background:#fff;border-radius:12px;padding:28px;text-align:center;color:#555}
@media (prefers-color-scheme:dark){body{background:#111;color:#eee}.lead,.empty{background:#1c1c1c}.msg{color:#ccc}.sub,.meta,.when{color:#aaa}a.btn.alt{background:transparent}}
"""


def _leads_doc(title: str, inner: str, status_code: int = 200) -> HTMLResponse:
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
           f'<title>{html.escape(title)}</title><style>{_LEADS_CSS}</style></head><body><div class="wrap">{inner}</div></body></html>')
    return HTMLResponse(content=doc, status_code=status_code, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _when(iso) -> str:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(_LAGOS).strftime("%d %b %Y, %I:%M %p").lstrip("0")
    except Exception:
        return ""


@router.get("/my-leads/{token}", include_in_schema=False)
def my_leads_page(token: str, request: Request, db=Depends(get_supabase)):
    _limit(request, token[:24], "link")
    try:
        d = cap.my_leads(db, token)
    except Exception:  # S14
        logger.exception("[SITE-CAPTURE] my leads failed")
        return _leads_doc("Try again", "<h1>Something went wrong</h1><p class=\"sub\">We couldn't open your enquiries right now. "
                          "Please try again in a minute.</p>", 503)
    if d is None:
        return _leads_doc("Link not valid", "<h1>This link isn't valid</h1><p class=\"sub\">Please ask for a fresh link.</p>", 404)
    biz = html.escape(d["business"])
    if not d["available"]:
        return _leads_doc("Not available", f"<h1>{biz}</h1><p class=\"sub\">The enquiries page is not part of the current plan. "
                          "Your enquiries are kept safe.</p>")
    if not d["leads"]:
        return _leads_doc("My leads", f"<h1>Enquiries for {biz}</h1><div class=\"empty\"><p>No enquiries yet.</p>"
                          "<p class=\"sub\">They will show here as soon as someone sends one from your website.</p></div>")
    cards = []
    for l in d["leads"]:
        status = '<span class="tag done">Answered</span>' if l["answered"] else '<span class="tag waiting">Waiting for your reply</span>'
        contact = " · ".join(html.escape(x) for x in (l["phone"], l["email"]) if x)
        src = f'<p class="meta">From: {html.escape(l["source"])}</p>' if l["source"] else ""
        msg = f'<p class="msg">{html.escape(l["message"])}</p>' if l["message"] else ""
        reply = f'<a class="btn" href="{html.escape(l["reply_url"], quote=True)}">Reply on WhatsApp</a>' if l["phone"] else (
            f'<a class="btn" href="{html.escape(l["reply_url"], quote=True)}">Reply by email</a>' if l["email"] else "")
        cards.append(f'<article class="lead"><div class="top"><p class="name">{html.escape(l["name"] or "Visitor")}</p>'
                     f'<span class="when">{html.escape(_when(l["created_at"]))}</span></div>'
                     f'{f"<p class=meta>{contact}</p>" if contact else ""}{msg}{src}<p class="meta">{status}</p>{reply}</article>')
    return _leads_doc("My leads", f'<h1>Enquiries for {biz}</h1><p class="sub">Your latest {d["total"]} enquiries, newest first.</p>'
                      + "".join(cards))
