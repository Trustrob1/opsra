"""
app/routers/public_performance.py
-----------------------------------
PIN-gated public routes for PERF-1 owner external dashboard.

No JWT dependency — auth is PIN session token only.
Redis brute-force: 5 attempts → 15-min lockout.
db via Depends(get_supabase) (Pattern 62). EXCEPTION: no get_current_org here.
Static routes before parameterised (Pattern 53).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import asyncio
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from app.database import get_supabase
import app.services.performance_service as perf_svc


logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Redis helpers for brute-force lockout
# ---------------------------------------------------------------------------
_LOCKOUT_ATTEMPTS = 5
_LOCKOUT_WINDOW   = 15 * 60  # 15 minutes in seconds


def _lockout_key(token: str) -> str:
    return f"owner_dashboard_lockout:{token}"


def _check_lockout(token: str) -> None:
    """Raise 429 if brute-force lockout is active."""
    try:
        import redis as redis_lib
        redis_url = os.environ.get("REDIS_URL", "")
        if not redis_url:
            return
        ssl = redis_url.startswith("rediss://")
        r = redis_lib.from_url(redis_url, decode_responses=True, ssl_cert_reqs=None if ssl else "required")
        count = r.get(_lockout_key(token))
        if count and int(count) >= _LOCKOUT_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Lockout check failed: %s", exc)  # fail-open


def _record_failed_attempt(token: str) -> None:
    try:
        import redis as redis_lib
        redis_url = os.environ.get("REDIS_URL", "")
        if not redis_url:
            return
        ssl = redis_url.startswith("rediss://")
        r = redis_lib.from_url(redis_url, decode_responses=True, ssl_cert_reqs=None if ssl else "required")
        key = _lockout_key(token)
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _LOCKOUT_WINDOW)
        pipe.execute()
    except Exception as exc:
        logger.warning("Failed to record lockout attempt: %s", exc)


def _clear_lockout(token: str) -> None:
    try:
        import redis as redis_lib
        redis_url = os.environ.get("REDIS_URL", "")
        if not redis_url:
            return
        ssl = redis_url.startswith("rediss://")
        r = redis_lib.from_url(redis_url, decode_responses=True, ssl_cert_reqs=None if ssl else "required")
        r.delete(_lockout_key(token))
    except Exception as exc:
        logger.warning("Failed to clear lockout: %s", exc)


def _verify_session_token(
    token: str,
    org_id: str,
    dashboard_token: str,
    authorization: str | None,
) -> None:
    """Verify Authorization header contains a valid 24h session token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="PIN session required")
    session_token = authorization.removeprefix("Bearer ").strip()
    if not perf_svc.verify_owner_session_token(session_token, org_id, dashboard_token):
        raise HTTPException(status_code=401, detail="Invalid or expired session token")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ASK-GUIDE — full "what can I ask" web page, linked from the WhatsApp HELP
# message instead of trying to fit an unbounded example list into a chat
# bubble. Reuses owner_dashboard_token as the sole credential, same as
# get_daily_report_pdf below (single-tap from WhatsApp, no session required).
#
# Deliberately separate from IntegrationProvider.capabilities()["examples"]
# (which stays short — 2-3 items — for the WhatsApp HELP message). This bank
# can be as long as useful since the guide page has no character ceiling.
# Grounded in each provider's actual documented data domain:
#   opsra_orders  -> opsra_orders_provider_service.py docstring + get_summary() fields
#   paystack      -> payment_service.py docstring + get_summary() fields
#   shopify       -> shopify_provider_service.py get_summary() fields
#     (total_revenue_ngn, total_orders, average_order_value_ngn,
#      fulfilment_rate_pct, unfulfilled_orders, top_products)
# Adding a new provider: add one entry here + one to registry.py's PROVIDERS.
# ---------------------------------------------------------------------------
_GUIDE_EXAMPLES = {
    "opsra_orders": {
        "label": "Leads, Pipeline & WhatsApp Orders",
        "emoji": "\U0001F4CA",
        "examples": [
            "How many leads came in this week?",
            "How many leads came in this month?",
            "What is my conversion rate this month?",
            "Which lead source is converting best?",
            "How many leads are in each stage?",
            "Show me my hot leads",
            "Show me new leads from Instagram",
            "Show me leads that haven't converted",
            "Show me unfulfilled WhatsApp orders",
            "Show me abandoned WhatsApp carts",
            "Show me recent conversions",
            "How many WhatsApp orders are pending?",
        ],
    },
    "paystack": {
        "label": "Subscription Payments & Revenue",
        "emoji": "\U0001F4B0",
        "examples": [
            "What's my subscription revenue this month?",
            "How many payment conversions this week?",
            "Payment summary for last quarter",
            "How much did I receive in payments today?",
            "What's my revenue this year so far?",
            "How many active subscriptions do I have?",
        ],
    },
    "shopify": {
        "label": "Shopify Store & Orders",
        "emoji": "\U0001F6CD\uFE0F",
        "examples": [
            "What's my Shopify revenue this month?",
            "How many orders came in this week?",
            "What are my top selling products?",
            "Show me unfulfilled orders",
            "What's my average order value?",
            "What's my fulfilment rate this month?",
        ],
    },
}

