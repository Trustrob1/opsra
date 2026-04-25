"""
tests/unit/test_sales_import_service.py
Unit tests for GPM-1E sales import service — 12 tests.
"""
import io
import pytest
from unittest.mock import MagicMock, patch

import openpyxl

from app.services.sales_import_service import (
    get_watermark,
    parse_excel_file,
    fetch_sheets_csv,
    save_watermark,
    validate_and_prepare_rows,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _mock_db_no_dupes():
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value  = chain
    chain.eq.return_value      = chain
    chain.execute.return_value = MagicMock(data=[])
    db.table.return_value = chain
    return db


# ---------------------------------------------------------------------------
# parse_excel_file
# ---------------------------------------------------------------------------

class TestParseExcelFile:

    def test_valid_xlsx_returns_correct_keys(self):
        data = _make_xlsx([
            ['customer_name', 'phone', 'amount', 'sale_date'],
            ['Emeka Okafor', '08012345678', '5000', '2026-04-01'],
        ])
        rows = parse_excel_file(data)
        assert len(rows) == 1
        assert rows[0]['customer_name'] == 'Emeka Okafor'
        assert rows[0]['amount'] == '5000'
        assert rows[0]['sale_date'] == '2026-04-01'

    def test_extra_columns_ignored(self):
        data = _make_xlsx([
            ['customer_name', 'amount', 'sale_date', 'favourite_colour'],
            ['Test User', '1000', '2026-04-01', 'blue'],
        ])
        rows = parse_excel_file(data)
        assert 'favourite_colour' not in rows[0]

    def test_missing_optional_columns_default_to_none(self):
        data = _make_xlsx([
            ['customer_name', 'amount', 'sale_date'],
            ['Ada Nwosu', '2000', '2026-04-10'],
        ])
        rows = parse_excel_file(data)
        assert rows[0]['phone'] is None
        assert rows[0]['region'] is None
        assert rows[0]['notes'] is None

    def test_empty_file_raises_value_error(self):
        data = _make_xlsx([])
        with pytest.raises(ValueError, match="empty"):
            parse_excel_file(data)

    def test_column_aliases_normalised(self):
        data = _make_xlsx([
            ['Name', 'Tel', 'Amount', 'Date'],
            ['Chidi Eze', '07011111111', '3500', '01/04/2026'],
        ])
        rows = parse_excel_file(data)
        assert rows[0]['customer_name'] == 'Chidi Eze'
        assert rows[0]['phone'] == '07011111111'


# ---------------------------------------------------------------------------
# fetch_sheets_csv
# ---------------------------------------------------------------------------

class TestFetchSheetsCsv:

    def test_valid_url_returns_parsed_rows(self):
        csv_content = "customer_name,amount,sale_date\nTunde Bello,8000,2026-04-01\n"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = csv_content
        with patch("app.services.sales_import_service.httpx.get", return_value=mock_response):
            rows = fetch_sheets_csv("https://docs.google.com/spreadsheets/d/ABC123/edit")
        assert len(rows) == 1
        assert rows[0]["customer_name"] == "Tunde Bello"

    def test_non_200_response_raises_value_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 403
        with patch("app.services.sales_import_service.httpx.get", return_value=mock_response):
            with pytest.raises(ValueError, match="HTTP 403"):
                fetch_sheets_csv("https://docs.google.com/spreadsheets/d/ABC123/edit")

    def test_network_error_raises_value_error(self):
        import httpx as _httpx
        with patch("app.services.sales_import_service.httpx.get",
                   side_effect=_httpx.RequestError("connection refused")):
            with pytest.raises(ValueError, match="Network error"):
                fetch_sheets_csv("https://docs.google.com/spreadsheets/d/ABC123/edit")

    def test_invalid_url_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid Google Sheets URL"):
            fetch_sheets_csv("https://www.google.com/not-a-sheet")


# ---------------------------------------------------------------------------
# validate_and_prepare_rows
# ---------------------------------------------------------------------------

class TestValidateAndPrepareRows:

    def test_missing_amount_produces_error_row(self):
        db = _mock_db_no_dupes()
        rows = [{'customer_name': 'Ada', 'amount': '', 'sale_date': '2026-04-01',
                 'phone': None, 'region': None, 'channel': None, 'source_team': None, 'notes': None}]
        result = validate_and_prepare_rows(rows, "org-1", db, "excel")
        assert len(result['error_rows']) == 1
        assert 'amount' in result['error_rows'][0]['message'].lower()

    def test_unparseable_date_produces_error_row(self):
        db = _mock_db_no_dupes()
        rows = [{'customer_name': 'Emeka', 'amount': '5000', 'sale_date': 'not-a-date',
                 'phone': None, 'region': None, 'channel': None, 'source_team': None, 'notes': None}]
        result = validate_and_prepare_rows(rows, "org-1", db, "excel")
        assert len(result['error_rows']) == 1

    def test_missing_customer_name_produces_error_row(self):
        db = _mock_db_no_dupes()
        rows = [{'customer_name': '', 'amount': '5000', 'sale_date': '2026-04-01',
                 'phone': None, 'region': None, 'channel': None, 'source_team': None, 'notes': None}]
        result = validate_and_prepare_rows(rows, "org-1", db, "excel")
        assert len(result['error_rows']) == 1

    def test_duplicate_phone_date_amount_flagged_still_in_valid_rows(self):
        db = MagicMock()
        existing = MagicMock()
        existing.data = [{'phone': '08012345678', 'sale_date': '2026-04-01', 'amount': 5000.0}]
        db.table.return_value.select.return_value.eq.return_value.execute.return_value = existing
        rows = [{'customer_name': 'Tunde', 'amount': '5000', 'sale_date': '2026-04-01',
                 'phone': '08012345678', 'region': None, 'channel': None, 'source_team': None, 'notes': None}]
        result = validate_and_prepare_rows(rows, "org-1", db, "excel")
        assert len(result['duplicate_warnings']) == 1
        assert len(result['valid_rows']) == 1
        assert result['duplicate_warnings'][0]['amount'] == 5000.0

    def test_same_phone_date_different_amount_not_flagged(self):
        db = MagicMock()
        existing = MagicMock()
        existing.data = [{'phone': '08012345678', 'sale_date': '2026-04-01', 'amount': 5000.0}]
        db.table.return_value.select.return_value.eq.return_value.execute.return_value = existing
        rows = [{'customer_name': 'Tunde', 'amount': '8000', 'sale_date': '2026-04-01',
                 'phone': '08012345678', 'region': None, 'channel': None, 'source_team': None, 'notes': None}]
        result = validate_and_prepare_rows(rows, "org-1", db, "excel")
        assert len(result['duplicate_warnings']) == 0
        assert len(result['valid_rows']) == 1

    def test_watermark_flags_rows_at_or_before_watermark_date(self):
        db = _mock_db_no_dupes()
        rows = [
            {'customer_name': 'Old Sale',  'amount': '1000', 'sale_date': '2026-03-31', 'phone': None, 'region': None, 'channel': None, 'source_team': None, 'notes': None},
            {'customer_name': 'New Sale',  'amount': '2000', 'sale_date': '2026-04-02', 'phone': None, 'region': None, 'channel': None, 'source_team': None, 'notes': None},
            {'customer_name': 'Same Date', 'amount': '3000', 'sale_date': '2026-04-01', 'phone': None, 'region': None, 'channel': None, 'source_team': None, 'notes': None},
        ]
        result = validate_and_prepare_rows(rows, "org-1", db, "sheets", watermark_date="2026-04-01")
        already = result['already_imported']
        # Both the old sale (March 31) and the same-date sale (April 1) should be flagged
        already_dates = {a['sale_date'] for a in already}
        assert '2026-03-31' in already_dates
        assert '2026-04-01' in already_dates
        assert '2026-04-02' not in already_dates
        # All three still in valid_rows — not blocked
        assert len(result['valid_rows']) == 3

    def test_no_watermark_produces_no_already_imported(self):
        db = _mock_db_no_dupes()
        rows = [{'customer_name': 'Test', 'amount': '5000', 'sale_date': '2026-01-01',
                 'phone': None, 'region': None, 'channel': None, 'source_team': None, 'notes': None}]
        result = validate_and_prepare_rows(rows, "org-1", db, "excel", watermark_date=None)
        assert result['already_imported'] == []


# ---------------------------------------------------------------------------
# Watermark helpers
# ---------------------------------------------------------------------------

class TestWatermarkHelpers:

    def test_get_watermark_returns_none_when_no_record(self):
        db = MagicMock()
        ms = MagicMock()
        ms.execute.return_value = MagicMock(data=None)
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value.maybe_single.return_value = ms
        result = get_watermark(db, "org-1", "excel", None)
        assert result is None

    def test_get_watermark_returns_date_string_when_record_exists(self):
        db = MagicMock()
        ms = MagicMock()
        ms.execute.return_value = MagicMock(data={"last_imported_date": "2026-04-01"})
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value.maybe_single.return_value = ms
        result = get_watermark(db, "org-1", "excel", None)
        assert result == "2026-04-01"

    def test_get_watermark_returns_none_on_db_failure(self):
        db = MagicMock()
        db.table.side_effect = Exception("db error")
        result = get_watermark(db, "org-1", "excel", None)
        assert result is None

    def test_save_watermark_calls_upsert(self):
        db = MagicMock()
        db.table.return_value.upsert.return_value.execute.return_value = MagicMock()
        save_watermark(db, "org-1", "excel", None, "2026-04-25")
        db.table.assert_called_with("sales_import_watermarks")
        db.table.return_value.upsert.assert_called_once()
