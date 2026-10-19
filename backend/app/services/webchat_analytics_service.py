"""
app/services/webchat_analytics_service.py
-----------------------------------------
WEBCHAT-5 — the numbers behind Admin > Web Chat: funnel, by source, by day, what chats cost, AI budget.

Read-only. Everything is filtered by org_id. No new tables: funnel counts come from webchat_events, chat facts from
webchat_sessions.state (human hand-offs, AI turns, checkouts, WhatsApp templates, reply emails), AI cost from
claude_usage_log (function webchat_ai_turn, logged whether or not billing is on) and what was actually charged from
credit_ledger. Paystack and Meta fees are not part of "cost per conversation".
S14: each block is independent; a failed block returns zeros rather than breaking the screen.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

KINDS = ("visit", "started", "contact", "booked", "handoff_sent", "redirect_sent")
FUNNEL = ("visit", "started", "contact", "booked")
AI_FUNCTION = "webchat_ai_turn"
DEFAULT_FX = 1340.0
CAP_ROWS = 20000


def _pct(a: int, b: int) -> Optional[float]:
    return round(100.0 * a / b, 1) if b else None


def _rows(build) -> list:
    """build is a zero-argument callable returning the query, so errors while building it are caught too."""
    try:
        return build().execute().data or []
    except Exception as exc:
        logger.warning("webchat analytics query failed: %s", exc)
        return []


def _funnel(db, org_id: str, since: str) -> dict:
    rows = _rows(lambda: db.table("webchat_events").select("kind, source, created_at").eq("org_id", org_id)
                 .gte("created_at", since).limit(CAP_ROWS))
    totals = {k: 0 for k in KINDS}
    by_source: dict = {}
    daily: dict = {}
    for r in rows:
        k = r.get("kind")
        if k not in totals:
            continue
        totals[k] += 1
        src = r.get("source") or "link"
        by_source.setdefault(src, {kk: 0 for kk in KINDS})[k] += 1
        day = str(r.get("created_at") or "")[:10]
        if day:
            daily.setdefault(day, {kk: 0 for kk in KINDS})[k] += 1
    rates = {"started_of_visit": _pct(totals["started"], totals["visit"]),
             "contact_of_started": _pct(totals["contact"], totals["started"]),
             "booked_of_contact": _pct(totals["booked"], totals["contact"])}
    sources = sorted(({"source": s, **c} for s, c in by_source.items()), key=lambda r: -r["visit"])
    days = [{"date": d, **daily[d]} for d in sorted(daily)]
    return {"totals": totals, "rates": rates, "sources": sources, "daily": days}


def _chats(db, org_id: str, since: str) -> dict:
    rows = _rows(lambda: db.table("webchat_sessions").select("id, lead_id, state, turn_count").eq("org_id", org_id)
                 .gte("created_at", since).limit(CAP_ROWS))
    out = {"chats": len(rows), "with_contact": 0, "handed_to_team": 0, "ai_chats": 0, "ai_turns": 0,
           "checkouts": 0, "whatsapp_templates": 0, "reply_emails": 0, "messages_sent_by_visitors": 0}
    for r in rows:
        st = r.get("state") or {}
        out["with_contact"] += 1 if r.get("lead_id") else 0
        out["handed_to_team"] += 1 if (st.get("human_at") or st.get("human")) else 0
        turns = int(st.get("ai_turns") or 0)
        out["ai_chats"] += 1 if turns else 0
        out["ai_turns"] += turns
        out["checkouts"] += 1 if st.get("last_checkout") else 0
        out["whatsapp_templates"] += int(st.get("wa_count") or 0)
        out["reply_emails"] += 1 if st.get("email_reply_at") else 0
        out["messages_sent_by_visitors"] += int(r.get("turn_count") or 0)
    return out


def _fx(db) -> float:
    try:
        from app.services import credit_service
        return float((credit_service.get_rates(db) or {}).get("fx_ngn_per_usd") or DEFAULT_FX)
    except Exception:
        return DEFAULT_FX


def _ai_cost(db, org_id: str, since: str) -> dict:
    usage = _rows(lambda: db.table("claude_usage_log").select("estimated_cost_usd").eq("org_id", org_id)
                  .eq("function_name", AI_FUNCTION).gte("called_at", since).limit(CAP_ROWS))
    usd = sum(float(r.get("estimated_cost_usd") or 0) for r in usage)
    ledger = _rows(lambda: db.table("credit_ledger").select("amount_kobo, meta").eq("org_id", org_id).eq("kind", "ai")
                   .gte("created_at", since).limit(CAP_ROWS))
    charged = sum(-int(r.get("amount_kobo") or 0) for r in ledger if (r.get("meta") or {}).get("function") == AI_FUNCTION)
    return {"calls": len(usage), "cost_usd": round(usd, 4), "cost_kobo": int(round(usd * _fx(db) * 100)),
            "charged_kobo": charged}


def _wallet(db, org_id: str) -> dict:
    try:
        from app.services import credit_service
        w = credit_service.get_wallet(db, org_id) or {}
        return {"balance_kobo": int(w.get("balance_kobo") or 0), "metering_enabled": bool(w.get("metering_enabled")),
                "month_ai_spend_kobo": credit_service.month_ai_spend_kobo(db, org_id) if w else 0,
                "ai_monthly_budget_kobo": w.get("ai_monthly_budget_kobo"),
                "ai_level": credit_service.get_ai_level(db, org_id)}
    except Exception as exc:
        logger.warning("webchat analytics wallet failed: %s", exc)
        return {"balance_kobo": 0, "metering_enabled": False, "month_ai_spend_kobo": 0, "ai_monthly_budget_kobo": None,
                "ai_level": "normal"}


def analytics(db, org_id: str, days: int = 30) -> dict:
    days = max(1, min(int(days or 30), 90))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    funnel, chats, ai, wallet = _funnel(db, org_id, since), _chats(db, org_id, since), _ai_cost(db, org_id, since), _wallet(db, org_id)
    cost = {**ai,
            "per_chat_kobo": int(round(ai["cost_kobo"] / chats["chats"])) if chats["chats"] else None,
            "per_ai_chat_kobo": int(round(ai["cost_kobo"] / chats["ai_chats"])) if chats["ai_chats"] else None,
            "per_contact_kobo": int(round(ai["cost_kobo"] / chats["with_contact"])) if chats["with_contact"] else None}
    return {"days": days, "since": since, "funnel": funnel, "chats": chats, "cost": cost, "wallet": wallet,
            "notes": ["AI cost is what the model calls cost at today's exchange rate; it is logged even when billing is off.",
                      "WhatsApp template messages and Paystack fees are not included in cost per chat."]}
