"""
app/services/stock_alert_service.py
-----------------------------------
STOCK-3 - daily low-stock alert.

An item is low when what's available (all locations together) is at or below its reorder level (the item's own,
else Inventory > Settings' default) - the same rule the Inventory screen uses. Managers get an Opsra notification and
owners get an email. Only items whose stock moved since the last alert are included, so an item that is low and
untouched isn't repeated every day. The first alert lists everything that is low.
"""
from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from app.services import inventory_service as stock

logger = logging.getLogger(__name__)

MAX_LISTED = 30


def _rows(res) -> list:
    data = getattr(res, "data", None)
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def _moved_items(db, org_id: str, since: Optional[str]) -> Optional[set]:
    """(product_id, variant) of items whose stock changed since the last alert. None = no earlier alert (all count)."""
    if not since:
        return None
    moves = _rows(db.table("stock_moves").select("item_id").eq("org_id", org_id).gt("created_at", since)
                  .limit(5000).execute())
    ids = list({m["item_id"] for m in moves})
    if not ids:
        return set()
    items = _rows(db.table("stock_items").select("id, product_id, variant").eq("org_id", org_id).in_("id", ids).execute())
    return {(i["product_id"], i.get("variant") or "") for i in items}


def low_items(db, org_id: str, since: Optional[str] = None) -> list:
    rows = stock.overview(db, org_id, manager=False, low_only=True)["items"]
    rows = [r for r in rows if r.get("product_active") and not r.get("old_size")]
    moved = _moved_items(db, org_id, since)
    if moved is not None:
        rows = [r for r in rows if (r["product_id"], r["variant"] or "") in moved]
    return rows


def _line(r: dict) -> str:
    name = f"{r.get('title') or 'Item'}{f' - ' + r['variant'] if r.get('variant') else ''}"
    return f"{name}: {r['available']} left (reorder at {r['reorder_level']})"


def _owner_emails(db, org_id: str) -> list:
    rows = _rows(db.table("users").select("email, is_active, roles(template)").eq("org_id", org_id).execute())
    out = []
    for r in rows:
        role = r.get("roles") or {}
        role = role[0] if isinstance(role, list) and role else role
        if r.get("is_active") is not False and (role or {}).get("template") == "owner" and r.get("email"):
            out.append(r["email"].strip())
    return sorted(set(out))


def _org_name(db, org_id: str) -> str:
    rows = _rows(db.table("organisations").select("name").eq("id", org_id).limit(1).execute())
    return (rows[0].get("name") if rows else None) or "Your business"


def _email(db, org_id: str, lines: list, more: int) -> int:
    api_key = os.environ.get("RESEND_API_KEY", "")
    to = _owner_emails(db, org_id)
    if not api_key or not to:
        return 0
    business = _org_name(db, org_id)
    tail = f"\n...and {more} more. See Inventory in Opsra." if more else "\nSee Inventory in Opsra."
    text = "These items are running low:\n\n" + "\n".join(lines) + "\n" + tail
    body = ("<p>These items are running low:</p><ul>" + "".join(f"<li>{html.escape(l)}</li>" for l in lines) + "</ul>"
            + f"<p>{html.escape(tail.strip())}</p>")
    sender = os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io")
    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({"from": f"Opsra <{sender}>", "to": to,
                            "subject": f"{business}: {len(lines) + more} item{'s' if len(lines) + more != 1 else ''} running low",
                            "text": text, "html": body})
        return len(to)
    except Exception as exc:
        logger.error("stock_alert: email failed org=%s: %s", org_id, exc)
        return 0


def alert_org(db, org_id: str, now: Optional[datetime] = None) -> dict:
    """Never raises. {low, notified, emailed}."""
    out = {"low": 0, "notified": 0, "emailed": 0}
    stamp = (now or datetime.now(timezone.utc)).isoformat()   # taken first: a change during this run counts next time
    try:
        settings = stock.get_settings(db, org_id)
        if not settings.get("enabled") or not settings.get("low_stock_alerts"):
            return out
        rows = low_items(db, org_id, settings.get("low_stock_alerted_at"))
        out["low"] = len(rows)
        if rows:
            lines = [_line(r) for r in rows[:MAX_LISTED]]
            more = max(len(rows) - MAX_LISTED, 0)
            from app.services import invoice_stock_service as inv_stock
            managers = inv_stock._manager_ids(db, org_id)
            title = f"{len(rows)} item{'s' if len(rows) != 1 else ''} running low"
            inv_stock._notify(db, org_id, managers, title, "\n".join(lines[:10]) + (f"\n...and {len(rows) - 10} more"
                                                                                  if len(rows) > 10 else ""),
                              kind="stock_low")
            out["notified"] = len(set(m for m in managers if m))
            out["emailed"] = _email(db, org_id, lines, more)
        db.table("stock_settings").update({"low_stock_alerted_at": stamp}).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.error("stock_alert: failed org=%s: %s", org_id, exc)
    return out


def alert_all(db, now: Optional[datetime] = None) -> dict:
    orgs = _rows(db.table("stock_settings").select("org_id").eq("enabled", True).neq("low_stock_alerts", False).execute())
    total = {"orgs": 0, "low": 0}
    for o in orgs:
        r = alert_org(db, o["org_id"], now)
        total["orgs"] += 1
        total["low"] += r["low"]
    return total
