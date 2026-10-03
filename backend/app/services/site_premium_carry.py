"""
app/services/site_premium_carry.py
-----------------------------------
SITE-PREMIUM P5-a - when a customer tries another design, their own look choices follow them where they fit:

  * the brand colour they picked (only when they really picked one; a colour the first design came with is not
    carried, so the new design keeps its own),
  * sections they hid, section heading sizes, and section colours - for sections that exist in BOTH designs.

Text and photos are not handled here: they live in the site's content, apart from the design, so every design
already shows them.

Each choice is applied on its own through plan_tweak, so every readability rule (contrast, brand-colour rules,
fixed colour set, no hiding the footer) still holds. A choice that does not fit the new design is skipped and
recorded, never forced. Nothing here raises: the redesign is already made, this only tidies it.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.services import site_premium_sections as sections
from app.services import site_premium_tweaks as tweaks
from app.services.site_ops_service import ValidationFailed

logger = logging.getLogger(__name__)

CHAIN_HOPS = 10


def _one(data):
    return (data or [None])[0] if isinstance(data, list) else data


def _accent_picked_in_chain(db: Any, org_id: str, design: dict) -> bool:
    """Older versions did not mark a customer's colour, so look back along the tweak versions for one."""
    cur = design
    for _ in range(CHAIN_HOPS):
        if cur.get("kind") != "patch":
            return False
        changes = (((cur.get("checks") or {}).get("tweak") or {}).get("changes")) or {}
        if "accent" in changes:
            return True
        parent = cur.get("parent_id")
        if not parent:
            return False
        cur = _one(db.table("site_designs").select("id, kind, parent_id, checks").eq("id", parent).eq("org_id", org_id)
                   .limit(1).execute().data) or {}
        if not cur:
            return False
    return False


def customer_choices(db: Any, org_id: str, site: dict) -> dict:
    """What the customer chose on the design that is live now."""
    if not site.get("current_design_id"):
        return {}
    cur = _one(db.table("site_designs").select("*").eq("id", site["current_design_id"]).eq("org_id", org_id)
               .limit(1).execute().data)
    if not cur:
        return {}
    art = cur.get("art_direction") or {}
    accent = None
    if art.get("customer_accent") or _accent_picked_in_chain(db, org_id, cur):
        accent = (art.get("accent_hex") or tweaks.current_tokens(cur).get("--accent") or "").upper() or None
    return {"accent": accent, "colours": dict(art.get("section_colours") or {}),
            "hidden": list(art.get("section_hidden") or []), "sizes": dict(art.get("section_size") or {})}


def _try(design: dict, content: dict, assets_by_id: dict, niche: Optional[str], **kw) -> tuple[dict, Optional[str]]:
    """One tweak. Returns (the design with it applied, or the same design) and a skip reason."""
    try:
        plan = tweaks.plan_tweak(design, content, assets_by_id, niche, **kw)
    except ValidationFailed as exc:
        text = str(exc)
        return design, (None if "already your current look" in text else text)
    except Exception as exc:  # S14
        logger.warning("site_premium_carry: tweak failed: %s", exc)
        return design, "It could not be applied."
    return {**design, "tokens": plan["tokens"], "art_direction": plan["art_direction"]}, None


def carry_over(choices: dict, design: dict, content: dict, assets_by_id: dict, niche: Optional[str]) -> tuple[dict, dict]:
    """Applies the customer's choices to a new design. Returns (the design, a report)."""
    report: dict = {"accent": False, "sections": [], "hidden": [], "sizes": [], "skipped": []}
    if not choices:
        return design, report
    valid = set(sections.section_names(design.get("skeleton_html") or ""))
    if choices.get("accent"):
        design, why = _try(design, content, assets_by_id, niche, accent=choices["accent"])
        if why:
            report["skipped"].append("brand colour")
        elif (design.get("art_direction") or {}).get("accent_hex") == choices["accent"]:
            report["accent"] = True
    for name, key in (choices.get("colours") or {}).items():
        if name not in valid:
            continue
        design, why = _try(design, content, assets_by_id, niche, section_colours={name: key})
        (report["skipped"].append(f"{name} colour") if why else report["sections"].append(name))
    for name in choices.get("hidden") or []:
        if name not in valid:
            continue
        design, why = _try(design, content, assets_by_id, niche, section_layout={name: {"show": False}})
        (report["skipped"].append(f"{name} hidden") if why else report["hidden"].append(name))
    for name, size in (choices.get("sizes") or {}).items():
        if name not in valid:
            continue
        design, why = _try(design, content, assets_by_id, niche, section_layout={name: {"size": size}})
        (report["skipped"].append(f"{name} size") if why else report["sizes"].append(name))
    return design, report


def carried_note(report: Optional[dict]) -> Optional[str]:
    """A plain sentence for the customer, or None when nothing was carried."""
    if not report:
        return None
    parts = []
    if report.get("accent"):
        parts.append("your brand colour")
    if report.get("sections") or report.get("hidden") or report.get("sizes"):
        parts.append("your section choices")
    if not parts:
        return None
    return "We kept " + " and ".join(parts) + " where they fit this design."


def carry_into_row(db: Any, org_id: str, site: dict, row: dict, content: dict, assets_by_id: dict, niche: Optional[str]) -> dict:
    """Applies the customer's choices to the held-back redesign row and saves it. S14: never raises."""
    try:
        choices = customer_choices(db, org_id, site)
        if not choices or not (choices.get("accent") or choices.get("colours") or choices.get("hidden") or choices.get("sizes")):
            return {}
        new_design, report = carry_over(choices, row, content, assets_by_id, niche)
        checks = dict(row.get("checks") or {})
        checks["carried"] = report
        patch = {"checks": checks}
        if new_design is not row:
            patch["tokens"] = new_design.get("tokens") or row.get("tokens")
            patch["art_direction"] = new_design.get("art_direction") or row.get("art_direction")
        db.table("site_designs").update(patch).eq("id", row["id"]).eq("org_id", org_id).execute()
        return report
    except Exception as exc:  # S14
        logger.warning("site_premium_carry: carry-over failed design=%s: %s", row.get("id"), exc)
        return {}
