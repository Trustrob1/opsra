"""
app/routers/growth_config.py
Growth configuration routes — GPM-1A + GPM-1E (watermark update).

Routes:
  GET    /api/v1/growth/teams
  POST   /api/v1/growth/teams
  PATCH  /api/v1/growth/teams/{team_id}
  DELETE /api/v1/growth/teams/{team_id}

  GET    /api/v1/growth/spend
  POST   /api/v1/growth/spend
  DELETE /api/v1/growth/spend/{spend_id}

  GET    /api/v1/growth/direct-sales
  POST   /api/v1/growth/direct-sales

  POST   /api/v1/growth/direct-sales/import/excel    ← GPM-1E
  POST   /api/v1/growth/direct-sales/import/sheets   ← GPM-1E
  DELETE /api/v1/growth/direct-sales/import/watermark ← GPM-1E (reset)

  PATCH  /api/v1/growth/direct-sales/{sale_id}
  DELETE /api/v1/growth/direct-sales/{sale_id}

Pattern 53: static routes before parameterised.
Pattern 62: db via Depends(get_supabase).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, field_validator

from app.database import get_supabase
from app.routers.auth import get_current_org
from app.services.sales_import_service import (
    fetch_sheets_csv,
    get_watermark,
    parse_excel_file,
    reset_watermark,
    save_watermark,
    validate_and_prepare_rows,
    fetch_aggregate_sheets_csv,
    _aggregate_rows_to_dicts,
    validate_and_prepare_aggregate_sales_rows,
    parse_multi_sheet_xlsx,
    _txn_rows_to_dicts,
    validate_and_prepare_transaction_sales_rows,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------

def _require_owner_or_ops(org: dict) -> None:
    roles = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Owner or ops_manager access required"},
        )


def _require_owner_ops_or_agent(org: dict) -> None:
    """REPORTS-DEPT-1 Phase 4b: broader than _require_owner_or_ops —
    sales_agent included, since every rep sees the full commission
    leaderboard (client-confirmed), not just managers."""
    roles = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template not in ("owner", "ops_manager", "sales_agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions"},
        )


def _require_owner(org: dict) -> None:
    roles = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Owner access required"},
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _success(data: object, message: str = "OK") -> dict:
    return {"success": True, "data": data, "message": message, "error": None}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TeamCreate(BaseModel):
    name:  str           = Field(..., min_length=1, max_length=100)
    color: Optional[str] = Field(None, max_length=20)


class TeamUpdate(BaseModel):
    name:      Optional[str]  = Field(None, min_length=1, max_length=100)
    color:     Optional[str]  = Field(None, max_length=20)
    is_active: Optional[bool] = None


class SpendCreate(BaseModel):
    period_start: str
    period_end:   str
    spend_type:   str
    team_name:    Optional[str] = None
    channel_name: Optional[str] = None
    amount:       float = Field(..., gt=0)
    currency:     str   = Field("NGN", max_length=10)
    notes:        Optional[str] = None


class DirectSaleCreate(BaseModel):
    customer_id:   Optional[str] = None
    customer_name: Optional[str] = Field(None, max_length=255)
    amount:        float         = Field(..., gt=0)
    currency:      str           = Field("NGN", max_length=10)
    sale_date:     str
    channel:       str           = Field("other", max_length=50)
    utm_source:    Optional[str] = Field(None, max_length=100)
    source_team:   Optional[str] = Field(None, max_length=100)
    notes:         Optional[str] = None
    phone:         Optional[str] = Field(None, max_length=20)
    region:        Optional[str] = Field(None, max_length=255)
    import_source: str           = Field("manual", max_length=20)


class DirectSaleUpdate(BaseModel):
    customer_id:   Optional[str]   = None
    customer_name: Optional[str]   = Field(None, max_length=255)
    amount:        Optional[float] = Field(None, gt=0)
    currency:      Optional[str]   = Field(None, max_length=10)
    sale_date:     Optional[str]   = None
    channel:       Optional[str]   = Field(None, max_length=50)
    utm_source:    Optional[str]   = Field(None, max_length=100)
    source_team:   Optional[str]   = Field(None, max_length=100)
    notes:         Optional[str]   = None


class SheetsImportBody(BaseModel):
    url:              str
    confirm:          bool            = False
    selected_indices: Optional[List[int]] = None  # indices into valid_rows to insert
    from_beginning:   bool            = False      # override watermark


class WatermarkResetBody(BaseModel):
    source_type: str           # 'excel' | 'sheets'
    sheet_url:   Optional[str] = None


# ---------------------------------------------------------------------------
# TEAM MANAGEMENT
# ---------------------------------------------------------------------------

@router.get("/growth/teams")
def list_teams(
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    result = (
        db.table("growth_teams")
        .select("*")
        .eq("org_id", org["org_id"])
        .order("created_at", desc=False)
        .execute()
    )
    return _success(result.data or [])


@router.post("/growth/teams", status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    now = _now_iso()
    result = (
        db.table("growth_teams")
        .insert({
            "org_id":     org["org_id"],
            "name":       payload.name,
            "color":      payload.color,
            "is_active":  True,
            "created_at": now,
            "updated_at": now,
        })
        .execute()
    )
    return _success(result.data[0] if result.data else {}, "Team created")


@router.patch("/growth/teams/{team_id}")
def update_team(
    team_id: str,
    payload: TeamUpdate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    existing = (
        db.table("growth_teams")
        .select("id")
        .eq("id", team_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Team not found"})
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    updates["updated_at"] = _now_iso()
    result = (
        db.table("growth_teams")
        .update(updates)
        .eq("id", team_id)
        .eq("org_id", org["org_id"])
        .execute()
    )
    return _success(result.data[0] if result.data else {}, "Team updated")


@router.delete("/growth/teams/{team_id}", status_code=status.HTTP_200_OK)
def delete_team(
    team_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    existing = (
        db.table("growth_teams")
        .select("id")
        .eq("id", team_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Team not found"})
    db.table("growth_teams").update({
        "is_active": False, "updated_at": _now_iso(),
    }).eq("id", team_id).eq("org_id", org["org_id"]).execute()
    return _success(None, "Team deactivated")


# ---------------------------------------------------------------------------
# CAMPAIGN SPEND
# ---------------------------------------------------------------------------

@router.get("/growth/spend")
def list_spend(
    period_start: Optional[str] = Query(None),
    period_end:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    query = (
        db.table("campaign_spend")
        .select("*")
        .eq("org_id", org["org_id"])
        .order("period_start", desc=True)
    )
    if period_start:
        query = query.gte("period_start", period_start)
    if period_end:
        query = query.lte("period_end", period_end)
    return _success(query.execute().data or [])


@router.post("/growth/spend", status_code=status.HTTP_201_CREATED)
def create_spend(
    payload: SpendCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    if payload.spend_type not in ("team", "channel"):
        raise HTTPException(status_code=422, detail={"code": "INVALID_SPEND_TYPE", "message": "spend_type must be 'team' or 'channel'"})
    if payload.spend_type == "team" and not payload.team_name:
        raise HTTPException(status_code=422, detail={"code": "MISSING_FIELD", "message": "team_name required when spend_type is 'team'"})
    if payload.spend_type == "channel" and not payload.channel_name:
        raise HTTPException(status_code=422, detail={"code": "MISSING_FIELD", "message": "channel_name required when spend_type is 'channel'"})
    result = db.table("campaign_spend").insert({
        "org_id": org["org_id"], "period_start": payload.period_start,
        "period_end": payload.period_end, "spend_type": payload.spend_type,
        "team_name": payload.team_name, "channel_name": payload.channel_name,
        "amount": payload.amount, "currency": payload.currency,
        "notes": payload.notes, "recorded_by": org["id"], "created_at": _now_iso(),
    }).execute()
    return _success(result.data[0] if result.data else {}, "Spend entry recorded")


@router.delete("/growth/spend/{spend_id}", status_code=status.HTTP_200_OK)
def delete_spend(
    spend_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    existing = (
        db.table("campaign_spend").select("id")
        .eq("id", spend_id).eq("org_id", org["org_id"])
        .maybe_single().execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Spend entry not found"})
    db.table("campaign_spend").delete().eq("id", spend_id).eq("org_id", org["org_id"]).execute()
    return _success(None, "Spend entry deleted")


# ---------------------------------------------------------------------------
# DIRECT SALES — list + create
# ---------------------------------------------------------------------------

@router.get("/growth/direct-sales")
def list_direct_sales(
    page:      int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    rep_id:    Optional[str] = Query(None),
    model:     Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """REPORTS-DEPT-1 Phase 4b: date_from/date_to/rep_id/model are new,
    optional filters for the Sales Record tab — all default to None,
    identical behaviour to before for any existing caller that omits them."""
    _require_owner_or_ops(org)
    offset = (page - 1) * page_size
    query = (
        db.table("direct_sales")
        .select("*", count="exact")
        .eq("org_id", org["org_id"])
    )
    if date_from:
        query = query.gte("sale_date", date_from)
    if date_to:
        query = query.lte("sale_date", date_to)
    if rep_id:
        query = query.eq("recorded_by", rep_id)
    if model:
        query = query.ilike("model", f"%{model}%")
    result = (
        query
        .order("sale_date", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )
    total = result.count or 0
    return _success({
        "items":     result.data or [],
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "has_more":  (offset + page_size) < total,
    })


@router.post("/growth/direct-sales", status_code=status.HTTP_201_CREATED)
def create_direct_sale(
    payload: DirectSaleCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    now = _now_iso()
    result = db.table("direct_sales").insert({
        "org_id": org["org_id"], "customer_id": payload.customer_id,
        "customer_name": payload.customer_name, "amount": payload.amount,
        "currency": payload.currency, "sale_date": payload.sale_date,
        "channel": payload.channel, "utm_source": payload.utm_source,
        "source_team": payload.source_team, "notes": payload.notes,
        "phone": payload.phone, "region": payload.region,
        "import_source": payload.import_source,
        "recorded_by": org["id"], "created_at": now, "updated_at": now,
    }).execute()
    return _success(result.data[0] if result.data else {}, "Direct sale recorded")


# ---------------------------------------------------------------------------
# DIRECT SALES — import routes  (Pattern 53: BEFORE /{sale_id})
# ---------------------------------------------------------------------------

@router.post("/growth/direct-sales/import/excel", status_code=status.HTTP_200_OK)
async def import_sales_excel(
    confirm:          bool = Query(False),
    from_beginning:   bool = Query(False),
    selected_indices: Optional[str] = Query(None),  # comma-separated indices into valid_rows
    file: UploadFile = File(...),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Upload Excel/CSV for bulk sales import.
    confirm=false        → preview only, nothing inserted.
    confirm=true         → insert selected_indices rows (or all valid if not provided).
    from_beginning=true  → ignore watermark for this import.
    selected_indices     → comma-separated list of valid_row indices to insert (0-based).
    """
    _require_owner_or_ops(org)

    allowed_extensions = (".xlsx", ".xls", ".csv")
    filename = (file.filename or "").lower()
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        content_type = (file.content_type or "").lower()
        allowed_types = {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel", "text/csv", "application/csv",
        }
        if content_type not in allowed_types:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_FILE_TYPE", "message": "Only .xlsx, .xls, or .csv files are accepted"},
            )

    file_bytes = await file.read()

    try:
        rows = parse_excel_file(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "PARSE_ERROR", "message": str(exc)})

    # Watermark
    watermark_date = None if from_beginning else get_watermark(db, org["org_id"], "excel", None)

    try:
        result = validate_and_prepare_rows(rows, org["org_id"], db, "excel", watermark_date)
    except Exception as exc:
        logger.exception("GPM-1E: validate_and_prepare_rows failed for excel import")
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    valid_rows         = result["valid_rows"]
    error_rows         = result["error_rows"]
    duplicate_warnings = result["duplicate_warnings"]
    already_imported   = result["already_imported"]

    if not confirm:
        return _success({
            "inserted":          0,
            "skipped":           len(error_rows),
            "errors":            error_rows,
            "duplicate_warnings": duplicate_warnings,
            "already_imported":  already_imported,
            "preview":           valid_rows[:10],
            "total_valid":       len(valid_rows),
            "watermark_date":    watermark_date,
        }, "Preview ready — send confirm=true to import")

    # Resolve which rows to insert
    rows_to_insert = _resolve_selected(valid_rows, selected_indices)

    inserted = 0
    if rows_to_insert:
        db.table("direct_sales").insert(rows_to_insert).execute()
        inserted = len(rows_to_insert)

    # Save watermark to max sale_date of inserted rows
    if inserted:
        max_date = max(r["sale_date"] for r in rows_to_insert)
        save_watermark(db, org["org_id"], "excel", None, max_date)

    return _success({
        "inserted":          inserted,
        "skipped":           len(valid_rows) - inserted + len(error_rows),
        "errors":            error_rows,
        "duplicate_warnings": duplicate_warnings,
        "already_imported":  already_imported,
        "preview":           [],
        "total_valid":       len(valid_rows),
        "watermark_date":    watermark_date,
    }, f"{inserted} sale(s) imported successfully")


