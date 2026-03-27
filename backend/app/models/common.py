"""
app/models/common.py
--------------------
Shared Pydantic response envelope models for all Opsra API endpoints.

Every route MUST return one of these wrappers — never return raw data.
Schema is defined in Technical Spec Section 9.2.
Error codes are defined in Technical Spec Section 9.3.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Error code enum — Technical Spec Section 9.3
# ---------------------------------------------------------------------------

class ErrorCode(str, Enum):
    UNAUTHORIZED           = "UNAUTHORIZED"           # 401 — no valid JWT
    FORBIDDEN              = "FORBIDDEN"              # 403 — lacks permission
    NOT_FOUND              = "NOT_FOUND"              # 404 — resource missing / outside org
    VALIDATION_ERROR       = "VALIDATION_ERROR"       # 422 — Pydantic / field validation
    INVALID_TRANSITION     = "INVALID_TRANSITION"     # 400 — state-machine violation
    DUPLICATE_DETECTED     = "DUPLICATE_DETECTED"     # 409 — duplicate phone/email/ref
    KNOWLEDGE_GAP          = "KNOWLEDGE_GAP"          # 200 — AI cannot answer (not an error)
    INTEGRATION_ERROR      = "INTEGRATION_ERROR"      # 503 — Meta / Anthropic / Resend down
    RATE_LIMITED           = "RATE_LIMITED"           # 429 — Redis rate limit hit
    ORGANISATION_SUSPENDED = "ORGANISATION_SUSPENDED" # 403 — org subscription suspended


# ---------------------------------------------------------------------------
# Error detail block — nested inside error responses
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    """
    Structured error payload returned when success=False.

    Attributes
    ----------
    code:    Machine-readable error code from ErrorCode enum.
    message: Human-readable description of what went wrong.
    field:   For VALIDATION_ERROR — which request field failed.
             None for all other error types.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    code: ErrorCode
    message: str = Field(..., max_length=500)
    field: Optional[str] = Field(
        default=None,
        description="Set only for VALIDATION_ERROR — identifies the failing field.",
    )


# ---------------------------------------------------------------------------
# Generic type variable for the data payload
# ---------------------------------------------------------------------------

DataT = TypeVar("DataT")


# ---------------------------------------------------------------------------
# Standard success / error envelope — Technical Spec Section 9.2
# ---------------------------------------------------------------------------

class ApiResponse(BaseModel, Generic[DataT]):
    """
    Universal API response envelope used by every Opsra endpoint.

    Success shape:
        {"success": true, "data": {...}, "message": null, "error": null}

    Error shape:
        {"success": false, "data": null, "error": {"code": "...", "message": "...", "field": null}, "message": null}
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    data: Optional[DataT] = None
    message: Optional[str] = Field(
        default=None,
        description="Optional human-readable success message.",
        max_length=500,
    )
    error: Optional[ErrorDetail] = None


# ---------------------------------------------------------------------------
# Paginated list wrapper — Technical Spec Section 9.2 (paginated list shape)
# ---------------------------------------------------------------------------

class PaginatedData(BaseModel, Generic[DataT]):
    """
    Inner data payload for paginated list endpoints.

    Shape (placed inside ApiResponse.data):
        {"items": [...], "total": 47, "page": 1, "page_size": 20, "has_more": true}
    """

    items: List[DataT]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=500)
    has_more: bool

    @classmethod
    def build(
        cls,
        items: List[DataT],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedData[DataT]":
        """Convenience constructor — computes has_more automatically."""
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(page * page_size) < total,
        )


# ---------------------------------------------------------------------------
# Helper factory functions — use these in every router
# ---------------------------------------------------------------------------

def ok(data: Any = None, message: Optional[str] = None) -> ApiResponse:
    """Return a successful ApiResponse envelope."""
    return ApiResponse(success=True, data=data, message=message, error=None)


def err(
    code: ErrorCode,
    message: str,
    field: Optional[str] = None,
) -> ApiResponse:
    """Return a failed ApiResponse envelope."""
    return ApiResponse(
        success=False,
        data=None,
        message=None,
        error=ErrorDetail(code=code, message=message, field=field),
    )


def paginated(
    items: List[Any],
    total: int,
    page: int,
    page_size: int,
) -> ApiResponse:
    """Return a successful paginated ApiResponse envelope."""
    return ApiResponse(
        success=True,
        data=PaginatedData.build(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        ),
        message=None,
        error=None,
    )