"""
tests/unit/test_claude_retry.py
--------------------------------
9E-G tests for G1 — tenacity @retry on Claude API calls.

Coverage:
  1.  RateLimitError on first call → retried → succeeds on second → returns text
  2.  RateLimitError three times → reraises → caller gets empty string (S14)
  3.  5xx APIStatusError → retried → succeeds → returns text
  4.  4xx APIStatusError (e.g. 400) → NOT retried → returns empty string immediately
  5.  Non-API exception (e.g. network) → NOT retried → returns empty string
  6.  call_haiku_sync: RateLimitError → retried → succeeds
  7.  call_haiku_sync: RateLimitError three times → reraises → caller handles (S14)
  8.  _is_retryable: RateLimitError → True
  9.  _is_retryable: 500 APIStatusError → True
  10. _is_retryable: 400 APIStatusError → False
  11. _is_retryable: generic Exception → False
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest
import anthropic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(text: str = "ok") -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    resp.usage = MagicMock(input_tokens=10, output_tokens=5)
    return resp


def _rate_limit_error() -> anthropic.RateLimitError:
    return anthropic.RateLimitError(
        message="rate limit",
        response=MagicMock(status_code=429, headers={}),
        body={},
    )


def _api_status_error(status_code: int) -> anthropic.APIStatusError:
    return anthropic.APIStatusError(
        message=f"error {status_code}",
        response=MagicMock(status_code=status_code, headers={}),
        body={},
    )


# ---------------------------------------------------------------------------
# 1–5: call_claude retry behaviour
# ---------------------------------------------------------------------------

class TestCallClaudeRetry:

    def test_rate_limit_then_success_returns_text(self):
        """RateLimitError on first attempt → retried → second attempt succeeds."""
        from app.services.ai_service import call_claude

        call_count = {"n": 0}

        def _side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _rate_limit_error()
            return _make_response("scored")

        with patch("app.services.ai_service._get_client") as mock_client_fn, \
             patch("app.services.ai_service.check_and_increment_token_usage", return_value=True):
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _side_effect
            mock_client_fn.return_value = mock_client

            result = call_claude("score this lead", org_id="org-1")

        assert result == "scored"
        assert call_count["n"] == 2

    def test_rate_limit_three_times_returns_empty_string(self):
        """Three consecutive RateLimitErrors → all retries exhausted → empty string (S14)."""
        from app.services.ai_service import call_claude

        with patch("app.services.ai_service._get_client") as mock_client_fn, \
             patch("app.services.ai_service.check_and_increment_token_usage", return_value=True):
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _rate_limit_error()
            mock_client_fn.return_value = mock_client

            result = call_claude("score this lead", org_id="org-1")

        assert result == ""

    def test_5xx_error_retried_then_succeeds(self):
        """500 APIStatusError → retried → succeeds on second attempt."""
        from app.services.ai_service import call_claude

        call_count = {"n": 0}

        def _side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _api_status_error(500)
            return _make_response("fallback")

        with patch("app.services.ai_service._get_client") as mock_client_fn, \
             patch("app.services.ai_service.check_and_increment_token_usage", return_value=True):
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _side_effect
            mock_client_fn.return_value = mock_client

            result = call_claude("prompt", org_id="org-1")

        assert result == "fallback"
        assert call_count["n"] == 2

    def test_4xx_error_not_retried(self):
        """400 APIStatusError → not retryable → returns empty string immediately (1 attempt)."""
        from app.services.ai_service import call_claude

        call_count = {"n": 0}

        def _side_effect(**kwargs):
            call_count["n"] += 1
            raise _api_status_error(400)

        with patch("app.services.ai_service._get_client") as mock_client_fn, \
             patch("app.services.ai_service.check_and_increment_token_usage", return_value=True):
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _side_effect
            mock_client_fn.return_value = mock_client

            result = call_claude("prompt", org_id="org-1")

        assert result == ""
        assert call_count["n"] == 1  # not retried

    def test_network_exception_not_retried(self):
        """Generic ConnectionError → not retryable → returns empty string (1 attempt)."""
        from app.services.ai_service import call_claude

        call_count = {"n": 0}

        def _side_effect(**kwargs):
            call_count["n"] += 1
            raise ConnectionError("network unreachable")

        with patch("app.services.ai_service._get_client") as mock_client_fn, \
             patch("app.services.ai_service.check_and_increment_token_usage", return_value=True):
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _side_effect
            mock_client_fn.return_value = mock_client

            result = call_claude("prompt", org_id="org-1")

        assert result == ""
        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# 6–7: call_haiku_sync retry behaviour
# ---------------------------------------------------------------------------

class TestCallHaikuSyncRetry:

    def test_rate_limit_then_success(self):
        """call_haiku_sync: RateLimitError → retried → succeeds."""
        from app.services.assistant_service import call_haiku_sync

        call_count = {"n": 0}

        def _side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _rate_limit_error()
            return _make_response("briefing text")

        with patch("app.services.assistant_service.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _side_effect
            mock_cls.return_value = mock_client

            result = call_haiku_sync("system prompt", [{"role": "user", "content": "hi"}])

        assert result == "briefing text"
        assert call_count["n"] == 2

    def test_rate_limit_three_times_reraises(self):
        """
        call_haiku_sync: three RateLimitErrors → reraises after retry exhaustion.
        The daily_briefing_worker's S14 try/except catches this at the caller level.
        """
        from app.services.assistant_service import call_haiku_sync

        with patch("app.services.assistant_service.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = _rate_limit_error()
            mock_cls.return_value = mock_client

            with pytest.raises(anthropic.RateLimitError):
                call_haiku_sync("system", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# 8–11: _is_retryable predicate
# ---------------------------------------------------------------------------

class TestIsRetryable:

    def test_rate_limit_error_is_retryable(self):
        from app.services.ai_service import _is_retryable
        assert _is_retryable(_rate_limit_error()) is True

    def test_500_api_status_error_is_retryable(self):
        from app.services.ai_service import _is_retryable
        assert _is_retryable(_api_status_error(500)) is True

    def test_400_api_status_error_not_retryable(self):
        from app.services.ai_service import _is_retryable
        assert _is_retryable(_api_status_error(400)) is False

    def test_generic_exception_not_retryable(self):
        from app.services.ai_service import _is_retryable
        assert _is_retryable(ValueError("bad")) is False