@router.post("/growth/direct-sales/import/sheets", status_code=status.HTTP_200_OK)
def import_sales_sheets(
    body: SheetsImportBody,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Pull a publicly shared Google Sheet and bulk import sales.
    Watermark is keyed by sheet URL — each sheet has its own memory.
    """
    _require_owner_or_ops(org)

    try:
        rows = fetch_sheets_csv(body.url)
    except Exception as exc:
        logger.exception("GPM-1E: fetch_sheets_csv failed")
        raise HTTPException(status_code=422, detail={"code": "FETCH_ERROR", "message": str(exc)})

    watermark_date = (
        None if body.from_beginning
        else get_watermark(db, org["org_id"], "sheets", body.url)
    )

    try:
        result = validate_and_prepare_rows(rows, org["org_id"], db, "sheets", watermark_date)
    except Exception as exc:
        logger.exception("GPM-1E: validate_and_prepare_rows failed for sheets import")
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    valid_rows         = result["valid_rows"]
    error_rows         = result["error_rows"]
    duplicate_warnings = result["duplicate_warnings"]
    already_imported   = result["already_imported"]

    if not body.confirm:
        return _success({
            "inserted":          0,
            "skipped":           len(error_rows),
            "errors":            error_rows,
            "duplicate_warnings": duplicate_warnings,
            "already_imported":  already_imported,
            "preview":           valid_rows[:10],
            "total_valid":       len(valid_rows),
            "watermark_date":    watermark_date,
        }, "Preview ready — send confirm=true to import")

    rows_to_insert = _resolve_selected(valid_rows, body.selected_indices)

    inserted = 0
    if rows_to_insert:
        db.table("direct_sales").insert(rows_to_insert).execute()
        inserted = len(rows_to_insert)

    if inserted:
        max_date = max(r["sale_date"] for r in rows_to_insert)
        save_watermark(db, org["org_id"], "sheets", body.url, max_date)

    return _success({
        "inserted":          inserted,
        "skipped":           len(valid_rows) - inserted + len(error_rows),
        "errors":            error_rows,
        "duplicate_warnings": duplicate_warnings,
        "already_imported":  already_imported,
        "preview":           [],
        "total_valid":       len(valid_rows),
        "watermark_date":    watermark_date,
    }, f"{inserted} sale(s) imported successfully")


@router.post("/growth/direct-sales/import/daily-aggregate/excel", status_code=status.HTTP_200_OK)
async def import_daily_aggregate_excel(
    confirm:          bool = Query(False),
    from_beginning:   bool = Query(False),
    selected_indices: Optional[str] = Query(None),
    file: UploadFile = File(...),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    REPORTS-DEPT-1 Phase 4: upload a daily-aggregate sales sheet (one row
    per day per rep, e.g. Date / Sales Rep / Mattress Revenue / Pillow
    Revenue — not the named-customer transaction shape import_sales_excel
    expects). Same confirm/preview flow as the existing importer, but a
    separate validator, and a separate watermark keyed under
    "daily_aggregate_excel" so it never collides with the named-customer
    importer's own watermark.
    """
    _require_owner_or_ops(org)

    allowed_extensions = (".xlsx", ".xls", ".csv")
    filename = (file.filename or "").lower()
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        content_type = (file.content_type or "").lower()
        allowed_types = {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel", "text/csv", "application/csv",
        }
        if content_type not in allowed_types:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_FILE_TYPE", "message": "Only .xlsx, .xls, or .csv files are accepted"},
            )

    file_bytes = await file.read()

    try:
        rows = parse_excel_file(file_bytes, row_mapper=_aggregate_rows_to_dicts)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "PARSE_ERROR", "message": str(exc)})

    watermark_date = None if from_beginning else get_watermark(db, org["org_id"], "agg_excel", None)

    try:
        result = validate_and_prepare_aggregate_sales_rows(rows, org["org_id"], db, "agg_excel", watermark_date)
    except Exception as exc:
        logger.exception("Phase 4: validate_and_prepare_aggregate_sales_rows failed for excel import")
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    valid_rows         = result["valid_rows"]
    error_rows         = result["error_rows"]
    duplicate_warnings = result["duplicate_warnings"]
    already_imported   = result["already_imported"]

    if not confirm:
        return _success({
            "inserted":          0,
            "skipped":           len(error_rows),
            "errors":            error_rows,
            "duplicate_warnings": duplicate_warnings,
            "already_imported":  already_imported,
            "preview":           valid_rows[:10],
            "total_valid":       len(valid_rows),
            "watermark_date":    watermark_date,
        }, "Preview ready — send confirm=true to import")

    rows_to_insert = _resolve_selected(valid_rows, selected_indices)

    inserted = 0
    if rows_to_insert:
        db.table("direct_sales").insert(rows_to_insert).execute()
        inserted = len(rows_to_insert)

    if inserted:
        max_date = max(r["sale_date"] for r in rows_to_insert)
        save_watermark(db, org["org_id"], "agg_excel", None, max_date)

    return _success({
        "inserted":          inserted,
        "skipped":           len(valid_rows) - inserted + len(error_rows),
        "errors":            error_rows,
        "duplicate_warnings": duplicate_warnings,
        "already_imported":  already_imported,
        "preview":           [],
        "total_valid":       len(valid_rows),
        "watermark_date":    watermark_date,
    }, f"{inserted} sale(s) imported successfully")


