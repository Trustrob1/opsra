"""
app/routers/inventory.py
------------------------
STOCK-1 - inventory. Staff routes, prefix /api/v1. Open to every product mode (no crm_only), like invoices.
Plan feature: `inventory` (whole router, plan_gate.require).

  GET    /inventory?q=&location_id=&low=     stock per product + size (cost prices only for managers)
  GET    /inventory/settings                 the switch and the default reorder level
  PUT    /inventory/settings                 (manager) turning it on the first time copies today's numbers in once
  GET    /inventory/locations                locations + the business's regions (for the Region box)
  POST   /inventory/locations                (manager) add one
  PATCH  /inventory/locations/{id}           (manager) rename, region, make main, turn off / on
  GET    /inventory/products?q=              products with their sizes, for the pickers
  GET    /inventory/history?product_id=&variant=&location_id=&limit=&offset=
  POST   /inventory/receive                  (manager) stock in, one or more lines, optional cost per unit
  POST   /inventory/adjust                   (manager) add / remove / set the count, with a reason
  PATCH  /inventory/items                    (manager) cost price, reorder level, SKU for one product + size
  GET    /inventory/transfers?status=        (STOCK-3) stock moves between locations, newest first
  POST   /inventory/transfers                (manager) send stock from one location to another
  POST   /inventory/transfers/{id}/receive   (manager) all or part arrived; cancel_rest sends the rest back
  POST   /inventory/transfers/{id}/cancel    (manager) everything not yet arrived goes back

Managers = owner, ops_manager, or a role with is_admin. S1/S2: org_id only from get_current_org; ids checked in the service.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.database import get_supabase
from app.dependencies import get_current_org, require_admin
from app.models.common import ok
from app.services import inventory_service as stock
from app.services import invoice_sales_service as sales
from app.services import stock_transfer_service as transfers
from app.services import plan_gate_service as plan_gate

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(plan_gate.require("inventory"))])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsIn(_Strict):
    enabled: Optional[bool] = None
    default_reorder_level: Optional[int] = Field(None, ge=0, le=1_000_000)
    online_location_id: Optional[UUID] = None     # STOCK-3: where website orders take stock from
    low_stock_alerts: Optional[bool] = None


class TransferLine(_Strict):
    product_id: UUID
    variant: Optional[str] = Field(None, max_length=100)
    quantity: int = Field(..., ge=1, le=1_000_000)


class TransferIn(_Strict):
    from_location_id: UUID
    to_location_id: UUID
    lines: List[TransferLine] = Field(..., min_length=1, max_length=100)
    note: Optional[str] = Field(None, max_length=300)


class ReceiveTransferLine(_Strict):
    line_id: UUID
    quantity: int = Field(..., ge=0, le=1_000_000)


class ReceiveTransferIn(_Strict):
    lines: List[ReceiveTransferLine] = Field(default_factory=list, max_length=100)
    cancel_rest: bool = False


class LocationIn(_Strict):
    name: str = Field(..., min_length=1, max_length=100)
    region: Optional[str] = Field(None, max_length=255)
    is_default: bool = False


class LocationPatch(_Strict):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    region: Optional[str] = Field(None, max_length=255)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class ReceiveLine(_Strict):
    product_id: UUID
    variant: Optional[str] = Field(None, max_length=100)
    quantity: int = Field(..., ge=1, le=1_000_000)
    unit_cost: Optional[Decimal] = Field(None, ge=0, le=100_000_000_000)


class ReceiveIn(_Strict):
    location_id: UUID
    lines: List[ReceiveLine] = Field(..., min_length=1, max_length=100)
    ref: Optional[str] = Field(None, max_length=200)
    note: Optional[str] = Field(None, max_length=500)


class AdjustIn(_Strict):
    location_id: UUID
    product_id: UUID
    variant: Optional[str] = Field(None, max_length=100)
    mode: Literal["add", "remove", "set"]
    quantity: int = Field(..., ge=0, le=1_000_000)
    reason: Literal["recount", "damaged", "lost", "found", "returned", "other"]
    note: Optional[str] = Field(None, max_length=400)


class ItemPatch(_Strict):
    product_id: UUID
    variant: Optional[str] = Field(None, max_length=100)
    cost_price: Optional[Decimal] = Field(None, ge=0, le=100_000_000_000)
    reorder_level: Optional[int] = Field(None, ge=0, le=1_000_000)
    sku: Optional[str] = Field(None, max_length=100)


def _fail(e: stock.StockError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={
        "success": False, "data": None,
        "error": {"code": e.code, "message": e.message, "field": e.field}})


def _org_id(org: dict) -> str:
    return org["org_id"]


def _uid(org: dict) -> Optional[str]:
    return org.get("id") or org.get("user_id")


def _manager(org: dict = Depends(get_current_org)) -> dict:
    if not stock.is_manager(org):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"code": "FORBIDDEN", "message": "Only owners, operations managers and admins can change stock."})
    return org


@router.get("/inventory")
async def get_inventory(q: Optional[str] = Query(None, max_length=100), location_id: Optional[UUID] = None,
                        low: bool = False, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    try:
        data = stock.overview(db, _org_id(org), stock.is_manager(org), q=q,
                              location_id=str(location_id) if location_id else None, low_only=low)
    except stock.StockError as e:
        return _fail(e)
    data["can_manage"] = stock.is_manager(org)
    return ok(data=data)


@router.get("/inventory/report")
async def get_inventory_report(start: Optional[date] = None, end: Optional[date] = None,
                               location_id: Optional[UUID] = None, format: Literal["json", "pdf", "csv"] = "json",
                               org: dict = Depends(require_admin), db=Depends(get_supabase)):
    """REPORT-1: stock now + moves in the period, as JSON, PDF or CSV (admins)."""
    from app.services import business_report_service as biz
    from app.services import invoice_service as inv
    try:
        data = biz.inventory_data(db, _org_id(org), start, end, str(location_id) if location_id else None)
    except stock.StockError as e:
        return _fail(e)
    if format == "json":
        return ok(data=data)
    if format == "csv":
        body, name, media = biz.inventory_csv(data).encode("utf-8-sig"), biz.filename("inventory", data, "csv"), "text/csv"
    else:
        body, name = biz.inventory_pdf(data, inv.get_settings(db, _org_id(org)))
        media = "application/pdf"
        if not body:
            return _fail(stock.StockError("INTEGRATION_ERROR", "The PDF could not be made. Please try again.", 503))
    return Response(content=body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/inventory/settings")
async def get_settings(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    return ok(data={**stock.get_settings(db, _org_id(org)), "can_manage": stock.is_manager(org)})


@router.put("/inventory/settings")
async def put_settings(body: SettingsIn, org: dict = Depends(_manager), db=Depends(get_supabase)):
    try:
        return ok(data=stock.save_settings(db, _org_id(org), _uid(org), body.model_dump(exclude_unset=True)))
    except stock.StockError as e:
        return _fail(e)


@router.get("/inventory/locations")
async def get_locations(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    return ok(data={"locations": stock.list_locations(db, _org_id(org)), "regions": sales.regions(db, _org_id(org)),
                    "enabled": stock.stock_on(db, _org_id(org))})   # STOCK-2: the invoice editor reads enabled


@router.get("/inventory/held")
async def get_held(location_id: Optional[UUID] = None, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    """STOCK-2: unpaid issued invoices holding stock, oldest first."""
    from app.services import invoice_stock_service as inv_stock
    return ok(data={"items": inv_stock.held_list(db, _org_id(org), str(location_id) if location_id else None)})


@router.get("/inventory/to-deliver")
async def get_to_deliver(location_id: Optional[UUID] = None, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    """STOCK-2: paid invoices with goods still to deliver, oldest first."""
    from app.services import invoice_stock_service as inv_stock
    return ok(data={"items": inv_stock.to_deliver_list(db, _org_id(org), str(location_id) if location_id else None)})


@router.get("/inventory/approvals")
async def get_approvals(org: dict = Depends(_manager), db=Depends(get_supabase)):
    """STOCK-2b: drafts waiting for an admin to approve taking stock from another location."""
    from app.services import invoice_stock_service as inv_stock
    return ok(data={"items": inv_stock.approvals_list(db, _org_id(org))})


@router.get("/inventory/availability")
async def get_availability(location_id: UUID, product_ids: str = Query(..., max_length=4000),
                           org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    """STOCK-2: what is available per size at one location, for the invoice editor's size picker."""
    from app.services import invoice_stock_service as inv_stock
    ids = []
    for raw in product_ids.split(",")[:100]:
        try:
            ids.append(str(UUID(raw.strip())))
        except ValueError:
            continue
    return ok(data={"location_id": str(location_id),
                    "products": inv_stock.availability(db, _org_id(org), str(location_id), ids)})


