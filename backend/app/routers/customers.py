"""
customers.py — Module 02 customer profile routes.

All routes are prefixed with /api/v1/customers via main.py include_router.
Internal prefix: none.

Routes (full paths after combining):
  GET   /api/v1/customers                    list_customers
  GET   /api/v1/customers/{customer_id}      get_customer
  PATCH /api/v1/customers/{customer_id}      update_customer
  GET   /api/v1/customers/{customer_id}/messages   get_customer_messages
  GET   /api/v1/customers/{customer_id}/tasks      get_customer_tasks
  GET   /api/v1/customers/{customer_id}/nps        get_customer_nps

Auth: JWT required on all routes (get_current_org dependency).
Response envelope: ok() / paginated() from app.models.common.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok, paginated
from app.models.customers import CustomerUpdate
from app.services import whatsapp_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Customer list
# ---------------------------------------------------------------------------

@router.get("")
def list_customers(
    churn_risk: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    onboarding_complete: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    result = whatsapp_service.list_customers(
        db=db,
        org_id=org["org_id"],
        churn_risk=churn_risk,
        assigned_to=assigned_to,
        onboarding_complete=onboarding_complete,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Customer profile
# ---------------------------------------------------------------------------

@router.get("/{customer_id}")
def get_customer(
    customer_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    customer = whatsapp_service.get_customer(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
    )
    return ok(data=customer)


@router.patch("/{customer_id}")
def update_customer(
    customer_id: str,
    payload: CustomerUpdate,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    updated = whatsapp_service.update_customer(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
        user_id=org["id"],
        payload=payload,
    )
    return ok(data=updated, message="Customer updated")


# ---------------------------------------------------------------------------
# Customer sub-resources
# ---------------------------------------------------------------------------

@router.get("/{customer_id}/messages")
def get_customer_messages(
    customer_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    result = whatsapp_service.get_customer_messages(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


@router.get("/{customer_id}/tasks")
def get_customer_tasks(
    customer_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    tasks = whatsapp_service.get_customer_tasks(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
    )
    return ok(data=tasks)


@router.get("/{customer_id}/nps")
def get_customer_nps(
    customer_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    responses = whatsapp_service.get_customer_nps(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
    )
    return ok(data=responses)