@router.post("/growth/direct-sales/import/daily-aggregate/sheets", status_code=status.HTTP_200_OK)
def import_daily_aggregate_sheets(
    body: SheetsImportBody,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    REPORTS-DEPT-1 Phase 4: same as import_daily_aggregate_excel, pulling
    from a publicly shared Google Sheet instead. Reuses SheetsImportBody —
    identical shape (url, confirm, selected_indices, from_beginning).
    """
    _require_owner_or_ops(org)

    try:
        rows = fetch_aggregate_sheets_csv(body.url)
    except Exception as exc:
        logger.exception("Phase 4: fetch_aggregate_sheets_csv failed")
        raise HTTPException(status_code=422, detail={"code": "FETCH_ERROR", "message": str(exc)})

    watermark_date = (
        None if body.from_beginning
        else get_watermark(db, org["org_id"], "agg_sheets", body.url)
    )

    try:
        result = validate_and_prepare_aggregate_sales_rows(rows, org["org_id"], db, "agg_sheets", watermark_date)
    except Exception as exc:
        logger.exception("Phase 4: validate_and_prepare_aggregate_sales_rows failed for sheets import")
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    valid_rows         = result["valid_rows"]
    error_rows         = result["error_rows"]
    duplicate_warnings = result["duplicate_warnings"]
    already_imported   = result["already_imported"]

    if not body.confirm:
        return _success({
            "inserted":          0,
            "skipped":           len(error_rows),
            "errors":            error_rows,
            "duplicate_warnings": duplicate_warnings,
            "already_imported":  already_imported,
            "preview":           valid_rows[:10],
            "total_valid":       len(valid_rows),
            "watermark_date":    watermark_date,
        }, "Preview ready — send confirm=true to import")

    rows_to_insert = _resolve_selected(valid_rows, body.selected_indices)

    inserted = 0
    if rows_to_insert:
        db.table("direct_sales").insert(rows_to_insert).execute()
        inserted = len(rows_to_insert)

    if inserted:
        max_date = max(r["sale_date"] for r in rows_to_insert)
        save_watermark(db, org["org_id"], "agg_sheets", body.url, max_date)

    return _success({
        "inserted":          inserted,
        "skipped":           len(valid_rows) - inserted + len(error_rows),
        "errors":            error_rows,
        "duplicate_warnings": duplicate_warnings,
        "already_imported":  already_imported,
        "preview":           [],
        "total_valid":       len(valid_rows),
        "watermark_date":    watermark_date,
    }, f"{inserted} sale(s) imported successfully")


@router.post("/growth/direct-sales/import/transactions/excel", status_code=status.HTTP_200_OK)
async def import_transaction_sales_excel(
    confirm:          bool = Query(False),
    from_beginning:   bool = Query(False),
    file: UploadFile = File(...),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    REPORTS-DEPT-1 Phase 4b: upload a per-sale transaction workbook with
    one tab per region (e.g. Lagos, Abuja) — Date/Sales Rep/Customer Name/
    Model/Units/Amount/Status. Feeds the Sales Record and Commissions tabs.
    Separate watermark ("txn_excel") from both the daily-aggregate and
    named-customer importers — three genuinely different row shapes,
    three independent sync points.
    """
    _require_owner_or_ops(org)

    allowed_extensions = (".xlsx", ".xls")
    filename = (file.filename or "").lower()
    if not filename.endswith(allowed_extensions):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_FILE_TYPE", "message": "Only .xlsx or .xls workbooks are accepted (multi-sheet required)"},
        )

    file_bytes = await file.read()

    try:
        all_sheets = parse_multi_sheet_xlsx(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "PARSE_ERROR", "message": str(exc)})

    # Only these two tabs are actual per-sale region logs — the workbook
    # also contains summary/commission/per-rep tabs (Breakdown, Summary,
    # ALL SALES, COMMISSIONS, MARYANN SALES, TOLU'SALE, Records) that
    # don't share this row shape and would otherwise be misread as regions.
    ALLOWED_REGIONS = {"lagos sales", "abuja sales"}
    sheets = {name: rows for name, rows in all_sheets.items() if name.strip().lower() in ALLOWED_REGIONS}

    if not sheets:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NO_MATCHING_SHEETS",
                "message": f"No 'Lagos Sales' or 'Abuja Sales' tab found. Sheets in this workbook: {', '.join(all_sheets.keys())}",
            },
        )

    rows_by_region = {name: _txn_rows_to_dicts(rows, name) for name, rows in sheets.items()}

    watermark_date = None if from_beginning else get_watermark(db, org["org_id"], "txn_excel", None)

    try:
        result = validate_and_prepare_transaction_sales_rows(rows_by_region, org["org_id"], db, "txn_excel", watermark_date)
    except Exception as exc:
        logger.exception("Phase 4b: validate_and_prepare_transaction_sales_rows failed")
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    valid_rows         = result["valid_rows"]
    error_rows         = result["error_rows"]
    duplicate_warnings = result["duplicate_warnings"]
    already_imported   = result["already_imported"]

    if not confirm:
        return _success({
            "inserted":          0,
            "skipped":           len(error_rows),
            "errors":            error_rows,
            "duplicate_warnings": duplicate_warnings,
            "already_imported":  already_imported,
            "preview":           valid_rows[:10],
            "total_valid":       len(valid_rows),
            "regions":           list(sheets.keys()),
            "watermark_date":    watermark_date,
        }, "Preview ready — send confirm=true to import")

    inserted = 0
    if valid_rows:
        db.table("direct_sales").insert(valid_rows).execute()
        inserted = len(valid_rows)

    if inserted:
        max_date = max(r["sale_date"] for r in valid_rows)
        save_watermark(db, org["org_id"], "txn_excel", None, max_date)

    return _success({
        "inserted":          inserted,
        "skipped":           len(error_rows),
        "errors":            error_rows,
        "duplicate_warnings": duplicate_warnings,
        "already_imported":  already_imported,
        "preview":           [],
        "total_valid":       len(valid_rows),
        "regions":           list(sheets.keys()),
        "watermark_date":    watermark_date,
    }, f"{inserted} sale(s) imported successfully")