_COMPARISON_EXAMPLES = [
    "Compare this month vs last month",
    "What is the percentage change in revenue this week vs last week?",
    "How many leads came in yesterday vs today?",
    "How did this quarter compare to last quarter?",
]

_REPORT_TYPES = [
    {
        "emoji": "\U0001F4C4",
        "title": "Period Summary",
        "desc": "A full overview across everything connected — leads, revenue, orders — for any date range.",
        "examples": ["Send me a report for this month", "PDF of this week", "Give me a report for July"],
    },
    {
        "emoji": "\U0001F4CB",
        "title": "Lead Pipeline",
        "desc": "Every lead in the period — name, phone, source, score, stage, last activity, assigned rep — sorted by stage.",
        "examples": ["Send me a PDF of my leads", "Export my pipeline", "Lead pipeline report for this month"],
    },
    {
        "emoji": "\U0001F4E6",
        "title": "Orders & Fulfilment",
        "desc": "Every order in the period, with status and fulfilment detail — works whether you use Shopify, WhatsApp commerce, or neither.",
        "examples": ["Orders report for this week", "Send me a PDF of unfulfilled orders", "Export my orders"],
    },
    {
        "emoji": "\U0001F4C8",
        "title": "Comparison",
        "desc": "Every key metric side by side against the equivalent prior period, with a plain-English summary.",
        "examples": ["Send a PDF comparing this month vs last month", "Performance comparison report"],
    },
]

_BRAND_TEAL = "#0d9488"  # placeholder — see owner_pdf_service.py note on ds.teal


def _render_ask_guide_html(org_name: str, connected_providers: list[str]) -> str:
    """
    Builds the full 'what can I ask' guide page. Only shows sections for
    providers actually connected to this org — mirrors build_help_message's
    filtering behaviour. PDF Reports and Comparisons sections always show
    if at least one provider is connected (both are provider-agnostic
    capabilities layered on top of whatever data sources exist).
    """
    if not connected_providers:
        body = (
            '<div class="empty">No data sources are connected yet. '
            "Please contact your Opsra administrator.</div>"
        )
        return _guide_shell(org_name, body)

    sections_html = ""
    for name in connected_providers:
        cfg = _GUIDE_EXAMPLES.get(name)
        if not cfg:
            continue
        items = "".join(f"<li>{ex}</li>" for ex in cfg["examples"])
        sections_html += f"""
        <section>
          <h2>{cfg['emoji']} {cfg['label']}</h2>
          <ul>{items}</ul>
        </section>
        """

    # Comparisons — provider-agnostic, always shown if anything is connected
    comp_items = "".join(f"<li>{ex}</li>" for ex in _COMPARISON_EXAMPLES)
    sections_html += f"""
    <section>
      <h2>\U0001F501 Comparisons</h2>
      <p class="sub">Ask any question above as a comparison — just say "vs", "compared to", or "change from".</p>
      <ul>{comp_items}</ul>
    </section>
    """

    # PDF Reports — provider-agnostic, always shown if anything is connected
    report_cards = ""
    for r in _REPORT_TYPES:
        ex_items = "".join(f"<li>{ex}</li>" for ex in r["examples"])
        report_cards += f"""
        <div class="report-card">
          <h3>{r['emoji']} {r['title']}</h3>
          <p class="sub">{r['desc']}</p>
          <ul>{ex_items}</ul>
        </div>
        """
    sections_html += f"""
    <section>
      <h2>\U0001F4C4 PDF Reports</h2>
      <p class="sub">Any of the above, delivered as a downloadable PDF — just ask.</p>
      <div class="report-grid">{report_cards}</div>
    </section>
    """

    return _guide_shell(org_name, sections_html)


