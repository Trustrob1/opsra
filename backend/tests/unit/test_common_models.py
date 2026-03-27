"""
tests/unit/test_common_models.py
---------------------------------
Unit tests for app/models/common.py — the shared response envelope.

Covers:
  - ApiResponse success shape
  - ApiResponse error shape
  - ErrorCode enum values match Technical Spec Section 9.3
  - PaginatedData.build() computes has_more correctly
  - ok(), err(), paginated() factory helpers
  - ErrorDetail field is None for non-validation errors

Run with:
    pytest tests/unit/test_common_models.py -v
"""

import pytest
from pydantic import ValidationError

from app.models.common import (
    ApiResponse,
    ErrorCode,
    ErrorDetail,
    PaginatedData,
    err,
    ok,
    paginated,
)


# ---------------------------------------------------------------------------
# ErrorCode enum — Technical Spec Section 9.3
# ---------------------------------------------------------------------------

class TestErrorCode:
    def test_all_required_codes_present(self):
        """Every code in Section 9.3 must exist in the enum."""
        required = {
            "UNAUTHORIZED",
            "FORBIDDEN",
            "NOT_FOUND",
            "VALIDATION_ERROR",
            "INVALID_TRANSITION",
            "DUPLICATE_DETECTED",
            "KNOWLEDGE_GAP",
            "INTEGRATION_ERROR",
            "RATE_LIMITED",
            "ORGANISATION_SUSPENDED",
        }
        actual = {code.value for code in ErrorCode}
        assert required == actual, f"Missing error codes: {required - actual}"

    def test_code_values_are_strings(self):
        for code in ErrorCode:
            assert isinstance(code.value, str)
            assert code.value == code.value.upper()


# ---------------------------------------------------------------------------
# ErrorDetail
# ---------------------------------------------------------------------------

class TestErrorDetail:
    def test_field_defaults_to_none(self):
        detail = ErrorDetail(code=ErrorCode.NOT_FOUND, message="Not found")
        assert detail.field is None

    def test_field_set_for_validation_error(self):
        detail = ErrorDetail(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid email",
            field="email",
        )
        assert detail.field == "email"

    def test_message_max_length_enforced(self):
        with pytest.raises(ValidationError):
            ErrorDetail(
                code=ErrorCode.FORBIDDEN,
                message="x" * 501,  # Over 500 char limit
            )


# ---------------------------------------------------------------------------
# ApiResponse — success shape
# ---------------------------------------------------------------------------

class TestApiResponseSuccess:
    def test_ok_shape(self):
        response = ok(data={"id": "abc"})
        assert response.success is True
        assert response.data == {"id": "abc"}
        assert response.error is None
        assert response.message is None

    def test_ok_with_message(self):
        response = ok(data={"id": "abc"}, message="Created successfully")
        assert response.message == "Created successfully"

    def test_ok_with_no_data(self):
        response = ok()
        assert response.success is True
        assert response.data is None

    def test_serialises_to_dict(self):
        response = ok(data={"result": 42})
        d = response.model_dump()
        assert d["success"] is True
        assert d["data"] == {"result": 42}
        assert d["error"] is None

    def test_ok_data_can_be_pydantic_model(self):
        from pydantic import BaseModel

        class Payload(BaseModel):
            name: str

        response = ok(data=Payload(name="Opsra"))
        assert response.success is True


# ---------------------------------------------------------------------------
# ApiResponse — error shape
# ---------------------------------------------------------------------------

class TestApiResponseError:
    def test_err_shape(self):
        response = err(code=ErrorCode.NOT_FOUND, message="Lead not found")
        assert response.success is False
        assert response.data is None
        assert response.message is None
        assert response.error is not None
        assert response.error.code == ErrorCode.NOT_FOUND
        assert response.error.message == "Lead not found"
        assert response.error.field is None

    def test_err_with_field(self):
        response = err(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid phone number",
            field="phone",
        )
        assert response.error.field == "phone"
        assert response.error.code == ErrorCode.VALIDATION_ERROR

    def test_err_serialises_to_dict(self):
        response = err(code=ErrorCode.UNAUTHORIZED, message="No token provided")
        d = response.model_dump()
        assert d["success"] is False
        assert d["data"] is None
        assert d["error"]["code"] == "UNAUTHORIZED"

    def test_all_error_codes_usable(self):
        for code in ErrorCode:
            response = err(code=code, message=f"Testing {code.value}")
            assert response.error.code == code


# ---------------------------------------------------------------------------
# PaginatedData
# ---------------------------------------------------------------------------

class TestPaginatedData:
    def test_has_more_true_when_items_remain(self):
        pd = PaginatedData.build(items=["a", "b"], total=10, page=1, page_size=2)
        assert pd.has_more is True  # (1 * 2) < 10

    def test_has_more_false_on_last_page(self):
        pd = PaginatedData.build(items=["a", "b"], total=4, page=2, page_size=2)
        assert pd.has_more is False  # (2 * 2) == 4

    def test_has_more_false_when_exactly_fits(self):
        pd = PaginatedData.build(items=list(range(5)), total=5, page=1, page_size=5)
        assert pd.has_more is False

    def test_total_zero(self):
        pd = PaginatedData.build(items=[], total=0, page=1, page_size=20)
        assert pd.has_more is False
        assert pd.total == 0

    def test_fields_set_correctly(self):
        pd = PaginatedData.build(items=[1, 2, 3], total=100, page=3, page_size=10)
        assert pd.page == 3
        assert pd.page_size == 10
        assert pd.total == 100
        assert len(pd.items) == 3

    def test_page_size_min_1(self):
        with pytest.raises(ValidationError):
            PaginatedData(items=[], total=0, page=1, page_size=0, has_more=False)

    def test_page_size_max_500(self):
        with pytest.raises(ValidationError):
            PaginatedData(items=[], total=0, page=1, page_size=501, has_more=False)


# ---------------------------------------------------------------------------
# paginated() factory helper
# ---------------------------------------------------------------------------

class TestPaginatedHelper:
    def test_paginated_response_shape(self):
        response = paginated(items=["x", "y"], total=20, page=1, page_size=2)
        assert response.success is True
        assert response.data.total == 20
        assert response.data.has_more is True
        assert response.error is None

    def test_paginated_last_page(self):
        response = paginated(items=["x"], total=1, page=1, page_size=20)
        assert response.data.has_more is False


# ---------------------------------------------------------------------------
# Technical Spec Section 9.2 — exact JSON structure contract
# ---------------------------------------------------------------------------

class TestResponseEnvelopeContract:
    """Ensure the serialised output matches Section 9.2 exactly."""

    def test_success_json_keys(self):
        d = ok(data={"id": "1"}).model_dump()
        assert set(d.keys()) == {"success", "data", "message", "error"}

    def test_error_json_keys(self):
        d = err(code=ErrorCode.FORBIDDEN, message="Forbidden").model_dump()
        assert set(d.keys()) == {"success", "data", "message", "error"}
        assert set(d["error"].keys()) == {"code", "message", "field"}

    def test_paginated_inner_keys(self):
        d = paginated(items=[], total=0, page=1, page_size=20).model_dump()
        assert set(d["data"].keys()) == {"items", "total", "page", "page_size", "has_more"}