"""
app/services/contact_export_service.py
--------------------------------------
WA-AUTO-2 - the owner's contact list as a CSV (name, WhatsApp number, where they came from, first seen).

Owner only. Every export is written to the audit log. Spreadsheet formulas are defused (a cell that starts with = + - or @ gets a
leading apostrophe) so a customer who types a formula as their name cannot run it on the owner's computer.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_ROWS = 20000
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
HEADER = ["name", "whatsapp", "type", "source", "first_seen"]


def _safe(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_DANGEROUS) else text


def _rows(db: Any, table: str, org_id: str, cols: str) -> list:
    q = db.table(table).select(cols).eq("org_id", org_id).is_("deleted_at", "null").order("created_at", desc=True).limit(_MAX_ROWS)
    return q.execute().data or []


def build_csv(db: Any, org_id: str) -> tuple[str, int]:
    """Returns (csv text, number of contacts). A table that cannot be read is left out rather than failing the export."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADER)
    count = 0
    for table, kind, cols in (("leads", "contact", "full_name, whatsapp, source, created_at"),
                              ("customers", "customer", "full_name, whatsapp, created_at")):
        try:
            rows = _rows(db, table, org_id, cols)
        except Exception as exc:
            logger.warning("contact_export: %s not readable org=%s: %s", table, org_id, exc)
            continue
        for r in rows:
            if not r.get("whatsapp"):
                continue
            writer.writerow([_safe(r.get("full_name")), _safe(r.get("whatsapp")), kind, _safe(r.get("source")),
                             _safe((r.get("created_at") or "")[:10])])
            count += 1
    return out.getvalue(), count


def write_audit(db: Any, org_id: str, user_id: str, count: int) -> None:
    db.table("audit_logs").insert({
        "org_id": org_id, "user_id": user_id, "action": "contacts_exported", "resource_type": "contacts",
        "resource_id": None, "old_value": None, "new_value": {"count": count},
    }).execute()
