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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.routers.auth import get_current_org
from app.services.sales_import_service import (
    fetch_sheets_csv,
    get_watermark,
    parse_excel_file,
    reset_watermark,
    save_watermark,
    validate_and_prepare_rows,
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
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    offset = (page - 1) * page_size
    result = (
        db.table("direct_sales")
        .select("*", count="exact")
        .eq("org_id", org["org_id"])
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
