"""
tests/unit/test_9e_a_observability.py
----------------------------------
Unit + integration tests for Phase 9E-A (Observability Foundation).

Coverage:
  1. GET /health — ok path (DB reachable)
  2. GET /health — degraded path (DB exception)
  3. check_meta_token_validity — valid token (200)
  4. check_meta_token_validity — invalid token (401)
  5. check_meta_token_validity — invalid token (403)
  6. check_meta_token_validity — network exception → False
  7. check_meta_token_validity — no token configured → True
  8. check_meta_token_validity — DB fetch exception → False
  9. run_meta_token_check — all tokens valid → 0 invalid
 10. run_meta_token_check — one invalid token → notified
 11. run_meta_token_check — per-org exception → S14 (loop continues)
 12. run_meta_token_check — org fetch failure → early return
 13. _notify_owner — owner found → notification inserted
 14. _notify_owner — no owner found → skips gracefully
 15. celery_app beat schedule — meta_token_check entry present
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chain(execute_data=None):
    """
    Build a fully chainable Supabase mock.

    Covers: .select() .eq() .limit() .maybe_single() .neq()
    And the attribute-style .not_ used in:
        db.table(...).select(...).eq(...).not_.is_(...).neq(...).execute()
    """
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.maybe_single.return_value = chain
    chain.neq.return_value = chain
    chain.insert.return_value = chain
    chain.execute.return_value = MagicMock(data=execute_data)

    # .not_ is an attribute (not a call) that exposes .is_()
    # chain.not_.is_(...) must return chain so .neq() and .execute() keep working
    chain.not_ = MagicMock()
    chain.not_.is_.return_value = chain

    return chain


# ---------------------------------------------------------------------------
# 1–2: Health check
# ---------------------------------------------------------------------------

class TestHealthCheck:

    def test_health_ok(self):
        """DB reachable → status ok."""
        from app.main import app

        mock_db = MagicMock()
        chain = _make_chain(execute_data=[{"id": "abc"}])
        mock_db.table.return_value = chain

        # Health check calls get_supabase() directly in the route body,
        # so patch at source rather than using dependency override.
        with patch("app.main.get_supabase", return_value=mock_db):
            with TestClient(app) as client:
                resp = client.get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["db"] == "ok"
        assert body["version"] == "49.0"

    def test_health_degraded(self):
        """DB ping raises → degraded, still returns 200."""
        from app.main import app

        mock_db = MagicMock()
        mock_db.table.side_effect = Exception("connection refused")

        with patch("app.main.get_supabase", return_value=mock_db):
            with TestClient(app) as client:
                resp = client.get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["db"] == "error"


# ---------------------------------------------------------------------------
# 3–8: check_meta_token_validity
# ---------------------------------------------------------------------------

class TestCheckMetaTokenValidity:

    def test_valid_token_returns_true(self):
        from app.services.whatsapp_service import check_meta_token_validity
        db = MagicMock()
        with patch(
            "app.services.whatsapp_service._get_org_wa_credentials",
            return_value=("phone_id", "valid_token_abcd", "waba_id"),
        ), patch("httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            result = check_meta_token_validity(db, "org-1")

        assert result is True

    def test_invalid_token_401_returns_false(self):
        from app.services.whatsapp_service import check_meta_token_validity
        db = MagicMock()
        with patch(
            "app.services.whatsapp_service._get_org_wa_credentials",
            return_value=("phone_id", "bad_token_1234", "waba_id"),
        ), patch("httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            result = check_meta_token_validity(db, "org-1")

        assert result is False

    def test_invalid_token_403_returns_false(self):
        from app.services.whatsapp_service import check_meta_token_validity
        db = MagicMock()
        with patch(
            "app.services.whatsapp_service._get_org_wa_credentials",
            return_value=("phone_id", "bad_token_1234", "waba_id"),
        ), patch("httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 403
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            result = check_meta_token_validity(db, "org-1")

        assert result is False

    def test_network_exception_returns_false(self):
        from app.services.whatsapp_service import check_meta_token_validity
        import httpx
        db = MagicMock()
        with patch(
            "app.services.whatsapp_service._get_org_wa_credentials",
            return_value=("phone_id", "some_token_abcd", "waba_id"),
        ), patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = (
                httpx.RequestError("timeout")
            )

            result = check_meta_token_validity(db, "org-1")

        assert result is False

    def test_no_token_returns_true(self):
        """No token configured → not applicable → True."""
        from app.services.whatsapp_service import check_meta_token_validity
        db = MagicMock()
        with patch(
            "app.services.whatsapp_service._get_org_wa_credentials",
            return_value=(None, None, None),
        ):
            result = check_meta_token_validity(db, "org-1")

        assert result is True

    def test_db_exception_returns_false(self):
        """DB fetch raises → S14 → False."""
        from app.services.whatsapp_service import check_meta_token_validity
        db = MagicMock()
        with patch(
            "app.services.whatsapp_service._get_org_wa_credentials",
            side_effect=Exception("db error"),
        ):
            result = check_meta_token_validity(db, "org-1")

        assert result is False


# ---------------------------------------------------------------------------
# 9–12: run_meta_token_check
# ---------------------------------------------------------------------------

class TestRunMetaTokenCheck:

    def _make_orgs_db(self, orgs: list[dict]) -> MagicMock:
        """
        Build a db mock whose organisations table returns `orgs`.
        All other tables (users, roles, user_roles, notifications) return [].
        Uses table.side_effect so each table gets its own chain.
        """
        db = MagicMock()

        def table_side_effect(table_name):
            chain = _make_chain(execute_data=orgs if table_name == "organisations" else [])
            if table_name == "notifications":
                chain.insert.return_value = chain
            return chain

        db.table.side_effect = table_side_effect
        return db

    def test_all_valid_tokens(self):
        from app.workers.meta_token_worker import run_meta_token_check
        orgs = [{"id": "org-1", "whatsapp_access_token": "tok_abcd"}]
        db = self._make_orgs_db(orgs)

        with patch("app.workers.meta_token_worker.get_supabase", return_value=db), \
             patch("app.workers.meta_token_worker.check_meta_token_validity", return_value=True):
            result = run_meta_token_check()

        assert result["orgs_checked"] == 1
        assert result["invalid_tokens"] == 0
        assert result["failed"] == 0

    def test_invalid_token_triggers_notification(self):
        from app.workers.meta_token_worker import run_meta_token_check
        orgs = [{"id": "org-1", "whatsapp_access_token": "tok_abcd"}]
        db = self._make_orgs_db(orgs)

        with patch("app.workers.meta_token_worker.get_supabase", return_value=db), \
             patch("app.workers.meta_token_worker.check_meta_token_validity", return_value=False), \
             patch("app.workers.meta_token_worker._notify_owner") as mock_notify:
            result = run_meta_token_check()

        assert result["invalid_tokens"] == 1
        assert result["notified"] == 1
        mock_notify.assert_called_once_with(db, "org-1")

    def test_per_org_exception_s14(self):
        """S14: exception on one org must not stop the loop."""
        from app.workers.meta_token_worker import run_meta_token_check
        orgs = [
            {"id": "org-1", "whatsapp_access_token": "tok_abcd"},
            {"id": "org-2", "whatsapp_access_token": "tok_efgh"},
        ]
        db = self._make_orgs_db(orgs)

        call_results = [Exception("boom"), True]

        def side_effect(db_, org_id):
            val = call_results.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        with patch("app.workers.meta_token_worker.get_supabase", return_value=db), \
             patch(
                 "app.workers.meta_token_worker.check_meta_token_validity",
                 side_effect=side_effect,
             ):
            result = run_meta_token_check()

        assert result["orgs_checked"] == 2
        assert result["failed"] == 1
        assert result["invalid_tokens"] == 0

    def test_org_fetch_failure_early_return(self):
        """DB failure fetching org list → early return, no crash."""
        from app.workers.meta_token_worker import run_meta_token_check
        db = MagicMock()
        db.table.side_effect = Exception("db down")

        with patch("app.workers.meta_token_worker.get_supabase", return_value=db):
            result = run_meta_token_check()

        assert result["orgs_checked"] == 0


# ---------------------------------------------------------------------------
# 13–14: _notify_owner
# ---------------------------------------------------------------------------

class TestNotifyOwner:

    def test_owner_found_notification_inserted(self):
        from app.workers.meta_token_worker import _notify_owner
        inserted = []

        db = MagicMock()

        def table_side(table_name):
            chain = _make_chain(execute_data=[])

            if table_name == "users":
                chain.execute.return_value = MagicMock(data=[{"id": "user-1"}])
            elif table_name == "roles":
                chain.execute.return_value = MagicMock(
                    data=[{"id": "role-1", "name": "owner"}]
                )
            elif table_name == "user_roles":
                chain.execute.return_value = MagicMock(
                    data=[{"role_id": "role-1"}]
                )
            elif table_name == "notifications":
                def capture_insert(data):
                    inserted.extend(data if isinstance(data, list) else [data])
                    return chain
                chain.insert.side_effect = capture_insert

            return chain

        db.table.side_effect = table_side

        _notify_owner(db, "org-1")

        assert len(inserted) == 1
        notif = inserted[0]
        assert notif["type"] == "whatsapp_token_invalid"
        assert notif["channel"] == "inapp"
        assert notif["user_id"] == "user-1"
        assert notif["org_id"] == "org-1"

    def test_no_owner_skips_gracefully(self):
        """No users with owner role → no insert, no crash."""
        from app.workers.meta_token_worker import _notify_owner
        db = MagicMock()

        def table_side(table_name):
            return _make_chain(execute_data=[])

        db.table.side_effect = table_side

        # Should not raise
        _notify_owner(db, "org-1")


# ---------------------------------------------------------------------------
# 15: beat schedule
# ---------------------------------------------------------------------------

class TestBeatSchedule:

    def test_meta_token_check_in_beat_schedule(self):
        from app.workers.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "meta_token_check" in schedule, (
            "meta_token_check beat entry missing from celery_app.conf.beat_schedule"
        )
        entry = schedule["meta_token_check"]
        assert entry["task"] == "app.workers.meta_token_worker.run_meta_token_check"

    def test_meta_token_worker_in_include_list(self):
        from app.workers.celery_app import celery_app
        includes = celery_app.conf.include or []
        assert "app.workers.meta_token_worker" in includes, (
            "meta_token_worker not in celery_app include list"
        )
