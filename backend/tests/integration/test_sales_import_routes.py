"""
tests/integration/test_sales_import_routes.py
Integration tests for GPM-1E import routes — 12 tests.

Pattern 44: override get_current_org directly.
Pattern 61: _ORG_PAYLOAD uses "id" not "user_id".
Pattern 62: db via Depends(get_supabase).
Pattern 63: patch paths from source imports.
"""
import io
import uuid
import pytest
import openpyxl
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.routers.auth import get_current_org

ORG_ID  = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())

_ORG_PAYLOAD = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles":  {"template": "owner", "permissions": {}},
}


def _make_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _mock_db():
    db = MagicMock()
    chain = MagicMock()
    chain.eq.return_value          = chain
    chain.is_.return_value         = chain
    chain.select.return_value      = chain
    chain.insert.return_value      = chain
    chain.upsert.return_value      = chain
    chain.delete.return_value      = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value     = MagicMock(data=[], count=0)
    db.table.return_value = chain
    return db


@pytest.fixture(autouse=True)
def override_deps():
    db = _mock_db()
    app.dependency_overrides[get_supabase]    = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
    yield db
    app.dependency_overrides.clear()


client = TestClient(app)


# ---------------------------------------------------------------------------
# Excel import
# ---------------------------------------------------------------------------

class TestExcelImport:

    def test_preview_returns_correct_row_count(self, override_deps):
        xlsx = _make_xlsx([
            ['customer_name', 'amount', 'sale_date'],
            ['Ada Nwosu',     '5000',   '2026-04-01'],
            ['Emeka Eze',     '3000',   '2026-04-02'],
        ])
        r = client.post(
            "/api/v1/growth/direct-sales/import/excel?confirm=false",
            files={"file": ("sales.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total_valid"] == 2
        assert data["inserted"] == 0

    def test_error_rows_flagged_valid_row_still_in_preview(self, override_deps):
        xlsx = _make_xlsx([
            ['customer_name', 'amount', 'sale_date'],
            ['Good Row',      '5000',   '2026-04-01'],
            ['Bad Row',       '',       '2026-04-02'],
        ])
        r = client.post(
            "/api/v1/growth/direct-sales/import/excel?confirm=false",
            files={"file": ("sales.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total_valid"] == 1
        assert len(data["errors"]) == 1

    def test_confirm_true_inserts_selected_rows(self, override_deps):
        xlsx = _make_xlsx([
            ['customer_name', 'amount', 'sale_date'],
            ['Tunde Bello',   '8000',   '2026-04-01'],
            ['Funmi Ade',     '4000',   '2026-04-02'],
        ])
        # Only insert index 0 (first valid row)
        r = client.post(
            "/api/v1/growth/direct-sales/import/excel?confirm=true&selected_indices=0",
            files={"file": ("sales.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert r.status_code == 200
        assert r.json()["data"]["inserted"] == 1

    def test_confirm_true_inserts_all_when_no_indices(self, override_deps):
        xlsx = _make_xlsx([
            ['customer_name', 'amount', 'sale_date'],
            ['Tunde Bello',   '8000',   '2026-04-01'],
            ['Funmi Ade',     '4000',   '2026-04-02'],
        ])
        r = client.post(
            "/api/v1/growth/direct-sales/import/excel?confirm=true",
            files={"file": ("sales.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert r.status_code == 200
        assert r.json()["data"]["inserted"] == 2

    def test_unsupported_file_type_returns_422(self, override_deps):
        r = client.post(
            "/api/v1/growth/direct-sales/import/excel?confirm=false",
            files={"file": ("data.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Google Sheets import
# ---------------------------------------------------------------------------

class TestSheetsImport:

    def test_preview_returns_rows_mocked(self, override_deps):
        csv_text = "customer_name,amount,sale_date\nChidi,4500,2026-04-05\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        with patch("app.services.sales_import_service.httpx.get", return_value=mock_resp):
            r = client.post("/api/v1/growth/direct-sales/import/sheets", json={
                "url": "https://docs.google.com/spreadsheets/d/TESTID/edit",
                "confirm": False,
            })
        assert r.status_code == 200
        assert r.json()["data"]["total_valid"] == 1
        assert r.json()["data"]["inserted"] == 0

    def test_confirm_true_inserts_all_rows(self, override_deps):
        csv_text = "customer_name,amount,sale_date\nFunmi,9000,2026-04-06\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        with patch("app.services.sales_import_service.httpx.get", return_value=mock_resp):
            r = client.post("/api/v1/growth/direct-sales/import/sheets", json={
                "url": "https://docs.google.com/spreadsheets/d/TESTID/edit",
                "confirm": True,
            })
        assert r.status_code == 200
        assert r.json()["data"]["inserted"] == 1

    def test_confirm_true_selected_indices_inserts_subset(self, override_deps):
        csv_text = "customer_name,amount,sale_date\nRow1,1000,2026-04-01\nRow2,2000,2026-04-02\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        with patch("app.services.sales_import_service.httpx.get", return_value=mock_resp):
            r = client.post("/api/v1/growth/direct-sales/import/sheets", json={
                "url": "https://docs.google.com/spreadsheets/d/TESTID/edit",
                "confirm": True,
                "selected_indices": [0],  # only first row
            })
        assert r.status_code == 200
        assert r.json()["data"]["inserted"] == 1

    def test_invalid_url_returns_422(self, override_deps):
        r = client.post("/api/v1/growth/direct-sales/import/sheets", json={
            "url": "https://www.google.com/not-a-sheet", "confirm": False,
        })
        assert r.status_code == 422

    def test_google_fetch_failure_returns_422_not_500(self, override_deps):
        import httpx as _httpx
        with patch("app.services.sales_import_service.httpx.get",
                   side_effect=_httpx.RequestError("timeout")):
            r = client.post("/api/v1/growth/direct-sales/import/sheets", json={
                "url": "https://docs.google.com/spreadsheets/d/TESTID/edit", "confirm": False,
            })
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "FETCH_ERROR"


# ---------------------------------------------------------------------------
# Watermark reset
# ---------------------------------------------------------------------------

class TestWatermarkReset:

    def test_reset_excel_watermark(self, override_deps):
        r = client.request("DELETE", "/api/v1/growth/direct-sales/import/watermark",
                           json={"source_type": "excel"})
        assert r.status_code == 200

    def test_reset_sheets_watermark(self, override_deps):
        r = client.request("DELETE", "/api/v1/growth/direct-sales/import/watermark",
                           json={"source_type": "sheets",
                                 "sheet_url": "https://docs.google.com/spreadsheets/d/X/edit"})
        assert r.status_code == 200

    def test_invalid_source_type_returns_422(self, override_deps):
        r = client.request("DELETE", "/api/v1/growth/direct-sales/import/watermark",
                           json={"source_type": "ftp"})
        assert r.status_code == 422
