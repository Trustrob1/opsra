"""
app/routers/contractors.py
CPM-1 — Contractor Performance Management

Routes (static before parameterised — Pattern 53):
  POST   /contractors/parse-contract-kpis  — AI contract parser (CPM-1A)
  GET    /contractors/scorecard            — summary card per contractor
  GET    /contractors                      — list all contractors for org
  POST   /contractors                      — create contractor
  GET    /contractors/{id}                 — single contractor with full detail
  PATCH  /contractors/{id}                 — update contractor
  DELETE /contractors/{id}                 — soft delete (owner only)
  GET    /contractors/{id}/kpi-actuals     — all KPI actuals for contractor
  POST   /contractors/{id}/kpi-actuals     — log or update a monthly KPI actual (upsert)
  GET    /contractors/{id}/tasks           — all tasks for contractor
  POST   /contractors/{id}/tasks           — create a single task manually
  PATCH  /contractors/{id}/tasks/{tid}     — update task status
  POST   /contractors/{id}/tasks/generate  — generate tasks from task_template

Security:
  Pattern 11 — JWT only (handled by get_current_org dependency)
  Pattern 12 — org_id never from payload, always from JWT via get_current_org
  Pattern 28 — get_current_org
  Pattern 53 — static routes before parameterised
  Pattern 62 — db via Depends(get_supabase)
  RBAC   — owner + ops_manager only for all routes

No Celery workers. No WhatsApp hooks.
AI used only in parse-contract-kpis route (CPM-1A).
"""
from __future__ import annotations

import logging
import io
from datetime import datetime, date, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic models ───────────────────────────────────────────────────────────

class KpiTarget(BaseModel):
    key: str
    label: str
    target_value: Optional[float] = None
    target_label: Optional[str] = None
    weight_pct: float = 0.0
    kpi_type: str = "manual"  # manual | leads_generated | conversion_rate | response_time


class RiskClause(BaseModel):
    clause_ref: str
    trigger_description: str
    consequence: str


class TaskTemplate(BaseModel):
    week_number: int
    phase: Optional[str] = None
    task_description: str
    due_day: Optional[int] = None
    owner: Optional[str] = None


class ContractorCreate(BaseModel):
    full_name: str
    role_title: str
    email: Optional[str] = None
    phone: Optional[str] = None
    contract_start: str           # ISO date string
    contract_end: Optional[str] = None
    contract_months: Optional[int] = None
    fee_structure: str
    fee_amount: float
    fee_currency: str = "NGN"
    fee_notes: Optional[str] = None
    payment_schedule: Optional[str] = None
    kpi_targets: List[KpiTarget] = []
    risk_clauses: List[RiskClause] = []
    task_template: List[TaskTemplate] = []


class ContractorUpdate(BaseModel):
    full_name: Optional[str] = None
    role_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    contract_end: Optional[str] = None
    contract_months: Optional[int] = None
    fee_structure: Optional[str] = None
    fee_amount: Optional[float] = None
    fee_currency: Optional[str] = None
    fee_notes: Optional[str] = None
    payment_schedule: Optional[str] = None
    kpi_targets: Optional[List[KpiTarget]] = None
    risk_clauses: Optional[List[RiskClause]] = None
    task_template: Optional[List[TaskTemplate]] = None
    status: Optional[str] = None
    termination_reason: Optional[str] = None
    termination_date: Optional[str] = None


class KpiActualCreate(BaseModel):
    month_label: str        # e.g. "Month 1"
    month_start: str        # ISO date
    kpi_key: str
    actual_value: Optional[float] = None
    actual_label: Optional[str] = None
    notes: Optional[str] = None


class TaskCreate(BaseModel):
    week_number: Optional[int] = None
    phase: Optional[str] = None
    task_description: str
    due_day: Optional[int] = None
    due_date: Optional[str] = None
    owner: Optional[str] = None


class TaskStatusUpdate(BaseModel):
    status: str             # not_started | in_progress | done | blocked
    done_date: Optional[str] = None
    notes: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_manager(org: dict) -> bool:
    """True if the current user is owner or ops_manager."""
    template = (org.get("roles") or {}).get("template", "").lower()
    return template in ("owner", "ops_manager")


