"""
app/services/site_partner_service.py
--------------------------------------
PARTNER-1A — Launch Partners (CAC agents who refer businesses for a website).

A partner is a `site_partners` row linked to a `site_builders` row, so the existing brief form,
WhatsApp notification and site creation all work unchanged (the form's builder_id is the partner's
linked builder). The partner's permanent link is `/p/{link_slug}` on the frontend; every visit mints
a NEW single-client brief form (audience "client") and sends the visitor to it.

Never raises past its callers for lookup problems (S14): open_link() returns a result kind instead.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

PARTNER_FORM_LABEL = "partner-link"   # stamped on every form opened through a partner link, so referrals can be told apart
PARTNER_MAX_ACTIVE_SITES = 100000      # partners are never held to the builder free-site limit
MAX_UNSUBMITTED_FORMS_PER_DAY = 200    # abuse cap: forms opened through one link and not yet submitted
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O/1/I/L


class PartnerError(Exception):
    """A user-correctable problem (shown to Opsra staff)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _new_code() -> str:
    return "OP" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(5))


def _new_slug() -> str:
    return secrets.token_urlsafe(9)       # 12 URL-safe chars, unguessable


def partner_link_url(slug: str) -> str:
    import os
    base = os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/")
    return f"{base}/p/{slug}"


def create_partner(db: Any, org_id: str, full_name: str, phone: str, email: Optional[str] = None,
                   agency_name: Optional[str] = None) -> dict:
    """Create (or link) the builder row, then the partner row. Returns the partner row plus its link."""
    from app.services import builder_login_service
    name = re.sub(r"\s+", " ", str(full_name or "")).strip()
    if not (2 <= len(name) <= 80):
        raise PartnerError("Please enter the partner's name.")
    variants = builder_login_service.phone_variants(str(phone or ""))
    if not variants:
        raise PartnerError("Please enter a valid WhatsApp number.")
    digits = variants[1]
    email = (str(email or "").strip().lower() or None)
    agency = (re.sub(r"\s+", " ", str(agency_name or "")).strip()[:200] or None)

    builder = _one((db.table("site_builders").select("*").eq("org_id", org_id)
                    .in_("phone_number", [variants[0], variants[1]]).limit(1).execute()).data)
    if builder:
        already = _one((db.table("site_partners").select("id").eq("org_id", org_id)
                        .eq("builder_id", builder["id"]).limit(1).execute()).data)
        if already:
            raise PartnerError("This number is already a partner.")
        updates = {"max_active_sites": PARTNER_MAX_ACTIVE_SITES, "status": "active", "updated_at": _iso()}
        if agency and not builder.get("business_name"):
            updates["business_name"] = agency
        db.table("site_builders").update(updates).eq("id", builder["id"]).eq("org_id", org_id).execute()
        builder = {**builder, **updates}
    else:
        row = {
            "org_id": org_id, "phone_number": digits, "full_name": name, "email": email,
            "business_name": agency, "status": "active", "source": "manual", "account_type": "builder",
            "max_active_sites": PARTNER_MAX_ACTIVE_SITES, "approved_orders_count": 0, "joined_at": _iso(),
        }
        builder = _one(db.table("site_builders").insert(row).execute().data) or row

    partner = None
    for _ in range(5):                    # retry on the (very unlikely) code/slug collision
        row = {
            "org_id": org_id, "builder_id": builder["id"], "full_name": name, "phone_number": digits,
            "email": email, "agency_name": agency, "partner_code": _new_code(), "link_slug": _new_slug(),
            "status": "active", "created_at": _iso(), "updated_at": _iso(),
        }
        try:
            partner = _one(db.table("site_partners").insert(row).execute().data) or row
            break
        except Exception as exc:          # unique violation → try fresh values
            logger.warning("[PARTNER-1A] partner insert retry: %s", exc)
    if not partner:
        raise PartnerError("Could not create the partner. Please try again.")
    return {**partner, "link_url": partner_link_url(partner["link_slug"])}


def set_status(db: Any, org_id: str, partner_id: str, status: str) -> Optional[dict]:
    if status not in ("active", "suspended"):
        raise PartnerError("Status must be active or suspended.")
    res = (db.table("site_partners").update({"status": status, "updated_at": _iso()})
           .eq("id", partner_id).eq("org_id", org_id).execute())
    return _one(res.data)


def list_partners(db: Any, org_id: str) -> list[dict]:
    rows = (db.table("site_partners").select("*").eq("org_id", org_id)
            .order("created_at", desc=True).limit(500).execute()).data or []
    return [{**r, "link_url": partner_link_url(r["link_slug"])} for r in rows]


def open_link(db: Any, slug: str, now: Optional[datetime] = None) -> dict:
    """Mint a fresh client brief form for the partner that owns `slug`.
    Returns {"kind": "ok", "url": ...} | {"kind": "inactive"} | {"kind": "not_found"} | {"kind": "busy"}."""
    now = now or _now()
    if not slug or len(slug) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        return {"kind": "not_found"}
    partner = _one((db.table("site_partners").select("*").eq("link_slug", slug).limit(1).execute()).data)
    if not partner:
        return {"kind": "not_found"}
    if partner.get("status") != "active":
        return {"kind": "inactive"}
    builder = _one((db.table("site_builders").select("*").eq("id", partner["builder_id"])
                    .eq("org_id", partner["org_id"]).limit(1).execute()).data)
    if not builder or builder.get("status") not in ("active",):
        return {"kind": "inactive"}

    since = _iso(now - timedelta(days=1))
    recent = (db.table("site_brief_forms").select("id").eq("org_id", partner["org_id"])
              .eq("builder_id", builder["id"]).eq("status", "open").gte("created_at", since)
              .limit(MAX_UNSUBMITTED_FORMS_PER_DAY + 1).execute()).data or []
    if len(recent) > MAX_UNSUBMITTED_FORMS_PER_DAY:
        return {"kind": "busy"}

    from app.services import site_chat_service
    _form, url = site_chat_service.create_form_link(db, partner["org_id"], builder, "client", client_label=PARTNER_FORM_LABEL)
    return {"kind": "ok", "url": url}
