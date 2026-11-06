"""
app/services/ai_pilot_service.py
--------------------------------
AI-PILOT-1 - run the AI sales rep side by side with the human reps so their results can be compared.

A WhatsApp number can have ai_pilot_pct (0-100). While it is above 0 and the number is not already fully AI, a share of
NEW WhatsApp enquiries is handled by the AI rep:
  * the share is picked by a stable hash of the sender's phone number, so a customer is always in the same group;
  * only brand-new contacts are eligible - anyone who already has a lead or customer record stays with the humans;
  * the lead is tagged leads.ai_pilot = true for good. When the AI hands over to a person, ai_owned goes false but the
    tag stays, so a lead the AI started and a human finished is still counted as an AI-started lead.
The comparison group is every other WhatsApp lead created since the pilot started.
S14: nothing here raises into the webhook.
"""
from __future__ import annotations

import logging
import zlib
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def in_sample(phone: Optional[str], pct: int) -> bool:
    if not phone or pct <= 0:
        return False
    if pct >= 100:
        return True
    return zlib.crc32(str(phone).strip().encode()) % 100 < pct


def takes(db, number_row: dict, sender_phone: str, customer_id: Optional[str], lead_id: Optional[str]) -> bool:
    """True when the AI rep should handle this inbound message on a number that is not fully AI."""
    try:
        pct = int((number_row or {}).get("ai_pilot_pct") or 0)
        if pct <= 0:
            return False
        if customer_id:
            return False
        if lead_id:   # a lead the AI already owns in this pilot keeps being served by it; anyone else stays with humans
            rows = (db.table("leads").select("ai_owned, ai_pilot").eq("id", lead_id).limit(1).execute().data) or []
            return bool(rows and rows[0].get("ai_pilot") and rows[0].get("ai_owned"))
        return in_sample(sender_phone, pct)
    except Exception as exc:
        logger.warning("ai_pilot.takes failed: %s", exc)
        return False


def mark_lead(db, org_id: str, lead_id: str) -> None:
    try:
        db.table("leads").update({"ai_pilot": True}).eq("id", lead_id).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.warning("ai_pilot.mark_lead failed lead=%s: %s", lead_id, exc)


def set_pilot(db, org_id: str, pct: int) -> dict:
    pct = int(pct)
    if pct < 0 or pct > 100:
        raise ValueError("The share must be between 0 and 100.")
    nums = (db.table("whatsapp_numbers").select("id, wa_sales_mode, ai_pilot_pct, ai_pilot_started_at")
            .eq("org_id", org_id).execute().data) or []
    if not nums:
        raise ValueError("No WhatsApp number is connected.")
    now = datetime.now(timezone.utc).isoformat()
    for n in nums:
        upd = {"ai_pilot_pct": pct}
        if pct > 0 and not n.get("ai_pilot_started_at"):
            upd["ai_pilot_started_at"] = now
        db.table("whatsapp_numbers").update(upd).eq("id", n["id"]).execute()
    return {"pct": pct, "started_at": next((n.get("ai_pilot_started_at") for n in nums if n.get("ai_pilot_started_at")), now),
            "numbers": len(nums)}


def _fetch_leads(db, org_id: str, since: str) -> list:
    out, start = [], 0
    while True:
        rows = (db.table("leads")
                .select("id, stage, ai_pilot, ai_owned, deal_value, first_contacted_at, response_time_minutes, created_at")
                .eq("org_id", org_id).eq("entry_path", "whatsapp").is_("deleted_at", "null")
                .gte("created_at", since).order("created_at").range(start, start + 999).execute().data) or []
        out += rows
        if len(rows) < 1000 or len(out) >= 30000:
            return out
        start += 1000


def _summ(rows: list) -> dict:
    n = len(rows)
    conv = [r for r in rows if r.get("stage") == "converted"]
    contacted = [r for r in rows if r.get("first_contacted_at")]
    rts = [r["response_time_minutes"] for r in rows if r.get("response_time_minutes") is not None]
    return {
        "leads": n,
        "contacted": len(contacted), "contacted_pct": round(100 * len(contacted) / n, 1) if n else 0,
        "converted": len(conv), "conversion_pct": round(100 * len(conv) / n, 2) if n else 0,
        "revenue_ngn": round(sum(float(r.get("deal_value") or 0) for r in conv)),
        "avg_response_minutes": round(sum(rts) / len(rts), 1) if rts else None,
    }


def report(db, org_id: str, since: Optional[str] = None) -> dict:
    nums = (db.table("whatsapp_numbers").select("ai_pilot_pct, ai_pilot_started_at").eq("org_id", org_id).execute().data) or []
    pct = max([int(n.get("ai_pilot_pct") or 0) for n in nums] or [0])
    started = since or next((n.get("ai_pilot_started_at") for n in nums if n.get("ai_pilot_started_at")), None)
    if not started:
        return {"pct": pct, "started_at": None, "ai": _summ([]), "human": _summ([]), "ai_handed_over": 0, "ai_cost_ngn": 0}
    rows = _fetch_leads(db, org_id, started)
    ai = [r for r in rows if r.get("ai_pilot")]
    human = [r for r in rows if not r.get("ai_pilot")]
    cost = 0.0
    try:
        cost_rows = (db.table("claude_usage_log").select("estimated_cost_usd").eq("org_id", org_id)
                     .eq("function_name", "ai_agent_turn").gte("created_at", started).limit(50000).execute().data) or []
        cost = sum(float(c.get("estimated_cost_usd") or 0) for c in cost_rows) * 1420
    except Exception:
        pass
    a = _summ(ai)
    return {"pct": pct, "started_at": started, "ai": a, "human": _summ(human),
            "ai_handed_over": sum(1 for r in ai if not r.get("ai_owned")),
            "ai_cost_ngn": round(cost),
            "ai_cost_per_lead_ngn": round(cost / len(ai), 2) if ai else None,
            "ai_cost_per_conversion_ngn": round(cost / a["converted"]) if a["converted"] else None}