@router.post("/inventory/locations")
async def post_location(body: LocationIn, org: dict = Depends(_manager), db=Depends(get_supabase)):
    try:
        return ok(data=stock.create_location(db, _org_id(org), body.model_dump()))
    except stock.StockError as e:
        return _fail(e)


@router.patch("/inventory/locations/{location_id}")
async def patch_location(location_id: UUID, body: LocationPatch, org: dict = Depends(_manager), db=Depends(get_supabase)):
    try:
        return ok(data=stock.update_location(db, _org_id(org), str(location_id), body.model_dump(exclude_unset=True)))
    except stock.StockError as e:
        return _fail(e)


@router.get("/inventory/products")
async def get_products(q: Optional[str] = Query(None, max_length=100), org: dict = Depends(get_current_org),
                       db=Depends(get_supabase)):
    return ok(data={"items": stock.search_products(db, _org_id(org), q)})


@router.get("/inventory/history")
async def get_history(product_id: Optional[UUID] = None, variant: Optional[str] = Query(None, max_length=100),
                      location_id: Optional[UUID] = None, limit: int = Query(50, ge=1, le=200),
                      offset: int = Query(0, ge=0, le=100_000), org: dict = Depends(get_current_org),
                      db=Depends(get_supabase)):
    return ok(data=stock.history(db, _org_id(org), product_id=str(product_id) if product_id else None, variant=variant,
                                 location_id=str(location_id) if location_id else None, limit=limit, offset=offset))


