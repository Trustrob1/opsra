"""
app/services/funnel_tools_service.py
-------------------------------------
FUNNEL-1B — dashboard tools for Event Funnels (spec §15.1):

  TemplateBudget        — optional ₦ cap on template messages (sequence templates + broadcasts)
  get_ad_spend / put_ad_spend
  get_overview          — 1A stats + ad spend, cost per lead/payment, pause flag, template spend, budget
  render_preview        — how a message looks to a lead (saved or unsaved config; nothing sent)
  reset_registration    — "Reset test lead" (unpaid only)
  duplicate_as_test     — draft copy with a 1-hour window and compressed timings
  gmail_list            — paid attendees' Gmails + who is missing one
  estimate/create/list/cancel broadcasts, drain_broadcasts (worker)

S14 in worker paths; route-facing functions raise FunnelToolError(code, message, status).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import funnel_service as fs
from app.services import funnel_messaging

logger = logging.getLogger(__name__)

BROADCAST_BATCH = 300          # sends per broadcast per worker run (every 5 min)
TEMPLATE_EVENT_TYPES = ["template_sent", "broadcast_sent"]


class FunnelToolError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------------------------------------------------------------------------
# Template budget (optional cap)
# ---------------------------------------------------------------------------

@dataclass
class TemplateBudget:
    funnel: dict
    cost: Optional[float] = None
    cap: Optional[float] = None
    used: int = 0
    _notified: bool = field(default=False, repr=False)

    @property
    def active(self) -> bool:
        return bool(self.cost and self.cap)

    @property
    def spent(self) -> float:
        return round(self.used * (self.cost or 0), 2)

    @property
    def remaining_messages(self) -> Optional[int]:
        if not self.active:
            return None
        return max(0, int(math.floor((self.cap - self.used * self.cost) / self.cost + 1e-9)))

    def allow(self, n: int = 1) -> bool:
        return (not self.active) or (self.remaining_messages or 0) >= n

    def consume(self, n: int = 1) -> None:
        self.used += n

    def as_dict(self) -> dict:
        return {"active": self.active, "cost_per_message": self.cost, "cap": self.cap,
                "messages_used": self.used, "spent": self.spent,
                "remaining_messages": self.remaining_messages,
                "remaining_amount": round(self.cap - self.spent, 2) if self.active else None}

    @classmethod
    def load(cls, db, funnel: dict) -> "TemplateBudget":
        st = fs.funnel_settings(funnel)
        used = 0
        try:
            used = len(fs._fetch_all(lambda: db.table("funnel_events").select("id")
                                     .eq("funnel_id", funnel["id"]).in_("type", TEMPLATE_EVENT_TYPES)))
        except Exception as exc:
            logger.warning("TemplateBudget.load failed funnel=%s: %s", funnel.get("id"), exc)
        return cls(funnel=funnel, cost=st.get("template_cost_estimate"), cap=st.get("template_budget_cap"), used=used)

    def notify_reached(self, db) -> None:
        """Tell managers once per funnel that the cap stopped template messages. S14."""
        if self._notified or not self.active:
            return
        self._notified = True
        try:
            done = (db.table("funnel_events").select("id").eq("funnel_id", self.funnel["id"])
                    .eq("type", "budget_cap_reached").limit(1).execute()).data
            if done:
                return
            fs.log_event(db, self.funnel["org_id"], self.funnel["id"], None, "budget_cap_reached",
                         detail={"cap": self.cap, "spent": self.spent})
            fs.notify_managers(db, self.funnel["org_id"], "Webinar template budget reached",
                               f"{self.funnel.get('name')}: template messages stopped at "
                               f"{fs.format_money(self.spent)} of your {fs.format_money(self.cap)} cap. "
                               "Raise the cap in Setup to resume.", "funnel_budget_cap", None)
        except Exception as exc:
            logger.warning("notify_reached failed funnel=%s: %s", self.funnel.get("id"), exc)


# ---------------------------------------------------------------------------
# Ad spend
# ---------------------------------------------------------------------------

def get_ad_spend(db, org_id: str, funnel_id: str, date_from: Optional[str] = None,
                 date_to: Optional[str] = None) -> list[dict]:
    def build():
        q = (db.table("funnel_ad_spend").select("spend_date, ad_code, amount")
             .eq("org_id", org_id).eq("funnel_id", funnel_id))
        if date_from:
            q = q.gte("spend_date", date_from)
        if date_to:
            q = q.lte("spend_date", date_to)
        return q.order("spend_date")
    return fs._fetch_all(build)


def put_ad_spend(db, org_id: str, funnel_id: str, rows: list[dict]) -> int:
    """Upsert by (funnel, date, code) — re-entering a day overwrites it."""
    now = fs._iso(fs._now())
    n = 0
    for r in rows:
        d, code, amount = str(r["date"]), r["ad_code"], float(r["amount"])
        existing = fs._one((db.table("funnel_ad_spend").select("id").eq("org_id", org_id)
                            .eq("funnel_id", funnel_id).eq("spend_date", d).eq("ad_code", code)
                            .limit(1).execute()).data)
        if existing:
            db.table("funnel_ad_spend").update({"amount": amount, "updated_at": now}) \
                .eq("id", existing["id"]).eq("org_id", org_id).execute()
        else:
            db.table("funnel_ad_spend").insert({
                "org_id": org_id, "funnel_id": funnel_id, "spend_date": d, "ad_code": code,
                "amount": amount, "created_at": now, "updated_at": now}).execute()
        n += 1
    return n


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def get_overview(db, org_id: str, funnel: dict) -> dict:
    stats = fs.get_funnel_stats(db, org_id, funnel)
    settings = fs.funnel_settings(funnel)
    threshold = float(settings.get("pause_spend_threshold") or 0)
    spend_rows = get_ad_spend(db, org_id, funnel["id"])
    spend_by_code: dict[str, float] = {}
    for r in spend_rows:
        spend_by_code[r["ad_code"]] = spend_by_code.get(r["ad_code"], 0.0) + float(r.get("amount") or 0)

    codes = {c["code"]: c for c in stats["by_ad_code"]}
    for code in spend_by_code:
        codes.setdefault(code, {"code": code, "leads": 0, "paid": 0, "seats": 0, "revenue": 0.0})
    labels = {str((c or {}).get("code", "")).upper(): (c or {}).get("label") for c in (funnel.get("ad_codes") or [])
              if isinstance(c, dict)}
    rows = []
    for code, c in codes.items():
        spend = round(spend_by_code.get(code, 0.0), 2)
        c = dict(c)
        c["label"] = labels.get(code)
        c["spend"] = spend
        c["cost_per_lead"] = round(spend / c["leads"], 2) if c["leads"] and spend else None
        c["cost_per_payment"] = round(spend / c["paid"], 2) if c["paid"] and spend else None
        c["roas"] = round(c["revenue"] / spend, 2) if spend else None
        c["pause_flag"] = bool(threshold and spend >= threshold and c["paid"] == 0)
        rows.append(c)
    rows.sort(key=lambda x: (x["cost_per_payment"] is None, x["cost_per_payment"] or 0, -x["revenue"]))

    budget = TemplateBudget.load(db, funnel)
    ad_total = round(sum(spend_by_code.values()), 2)
    template_spend = budget.spent if budget.cost else None
    total_cost = ad_total + (template_spend or 0)
    stats.update({
        "by_ad_code": rows,
        "ad_spend": ad_total,
        "template_messages": budget.used,
        "template_spend_estimate": template_spend,
        "cost_per_payment": round(total_cost / stats["paid"], 2) if stats["paid"] and total_cost else None,
        "roas": round(stats["revenue"] / total_cost, 2) if total_cost else None,
        "pause_threshold": threshold,
        "template_budget": budget.as_dict(),
        "spend_by_day": _spend_by_day(spend_rows),
    })
    return stats


def _spend_by_day(rows: list[dict]) -> list[dict]:
    out: dict[str, float] = {}
    for r in rows:
        d = str(r["spend_date"])[:10]
        out[d] = out.get(d, 0.0) + float(r.get("amount") or 0)
    return [{"date": d, "spend": round(v, 2)} for d, v in sorted(out.items())]


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

_PAY_BUTTON_KEYS = {"greeting", "pay_link_resend", "group_offer"}


def render_preview(funnel: dict, req: dict, now: Optional[datetime] = None) -> dict:
    """req = PreviewRequest.model_dump(). Pure — nothing stored or sent."""
    now = now or fs._now()
    f = dict(funnel)
    if req.get("messages"):
        merged = dict(f.get("messages") or {})
        merged.update({k: v for k, v in req["messages"].items() if v is not None})
        f["messages"] = merged
    if req.get("sequence") is not None:
        f["sequence"] = req["sequence"]
    f["status"] = "active"  # preview prices as if live
    sample = req.get("sample") or {}
    reg = {
        "id": "preview", "org_id": f.get("org_id"), "funnel_id": f.get("id"), "phone": "2348000000000",
        "name": sample.get("name") or "Ada Obi", "email": sample.get("email") or ("ada@gmail.com" if sample.get("paid") else None),
        "status": "paid" if sample.get("paid") else "new", "pay_token": "PREVIEW", "ref_code": "AB1234",
        "first_message_at": fs._iso(now - timedelta(hours=float(sample.get("hours_since_first") or 0))),
        "last_inbound_at": fs._iso(now), "early_override_until": None, "done_steps": [],
    }
    ctx = fs.build_context(f, reg, now)
    quote = fs.current_price(f, reg, now)
    msgs = fs.funnel_messages(f)
    out = {"text": "", "button": None, "template": None, "template_params": [], "price": ctx["price"],
           "tier": quote.tier, "closed": quote.status == "closed"}

    if req.get("step_key"):
        step = next((s for s in fs.funnel_sequence(f) if s["key"] == req["step_key"]), None)
        if not step:
            raise FunnelToolError("NOT_FOUND", "Step not found", 404)
        out["text"] = fs.render(step.get("text"), ctx)
        if step.get("include_pay_button"):
            out["button"] = fs.render(msgs.get("pay_button") or "Pay {price}", ctx)[:20]
        if step.get("template_name"):
            out["template"] = step["template_name"]
            out["template_params"] = [fs.render(p, ctx) for p in step.get("template_params") or []]
        return out
    if req.get("message_key"):
        key = req["message_key"]
        if key not in msgs or key == "faq":
            raise FunnelToolError("NOT_FOUND", "Unknown message", 404)
        out["text"] = fs.render(msgs[key], ctx)
        if key in _PAY_BUTTON_KEYS:
            out["button"] = fs.render(msgs.get("pay_button") or "Pay {price}", ctx)[:20]
        if key == "greeting":
            out["faq_buttons"] = [f_["title"] for f_ in (msgs.get("faq") or [])]
        return out
    out["text"] = fs.render(req.get("text") or "", ctx)
    return out


# ---------------------------------------------------------------------------
# Test tools
# ---------------------------------------------------------------------------

def reset_registration(db, org_id: str, funnel_id: str, reg: dict) -> None:
    if reg.get("status") == "paid" or float(reg.get("amount_paid") or 0) > 0:
        raise FunnelToolError("CONFLICT", "This lead has paid — paid records can't be reset.", 409)
    fs.log_event(db, org_id, funnel_id, None, "test_lead_reset", detail={"phone_last4": (reg.get("phone") or "")[-4:]})
    db.table("funnel_registrations").delete().eq("id", reg["id"]).eq("org_id", org_id).execute()


def duplicate_as_test(db, org_id: str, funnel: dict) -> dict:
    """Draft copy for an end-to-end test: window mode, 1-hour window, per-lead timings ÷ 24,
    event reminders switched off (they'd go to real leads' dates)."""
    now = fs._iso(fs._now())
    steps = []
    for s in fs.funnel_sequence(funnel):
        s = dict(s)
        if s["anchor"] in ("first_message", "window_end"):
            s["offset_minutes"] = max(1, int(round(s["offset_minutes"] / 24))) if s["offset_minutes"] > 0 else s["offset_minutes"]
        elif s["anchor"] == "early_deadline":
            s["anchor"] = "window_end"
            s["offset_minutes"] = max(1, int(round(abs(s["offset_minutes"]) / 24))) * (1 if s["offset_minutes"] >= 0 else -1)
        else:
            s["enabled"] = False
        steps.append(s)
    settings = dict(funnel.get("settings") or {})
    settings.update({"pause_minutes_after_reply": 5, "stale_after_minutes": 60, "respect_quiet_hours": False})
    copy = {k: funnel.get(k) for k in (
        "whatsapp_number_id", "event_title", "event_starts_at", "registration_closes_at", "early_price",
        "regular_price", "group_size", "group_price", "currency", "paid_group_link", "prep_group_link",
        "bonus_link", "ad_codes", "messages")}
    copy.update({
        "org_id": org_id, "name": ("TEST — " + (funnel.get("name") or ""))[:120], "status": "draft",
        "pricing_mode": "window", "window_hours": 1, "early_deadline_at": None,
        "sequence": steps, "settings": settings, "created_at": now, "updated_at": now,
    })
    res = db.table("event_funnels").insert(copy).execute()
    return fs._one(res.data) or copy


def gmail_list(db, org_id: str, funnel_id: str) -> dict:
    rows = fs._fetch_all(lambda: db.table("funnel_registrations")
                         .select("id, name, phone, email, seats, lead_id")
                         .eq("org_id", org_id).eq("funnel_id", funnel_id).eq("status", "paid").order("paid_at"))
    emails, missing, seen = [], [], set()
    for r in rows:
        e = (r.get("email") or "").strip().lower()
        if e:
            if e not in seen:
                seen.add(e)
                emails.append(e)
        else:
            missing.append({"id": r["id"], "name": r.get("name"), "phone": r.get("phone"), "seats": r.get("seats")})
    return {"emails": emails, "count": len(emails), "missing": missing, "joined": ", ".join(emails)}


def registration_events(db, org_id: str, funnel_id: str, reg_id: str) -> list[dict]:
    """Timeline for the Leads drawer (newest first, max 200)."""
    return (db.table("funnel_events").select("type, step_key, detail, created_at").eq("org_id", org_id)
            .eq("funnel_id", funnel_id).eq("registration_id", reg_id)
            .order("created_at", desc=True).limit(200).execute()).data or []


def ask_for_gmail(db, org_id: str, funnel: dict, reg: dict) -> bool:
    number_row = fs._number_row_by_id(db, org_id, funnel.get("whatsapp_number_id"))
    if not number_row:
        return False
    text = fs.render("Hi {name} 👋 Please reply with the *Gmail address* you'll use to join the Google Meet "
                     "on {date}, so I can send your invite.", fs.build_context(funnel, reg, fs._now()))
    return funnel_messaging.send_text(db, org_id, number_row, reg["phone"], text, reg.get("lead_id"))


# ---------------------------------------------------------------------------
# Broadcasts
# ---------------------------------------------------------------------------

def _recipients(db, org_id: str, funnel_id: str, audience: str, ad_code: Optional[str]) -> list[dict]:
    statuses = {"unpaid": ["new"], "paid": ["paid"], "all": ["new", "paid"]}[audience]

    def build():
        q = (db.table("funnel_registrations").select("*").eq("org_id", org_id).eq("funnel_id", funnel_id)
             .in_("status", statuses))
        if ad_code:
            q = q.eq("ad_code", ad_code)
        return q.order("created_at")
    return fs._fetch_all(build)


def create_broadcast(db, org_id: str, funnel: dict, payload: dict, user_id: Optional[str]) -> dict:
    recips = _recipients(db, org_id, funnel["id"], payload["audience"], payload.get("ad_code"))
    budget = TemplateBudget.load(db, funnel)
    n = len(recips)
    est = round(n * budget.cost, 2) if budget.cost else None
    summary = {"recipients": n, "estimated_cost": est, "template_budget": budget.as_dict(),
               "within_budget": budget.allow(n) if n else True}
    if payload.get("dry_run"):
        return summary
    if n == 0:
        raise FunnelToolError("VALIDATION_ERROR", "No leads match this segment.")
    if not budget.allow(n):
        raise FunnelToolError(
            "BUDGET_CAP",
            f"This would send {n} template messages but your budget allows {budget.remaining_messages} more "
            f"({fs.format_money(budget.as_dict()['remaining_amount'])} left of {fs.format_money(budget.cap)}). "
            "Narrow the segment or raise the cap in Setup.", 422)
    now = fs._iso(fs._now())
    row = {
        "org_id": org_id, "funnel_id": funnel["id"], "template_name": payload["template_name"],
        "template_params": payload.get("template_params") or [], "language": payload.get("language") or "en",
        "audience": payload["audience"], "ad_code": payload.get("ad_code"), "status": "queued",
        "total": n, "sent": 0, "failed": 0, "created_by": user_id, "created_at": now,
    }
    res = db.table("funnel_broadcasts").insert(row).execute()
    out = fs._one(res.data) or row
    out.update(summary)
    return out


def list_broadcasts(db, org_id: str, funnel_id: str) -> list[dict]:
    return (db.table("funnel_broadcasts").select("*").eq("org_id", org_id).eq("funnel_id", funnel_id)
            .order("created_at", desc=True).limit(100).execute()).data or []


def cancel_broadcast(db, org_id: str, funnel_id: str, broadcast_id: str) -> dict:
    b = fs._one((db.table("funnel_broadcasts").select("*").eq("id", broadcast_id).eq("org_id", org_id)
                 .eq("funnel_id", funnel_id).limit(1).execute()).data)
    if not b:
        raise FunnelToolError("NOT_FOUND", "Broadcast not found", 404)
    if b["status"] not in ("queued", "sending"):
        raise FunnelToolError("CONFLICT", f"Broadcast is already {b['status']}.", 409)
    db.table("funnel_broadcasts").update({"status": "cancelled", "finished_at": fs._iso(fs._now())}) \
        .eq("id", broadcast_id).eq("org_id", org_id).in_("status", ["queued", "sending"]).execute()
    b["status"] = "cancelled"
    return b


def drain_broadcasts(db, funnel: dict, now: datetime) -> dict:
    """Worker: send the next batch of every queued/sending broadcast for this funnel. S14 per recipient."""
    out = {"sent": 0, "failed": 0}
    org_id = funnel["org_id"]
    queue = (db.table("funnel_broadcasts").select("*").eq("org_id", org_id).eq("funnel_id", funnel["id"])
             .in_("status", ["queued", "sending"]).order("created_at").execute()).data or []
    if not queue:
        return out
    from app.utils.org_gates import is_org_active, is_quiet_hours
    org = fs._one((db.table("organisations").select("id, subscription_status, quiet_hours_start, quiet_hours_end, timezone")
                   .eq("id", org_id).limit(1).execute()).data) or {}
    if not is_org_active(org) or is_quiet_hours(org, now):
        return out
    number_row = fs._number_row_by_id(db, org_id, funnel.get("whatsapp_number_id"))
    if not number_row or number_row.get("wa_sales_mode") != "event_funnel":
        return out
    budget = TemplateBudget.load(db, funnel)

    for b in queue:
        key = f"bc_{b['id']}"
        if b["status"] == "queued":
            db.table("funnel_broadcasts").update({"status": "sending"}).eq("id", b["id"]).execute()
        done_ids = {r["registration_id"] for r in fs._fetch_all(
            lambda: db.table("funnel_events").select("registration_id").eq("funnel_id", funnel["id"]).eq("step_key", key))}
        pending = [r for r in _recipients(db, org_id, funnel["id"], b["audience"], b.get("ad_code"))
                   if r["id"] not in done_ids]
        sent = failed = 0
        capped = False
        for reg in pending[:BROADCAST_BATCH]:
            if not budget.allow():
                capped = True
                budget.notify_reached(db)
                break
            try:
                if not fs.log_event(db, org_id, funnel["id"], reg["id"], "broadcast_sent", key,
                                    {"broadcast_id": b["id"]}):
                    continue  # already claimed by another run
                ctx = fs.build_context(funnel, reg, now)
                params = [fs.render(p, ctx) for p in (b.get("template_params") or [])]
                ok = funnel_messaging.send_template(db, org_id, number_row, reg["phone"], b["template_name"],
                                                    params, language=b.get("language") or "en",
                                                    lead_id=reg.get("lead_id"))
                if ok:
                    budget.consume()   # Meta only charges delivered-to-API sends
                    sent += 1
                else:
                    failed += 1
                    db.table("funnel_events").update({"type": "broadcast_failed"}) \
                        .eq("registration_id", reg["id"]).eq("step_key", key).execute()
            except Exception as exc:  # S14
                failed += 1
                logger.warning("drain_broadcasts: recipient failed bc=%s: %s", b["id"], exc)
        update = {"sent": int(b.get("sent") or 0) + sent, "failed": int(b.get("failed") or 0) + failed}
        if capped:
            update.update({"status": "capped", "finished_at": fs._iso(now)})
        elif len(pending) <= BROADCAST_BATCH:
            update.update({"status": "done", "finished_at": fs._iso(now)})
        db.table("funnel_broadcasts").update(update).eq("id", b["id"]).in_("status", ["queued", "sending"]).execute()
        out["sent"] += sent
        out["failed"] += failed
        if capped:
            break
    return out