def _guide_shell(org_name: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What can I ask? \u2014 {org_name}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f7f9f9; color: #1a1a1a; margin: 0; padding: 20px 16px 60px;
    max-width: 640px; margin-left: auto; margin-right: auto;
  }}
  header {{ margin-bottom: 24px; }}
  h1 {{ color: {_BRAND_TEAL}; font-size: 22px; margin: 0 0 4px; }}
  .subtitle {{ color: #666; font-size: 14px; }}
  .intro {{
    background: #e6f7f5; border-left: 3px solid {_BRAND_TEAL};
    padding: 12px 14px; border-radius: 6px; font-size: 14px; margin-bottom: 24px;
  }}
  section {{ margin-bottom: 28px; }}
  h2 {{ font-size: 17px; border-bottom: 1px solid #e0e0e0; padding-bottom: 6px; }}
  h3 {{ font-size: 15px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 13px; margin: 4px 0 8px; }}
  ul {{ margin: 0; padding-left: 20px; }}
  li {{ font-size: 14px; padding: 3px 0; }}
  .report-grid {{ display: grid; grid-template-columns: 1fr; gap: 12px; margin-top: 8px; }}
  .report-card {{
    background: #fff; border: 1px solid #e5e5e5; border-radius: 8px; padding: 14px;
  }}
  .empty {{ color: #666; font-size: 15px; padding: 40px 0; text-align: center; }}
  footer {{ margin-top: 32px; color: #999; font-size: 12px; text-align: center; }}
  @media (min-width: 480px) {{
    .report-grid {{ grid-template-columns: 1fr 1fr; }}
  }}
</style>
</head>
<body>
  <header>
    <h1>What can I ask?</h1>
    <div class="subtitle">{org_name}'s WhatsApp business assistant</div>
  </header>
  <div class="intro">
    Ask in plain English \u2014 no fixed commands. The examples below show what's
    possible, but you can phrase things however feels natural, ask follow-up
    questions, and combine periods (this week, last month, this year, or any
    custom range).
  </div>
  {body_html}
  <footer>Generated by Opsra</footer>
</body>
</html>"""


class PinVerifyRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=6, pattern=r"^\d{4,6}$")


class ApproveLogRequest(BaseModel):
    log_id: str


class FlagLogRequest(BaseModel):
    log_id: str
    note:   str = Field(..., max_length=500)


# ---------------------------------------------------------------------------
# Routes — STATIC /verify before PARAMETERISED (Pattern 53)
# Note: all routes share /{token} prefix — static sub-paths registered first.
# ---------------------------------------------------------------------------

# POST /public/owner-dashboard/{token}/verify
_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}

@router.post("/public/owner-dashboard/{token}/verify")
def verify_pin(
    token: str,
    payload: PinVerifyRequest,
    db=Depends(get_supabase),
):
    _check_lockout(token)
    org = perf_svc.verify_owner_dashboard_pin(db, token, payload.pin)
    if not org:
        _record_failed_attempt(token)
        raise HTTPException(status_code=401, detail="Invalid PIN")
    _clear_lockout(token)
    session_token = perf_svc.generate_owner_session_token(org["id"], token)
    return JSONResponse(content={
        "session_token": session_token,
        "org_id": org["id"],
        "org_name": org.get("name", ""),
        "expires_in_seconds": 86400,
    }, headers=_CORS_HEADERS)


# POST /public/owner-dashboard/{token}/approve
@router.post("/public/owner-dashboard/{token}/approve")
def approve_log(
    token: str,
    payload: ApproveLogRequest,
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
):
    # Resolve org_id from token
    org = db.table("organisations").select("id").eq("owner_dashboard_token", token).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _verify_session_token(token, row["id"], token, authorization)
    perf_svc.approve_log(db, row["id"], payload.log_id)
    return {"data": {"ok": True}}


# POST /public/owner-dashboard/{token}/flag
@router.post("/public/owner-dashboard/{token}/flag")
def flag_log(
    token: str,
    payload: FlagLogRequest,
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
):
    org = db.table("organisations").select("id").eq("owner_dashboard_token", token).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _verify_session_token(token, row["id"], token, authorization)

    # Find owner + ops_manager user IDs to notify (Pattern 48)
    users_res = db.table("users").select("id, roles(template)").eq("org_id", row["id"]).execute()
    notif_ids = [
        u["id"] for u in (users_res.data or [])
        if (u.get("roles") or {}).get("template", "") in ("owner", "ops_manager")
    ]
    perf_svc.flag_log(db, row["id"], payload.log_id, payload.note, notif_ids)
    return {"data": {"ok": True}}


# GET /public/owner-dashboard/{token}
@router.get("/public/owner-dashboard/{token}")
async def get_owner_dashboard(
    token: str,
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
):
    org = db.table("organisations").select("id, name, health_score_weights").eq(
        "owner_dashboard_token", token
    ).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _verify_session_token(token, row["id"], token, authorization)

    panels, health = await asyncio.gather(
        perf_svc.get_owner_dashboard_panels(db, row["id"]),
        perf_svc.get_health_score(db, row["id"]),
    )
    content = {
        "org_name": row.get("name", ""),
        "health_score": health,
        "panels": panels,
    }
    return JSONResponse(content=content, headers={
        "Access-Control-Allow-Origin":  "*",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    })

@router.get("/public/owner-dashboard/{token}/goals")
async def get_owner_dashboard_goals(
    token: str,
    period_start: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
):
    org = db.table("organisations").select("id").eq("owner_dashboard_token", token).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _verify_session_token(token, row["id"], token, authorization)
    from datetime import date
    if not period_start:
        d = date.today()
        period_start = str(date(d.year, d.month, 1))
    return JSONResponse(
        content={"data": perf_svc.get_business_goals(db, row["id"], period_start)},
        headers=_CORS_HEADERS,
    )


# GET /public/owner-dashboard/{token}/ask-guide
# No session token required — dashboard_token IS the credential, same as
# daily-report-pdf below. Single-tap from a short WhatsApp HELP link.
@router.get("/public/owner-dashboard/{token}/ask-guide")
async def get_ask_guide(token: str, db=Depends(get_supabase)):
    from fastapi.responses import HTMLResponse
    from app.integrations.registry import get_connected_providers

    org = db.table("organisations").select("id, name").eq(
        "owner_dashboard_token", token
    ).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    connected = get_connected_providers(db, row["id"])
    html = _render_ask_guide_html(row.get("name") or "Your Business", connected)
    return HTMLResponse(content=html, headers={"Access-Control-Allow-Origin": "*"})

# GET /r/report/{short_code} — OWNER-PDF-1 short-link redirect.
# Registered BEFORE /r/{token}/{date} below (Pattern 53 — static before
# parameterised): "report" is a literal path segment, not a token, so it
# must be matched first or /r/{token}/{date} would greedily consume it as
# token="report". short_code is looked up in owner_pdf_report_links
# (see migration_owner_pdf_report_links.sql) — a fresh 1h Supabase signed
# URL is generated at click time; the 24h "link expires" promise made to
# the owner is enforced against that table's expires_at, not against any
# Supabase-issued token embedded in the WhatsApp message itself.
@router.get("/r/report/{short_code}")
async def owner_pdf_report_shortlink(short_code: str, db=Depends(get_supabase)):
    from fastapi.responses import RedirectResponse

    result = (
        db.table("owner_pdf_report_links")
        .select("org_id, storage_path, expires_at")
        .eq("short_code", short_code)
        .maybe_single()
        .execute()
    )
    row = result.data
    if isinstance(row, list):
        row = row[0] if row else None
    if not row:
        raise HTTPException(status_code=404, detail="Link not found or expired")

    try:
        expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        from datetime import timezone as _timezone
        if expires_at < datetime.now(_timezone.utc):
            raise HTTPException(status_code=410, detail="This link has expired")
    except HTTPException:
        raise
    except Exception as exc:
        # Don't 500 the owner over a parsing quirk — log and allow through,
        # matching the fail-open posture used for the lockout checks above.
        logger.warning("owner_pdf_report_shortlink: expires_at parse failed short_code=%s: %s", short_code, exc)

    try:
        signed = db.storage.from_("owner-reports").create_signed_url(row["storage_path"], 3600)
        if isinstance(signed, dict):
            url = signed.get("signedURL") or signed.get("signed_url") or signed.get("signedUrl")
        else:
            url = getattr(signed, "signed_url", None) or getattr(signed, "signedURL", None)
        if not url:
            raise HTTPException(status_code=500, detail="Could not generate report link")
        if not url.startswith("http"):
            supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
            url = f"{supabase_url}{url}" if url.startswith("/storage") else f"{supabase_url}/storage/v1{url}"
        return RedirectResponse(url=url, status_code=302)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("owner_pdf_report_shortlink: signing failed short_code=%s: %s", short_code, exc)
        raise HTTPException(status_code=500, detail="Could not generate report link")


# GET /r/{token}/{date} — short-link redirect to daily-report-pdf
# Token-as-credential, no session required. 302 (not 301) so the
# destination can change in future without browsers caching the old path.
@router.get("/r/{token}/{date}")
async def daily_report_shortlink(token: str, date: str, db=Depends(get_supabase)):
    from fastapi.responses import RedirectResponse
    org = db.table("organisations").select("id").eq(
        "owner_dashboard_token", token
    ).limit(1).execute()
    if not (org.data or []):
        raise HTTPException(status_code=404, detail="Link not found")
    return RedirectResponse(
        url=f"/api/v1/public/owner-dashboard/{token}/daily-report-pdf?date={date}",
        status_code=302,
    )


# GET /public/owner-dashboard/{token}/daily-report-pdf
# No session token required — dashboard_token IS the credential.
# Single-tap from WhatsApp link: opens the activity log PDF inline.
@router.get("/public/owner-dashboard/{token}/daily-report-pdf")
async def get_daily_report_pdf(
    token: str,
    date: Optional[str] = None,
    db=Depends(get_supabase),
):
    from fastapi.responses import Response
    from app.routers.activity_logs import (
        build_daily_report_data,
        _generate_activity_log_pdf,
    )

    org = db.table("organisations").select("id, name").eq(
        "owner_dashboard_token", token
    ).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    from datetime import date as _date
    if date:
        try:
            report_date = _date.fromisoformat(date)
            if report_date > _date.today():
                report_date = _date.today()
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        report_date = _date.today() - timedelta(days=1)

    try:
        report_data = build_daily_report_data(
            db              = db,
            org_id          = row["id"],
            report_date_str = report_date.isoformat(),
            org_name        = row.get("name", ""),
        )
        pdf_bytes = _generate_activity_log_pdf(report_data)
    except Exception as exc:
        logger.error("get_daily_report_pdf: generation failed — %s", exc)
        raise HTTPException(status_code=500, detail="Could not generate report.")

    org_slug = (row.get("name") or "org").replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="Activity_Log_{org_slug}_{report_date}.pdf"',
            "Access-Control-Allow-Origin": "*",
        },
    )


# GET /public/owner-dashboard/{token}/brief
@router.get("/public/owner-dashboard/{token}/brief")
async def get_owner_brief(
    token: str,
    date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
):
    org = db.table("organisations").select("id, name").eq(
        "owner_dashboard_token", token
    ).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _verify_session_token(token, row["id"], token, authorization)

    # Resolve brief_date — default to yesterday so the morning view is always populated
    from datetime import date as _date
    brief_date = None
    if date:
        try:
            brief_date = _date.fromisoformat(date)
            # Clamp to today — never allow future dates
            if brief_date > _date.today():
                brief_date = _date.today()
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        brief_date = _date.today() - timedelta(days=1)

    brief = await perf_svc.get_daily_brief(db, row["id"], brief_date=brief_date)
    health = await perf_svc.get_health_score(db, row["id"])
    return JSONResponse(
        content={"org_name": row.get("name", ""), "health": health, "brief": brief},
        headers=_CORS_HEADERS,
    )
