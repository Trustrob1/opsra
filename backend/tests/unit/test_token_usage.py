"""
tests/unit/test_token_usage.py
-------------------------------
9E-G tests for G2 — per-org daily Claude API token usage tracking.

Coverage:
  1.  Under soft limit → returns True, no Sentry alert
  2.  Crossing soft limit (50k) → returns True, Sentry warning fired
  3.  At hard limit (100k) before call → returns False (call blocked)
  4.  Redis unavailable → returns True (S14 — never block on infra error)
  5.  org_id=None → returns True (tracking skipped gracefully)
  6.  Token key format is correct: claude_tokens:{org_id}:{date}
  7.  TTL is set to 48 hours
  8.  call_claude: hard limit reached → returns empty string without calling API
  9.  call_claude: successful call → token counter incremented with usage tokens
  10. call_claude: no org_id → API called, no token tracking attempted
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch, call
import pytest


ORG_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis_mock(current_value: int = 0):
    """Build a mock Redis client returning current_value for GET."""
    r = MagicMock()
    r.get.return_value = str(current_value)
    pipe = MagicMock()
    pipe.incrby.return_value = pipe
    pipe.expire.return_value = pipe
    pipe.execute.return_value = [current_value + 10, True]
    r.pipeline.return_value = pipe
    return r, pipe


def _make_response(input_tokens: int = 100, output_tokens: int = 50) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text="result")]
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


# ---------------------------------------------------------------------------
# 1–7: check_and_increment_token_usage
# ---------------------------------------------------------------------------

class TestTokenUsage:

    def test_under_soft_limit_returns_true_no_sentry(self):
        """Under 50k tokens → returns True, no Sentry capture."""
        from app.services.ai_service import check_and_increment_token_usage

        r, pipe = _make_redis_mock(current_value=1000)
        pipe.execute.return_value = [1100, True]

        with patch("app.services.ai_service._get_redis", return_value=r), \
             patch("app.services.ai_service.sentry_sdk") as mock_sentry:
            result = check_and_increment_token_usage(ORG_ID, 100)

        assert result is True
        mock_sentry.capture_message.assert_not_called()

    def test_crossing_soft_limit_fires_sentry_warning(self):
        """
        Current usage just below 50k, adding tokens crosses it
        → returns True (allowed) + Sentry warning.
        """
        from app.services.ai_service import check_and_increment_token_usage

        r, pipe = _make_redis_mock(current_value=49_900)
        pipe.execute.return_value = [50_100, True]  # new total crosses 50k

        with patch("app.services.ai_service._get_redis", return_value=r), \
             patch("app.services.ai_service.sentry_sdk") as mock_sentry:
            result = check_and_increment_token_usage(ORG_ID, 200)

        assert result is True
        mock_sentry.capture_message.assert_called_once()
        args = mock_sentry.capture_message.call_args
        assert args[1]["level"] == "warning"

    def test_at_hard_limit_returns_false(self):
        """Current usage at/above 100k → returns False (call blocked)."""
        from app.services.ai_service import check_and_increment_token_usage

        r, pipe = _make_redis_mock(current_value=100_000)

        with patch("app.services.ai_service._get_redis", return_value=r), \
             patch("app.services.ai_service.sentry_sdk") as mock_sentry:
            result = check_and_increment_token_usage(ORG_ID, 100)

        assert result is False
        mock_sentry.capture_message.assert_called_once()
        args = mock_sentry.capture_message.call_args
        assert args[1]["level"] == "error"

    def test_redis_unavailable_returns_true(self):
        """Redis raises on connect → S14 → returns True (never block)."""
        from app.services.ai_service import check_and_increment_token_usage

        with patch("app.services.ai_service._get_redis", return_value=None):
            result = check_and_increment_token_usage(ORG_ID, 100)

        assert result is True

    def test_no_org_id_returns_true(self):
        """org_id=None → tracking skipped → True."""
        from app.services.ai_service import check_and_increment_token_usage

        with patch("app.services.ai_service._get_redis") as mock_redis_fn:
            result = check_and_increment_token_usage(None, 100)

        assert result is True
        mock_redis_fn.assert_not_called()

    def test_key_format_is_correct(self):
        """Redis key must be claude_tokens:{org_id}:{YYYY-MM-DD}."""
        from app.services.ai_service import check_and_increment_token_usage

        r, pipe = _make_redis_mock(current_value=0)
        pipe.execute.return_value = [100, True]

        today = date.today().isoformat()
        expected_key = f"claude_tokens:{ORG_ID}:{today}"

        with patch("app.services.ai_service._get_redis", return_value=r):
            check_and_increment_token_usage(ORG_ID, 100)

        r.get.assert_called_with(expected_key)

    def test_ttl_set_to_48_hours(self):
        """Redis key TTL must be set to 172800 seconds (48 hours)."""
        from app.services.ai_service import check_and_increment_token_usage

        r, pipe = _make_redis_mock(current_value=0)
        pipe.execute.return_value = [100, True]

        with patch("app.services.ai_service._get_redis", return_value=r):
            check_and_increment_token_usage(ORG_ID, 100)

        pipe.expire.assert_called_once()
        args = pipe.expire.call_args[0]
        assert args[1] == 172_800


# ---------------------------------------------------------------------------
# 8–10: call_claude integration with token tracking
# ---------------------------------------------------------------------------

class TestCallClaudeTokenIntegration:

    def test_hard_limit_blocks_api_call(self):
        """If check_and_increment returns False (hard limit), API is never called."""
        from app.services.ai_service import call_claude

        with patch("app.services.ai_service.check_and_increment_token_usage",
                   return_value=False) as mock_check, \
             patch("app.services.ai_service._get_client") as mock_client_fn:

            result = call_claude("prompt", org_id=ORG_ID)

        assert result == ""
        mock_client_fn.assert_not_called()

    def test_successful_call_increments_token_counter(self):
        """After a successful call, token counter called with actual usage tokens."""
        from app.services.ai_service import call_claude

        increments = []

        def _track(org_id, tokens):
            increments.append((org_id, tokens))
            return True

        with patch("app.services.ai_service.check_and_increment_token_usage",
                   side_effect=_track), \
             patch("app.services.ai_service._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _make_response(
                input_tokens=80, output_tokens=20
            )
            mock_client_fn.return_value = mock_client

            result = call_claude("prompt", org_id=ORG_ID)

        assert result == "result"
        # First call (pre-check with 0), second call (post-call with actual tokens)
        assert any(tokens == 100 for _, tokens in increments)  # 80 + 20

    def test_no_org_id_calls_api_without_tracking(self):
        """call_claude without org_id makes the API call but skips token tracking."""
        from app.services.ai_service import call_claude

        with patch("app.services.ai_service.check_and_increment_token_usage") as mock_track, \
             patch("app.services.ai_service._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _make_response()
            mock_client_fn.return_value = mock_client

            result = call_claude("prompt")  # no org_id

        assert result == "result"
        mock_track.assert_not_called()