@router.delete("/growth/direct-sales/import/{import_source}/clear", status_code=status.HTTP_200_OK)
def clear_imported_sales(
    import_source: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    REPORTS-DEPT-1 Phase 4b: bulk-delete every direct_sales row that came
    from a given import source, for this org. Needed when source data was
    corrected after a bad import (e.g. malformed dates) — re-uploading a
    fixed sheet on top of bad rows wouldn't just duplicate them (the
    dates are different now, so duplicate-detection can't catch it), it
    could also be silently skipped entirely if a garbage date poisoned
    the watermark into the far future. This route only deletes; resetting
    the watermark is a separate call the frontend makes right after.
    """
    _require_owner_or_ops(org)
    db.table("direct_sales").delete().eq("org_id", org["org_id"]).eq("import_source", import_source).execute()
    return _success(None, f"Cleared all sales imported from '{import_source}'")


@router.delete("/growth/direct-sales/import/watermark", status_code=status.HTTP_200_OK)
def reset_import_watermark(
    body: WatermarkResetBody,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """Reset the import watermark for a source so the next import starts from scratch."""
    _require_owner_or_ops(org)
    if body.source_type not in ("excel", "sheets"):
        raise HTTPException(status_code=422, detail={"code": "INVALID_SOURCE_TYPE", "message": "source_type must be 'excel' or 'sheets'"})
    reset_watermark(db, org["org_id"], body.source_type, body.sheet_url)
    return _success(None, f"Watermark reset for {body.source_type}")


# ---------------------------------------------------------------------------
# DIRECT SALES — parameterised routes  (Pattern 53: AFTER static routes)
# ---------------------------------------------------------------------------

@router.patch("/growth/direct-sales/{sale_id}")
def update_direct_sale(
    sale_id: str,
    payload: DirectSaleUpdate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    existing = (
        db.table("direct_sales").select("id")
        .eq("id", sale_id).eq("org_id", org["org_id"])
        .maybe_single().execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Direct sale not found"})
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    updates["updated_at"] = _now_iso()
    result = (
        db.table("direct_sales").update(updates)
        .eq("id", sale_id).eq("org_id", org["org_id"]).execute()
    )
    return _success(result.data[0] if result.data else {}, "Direct sale updated")


@router.delete("/growth/direct-sales/{sale_id}", status_code=status.HTTP_200_OK)
def delete_direct_sale(
    sale_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    existing = (
        db.table("direct_sales").select("id")
        .eq("id", sale_id).eq("org_id", org["org_id"])
        .maybe_single().execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Direct sale not found"})
    db.table("direct_sales").delete().eq("id", sale_id).eq("org_id", org["org_id"]).execute()
    return _success(None, "Direct sale deleted")


# ---------------------------------------------------------------------------
# COMMISSION RATES — REPORTS-DEPT-1 Phase 4b
# Same JSONB-on-organisations pattern as departments/teams (admin.py), but
# lives here since it's a sales/commission concept, not an admin-nav one —
# managed from the Commissions tab UI directly, per client preference.
# ---------------------------------------------------------------------------

class CommissionRateCreate(BaseModel):
    product_name: str = Field(..., min_length=1, max_length=200)
    rate_per_unit: float = Field(..., ge=0)


class CommissionRateUpdate(BaseModel):
    product_name: Optional[str] = None
    rate_per_unit: Optional[float] = None

    @field_validator("product_name")
    @classmethod
    def _validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Product name cannot be empty")
        return v.strip() if v else v


def _require_commission_manager(org: dict) -> None:
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can manage commission rates."},
        )


@router.get("/growth/commission-rates")
def get_commission_rates(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """No role restriction beyond authentication — every rep views the
    commission leaderboard, and needs to see the rates behind it."""
    result = (
        db.table("organisations")
        .select("commission_rates")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    rates = (data or {}).get("commission_rates") or []
    return _success({"commission_rates": rates})


@router.post("/growth/commission-rates", status_code=status.HTTP_201_CREATED)
def create_commission_rate(
    payload: CommissionRateCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_commission_manager(org)
    result = (
        db.table("organisations")
        .select("commission_rates")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    rates = (data or {}).get("commission_rates") or []

    existing_names = {r.get("product_name", "").strip().lower() for r in rates}
    if payload.product_name.strip().lower() in existing_names:
        raise HTTPException(
            status_code=422,
            detail={"code": "DUPLICATE_NAME", "message": "A rate for this product already exists."},
        )

    new_rate = {
        "id": str(uuid.uuid4()),
        "product_name": payload.product_name.strip(),
        "rate_per_unit": payload.rate_per_unit,
    }
    rates.append(new_rate)
    db.table("organisations").update({
        "commission_rates": rates,
        "updated_at": _now_iso(),
    }).eq("id", org["org_id"]).execute()
    return _success({"commission_rates": rates}, "Commission rate added")


@router.patch("/growth/commission-rates/{rate_id}")
def update_commission_rate(
    rate_id: str,
    payload: CommissionRateUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_commission_manager(org)
    result = (
        db.table("organisations")
        .select("commission_rates")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    rates = (data or {}).get("commission_rates") or []

    found = False
    for r in rates:
        if r.get("id") == rate_id:
            found = True
            if payload.product_name is not None:
                r["product_name"] = payload.product_name
            if payload.rate_per_unit is not None:
                r["rate_per_unit"] = payload.rate_per_unit
            break
    if not found:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Commission rate not found"},
        )

    db.table("organisations").update({
        "commission_rates": rates,
        "updated_at": _now_iso(),
    }).eq("id", org["org_id"]).execute()
    return _success({"commission_rates": rates}, "Commission rate updated")


@router.delete("/growth/commission-rates/{rate_id}", status_code=status.HTTP_200_OK)
def delete_commission_rate(
    rate_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Hard delete — unlike departments/teams, a removed product rate has
    no historical-reporting reason to be preserved; past commission
    figures were already computed and aren't recalculated retroactively."""
    _require_commission_manager(org)
    result = (
        db.table("organisations")
        .select("commission_rates")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    rates = (data or {}).get("commission_rates") or []

    new_rates = [r for r in rates if r.get("id") != rate_id]
    if len(new_rates) == len(rates):
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Commission rate not found"},
        )

    db.table("organisations").update({
        "commission_rates": new_rates,
        "updated_at": _now_iso(),
    }).eq("id", org["org_id"]).execute()
    return _success({"commission_rates": new_rates}, "Commission rate removed")


@router.get("/growth/direct-sales/commissions")
def list_commission_sales(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    REPORTS-DEPT-1 Phase 4b: commission-relevant sales for the Commissions
    tab leaderboard. Broader access than list_direct_sales (owner/
    ops_manager/sales_agent) but narrower field selection — deliberately
    excludes customer_name/phone/notes so reps see commission data, not
    customer PII, just because they're allowed to view earnings.
    Only rows with a model set (i.e. from the transaction-level import —
    daily-aggregate/named-customer rows have no model and can't be
    commission-matched). Returns ALL matching rows, not paginated —
    accurate totals need the full dataset.
    """
    _require_owner_ops_or_agent(org)
    query = (
        db.table("direct_sales")
        .select("id, sale_date, recorded_by, model, units, amount, reconciliation_status, region")
        .eq("org_id", org["org_id"])
        .not_.is_("model", "null")
    )
    if date_from:
        query = query.gte("sale_date", date_from)
    if date_to:
        query = query.lte("sale_date", date_to)
    result = query.order("sale_date", desc=True).limit(5000).execute()

    rows = result.data or []
    rep_ids = {r["recorded_by"] for r in rows if r.get("recorded_by")}
    rep_names: dict = {}
    if rep_ids:
        try:
            u_res = (
                db.table("users")
                .select("id, full_name")
                .eq("org_id", org["org_id"])
                .in_("id", list(rep_ids))
                .execute()
            )
            rep_names = {u["id"]: u.get("full_name") for u in (u_res.data or [])}
        except Exception:
            logger.warning("list_commission_sales: rep name lookup failed — showing unnamed reps.")

    for r in rows:
        r["rep_name"] = rep_names.get(r.get("recorded_by")) or "Unassigned"

    return _success({"items": rows})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_selected(
    valid_rows: list[dict],
    selected_indices,  # str (comma-sep) | list[int] | None
) -> list[dict]:
    """
    Return the subset of valid_rows to actually insert.
    If selected_indices is None/empty → insert all valid_rows.
    """
    if selected_indices is None:
        return valid_rows
    # Handle both str (query param) and list[int] (JSON body)
    if isinstance(selected_indices, str):
        if not selected_indices.strip():
            return valid_rows
        try:
            indices = [int(x.strip()) for x in selected_indices.split(",") if x.strip()]
        except ValueError:
            return valid_rows
    else:
        indices = list(selected_indices)
    if not indices:
        return valid_rows
    return [valid_rows[i] for i in indices if 0 <= i < len(valid_rows)]
