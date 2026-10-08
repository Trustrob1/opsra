"""
app/services/site_giveaway_service.py
---------------------------------------
GIVEAWAY-1 — a group owner (a Launch Partner) is given N free website slots (default 5). Group members open the
giveaway link /g/{slug}, agree that the finished site is shown in the group, and fill the normal client brief form.
The slot is claimed when the form is SUBMITTED (first N complete submissions win), never when it is merely opened.

  get_public()   slots left, fee, renewal and edit terms for the public page
  open_entry()   contact details + consent -> a fresh client brief form owned by the group owner's builder + an 'opened' entry
  claim_slot()   called by the form submit route just before the site is created; raises GiveawayFull when none left
                 and GiveawayDuplicate when the same WhatsApp number already holds a slot
  attach_site()  records the created site on the entry
  on_won()       after the site exists: private winner link by email + WhatsApp, and an alert to Opsra staff
  winner_view() / winner_checkout() / winner_domain_check()   the winner's private page (/w/{token}): preview,
                 and paying the giveaway fee through the normal order + hosting pipeline
  list/create/set_status/entries/void_slot   staff

Atomic claim: (giveaway_id, position) is unique, so two simultaneous submissions can never take the same slot.
Allowed site types are whatever the active presets are (WhatsApp-contact one-pagers); there is no web-app or
full-store preset, so nothing extra is needed to keep those out.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PAID_STATES = ("awaiting_approval", "fulfilling", "live", "needs_builder_choice")
MAX_OPEN_FORMS_PER_DAY = 300        # unsubmitted forms per giveaway per day (abuse cap)
_CLAIM_TRIES = 6


class GiveawayError(Exception):
    """User-correctable problem (shown to staff)."""


class GiveawayFull(Exception):
    """No free slot left when a form is submitted."""


class GiveawayDuplicate(Exception):
    """This WhatsApp number already holds a slot in this giveaway."""


class WinnerError(Exception):
    """A winner-page problem with a user-safe message. status_code is the HTTP status the router uses."""
    def __init__(self, message: str, status_code: int = 422, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.status_code, self.code = status_code, code


_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")
FEE_MIN, FEE_MAX = 1000, 10_000_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def giveaway_url(slug: str) -> str:
    import os
    base = os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/")
    return f"{base}/g/{slug}"


def _winners(db: Any, giveaway_id: str) -> int:
    rows = (db.table("site_giveaway_entries").select("id").eq("giveaway_id", giveaway_id)
            .eq("status", "winner").limit(1000).execute()).data or []
    return len(rows)


# ───────────────────────────── staff ─────────────────────────────

def _money_int(value, label: str, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        raise GiveawayError(f"{label} must be a number.")
    if not (FEE_MIN <= n <= FEE_MAX):
        raise GiveawayError(f"{label} must be between ₦{FEE_MIN:,} and ₦{FEE_MAX:,}.")
    return n


def create_giveaway(db: Any, org_id: str, partner_id: str, title: str, total_slots: int = 5,
                    fee_ngn=None, renewal_ngn=None) -> dict:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    if not (3 <= len(title) <= 120):
        raise GiveawayError("Please enter a title for the giveaway.")
    try:
        slots = int(total_slots)
    except (TypeError, ValueError):
        raise GiveawayError("Slots must be a number.")
    if not (1 <= slots <= 100):
        raise GiveawayError("Slots must be between 1 and 100.")
    fee = _money_int(fee_ngn, "The domain and hosting fee", 24500)
    renewal = _money_int(renewal_ngn, "The yearly renewal", 25000)
    partner = _one((db.table("site_partners").select("*").eq("id", partner_id).eq("org_id", org_id).limit(1).execute()).data)
    if not partner:
        raise GiveawayError("Choose a group owner (partner) first.")
    if partner.get("status") != "active":
        raise GiveawayError("That partner is suspended.")
    row = None
    for _ in range(5):
        cand = {"org_id": org_id, "partner_id": partner_id, "title": title, "total_slots": slots,
                "fee_ngn": fee, "renewal_ngn": renewal,
                "slug": secrets.token_urlsafe(7), "status": "active", "created_at": _iso(), "updated_at": _iso()}
        try:
            row = _one(db.table("site_giveaways").insert(cand).execute().data) or cand
            break
        except Exception as exc:
            logger.warning("[GIVEAWAY-1] slug retry: %s", exc)
    if not row:
        raise GiveawayError("Could not create the giveaway. Please try again.")
    return {**row, "link_url": giveaway_url(row["slug"]), "taken": 0, "left": slots}


def list_giveaways(db: Any, org_id: str) -> list[dict]:
    rows = (db.table("site_giveaways").select("*").eq("org_id", org_id).order("created_at", desc=True).limit(200).execute()).data or []
    partners = {p["id"]: p for p in (db.table("site_partners").select("id,full_name,agency_name").eq("org_id", org_id)
                                     .limit(1000).execute()).data or []}
    out = []
    for r in rows:
        taken = _winners(db, r["id"])
        p = partners.get(r["partner_id"]) or {}
        out.append({**r, "link_url": giveaway_url(r["slug"]), "taken": taken, "left": max(0, r["total_slots"] - taken),
                    "owner_name": p.get("agency_name") or p.get("full_name")})
    return out


def set_status(db: Any, org_id: str, giveaway_id: str, status: str) -> Optional[dict]:
    if status not in ("active", "closed"):
        raise GiveawayError("Status must be active or closed.")
    res = (db.table("site_giveaways").update({"status": status, "updated_at": _iso()})
           .eq("id", giveaway_id).eq("org_id", org_id).execute())
    return _one(res.data)


def entries(db: Any, org_id: str, giveaway_id: str) -> list[dict]:
    rows = (db.table("site_giveaway_entries").select("*").eq("org_id", org_id).eq("giveaway_id", giveaway_id)
            .eq("status", "winner").order("position").limit(200).execute()).data or []
    out = []
    for e in rows:
        site = _one((db.table("sites").select("client_business_name,status,live_url").eq("id", e["site_id"]).limit(1).execute()).data) if e.get("site_id") else None
        out.append({"position": e.get("position"), "claimed_at": e.get("claimed_at"), "site_id": e.get("site_id"),
                    "business_name": (site or {}).get("client_business_name"), "site_status": (site or {}).get("status"),
                    "live_url": (site or {}).get("live_url"),
                    "contact_name": e.get("contact_name"), "contact_phone": e.get("contact_phone"),
                    "contact_email": e.get("contact_email"),
                    "paid": bool(site and _initial_order_paid(db, e["site_id"]))})
    return out


def _initial_order_paid(db: Any, site_id: str) -> bool:
    rows = (db.table("site_orders").select("id,status,kind").eq("site_id", site_id).eq("kind", "initial")
            .limit(50).execute()).data or []
    return any(r.get("status") in _PAID_STATES for r in rows)


def void_slot(db: Any, org_id: str, giveaway_id: str, position: int) -> dict:
    """Staff: take a slot back (no-show, fake or unsuitable entry). Refused once the winner has paid.
    The slot is free again for the next member; the winner link stops working."""
    entry = _one((db.table("site_giveaway_entries").select("*").eq("org_id", org_id).eq("giveaway_id", giveaway_id)
                  .eq("position", position).eq("status", "winner").limit(1).execute()).data)
    if not entry:
        raise GiveawayError("That slot isn't taken.")
    if entry.get("site_id") and _initial_order_paid(db, entry["site_id"]):
        raise GiveawayError("This winner has already paid, so the slot can't be voided here.")
    if entry.get("site_id"):
        db.table("sites").update({"deleted_at": _iso(), "updated_at": _iso()}).eq("id", entry["site_id"])             .eq("org_id", org_id).execute()
    db.table("site_giveaway_entries").update({"status": "voided", "position": None, "winner_token_hash": None})         .eq("id", entry["id"]).execute()
    return {"position": position, "status": "voided"}


# ───────────────────────────── public ─────────────────────────────

def _by_slug(db: Any, slug: str) -> Optional[dict]:
    if not slug or len(slug) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        return None
    return _one((db.table("site_giveaways").select("*").eq("slug", slug).limit(1).execute()).data)


def _terms(db: Any, org_id: str) -> dict:
    """The edit and care-plan terms shown to members, read from the live settings so they never drift from billing."""
    from app.services import pricing_service, site_care_plan_service
    cfg = site_care_plan_service.get_config(pricing_service.get_settings(db, org_id))
    limits = []
    try:
        presets = (db.table("site_presets").select("max_items").eq("org_id", org_id).eq("is_active", True).limit(50).execute()).data or []
        limits = [int(p["max_items"]) for p in presets if p.get("max_items")]
    except Exception:  # S14
        logger.warning("[GIVEAWAY-1] preset limits unavailable")
    return {"free_edits": cfg["free_edits"], "care_price_ngn": cfg["price_ngn"], "care_edits_per_month": cfg["edits_per_month"],
            "pack_price_ngn": cfg["pack_price_ngn"], "pack_edits": cfg["pack_edits"],
            "edit_item_cap": site_care_plan_service.EDIT_ITEM_CAP, "max_items": min(limits) if limits else None}


def get_public(db: Any, slug: str) -> Optional[dict]:
    g = _by_slug(db, slug)
    if not g:
        return None
    partner = _one((db.table("site_partners").select("full_name,agency_name,status").eq("id", g["partner_id"]).limit(1).execute()).data) or {}
    taken = _winners(db, g["id"])
    left = max(0, g["total_slots"] - taken)
    is_open = g["status"] == "active" and partner.get("status") == "active" and left > 0
    return {"title": g["title"], "owner_name": partner.get("agency_name") or partner.get("full_name"),
            "total": g["total_slots"], "taken": min(taken, g["total_slots"]), "left": left,
            "status": g["status"], "open": is_open,
            "fee_ngn": g.get("fee_ngn") or 24500, "renewal_ngn": g.get("renewal_ngn") or 25000,
            "terms": _terms(db, g["org_id"])}


def _clean_contact(contact: Optional[dict]) -> dict:
    from app.services import builder_login_service
    contact = contact or {}
    name = re.sub(r"\s+", " ", str(contact.get("name") or "")).strip()
    email = str(contact.get("email") or "").strip().lower()
    variants = builder_login_service.phone_variants(str(contact.get("phone") or ""))
    if not (2 <= len(name) <= 80):
        raise GiveawayError("Please enter your name.")
    if not _EMAIL_RE.match(email) or len(email) > 255:
        raise GiveawayError("Please enter a valid email address.")
    if not variants:
        raise GiveawayError("Please enter a valid WhatsApp number.")
    return {"name": name, "email": email, "phone": variants[1]}      # digits, no '+': one spelling per number


def _phone_holds_slot(db: Any, giveaway_id: str, phone: str, exclude_entry_id: Optional[str] = None) -> bool:
    rows = (db.table("site_giveaway_entries").select("id").eq("giveaway_id", giveaway_id).eq("status", "winner")
            .eq("contact_phone", phone).limit(5).execute()).data or []
    return any(r.get("id") != exclude_entry_id for r in rows)


def open_entry(db: Any, slug: str, consent: bool, contact: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    """{"kind": ok|full|closed|not_found|consent_required|invalid|duplicate|busy, "url"?, "message"?}"""
    now = now or _now()
    g = _by_slug(db, slug)
    if not g:
        return {"kind": "not_found"}
    if consent is not True:
        return {"kind": "consent_required"}
    try:
        who = _clean_contact(contact)
    except GiveawayError as exc:
        return {"kind": "invalid", "message": str(exc)}
    partner = _one((db.table("site_partners").select("*").eq("id", g["partner_id"]).limit(1).execute()).data)
    builder = _one((db.table("site_builders").select("*").eq("id", partner["builder_id"]).eq("org_id", g["org_id"]).limit(1).execute()).data) if partner else None
    if g["status"] != "active" or not partner or partner.get("status") != "active" or not builder or builder.get("status") != "active":
        return {"kind": "closed"}
    if max(0, g["total_slots"] - _winners(db, g["id"])) <= 0:
        return {"kind": "full"}
    if _phone_holds_slot(db, g["id"], who["phone"]):
        return {"kind": "duplicate"}
    since = _iso(now - timedelta(days=1))
    recent = (db.table("site_giveaway_entries").select("id").eq("giveaway_id", g["id"]).eq("status", "opened")
              .gte("created_at", since).limit(MAX_OPEN_FORMS_PER_DAY + 1).execute()).data or []
    if len(recent) > MAX_OPEN_FORMS_PER_DAY:
        return {"kind": "busy"}
    from app.services import site_chat_service
    form, url = site_chat_service.create_form_link(db, g["org_id"], builder, "client", client_label=f"Giveaway: {g['title']}"[:120])
    db.table("site_giveaway_entries").insert({
        "org_id": g["org_id"], "giveaway_id": g["id"], "form_id": form.get("id"), "status": "opened",
        "contact_name": who["name"], "contact_phone": who["phone"], "contact_email": who["email"],
        "consent_at": _iso(now), "created_at": _iso(now),
    }).execute()
    return {"kind": "ok", "url": url}


# ───────────────────────────── claim (called from the form submit route) ─────────────────────────────

def _hash(raw: str) -> str:
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def claim_slot(db: Any, form: dict) -> Optional[dict]:
    """None when this form isn't part of a giveaway. Otherwise the entry now holding a slot, with a transient
    "_winner_token" (the raw private link token, never stored) when one was just issued.
    Raises GiveawayFull when every slot is taken, GiveawayDuplicate when this WhatsApp number already holds one.
    Idempotent for a form that already holds a slot."""
    if not form or not form.get("id"):
        return None
    entry = _one((db.table("site_giveaway_entries").select("*").eq("form_id", form["id"]).limit(1).execute()).data)
    if not entry:
        return None
    from app.models.sites import generate_form_token
    if entry.get("status") == "winner":
        if entry.get("site_id"):
            return entry
        raw, hashed = generate_form_token()       # claimed but the site never got created: reissue the link
        db.table("site_giveaway_entries").update({"winner_token_hash": hashed}).eq("id", entry["id"]).execute()
        return {**entry, "_winner_token": raw}
    g = _one((db.table("site_giveaways").select("*").eq("id", entry["giveaway_id"]).limit(1).execute()).data)
    if not g or g["status"] != "active":
        raise GiveawayFull()
    if entry.get("contact_phone") and _phone_holds_slot(db, g["id"], entry["contact_phone"], entry["id"]):
        raise GiveawayDuplicate()
    for _ in range(_CLAIM_TRIES):
        taken = (db.table("site_giveaway_entries").select("position").eq("giveaway_id", g["id"])
                 .eq("status", "winner").limit(1000).execute()).data or []
        if len(taken) >= g["total_slots"]:
            raise GiveawayFull()
        pos = max([int(t["position"]) for t in taken if t.get("position") is not None] or [0]) + 1
        raw, hashed = generate_form_token()
        try:
            res = (db.table("site_giveaway_entries").update({"status": "winner", "position": pos, "claimed_at": _iso(),
                                                              "winner_token_hash": hashed})
                   .eq("id", entry["id"]).execute())
            return {**(_one(res.data) or {**entry, "status": "winner", "position": pos}), "_winner_token": raw}
        except Exception as exc:        # unique (giveaway_id, position) or (giveaway_id, phone): lost a race, look again
            logger.info("[GIVEAWAY-1] claim retry: %s", exc)
            if entry.get("contact_phone") and _phone_holds_slot(db, g["id"], entry["contact_phone"], entry["id"]):
                raise GiveawayDuplicate()
    raise GiveawayFull()


def attach_site(db: Any, entry: Optional[dict], site_id: str) -> None:
    if not entry or not site_id:
        return
    try:
        db.table("site_giveaway_entries").update({"site_id": site_id}).eq("id", entry["id"]).execute()
    except Exception:  # S14 - the site exists either way
        logger.exception("[GIVEAWAY-1] attach_site failed entry=%s", entry.get("id"))


def winner_url(raw_token: str) -> str:
    import os
    base = os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/")
    return f"{base}/w/{raw_token}"


def on_won(db: Any, entry: Optional[dict], site_name: str = "") -> Optional[str]:
    """After the site exists: send the private winner link (email + WhatsApp) and alert staff. Never raises (S14).
    Returns the winner URL, or None when this form isn't a giveaway entry / no new link was issued."""
    raw = (entry or {}).get("_winner_token")
    if not entry or not raw:
        return None
    url = winner_url(raw)
    try:
        g = _one((db.table("site_giveaways").select("*").eq("id", entry["giveaway_id"]).limit(1).execute()).data) or {}
        name = entry.get("contact_name") or "there"
        first = name.split(" ")[0]
        text = (f"Hi {first}, you've won a free website slot ({g.get('title', 'giveaway')}).\n\n"
                f"Your private page: {url}\n\n"
                "Your preview will appear there within 24 hours. You only pay the domain and hosting fee "
                "after you've seen it. Please keep this link private.")
        sent = False
        try:
            from app.services import site_partner_apply_service
            sent = site_partner_apply_service._send_email(entry.get("contact_email"), "Your free website slot", text)
        except Exception:
            logger.exception("[GIVEAWAY-1] winner email failed")
        try:
            partner = _one((db.table("site_partners").select("builder_id").eq("id", g.get("partner_id")).limit(1).execute()).data) or {}
            builder = _one((db.table("site_builders").select("*").eq("id", partner.get("builder_id")).limit(1).execute()).data)
            number_row = _one((db.table("whatsapp_numbers").select("*").eq("org_id", entry["org_id"])
                               .eq("wa_sales_mode", "site_builder").limit(1).execute()).data) if builder else None
            if number_row and entry.get("contact_phone"):
                from app.services.whatsapp_service import send_agent_text_message
                send_agent_text_message(db=db, org_id=entry["org_id"], phone_number=str(entry["contact_phone"]).lstrip("+"),
                                        lead_id=None, message=text, phone_id=number_row.get("phone_id"),
                                        access_token=number_row.get("access_token"))
        except Exception:
            logger.warning("[GIVEAWAY-1] winner WhatsApp not sent (needs an open 24h window until templates are approved)")
        try:
            from app.services import funnel_service
            funnel_service.notify_managers(
                db, entry["org_id"], f"Giveaway slot won: {site_name or 'new site'}",
                f"{g.get('title', 'Giveaway')} · slot {entry.get('position')} of {g.get('total_slots')} · "
                f"{entry.get('contact_name')} {entry.get('contact_phone')}" + ("" if sent else " · email not sent"),
                "giveaway_slot_won", None)
        except Exception:
            logger.warning("[GIVEAWAY-1] staff alert failed")
    except Exception:
        logger.exception("[GIVEAWAY-1] on_won failed entry=%s", entry.get("id"))
    return url


