"""
tests/unit/test_sa2_monitoring.py
SA-2A — Unit tests for monitoring_service and ai_service SA-2A additions.

10 tests as per SA-2A spec:
  log_system_error S14
  write_worker_log S14
  generate_fix_hint S14
  _log_claude_usage cost calc + S14
  _write_worker_log correct row + S14
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _mock_db():
    db = MagicMock()
    chain = MagicMock()
    chain.insert.return_value = chain
    chain.execute.return_value = MagicMock(data=[])
    db.table.return_value = chain
    return db


ORG_ID = "11111111-1111-1111-1111-111111111111"


# ═══════════════════════════════════════════════════════════════════════════
# log_system_error
# ═══════════════════════════════════════════════════════════════════════════

class TestLogSystemError:

    def test_writes_row_to_db(self):
        """log_system_error inserts a row into system_error_log."""
        from app.services.monitoring_service import log_system_error

        db = _mock_db()
        with patch("app.services.monitoring_service.log_system_error.__wrapped__", None, create=True):
            log_system_error(
                db,
                error_type="test_error",
                error_message="Something broke",
                org_id=ORG_ID,
                generate_hint=False,
            )

        db.table.assert_called_with("system_error_log")
        db.table("system_error_log").insert.assert_called_once()
        row = db.table("system_error_log").insert.call_args[0][0]
        assert row["error_type"] == "test_error"
        assert row["org_id"] == ORG_ID
        assert "Something broke" in row["error_message"]

    def test_s14_never_raises_on_db_failure(self):
        """log_system_error never raises even if DB insert fails."""
        from app.services.monitoring_service import log_system_error

        db = _mock_db()
        db.table.side_effect = Exception("DB down")

        # Must not raise
        log_system_error(
            db,
            error_type="test_error",
            error_message="boom",
            generate_hint=False,
        )

    def test_calls_sentry_with_exception(self):
        """log_system_error calls sentry_sdk.capture_exception when exc provided."""
        from app.services.monitoring_service import log_system_error

        db = _mock_db()
        exc = ValueError("test exc")

        with patch("app.services.monitoring_service.sentry_sdk") as mock_sentry:
            log_system_error(
                db,
                error_type="test_error",
                error_message="boom",
                exc=exc,
                generate_hint=False,
            )
        mock_sentry.capture_exception.assert_called_once_with(exc)

    def test_truncates_long_error_message(self):
        """log_system_error truncates error_message to 2000 chars."""
        from app.services.monitoring_service import log_system_error

        db = _mock_db()
        long_msg = "x" * 5000

        log_system_error(db, error_type="t", error_message=long_msg, generate_hint=False)

        row = db.table("system_error_log").insert.call_args[0][0]
        assert len(row["error_message"]) <= 2000


# ═══════════════════════════════════════════════════════════════════════════
# write_worker_log
# ═══════════════════════════════════════════════════════════════════════════

class TestWriteWorkerLog:

    def test_writes_correct_row(self):
        """write_worker_log writes the correct fields to worker_run_log."""
        from app.services.monitoring_service import write_worker_log

        db = _mock_db()
        started = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)

        write_worker_log(
            db,
            worker_name="broadcast_worker",
            status="passed",
            items_processed=10,
            items_failed=0,
            items_skipped=2,
            started_at=started,
        )

        db.table.assert_called_with("worker_run_log")
        row = db.table("worker_run_log").insert.call_args[0][0]
        assert row["worker_name"] == "broadcast_worker"
        assert row["status"] == "passed"
        assert row["items_processed"] == 10
        assert row["items_skipped"] == 2
        assert row["started_at"] == started.isoformat()

    def test_upgrades_status_to_partial_when_failures(self):
        """write_worker_log upgrades 'passed' to 'partial' when items_failed > 0."""
        from app.services.monitoring_service import write_worker_log

        db = _mock_db()

        write_worker_log(
            db,
            worker_name="drip_worker",
            status="passed",
            items_processed=5,
            items_failed=2,
        )

        row = db.table("worker_run_log").insert.call_args[0][0]
        assert row["status"] == "partial"

    def test_s14_never_raises_on_db_failure(self):
        """write_worker_log never raises even if DB insert fails."""
        from app.services.monitoring_service import write_worker_log

        db = _mock_db()
        db.table.side_effect = Exception("DB down")

        # Must not raise
        write_worker_log(db, worker_name="test_worker", status="passed")


# ═══════════════════════════════════════════════════════════════════════════
# generate_fix_hint
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateFixHint:

    def test_returns_string_on_success(self):
        """generate_fix_hint returns a non-empty string when call_claude succeeds."""
        from app.services.ai_service import generate_fix_hint

        with patch("app.services.ai_service.call_claude", return_value="Check your DB connection. Ensure the env vars are set correctly."):
            result = generate_fix_hint(
                error_type="db_error",
                error_message="connection refused",
            )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_s14_returns_none_on_claude_failure(self):
        """generate_fix_hint returns None (not raises) when call_claude fails."""
        from app.services.ai_service import generate_fix_hint

        with patch("app.services.ai_service.call_claude", side_effect=Exception("API down")):
            result = generate_fix_hint(
                error_type="worker_failure",
                error_message="timeout",
            )
        assert result is None

    def test_s14_returns_none_on_empty_response(self):
        """generate_fix_hint returns None when call_claude returns empty string."""
        from app.services.ai_service import generate_fix_hint

        with patch("app.services.ai_service.call_claude", return_value=""):
            result = generate_fix_hint(
                error_type="worker_failure",
                error_message="timeout",
            )
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# _log_claude_usage
# ═══════════════════════════════════════════════════════════════════════════

class TestLogClaudeUsage:

    def test_cost_calculation_sonnet(self):
        """_log_claude_usage calculates Sonnet cost correctly."""
        from app.services.ai_service import _log_claude_usage

        db = _mock_db()

        _log_claude_usage(
            db,
            org_id=ORG_ID,
            function_name="score_lead_with_ai",
            model="claude-sonnet-4-20250514",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        row = db.table("claude_usage_log").insert.call_args[0][0]
        # Sonnet: input $3/M + output $15/M = $18 total for 1M each
        assert float(row["estimated_cost_usd"]) == pytest.approx(18.0, abs=0.001)
        assert row["total_tokens"] == 2_000_000

    def test_cost_calculation_haiku(self):
        """_log_claude_usage calculates Haiku cost correctly."""
        from app.services.ai_service import _log_claude_usage

        db = _mock_db()

        _log_claude_usage(
            db,
            org_id=ORG_ID,
            function_name="generate_fix_hint",
            model="claude-haiku-4-5-20251001",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        row = db.table("claude_usage_log").insert.call_args[0][0]
        # Haiku: input $0.80/M + output $4/M = $4.80 total for 1M each
        assert float(row["estimated_cost_usd"]) == pytest.approx(4.80, abs=0.001)

    def test_writes_correct_fields(self):
        """_log_claude_usage writes org_id, function_name, model, tokens to DB."""
        from app.services.ai_service import _log_claude_usage

        db = _mock_db()

        _log_claude_usage(
            db,
            org_id=ORG_ID,
            function_name="generate_ticket_reply",
            model="claude-haiku-4-5-20251001",
            input_tokens=500,
            output_tokens=200,
        )

        row = db.table("claude_usage_log").insert.call_args[0][0]
        assert row["org_id"] == ORG_ID
        assert row["function_name"] == "generate_ticket_reply"
        assert row["input_tokens"] == 500
        assert row["output_tokens"] == 200

    def test_s14_never_raises_on_db_failure(self):
        """_log_claude_usage never raises even if DB insert fails."""
        from app.services.ai_service import _log_claude_usage

        db = _mock_db()
        db.table.side_effect = Exception("DB down")

        # Must not raise
        _log_claude_usage(
            db,
            org_id=ORG_ID,
            function_name="score_lead",
            model="claude-haiku-4-5-20251001",
            input_tokens=100,
            output_tokens=50,
        )