@router.post("/inventory/receive")
async def post_receive(body: ReceiveIn, org: dict = Depends(_manager), db=Depends(get_supabase)):
    try:
        return ok(data=stock.receive(db, _org_id(org), _uid(org), body.model_dump(mode="json")))
    except stock.StockError as e:
        return _fail(e)


@router.post("/inventory/adjust")
async def post_adjust(body: AdjustIn, org: dict = Depends(_manager), db=Depends(get_supabase)):
    try:
        return ok(data=stock.adjust(db, _org_id(org), _uid(org), body.model_dump(mode="json")))
    except stock.StockError as e:
        return _fail(e)


@router.patch("/inventory/items")
async def patch_item(body: ItemPatch, org: dict = Depends(_manager), db=Depends(get_supabase)):
    try:
        return ok(data=stock.update_item(db, _org_id(org), body.model_dump(mode="json", exclude_unset=True)))
    except stock.StockError as e:
        return _fail(e)


# ───────────────────────────── STOCK-3: moving stock between locations ─────────────────────────────

@router.get("/inventory/transfers")
async def get_transfers(status_: Optional[Literal["in_transit", "done", "cancelled"]] = Query(None, alias="status"),
                        org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    return ok(data={"transfers": transfers.list_transfers(db, _org_id(org), status_),
                    "can_manage": stock.is_manager(org)})


@router.post("/inventory/transfers")
async def post_transfer(body: TransferIn, org: dict = Depends(_manager), db=Depends(get_supabase)):
    try:
        return ok(data=transfers.send(db, _org_id(org), _uid(org), body.model_dump(mode="json")))
    except stock.StockError as e:
        return _fail(e)


@router.post("/inventory/transfers/{transfer_id}/receive")
async def post_transfer_receive(transfer_id: UUID, body: ReceiveTransferIn, org: dict = Depends(_manager),
                                db=Depends(get_supabase)):
    try:
        data = body.model_dump(mode="json")
        return ok(data=transfers.receive(db, _org_id(org), _uid(org), str(transfer_id), data["lines"], data["cancel_rest"]))
    except stock.StockError as e:
        return _fail(e)


@router.post("/inventory/transfers/{transfer_id}/cancel")
async def post_transfer_cancel(transfer_id: UUID, org: dict = Depends(_manager), db=Depends(get_supabase)):
    try:
        return ok(data=transfers.cancel(db, _org_id(org), _uid(org), str(transfer_id)))
    except stock.StockError as e:
        return _fail(e)