# ───────────────────────────── the winner's private page ─────────────────────────────

def _winner_context(db: Any, raw_token: str):
    if not raw_token or len(raw_token) > 128:
        raise WinnerError("This link isn't valid.", 404, "NOT_FOUND")
    entry = _one((db.table("site_giveaway_entries").select("*").eq("winner_token_hash", _hash(raw_token))
                  .eq("status", "winner").limit(1).execute()).data)
    if not entry:
        raise WinnerError("This link isn't valid.", 404, "NOT_FOUND")
    g = _one((db.table("site_giveaways").select("*").eq("id", entry["giveaway_id"]).limit(1).execute()).data)
    if not g:
        raise WinnerError("This link isn't valid.", 404, "NOT_FOUND")
    site = _one((db.table("sites").select("*").eq("id", entry["site_id"]).is_("deleted_at", "null").limit(1).execute()).data) if entry.get("site_id") else None
    return entry, g, site


def winner_view(db: Any, raw_token: str) -> dict:
    import os
    entry, g, site = _winner_context(db, raw_token)
    partner = _one((db.table("site_partners").select("full_name,agency_name").eq("id", g["partner_id"]).limit(1).execute()).data) or {}
    stage, preview_url, can_pay, live_url = "building", None, False, None
    if site:
        paid = _initial_order_paid(db, site["id"])
        st = site.get("status")
        if st == "live" or site.get("live_url"):
            stage, live_url = "live", site.get("live_url")
        elif paid:
            stage = "going_live"
        elif st in ("preview_ready", "revising") and site.get("slug"):
            stage, can_pay = "preview", True
        if site.get("slug") and site.get("rendered_html"):
            base = os.getenv("PUBLIC_API_URL", "https://opsra.onrender.com").rstrip("/")
            preview_url = f"{base}/s/{site['slug']}"
    return {"stage": stage, "business_name": (site or {}).get("client_business_name"),
            "group_name": g["title"], "owner_name": partner.get("agency_name") or partner.get("full_name"),
            "position": entry.get("position"), "preview_url": preview_url, "live_url": live_url,
            "can_pay": can_pay, "fee_ngn": g.get("fee_ngn") or 24500, "renewal_ngn": g.get("renewal_ngn") or 25000,
            "terms": _terms(db, g["org_id"]),
            "contact": {"name": entry.get("contact_name"), "email": entry.get("contact_email"), "phone": entry.get("contact_phone")}}


