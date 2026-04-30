"""
tests/integration/test_lead_import_routes.py

Integration tests for S10 — CSV/Excel bulk import security guards:
  POST /api/v1/leads/import

Covers:
  - Valid CSV accepted (202)
  - Valid XLSX accepted (not 415)
  - File over 25 MB rejected (413)
  - Binary files disguised as CSV rejected (415):
      JPEG, PNG, ZIP (non-xlsx), legacy XLS, Windows EXE, Linux ELF

Patterns:
  - Pattern 3  : get_supabase ALWAYS overridden
  - Pattern 32 : pop() teardown via fixture
  - S10        : magic byte + size guard in import_leads route
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000099"

_MOCK_ORG = {
    "id":        USER_ID,
    "org_id":    ORG_ID,
    "email":     "owner@test.com",
    "full_name": "Test Owner",
    "is_active": True,
    "roles": {"template": "owner", "permissions": {}},
}

_MOCK_JOB = {
    "job_id":    "job-001",
    "status":    "completed",
    "succeeded": 1,
    "failed":    0,
    "errors":    [],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    mock_db = MagicMock()
    app.dependency_overrides[get_supabase]    = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: _MOCK_ORG
    yield TestClient(app, raise_server_exceptions=False), mock_db
    app.dependency_overrides.pop(get_supabase, None)
    app.dependency_overrides.pop(get_current_org, None)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _post_import(tc, content: bytes, filename: str, content_type: str = "text/csv"):
    """POST to /api/v1/leads/import with lead_service calls patched out."""
    with patch("app.routers.leads.lead_service.create_import_job", return_value="job-001"), \
         patch("app.routers.leads.lead_service.process_csv_import",  return_value=None), \
         patch("app.routers.leads.lead_service.get_import_job",      return_value=_MOCK_JOB):
        return tc.post(
            "/api/v1/leads/import",
            files={"file": (filename, io.BytesIO(content), content_type)},
            headers={"Authorization": "Bearer mock-token"},
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestImportLeadsHappyPath:

    def test_valid_csv_returns_202(self, client):
        tc, _ = client
        csv_content = b"full_name,phone\nTayo Ade,08031234567\n"
        resp = _post_import(tc, csv_content, "leads.csv", "text/csv")
        assert resp.status_code == 202

    def test_valid_csv_response_envelope(self, client):
        tc, _ = client
        csv_content = b"full_name,phone\nTayo Ade,08031234567\n"
        resp = _post_import(tc, csv_content, "leads.csv", "text/csv")
        body = resp.json()
        assert body["success"] is True

    def test_valid_xlsx_not_rejected_by_magic_byte_guard(self, client):
        """
        XLSX is a ZIP file — its magic bytes are PK\x03\x04.
        The guard must allow it when the extension is .xlsx.
        """
        tc, _ = client
        xlsx_magic = b"\x50\x4b\x03\x04" + b"\x00" * 100
        resp = _post_import(
            tc, xlsx_magic, "leads.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        # 202 (success) or 422 (parse error) are both acceptable —
        # what must NOT happen is 415 from the magic byte guard.
        assert resp.status_code != 415, (
            "XLSX with .xlsx extension must not be rejected by magic byte guard"
        )


# ---------------------------------------------------------------------------
# Size guard — S10
# ---------------------------------------------------------------------------

class TestImportLeadsSizeGuard:

    def test_file_over_25mb_returns_413(self, client):
        tc, _ = client
        oversized = b"x" * (25 * 1024 * 1024 + 1)
        resp = _post_import(tc, oversized, "big.csv", "text/csv")
        assert resp.status_code == 413

    def test_file_exactly_at_25mb_not_rejected_by_size_guard(self, client):
        """Edge case: file at exactly 25 MB must not trigger 413."""
        tc, _ = client
        at_limit = b"a,b\n" + b"x" * (25 * 1024 * 1024 - 4)
        resp = _post_import(tc, at_limit, "edge.csv", "text/csv")
        assert resp.status_code != 413, (
            "File at exactly 25 MB must not trigger size guard"
        )


# ---------------------------------------------------------------------------
# Magic byte guard — S10
# ---------------------------------------------------------------------------

class TestImportLeadsMagicByteGuard:

    def test_jpeg_disguised_as_csv_returns_415(self, client):
        tc, _ = client
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = _post_import(tc, jpeg, "data.csv", "text/csv")
        assert resp.status_code == 415

    def test_png_disguised_as_csv_returns_415(self, client):
        tc, _ = client
        png = b"\x89PNG" + b"\x00" * 100
        resp = _post_import(tc, png, "data.csv", "text/csv")
        assert resp.status_code == 415

    def test_windows_exe_disguised_as_csv_returns_415(self, client):
        tc, _ = client
        exe = b"MZ" + b"\x00" * 100
        resp = _post_import(tc, exe, "data.csv", "text/csv")
        assert resp.status_code == 415

    def test_linux_elf_disguised_as_csv_returns_415(self, client):
        tc, _ = client
        elf = b"\x7fELF" + b"\x00" * 100
        resp = _post_import(tc, elf, "data.csv", "text/csv")
        assert resp.status_code == 415

    def test_zip_with_csv_extension_returns_415(self, client):
        """ZIP magic bytes with .csv extension must be rejected."""
        tc, _ = client
        zip_file = b"\x50\x4b\x03\x04" + b"\x00" * 100
        resp = _post_import(tc, zip_file, "data.csv", "text/csv")
        assert resp.status_code == 415

    def test_legacy_xls_disguised_as_csv_returns_415(self, client):
        tc, _ = client
        xls = b"\xd0\xcf\x11\xe0" + b"\x00" * 100
        resp = _post_import(tc, xls, "data.csv", "text/csv")
        assert resp.status_code == 415

    def test_error_detail_code_is_validation_error(self, client):
        """415 response must include VALIDATION_ERROR code in detail."""
        tc, _ = client
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = _post_import(tc, jpeg, "data.csv", "text/csv")
        assert resp.status_code == 415
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "VALIDATION_ERROR"