def _require_manager(org: dict) -> None:
    """Raise 403 if current user is not owner or ops_manager."""
    if not _is_manager(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Manager access required"},
        )


def _fetch_contractor(db, contractor_id: str, org_id: str) -> dict:
    """Fetch a single non-deleted contractor. Raises 404 if not found."""
    result = (
        db.table("contractors")
        .select("*")
        .eq("id", contractor_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Contractor not found"},
        )
    data = result.data
    if isinstance(data, list):
        data = data[0]
    return data


def _kpi_status(target_value, actual_value, kpi_type: str) -> str:
    """
    Compute KPI achievement status.
    Returns: 'on_track' | 'at_risk' | 'off_track' | 'pending'
    """
    if actual_value is None:
        return "pending"
    if kpi_type == "leads_generated":
        pct = actual_value / target_value * 100 if target_value else 0
        if pct >= 100:
            return "on_track"
        if pct >= 70:
            return "at_risk"
        return "off_track"
    if kpi_type == "conversion_rate":
        if actual_value >= target_value:
            return "on_track"
        if actual_value >= target_value * 0.7:
            return "at_risk"
        return "off_track"
    if kpi_type == "response_time":
        # Lower is better
        if actual_value <= target_value:
            return "on_track"
        if actual_value <= target_value * 1.3:
            return "at_risk"
        return "off_track"
    # manual kpi_type — no numeric comparison possible
    return "pending"


def _compute_risk_summary(actuals_by_month: dict, kpi_targets: list) -> dict:
    """
    Compute termination risk from monthly KPI actuals.

    actuals_by_month: { "Month 1": { kpi_key: actual_value, ... }, ... }
    kpi_targets: list of KpiTarget dicts

    Returns:
        {
          consecutive_months_off_track: int,
          at_termination_risk: bool,
          missed_kpi_months: [str]
        }
    """
    if not kpi_targets or not actuals_by_month:
        return {
            "consecutive_months_off_track": 0,
            "at_termination_risk": False,
            "missed_kpi_months": [],
        }

    # Sort months by label numerically (Month 1, Month 2, ...)
    def _month_sort_key(label: str) -> int:
        try:
            return int(label.replace("Month", "").strip())
        except ValueError:
            return 0

    sorted_months = sorted(actuals_by_month.keys(), key=_month_sort_key)
    missed_kpi_months = []

    for month_label in sorted_months:
        month_actuals = actuals_by_month[month_label]
        all_off_track = True
        for kpi in kpi_targets:
            key = kpi.get("key") if isinstance(kpi, dict) else kpi.key
            kpi_type = kpi.get("kpi_type", "manual") if isinstance(kpi, dict) else kpi.kpi_type
            target_val = kpi.get("target_value") if isinstance(kpi, dict) else kpi.target_value
            actual_val = month_actuals.get(key)
            st = _kpi_status(target_val, actual_val, kpi_type)
            if st != "off_track":
                all_off_track = False
                break
        if all_off_track:
            missed_kpi_months.append(month_label)

    # Count consecutive trailing off-track months
    consecutive = 0
    for month_label in reversed(sorted_months):
        if month_label in missed_kpi_months:
            consecutive += 1
        else:
            break

    return {
        "consecutive_months_off_track": consecutive,
        "at_termination_risk": consecutive >= 2,
        "missed_kpi_months": missed_kpi_months,
    }


def _enrich_contractor(contractor: dict, db) -> dict:
    """
    Attach kpi_actuals_by_month and risk_summary to a contractor dict.
    Used by both GET /contractors/{id} and GET /contractors/scorecard.
    """
    contractor_id = contractor["id"]
    org_id = contractor["org_id"]

    actuals_result = (
        db.table("contractor_kpi_actuals")
        .select("*")
        .eq("contractor_id", contractor_id)
        .eq("org_id", org_id)
        .order("month_start", desc=False)
        .execute()
    )
    actuals = actuals_result.data or []
    if isinstance(actuals, dict):
        actuals = [actuals]

    # Group actuals by month_label → { "Month 1": { kpi_key: actual_value } }
    actuals_by_month: dict = {}
    for row in actuals:
        ml = row.get("month_label", "")
        if ml not in actuals_by_month:
            actuals_by_month[ml] = {}
        actuals_by_month[ml][row["kpi_key"]] = row.get("actual_value")

    kpi_targets = contractor.get("kpi_targets") or []

    # Build month-by-month KPI status grid
    kpi_months = {}
    for month_label, month_actuals in actuals_by_month.items():
        kpi_months[month_label] = {}
        for kpi in kpi_targets:
            key = kpi.get("key") if isinstance(kpi, dict) else kpi
            kpi_type = kpi.get("kpi_type", "manual") if isinstance(kpi, dict) else "manual"
            target_val = kpi.get("target_value") if isinstance(kpi, dict) else None
            actual_val = month_actuals.get(key)
            kpi_months[month_label][key] = {
                "actual_value": actual_val,
                "status": _kpi_status(target_val, actual_val, kpi_type),
            }

    risk_summary = _compute_risk_summary(actuals_by_month, kpi_targets)

    contractor["kpi_actuals_raw"] = actuals
    contractor["kpi_months"] = kpi_months
    contractor["risk_summary"] = risk_summary
    return contractor


# ── Routes ────────────────────────────────────────────────────────────────────

# ── CPM-1A: AI Contract Parser ────────────────────────────────────────────────
# Static route — must appear before /{id} routes (Pattern 53)

@router.post("/contractors/parse-contract-kpis")
async def parse_contract_kpis(
    file: UploadFile = File(...),
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    CPM-1A: Upload a PDF or DOCX contract and extract KPI targets and
    risk clauses using Claude Sonnet. Returns structured data for the
    frontend to pre-fill the ContractorCreateModal Step 3 + Step 4.

    No DB writes — pure parsing, returns data only.
    Fails gracefully: never 500s, returns empty arrays on any extraction failure.
    """
    _require_manager(org)

    filename = (file.filename or "").lower()
    if not (filename.endswith(".pdf") or filename.endswith(".docx")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_FILE", "message": "Only PDF and DOCX files are supported"},
        )

    content = await file.read()

    # ── Extract text from file ────────────────────────────────────────────────
    contract_text = ""
    try:
        if filename.endswith(".pdf"):
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            contract_text = "\n".join(pages)
        else:
            import docx
            doc = docx.Document(io.BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            contract_text = "\n".join(paragraphs)
    except Exception as exc:
        logger.warning("parse_contract_kpis: text extraction failed — %s", exc)
        return ok(
            data={"kpis": [], "risk_clauses": [], "raw_summary": ""},
            message="Could not extract text from file",
        )

    if not contract_text.strip():
        return ok(
            data={"kpis": [], "risk_clauses": [], "raw_summary": ""},
            message="No text found in file",
        )

    # Truncate to ~8000 tokens (approx 32000 chars) — KPIs are usually early in contracts
    contract_text = contract_text[:32000]

    # ── Call Claude Sonnet ────────────────────────────────────────────────────
    try:
        import anthropic
        from app.config import settings

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        prompt = f"""You are a contract analyst. Extract all KPI targets and performance clauses from this contractor agreement.

Return ONLY valid JSON in this exact format — no preamble, no markdown fences, no explanation:
{{
  "kpis": [
    {{
      "key": "snake_case_unique_key",
      "label": "Human readable KPI name",
      "kpi_type": "leads_generated",
      "target_value": 50,
      "target_label": "50 leads per month",
      "weight_pct": 40
    }}
  ],
  "risk_clauses": [
    {{
      "clause_ref": "Clause 7.2",
      "trigger_description": "Two consecutive months below target",
      "consequence": "Contract may be terminated with 14 days notice"
    }}
  ],
  "raw_summary": "One paragraph plain English summary of contractor obligations and key performance expectations."
}}

Rules:
- kpi_type must be one of: leads_generated, conversion_rate, response_time, manual
- Use leads_generated for count-based targets (calls, leads, deliverables)
- Use conversion_rate for percentage targets
- Use response_time for time/speed targets where lower is better
- Use manual for anything else
- weight_pct values should sum to 100; estimate proportionally if not explicitly stated
- target_value must be a number (not a string); use null if not determinable
- If no KPIs are found, return empty arrays
- Return ONLY the JSON object

CONTRACT TEXT:
{contract_text}"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()

        # Strip any accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        import json
        parsed = json.loads(raw)

        kpis = parsed.get("kpis") or []
        risk_clauses = parsed.get("risk_clauses") or []
        raw_summary = parsed.get("raw_summary") or ""

        return ok(
            data={
                "kpis": kpis,
                "risk_clauses": risk_clauses,
                "raw_summary": raw_summary,
            },
            message=f"Extracted {len(kpis)} KPIs and {len(risk_clauses)} risk clauses",
        )

    except Exception as exc:
        logger.warning("parse_contract_kpis: Claude call failed — %s", exc)
        return ok(
            data={"kpis": [], "risk_clauses": [], "raw_summary": ""},
            message="Could not extract KPIs automatically — please add them manually",
        )


# ── Scorecard — static, before /{id} (Pattern 53) ────────────────────────────

@router.get("/contractors/scorecard")
def get_contractor_scorecard(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: Summary scorecard for all contractors. Manager view."""
    _require_manager(org)
    org_id = org["org_id"]

    result = (
        db.table("contractors")
        .select("*")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=False)
        .execute()
    )
    contractors = result.data or []
    if isinstance(contractors, dict):
        contractors = [contractors]

    enriched = [_enrich_contractor(c, db) for c in contractors]
    return ok(data={"items": enriched, "total": len(enriched)})


# ── List + Create ─────────────────────────────────────────────────────────────

@router.get("/contractors")
def list_contractors(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: List all contractors for the org."""
    _require_manager(org)
    org_id = org["org_id"]

    result = (
        db.table("contractors")
        .select("*")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    contractors = result.data or []
    if isinstance(contractors, dict):
        contractors = [contractors]

    return ok(data={"items": contractors, "total": len(contractors)})


@router.post("/contractors")
def create_contractor(
    payload: ContractorCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: Create a new contractor profile."""
    _require_manager(org)
    org_id = org["org_id"]

    if not payload.full_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Full name is required"},
        )
    if not payload.role_title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Role title is required"},
        )

    row = {
        "org_id":           org_id,
        "full_name":        payload.full_name.strip(),
        "role_title":       payload.role_title.strip(),
        "email":            payload.email or None,
        "phone":            payload.phone or None,
        "contract_start":   payload.contract_start,
        "contract_end":     payload.contract_end or None,
        "contract_months":  payload.contract_months or None,
        "fee_structure":    payload.fee_structure,
        "fee_amount":       payload.fee_amount,
        "fee_currency":     payload.fee_currency,
        "fee_notes":        payload.fee_notes or None,
        "payment_schedule": payload.payment_schedule or None,
        "kpi_targets":      [k.model_dump() for k in payload.kpi_targets],
        "risk_clauses":     [r.model_dump() for r in payload.risk_clauses],
        "task_template":    [t.model_dump() for t in payload.task_template],
        "status":           "active",
        "created_at":       datetime.now(timezone.utc).isoformat(),
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }

    result = db.table("contractors").insert(row).execute()
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else row

    return ok(data=data, message="Contractor created")


# ── Single contractor ─────────────────────────────────────────────────────────

@router.get("/contractors/{contractor_id}")
def get_contractor(
    contractor_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: Get a single contractor with KPI actuals and risk summary."""
    _require_manager(org)
    org_id = org["org_id"]
    contractor = _fetch_contractor(db, contractor_id, org_id)
    enriched = _enrich_contractor(contractor, db)
    return ok(data=enriched)


@router.patch("/contractors/{contractor_id}")
def update_contractor(
    contractor_id: str,
    payload: ContractorUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: Update a contractor profile."""
    _require_manager(org)
    org_id = org["org_id"]
    _fetch_contractor(db, contractor_id, org_id)  # confirm exists

    update_data = {}
    for field, value in payload.model_dump().items():
        if value is not None:
            if field in ("kpi_targets", "risk_clauses", "task_template") and isinstance(value, list):
                update_data[field] = [
                    item.model_dump() if hasattr(item, "model_dump") else item
                    for item in value
                ]
            else:
                update_data[field] = value

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "No fields provided to update"},
        )

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        db.table("contractors")
        .update(update_data)
        .eq("id", contractor_id)
        .eq("org_id", org_id)
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else update_data

    return ok(data=data, message="Contractor updated")


@router.delete("/contractors/{contractor_id}")
def delete_contractor(
    contractor_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: Soft-delete a contractor. Owner only."""
    template = (org.get("roles") or {}).get("template", "").lower()
    if template != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners can delete contractors"},
        )

    org_id = org["org_id"]
    _fetch_contractor(db, contractor_id, org_id)

    db.table("contractors").update({
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", contractor_id).eq("org_id", org_id).execute()

    return ok(data={"id": contractor_id}, message="Contractor deleted")


# ── KPI Actuals ───────────────────────────────────────────────────────────────

@router.get("/contractors/{contractor_id}/kpi-actuals")
def get_kpi_actuals(
    contractor_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: Get all KPI actuals for a contractor."""
    _require_manager(org)
    org_id = org["org_id"]
    _fetch_contractor(db, contractor_id, org_id)

    result = (
        db.table("contractor_kpi_actuals")
        .select("*")
        .eq("contractor_id", contractor_id)
        .eq("org_id", org_id)
        .order("month_start", desc=False)
        .execute()
    )
    actuals = result.data or []
    if isinstance(actuals, dict):
        actuals = [actuals]

    return ok(data={"items": actuals, "total": len(actuals)})


@router.post("/contractors/{contractor_id}/kpi-actuals")
def log_kpi_actual(
    contractor_id: str,
    payload: KpiActualCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    CPM-1: Log or update a monthly KPI actual (upsert).
    Unique on (contractor_id, month_label, kpi_key).
    """
    _require_manager(org)
    org_id = org["org_id"]
    user_id = org["id"]
    _fetch_contractor(db, contractor_id, org_id)

    # Check for existing row
    existing = (
        db.table("contractor_kpi_actuals")
        .select("id")
        .eq("contractor_id", contractor_id)
        .eq("month_label", payload.month_label)
        .eq("kpi_key", payload.kpi_key)
        .maybe_single()
        .execute()
    )
    existing_data = existing.data
    if isinstance(existing_data, list):
        existing_data = existing_data[0] if existing_data else None

    now_iso = datetime.now(timezone.utc).isoformat()

    if existing_data:
        # Update
        update_row = {
            "actual_value": payload.actual_value,
            "actual_label": payload.actual_label or None,
            "notes":        payload.notes or None,
            "logged_by":    user_id,
            "updated_at":   now_iso,
        }
        result = (
            db.table("contractor_kpi_actuals")
            .update(update_row)
            .eq("id", existing_data["id"])
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else update_row
        return ok(data=data, message="KPI actual updated")
    else:
        # Insert
        insert_row = {
            "org_id":        org_id,
            "contractor_id": contractor_id,
            "month_label":   payload.month_label,
            "month_start":   payload.month_start,
            "kpi_key":       payload.kpi_key,
            "actual_value":  payload.actual_value,
            "actual_label":  payload.actual_label or None,
            "notes":         payload.notes or None,
            "logged_by":     user_id,
            "created_at":    now_iso,
            "updated_at":    now_iso,
        }
        result = db.table("contractor_kpi_actuals").insert(insert_row).execute()
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else insert_row
        return ok(data=data, message="KPI actual logged")


# ── Tasks ─────────────────────────────────────────────────────────────────────

@router.get("/contractors/{contractor_id}/tasks")
def get_contractor_tasks(
    contractor_id: str,
    status_filter: Optional[str] = None,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: Get all tasks for a contractor."""
    _require_manager(org)
    org_id = org["org_id"]
    _fetch_contractor(db, contractor_id, org_id)

    query = (
        db.table("contractor_tasks")
        .select("*")
        .eq("contractor_id", contractor_id)
        .eq("org_id", org_id)
        .order("due_date", desc=False)
    )
    # Python-side filtering for status (Pattern 33 — no ILIKE)
    result = query.execute()
    tasks = result.data or []
    if isinstance(tasks, dict):
        tasks = [tasks]

    if status_filter:
        tasks = [t for t in tasks if t.get("status") == status_filter]

    return ok(data={"items": tasks, "total": len(tasks)})


@router.post("/contractors/{contractor_id}/tasks")
def create_contractor_task(
    contractor_id: str,
    payload: TaskCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: Manually create a single task for a contractor."""
    _require_manager(org)
    org_id = org["org_id"]
    contractor = _fetch_contractor(db, contractor_id, org_id)

    # Compute due_date from due_day + contract_start if not provided
    due_date = payload.due_date or None
    if not due_date and payload.due_day is not None:
        try:
            start = date.fromisoformat(contractor["contract_start"])
            due_date = (start + timedelta(days=payload.due_day)).isoformat()
        except Exception:
            due_date = None

    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        "org_id":           org_id,
        "contractor_id":    contractor_id,
        "week_number":      payload.week_number or None,
        "phase":            payload.phase or None,
        "task_description": payload.task_description.strip(),
        "due_day":          payload.due_day or None,
        "due_date":         due_date,
        "owner":            payload.owner or None,
        "status":           "not_started",
        "created_at":       now_iso,
        "updated_at":       now_iso,
    }

    result = db.table("contractor_tasks").insert(row).execute()
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else row

    return ok(data=data, message="Task created")


@router.patch("/contractors/{contractor_id}/tasks/{task_id}")
def update_contractor_task(
    contractor_id: str,
    task_id: str,
    payload: TaskStatusUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CPM-1: Update task status."""
    _require_manager(org)
    org_id = org["org_id"]
    _fetch_contractor(db, contractor_id, org_id)

    valid_statuses = ("not_started", "in_progress", "done", "blocked")
    if payload.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": f"Status must be one of: {', '.join(valid_statuses)}"},
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    update_data: dict = {
        "status":     payload.status,
        "updated_at": now_iso,
    }
    if payload.status == "done":
        update_data["done_date"] = payload.done_date or date.today().isoformat()
    if payload.notes is not None:
        update_data["notes"] = payload.notes

    result = (
        db.table("contractor_tasks")
        .update(update_data)
        .eq("id", task_id)
        .eq("contractor_id", contractor_id)
        .eq("org_id", org_id)
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else update_data

    return ok(data=data, message="Task updated")


# ── Generate tasks from template — static sub-route before /{id} params ───────

@router.post("/contractors/{contractor_id}/tasks/generate")
def generate_contractor_tasks(
    contractor_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    CPM-1: Generate contractor_tasks rows from the task_template JSONB.
    Computes due_date from contract_start + due_day.
    Skips tasks that already exist (same contractor_id + week_number + task_description).
    """
    _require_manager(org)
    org_id = org["org_id"]
    contractor = _fetch_contractor(db, contractor_id, org_id)

    template = contractor.get("task_template") or []
    if not template:
        return ok(data={"created": 0}, message="No task template defined")

    try:
        contract_start = date.fromisoformat(contractor["contract_start"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Invalid contract_start date on contractor"},
        )

    # Fetch existing tasks to skip duplicates
    existing_result = (
        db.table("contractor_tasks")
        .select("week_number, task_description")
        .eq("contractor_id", contractor_id)
        .execute()
    )
    existing_tasks = existing_result.data or []
    if isinstance(existing_tasks, dict):
        existing_tasks = [existing_tasks]

    existing_set = {
        (str(t.get("week_number")), t.get("task_description", "").strip())
        for t in existing_tasks
    }

    now_iso = datetime.now(timezone.utc).isoformat()
    to_insert = []

    for item in template:
        week_number      = item.get("week_number")
        task_description = (item.get("task_description") or "").strip()
        due_day          = item.get("due_day")

        if not task_description:
            continue

        key = (str(week_number), task_description)
        if key in existing_set:
            continue  # skip duplicates

        due_date = None
        if due_day is not None:
            try:
                due_date = (contract_start + timedelta(days=int(due_day))).isoformat()
            except Exception:
                due_date = None

        to_insert.append({
            "org_id":           org_id,
            "contractor_id":    contractor_id,
            "week_number":      week_number,
            "phase":            item.get("phase") or None,
            "task_description": task_description,
            "due_day":          due_day,
            "due_date":         due_date,
            "owner":            item.get("owner") or None,
            "status":           "not_started",
            "created_at":       now_iso,
            "updated_at":       now_iso,
        })

    if to_insert:
        db.table("contractor_tasks").insert(to_insert).execute()

    return ok(
        data={"created": len(to_insert)},
        message=f"{len(to_insert)} tasks generated",
    )