def winner_domain_check(db: Any, raw_token: str, domain: str) -> dict:
    from app.services import domain_check_service
    entry, g, _site = _winner_context(db, raw_token)
    try:
        return domain_check_service.check_domain(db, g["org_id"], f"giveaway:{entry['id']}", domain)
    except domain_check_service.RateLimited as exc:
        raise WinnerError(str(exc), 429, "RATE_LIMITED")
    except domain_check_service.InvalidDomain as exc:
        raise WinnerError(str(exc))


def winner_checkout(db: Any, raw_token: str, body: dict) -> dict:
    """The winner pays the giveaway's fee (never a number from the browser) through the normal order + hosting pipeline."""
    from pydantic import ValidationError
    from app.models.sites import CheckoutRequest
    from app.services import pricing_service, site_access_service, site_order_service
    entry, g, site = _winner_context(db, raw_token)
    if not site:
        raise WinnerError("Your site is not ready yet. Please check back once your preview is ready.", 409, "NOT_READY")
    if _initial_order_paid(db, site["id"]):
        raise WinnerError("Payment has already been received for this site.", 409, "ALREADY_PAID")
    if site.get("status") not in ("preview_ready", "revising"):
        raise WinnerError("Your preview isn't ready yet. You can pay once you've seen it.", 409, "NOT_READY")
    body = body or {}
    owner = body.get("legal_owner") or {}
    try:
        req = CheckoutRequest(
            site_id=site["id"], route="standard", domain=str(body.get("domain") or ""),
            backup_domain=str(body.get("backup_domain") or ""),
            legal_owner={"full_name": owner.get("full_name"), "email": owner.get("email"),
                         "phone": owner.get("phone"), "address": owner.get("address")},
            accepted_terms=body.get("accepted_terms") is True)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        msg = str(first.get("msg", "Please check your details")).replace("Value error, ", "")
        raise WinnerError(msg)
    partner = _one((db.table("site_partners").select("builder_id").eq("id", g["partner_id"]).limit(1).execute()).data)
    builder = _one((db.table("site_builders").select("*").eq("id", partner["builder_id"]).eq("org_id", g["org_id"]).limit(1).execute()).data) if partner else None
    if not builder:
        raise WinnerError("This giveaway can't take payments right now. Please contact the organisers.", 503, "UNAVAILABLE")
    if not site_access_service.ensure_lead(db, g["org_id"], builder):
        raise WinnerError("We couldn't start your payment just now. Please try again shortly.", 503, "UNAVAILABLE")
    try:
        return site_order_service.create_checkout(db, g["org_id"], builder, req, fixed_amount=g.get("fee_ngn") or 24500)
    except site_order_service.SiteNotFound:
        raise WinnerError("Site not found.", 404, "NOT_FOUND")
    except (site_order_service.CheckoutBlocked, pricing_service.PricingError) as exc:
        raise WinnerError(str(exc))
